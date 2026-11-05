"""Recrawl one resolved primary page without revisiting other candidates.

Run from project root:
  python -m scripts.recrawl_priority_page --keyword aviator --engine google --side benchmark
"""
from __future__ import annotations

import argparse
from urllib.parse import urlsplit, urlunsplit

from collectors.dataforseo_client import load_json, save_json
from collectors.playwright_collector import crawl_page
from config.settings import ROOT, keyword_slug


def normalized_url(url: str) -> str:
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(),
                       (parts.path or "/").rstrip("/") or "/", parts.query, ""))


def main() -> None:
    parser = argparse.ArgumentParser(description="Recrawl one exact resolved ranking URL")
    parser.add_argument("--keyword", required=True)
    parser.add_argument("--engine", choices=["google", "bing"], default="google")
    parser.add_argument("--side", choices=["ours", "benchmark"], required=True)
    args = parser.parse_args()
    slug = keyword_slug(args.keyword)
    resolved_path = ROOT / "data" / "processed" / slug / "resolved_candidates.json"
    if not resolved_path.exists():
        parser.error(f"Missing {resolved_path}. Resolve the SERP first.")
    resolved = load_json(resolved_path)
    if str(resolved.get("keyword", "")).strip().lower() != args.keyword.strip().lower():
        parser.error("Resolved data keyword does not match the requested keyword.")
    comparison = (resolved.get("engines", {}).get(args.engine, {}).get("comparison") or {})
    url_key = "our_url" if args.side == "ours" else "benchmark_url"
    position_key = "our_position" if args.side == "ours" else "benchmark_position"
    url = comparison.get(url_key)
    if not url:
        parser.error(f"No resolved {args.side} URL for {args.engine}.")

    output = ROOT / "data" / "raw" / "pages" / f"{slug}_{args.engine}_{args.side}.json"
    print(f"Recrawling {args.side} [{args.engine}] {url}", flush=True)
    page_data = crawl_page(url)
    page_data.update({
        "keyword": args.keyword, "serp_engine": args.engine,
        "ranking_url": url, "ranking_position": comparison.get(position_key),
        "target_side": args.side, "evidence_scope": "page",
    })
    if page_data.get("requested_url") and normalized_url(page_data["requested_url"]) != normalized_url(url):
        page_data["url_alignment"] = "requested_url_mismatch"
    elif page_data.get("final_url") and normalized_url(page_data["final_url"]) != normalized_url(url):
        page_data["url_alignment"] = "redirected_from_ranking_url"
    else:
        page_data["url_alignment"] = "matched" if page_data.get("final_url") else "unverified"

    output.parent.mkdir(parents=True, exist_ok=True)
    # Overwrite only this side's existing raw crawl, never paid API caches.
    save_json(page_data, output)
    print(f"Saved: {output}")
    print("Extraction status:", page_data.get("extraction_status", "unknown"))
    print("Body words:", page_data.get("word_count"))
    print("Rendered main words:", page_data.get("rendered_main_word_count"))
    print("H1 count:", page_data.get("h1_count"))
    print("Content reason:", page_data.get("content_quality_reason"))
    print("URL alignment:", page_data.get("url_alignment"))
    if page_data.get("extraction_status") != "complete":
        print("REVIEW: Content not confirmed. See local diagnostics before normalizing.")


if __name__ == "__main__":
    main()
