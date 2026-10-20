from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit, urlunsplit

from collectors.dataforseo_client import load_json, save_json
from collectors.playwright_collector import crawl_page
from config.settings import RAW_DIR, PROCESSED_DIR, settings, KEYWORD_SLUG
from scripts.resolve_pages import normalized_url


def crawl_output_filename(keyword_slug: str, engine: str, label: str, url: str, target: bool) -> str:
    """Keep legacy priority filenames; make candidate filenames URL-unique."""
    safe_label = re.sub(r"[^a-zA-Z0-9._-]+", "_", label).strip("._-")[:70] or "candidate"
    if target and label in {"ours", "benchmark"}:
        # Required by normalize_data.py for priority page normalization.
        return f"{keyword_slug}_{engine}_{label}.json"
    parsed = urlsplit(url.strip())
    canonical = urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", parsed.query, ""))
    url_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"{keyword_slug}_{engine}_{safe_label}_{url_id}.json"


def main() -> None:
    resolved = PROCESSED_DIR / "resolved_candidates.json"
    if not resolved.exists():
        raise SystemExit("Run python -m scripts.resolve_pages --engine all first.")
    data = load_json(resolved)

    urls: list[tuple[str, str, str, int | None, bool]] = []
    for engine in ["google", "bing"]:
        comparison = (data.get("engines", {}).get(engine, {}).get("comparison") or {})
        if comparison.get("our_url"):
            urls.append(("ours", engine, comparison["our_url"], comparison.get("our_position"), True))
        if comparison.get("benchmark_url"):
            urls.append(("benchmark", engine, comparison["benchmark_url"], comparison.get("benchmark_position"), True))

        candidates = data.get("engines", {}).get(engine, {}).get("candidates", [])
        for candidate in candidates[: settings.candidate_crawl_limit]:
            if candidate.get("url"):
                label = candidate.get("domain") or "candidate"
                urls.append((label, engine, candidate["url"], candidate.get("rank_group"), False))

    seen: set[tuple] = set()
    unique: list[tuple[str, str, str, int | None, bool]] = []
    for row in urls:
        # Keep distinct engine-specific priority snapshots, even for the same URL.
        key = (row[1], row[0] if row[4] else "candidate", normalized_url(row[2]))
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)

    for label, engine, url, rank, target in unique:
        print(f"Crawling {label} [{engine}] rank={rank}: {url}")
        try:
            page_data = crawl_page(url)
        except Exception as exc:
            page_data = {
                "requested_url": url,
                "final_url": None,
                "status_code": None,
                "crawl_failed": True,
                "error": str(exc),
            }
        page_data.update({
            "keyword": settings.keyword, "serp_engine": engine,
            "ranking_url": url, "ranking_position": rank,
            "target_side": label if target else "candidate",
            "evidence_scope": "page",
        })
        if page_data.get("requested_url") and normalized_url(page_data["requested_url"]) != normalized_url(url):
            page_data["url_alignment"] = "requested_url_mismatch"
        elif page_data.get("final_url") and normalized_url(page_data["final_url"]) != normalized_url(url):
            page_data["url_alignment"] = "redirected_from_ranking_url"
        else:
            page_data["url_alignment"] = "matched" if page_data.get("final_url") else "unverified"
        filename = crawl_output_filename(KEYWORD_SLUG, engine, label, url, target)
        out = RAW_DIR / "pages" / filename
        save_json(page_data, out)
        print(f"Saved: {out}")


if __name__ == "__main__":
    main()
