"""Read-only URL-first SEO comparison JSON validator (standard library only).

Run from the seo_competitor_engine project root:
    python -m scripts.validate_comparison --keyword aviator

Exit codes: 0 = no hard validation failures (warnings may remain);
            1 = missing/invalid file or structural/URL alignment failure.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def normalized_url(value: object) -> str | None:
    """Compare URL identities without changing the original observed URLs."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parts = urlsplit(value.strip())
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            return None
        host = parts.hostname.lower()
        port = f":{parts.port}" if parts.port and parts.port not in (80, 443) else ""
        path = (parts.path or "/").rstrip("/") or "/"
        return urlunsplit((parts.scheme.lower(), host + port, path, parts.query, ""))
    except ValueError:
        return None


class Report:
    def __init__(self) -> None:
        self.failures = 0
        self.warnings = 0
        self.passes = 0

    def pass_(self, message: str) -> None:
        self.passes += 1
        print(f"PASS  {message}")

    def warn(self, message: str) -> None:
        self.warnings += 1
        print(f"WARN  {message}")

    def fail(self, message: str) -> None:
        self.failures += 1
        print(f"FAIL  {message}")


def as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def validate(data: object, expected_keyword: str, report: Report) -> None:
    if not isinstance(data, dict):
        report.fail("Root must be a JSON object")
        return
    report.pass_("JSON root is an object")

    keyword = data.get("keyword")
    print(f"Keyword in report: {keyword!r}")
    if keyword != expected_keyword:
        report.fail(f"Keyword mismatch: expected {expected_keyword!r}")
    else:
        report.pass_("Keyword matches requested analysis")

    ranking = as_dict(as_dict(data.get("ranking_summary")).get("google"))
    targets = as_dict(data.get("primary_ranking_urls"))
    if not ranking:
        report.fail("ranking_summary.google is missing")
    if not targets:
        report.fail("primary_ranking_urls is missing")

    print("\n=== GOOGLE SERP / URL IDENTITY ===")
    for side, rank_key, url_key in (
        ("ours", "our_position", "our_url"),
        ("benchmark", "benchmark_position", "benchmark_url"),
    ):
        rank = ranking.get(rank_key)
        rank_url = ranking.get(url_key)
        target = targets.get(side)
        print(f"{side}: rank={rank!r} | SERP URL={rank_url!r} | target={target!r}")
        if not isinstance(rank, int) or isinstance(rank, bool) or rank <= 0:
            report.fail(f"{side}: no valid positive Google organic position")
        else:
            report.pass_(f"{side}: Google rank #{rank} recorded")
        if not normalized_url(rank_url) or not normalized_url(target):
            report.fail(f"{side}: missing or invalid exact ranking URL")
        elif normalized_url(rank_url) != normalized_url(target):
            report.fail(f"{side}: primary URL does not match Google SERP URL")
        else:
            report.pass_(f"{side}: primary URL matches observed SERP URL")

    if isinstance(ranking.get("our_position"), int) and isinstance(ranking.get("benchmark_position"), int):
        calculated = ranking["our_position"] - ranking["benchmark_position"]
        if ranking.get("position_gap") == calculated:
            report.pass_(f"Google position gap is consistent ({calculated:+d})")
        else:
            report.fail(f"Google position gap mismatch; expected {calculated:+d}")

    print("\n=== PAGE-LEVEL EVIDENCE ===")
    quality = as_dict(data.get("evidence_quality"))
    page_evidence = as_dict(data.get("page_level_evidence"))
    if not isinstance(data.get("page_level_evidence"), dict):
        report.fail("page_level_evidence section is missing")
    if not isinstance(data.get("evidence_quality"), dict):
        report.fail("evidence_quality section is missing")

    for side in ("ours", "benchmark"):
        target = normalized_url(targets.get(side))
        page = as_dict(page_evidence.get(side))
        status = quality.get(f"page_{side}", "not recorded")
        print(f"{side}: quality={status!r} | retained_page={'yes' if page else 'no'}")
        if not page:
            if status == "usable":
                report.fail(f"{side}: quality says usable but no page evidence is present")
            else:
                report.warn(f"{side}: page evidence withheld/unavailable ({status})")
            continue
        identity = normalized_url(page.get("ranking_url") or page.get("requested_url"))
        if not target or not identity or identity != target:
            report.fail(f"{side}: page evidence URL differs from primary SERP URL")
        else:
            report.pass_(f"{side}: page evidence URL aligned")
        if page.get("url_alignment") != "matched":
            report.fail(f"{side}: retained page has unverified URL alignment")
        if page.get("extraction_status") != "complete" or page.get("crawl_failed"):
            report.fail(f"{side}: retained page has incomplete/failed extraction")
        words = page.get("word_count")
        if isinstance(words, int) and words < 200:
            report.fail(f"{side}: thin page ({words} words) was retained as usable evidence")
        if status != "usable":
            report.warn(f"{side}: retained page but quality status is {status!r}")

    print("\n=== PAGE BACKLINKS ===")
    for side, key in (("ours", "backlinks_ours"), ("benchmark", "backlinks_benchmark")):
        backlink = as_dict(page_evidence.get(key))
        status = quality.get(f"backlinks_{side}_page", "not recorded")
        if not backlink:
            if status == "usable":
                report.fail(f"{side}: backlinks marked usable but missing")
            else:
                report.warn(f"{side}: page backlinks unavailable ({status}); NOT interpreted as zero")
            continue
        if backlink.get("scope") != "page" or backlink.get("target_verified") is not True:
            report.fail(f"{side}: page backlinks scope/target verification invalid")
        elif normalized_url(backlink.get("target")) != normalized_url(targets.get(side)):
            report.fail(f"{side}: backlink target differs from SERP ranking URL")
        else:
            report.pass_(f"{side}: page backlink target verified")

    print("\n=== DOMAIN-LEVEL EVIDENCE ===")
    domain_evidence = data.get("domain_level_evidence")
    if not isinstance(domain_evidence, dict):
        report.fail("domain_level_evidence section is missing")
    else:
        for side in ("ours", "benchmark"):
            ranked = domain_evidence.get(f"ranked_{side}")
            print(f"{side}: ranked keywords data={'present' if ranked else 'missing'}")
            if not ranked:
                report.warn(f"{side}: domain-wide ranked-keyword evidence missing")
        report.pass_("Domain-wide evidence is in its own section")

    print("\n=== FINDINGS ===")
    findings = data.get("findings")
    if not isinstance(findings, list):
        report.fail("findings must be a list")
    else:
        print(f"Finding count: {len(findings)}")
        for i, finding in enumerate(findings, 1):
            if not isinstance(finding, dict):
                report.fail(f"Finding {i} is not an object")
                continue
            print(f"  {i}. [{finding.get('confidence', '?')}] {finding.get('category', '?')}")
        report.pass_("Findings list is readable")

    policy = as_dict(data.get("analysis_policy"))
    if policy.get("url_first"):
        report.pass_("URL-first analysis policy recorded")
    else:
        report.warn("URL-first policy not explicitly recorded")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a saved SEO comparison without making API calls")
    parser.add_argument("--keyword", default="aviator", help="Keyword whose output should be checked (default: aviator)")
    parser.add_argument("--file", type=Path, help="Optional explicit comparison JSON path")
    args = parser.parse_args()
    keyword = args.keyword.strip()
    if not keyword:
        parser.error("--keyword cannot be blank")
    # Match the project's keyword slug naming for ordinary single/multiword keywords.
    slug = re.sub(r"[^a-z0-9]+", "_", keyword.lower()).strip("_")
    if not slug:
        parser.error("--keyword must contain letters or digits")
    file_path = args.file or (PROJECT_ROOT / "output" / "results" / slug / f"{slug}_comparison.json")
    if not file_path.is_absolute():
        file_path = PROJECT_ROOT / file_path
    print("=== URL-FIRST SEO COMPARISON VALIDATION ===")
    print(f"File: {file_path}")
    try:
        data = json.loads(file_path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        print("FAIL  File not found. Run the analyze stage first or use --file PATH")
        return 1
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"FAIL  Could not read valid JSON: {exc}")
        return 1
    report = Report()
    report.pass_("JSON parsed successfully")
    validate(data, keyword, report)
    print("\n=== SUMMARY ===")
    print(f"PASS={report.passes} WARN={report.warnings} FAIL={report.failures}")
    print("VALIDATION FAILED" if report.failures else "STRUCTURAL VALIDATION PASSED (review warnings)")
    print("This is a local structural check, not independent proof of search-engine rankings.")
    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
