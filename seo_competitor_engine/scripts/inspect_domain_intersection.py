"""Read-only inspector for keyword-scoped DataForSEO Domain Intersection output."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def load_json(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def get_rank(element):
    """DataForSEO records may expose rank directly or under serp_item."""
    if not isinstance(element, dict):
        return None
    inner = element.get("serp_item") if isinstance(element.get("serp_item"), dict) else {}
    for source in (element, inner):
        value = source.get("rank_group")
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return None


def show_report(data: dict, keyword: str, limit: int) -> str:
    lines = []
    def add(message=""):
        lines.append(message)

    rows = data.get("items")
    if not isinstance(rows, list):
        raise ValueError("Missing or invalid 'items' array in normalized file")
    first = data.get("target1") or "target1 (not recorded)"
    second = data.get("target2") or "target2 (not recorded)"
    add("=== DOMAIN INTERSECTION REPORT ===")
    add(f"Analysis keyword: {keyword}")
    add(f"Domain 1: {first}")
    add(f"Domain 2: {second}")
    add(f"Scope: {data.get('scope', 'not recorded')}")
    add(f"API total_count: {data.get('total_count', 'not reported')}")
    add(f"Normalized records: {len(rows)}")
    add(f"Locally excluded nonmatches: {data.get('excluded_nonmatching_items', 'not reported')}")
    add("Note: total_count may exceed returned records due to the API limit.")
    add("Note: shared-keyword intersection does not show keywords unique to one domain.")
    add()
    add("=== KEYWORD RANKING COMPARISON ===")
    add("Keyword | Search volume | Domain 1 rank | Domain 2 rank | Leader")
    add("-" * 90)
    counts = Counter()
    anomalies = []
    valid = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            anomalies.append(f"Record {i + 1}: not a JSON object")
            continue
        term = str(row.get("keyword") or "").strip()
        if not term:
            anomalies.append(f"Record {i + 1}: missing keyword")
            continue
        if keyword.casefold() not in term.casefold():
            anomalies.append(f"Record {i + 1}: keyword '{term}' does not contain '{keyword}'")
        rank1 = get_rank(row.get("first_domain_serp_element"))
        rank2 = get_rank(row.get("second_domain_serp_element"))
        # The normalizer's direct rank values can be used when the nested records are absent.
        if rank1 is None and isinstance(row.get("our_rank"), int) and row["our_rank"] > 0:
            rank1 = row["our_rank"]
        if rank2 is None and isinstance(row.get("benchmark_rank"), int) and row["benchmark_rank"] > 0:
            rank2 = row["benchmark_rank"]
        if rank1 is None or rank2 is None:
            leader = "unknown (missing rank)"
            anomalies.append(f"Keyword '{term}': one or both organic ranks missing")
        elif rank1 < rank2:
            leader = "Domain 1"
        elif rank2 < rank1:
            leader = "Domain 2"
        else:
            leader = "tie"
        counts[leader] += 1
        valid.append((term, row.get("search_volume"), rank1, rank2, leader))
    for term, volume, rank1, rank2, leader in valid[:limit]:
        add(f"{term} | {volume if volume is not None else 'N/A'} | {('#'+str(rank1)) if rank1 is not None else 'N/A'} | {('#'+str(rank2)) if rank2 is not None else 'N/A'} | {leader}")
    if len(valid) > limit:
        add(f"... {len(valid) - limit} more rows not displayed; use --limit to show more")
    add()
    add("=== SUMMARY ===")
    add(f"Domain 1 ahead: {counts['Domain 1']}")
    add(f"Domain 2 ahead: {counts['Domain 2']}")
    add(f"Ties: {counts['tie']}")
    add(f"Rank comparison unavailable: {counts['unknown (missing rank)']}")
    add(f"Validation warnings: {len(anomalies)}")
    for warning in anomalies[:20]:
        add("WARN: " + warning)
    if len(anomalies) > 20:
        add(f"... {len(anomalies)-20} additional warnings")
    if not rows:
        add("WARN: No shared keyword rows returned; check the raw API response and filter.")
    add("Rankings are from the saved DataForSEO response, not a fresh Google SERP.")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keyword", default="aviator")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--file", type=Path, help="Optional normalized JSON file path")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    import re
    slug = re.sub(r"[^a-z0-9]+", "_", args.keyword.casefold()).strip("_")
    if not slug:
        parser.error("--keyword must contain letters or numbers")
    root = Path(__file__).resolve().parents[1]
    source = args.file or root / "data" / "processed" / slug / "domain_intersection.json"
    try:
        data = load_json(source)
        print(show_report(data, args.keyword, args.limit), end="")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
