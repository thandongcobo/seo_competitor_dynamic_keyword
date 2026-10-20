from __future__ import annotations

import argparse
import json

from collectors.backlinks_collector import summary_payload, backlinks_payload
from collectors.dataforseo_client import DataForSEOClient, load_json, save_json
from collectors.request_cache import cached_post
from config.settings import RAW_DIR, PROCESSED_DIR, settings, KEYWORD_SLUG
from scripts.resolve_pages import require_target


def resolve_target(side: str, level: str, engine: str = "google") -> str:
    if level == "domain":
        return settings.our_domain if side == "ours" else settings.benchmark_competitor_domain
    # Explicitly reject .env page overrides: only SERP-observed URLs are eligible.
    return require_target(side, engine)["ranking_url"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one Backlinks API request at a time.")
    parser.add_argument("--side", choices=["ours", "benchmark"], required=True)
    parser.add_argument("--level", choices=["domain", "page"], default="page")
    parser.add_argument("--engine", choices=["google", "bing"], default="google", help="Ranking source for page-level targets")
    parser.add_argument("--type", choices=["summary", "sample"], default="summary")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--force", action="store_true", help="Deliberately bypass the local paid-request cache.")
    args = parser.parse_args()

    if args.limit < 1 or args.limit > 1000:
        raise SystemExit("--limit must be between 1 and 1000")

    target = resolve_target(args.side, args.level, args.engine)
    if args.type == "summary":
        endpoint = "/v3/backlinks/summary/live"
        payload = summary_payload(target, include_subdomains=(args.level == "domain"))
    else:
        endpoint = "/v3/backlinks/backlinks/live"
        payload = backlinks_payload(target, limit=args.limit)

    print("Endpoint:", endpoint)
    print("Target:", target)
    print("Payload:")
    print(json.dumps(payload, indent=2))

    if not args.execute:
        print("\nDRY RUN ONLY. Add --execute to make the paid Backlinks request.")
        return

    client = DataForSEOClient()
    response, cache_hit = cached_post(client, endpoint, payload, force=args.force)
    suffix = "benchmark" if args.side == "benchmark" else "ours"
    engine_suffix = f"_{args.engine}" if args.level == "page" and args.engine != "google" else ""
    out = RAW_DIR / "backlinks" / f"{KEYWORD_SLUG}_{suffix}_{args.level}_{args.type}{engine_suffix}.json"
    save_json(response, out)
    save_json({"keyword": settings.keyword, "side": args.side, "scope": args.level,
               "engine": args.engine if args.level == "page" else None,
               "target": target, "endpoint": endpoint}, out.with_suffix(".meta.json"))
    print("CACHE HIT - no new paid request was made." if cache_hit else "API request completed and cached.")
    print(f"Saved: {out}")
    print("Reported request cost (USD):", response.get("cost"))


if __name__ == "__main__":
    main()
