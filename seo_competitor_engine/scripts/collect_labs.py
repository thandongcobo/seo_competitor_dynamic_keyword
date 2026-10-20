from __future__ import annotations

import argparse
import json

from collectors.dataforseo_client import DataForSEOClient, save_json
from collectors.request_cache import cached_post
from collectors.labs_collector import (
    keyword_overview_payload,
    search_intent_payload,
    domain_intersection_payload,
    ranked_keywords_payload,
    competitors_domain_payload,
)
from config.settings import RAW_DIR, settings, KEYWORD_SLUG


def build(action: str, limit: int):
    loc = settings.labs_location_name
    lang = settings.language_code
    if action == "keyword_overview":
        return "/v3/dataforseo_labs/google/keyword_overview/live", keyword_overview_payload(settings.keyword, loc, lang)
    if action == "search_intent":
        return "/v3/dataforseo_labs/google/search_intent/live", search_intent_payload(settings.keyword)
    if action == "domain_intersection":
        return "/v3/dataforseo_labs/google/domain_intersection/live", domain_intersection_payload(settings.our_domain, settings.benchmark_competitor_domain, loc, lang, limit, keyword=settings.keyword)
    if action == "ranked_ours":
        return "/v3/dataforseo_labs/google/ranked_keywords/live", ranked_keywords_payload(settings.our_domain, loc, lang, limit)
    if action == "ranked_benchmark":
        return "/v3/dataforseo_labs/google/ranked_keywords/live", ranked_keywords_payload(settings.benchmark_competitor_domain, loc, lang, limit)
    if action == "competitors_domain":
        return "/v3/dataforseo_labs/google/competitors_domain/live", competitors_domain_payload(settings.our_domain, loc, lang, limit)
    raise ValueError(action)


def main() -> None:
    actions = ["keyword_overview", "search_intent", "domain_intersection", "ranked_ours", "ranked_benchmark", "competitors_domain"]
    parser = argparse.ArgumentParser(description="Run one DataForSEO Labs request at a time.")
    parser.add_argument("--action", choices=actions, required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--force", action="store_true", help="Deliberately bypass the local paid-request cache.")
    args = parser.parse_args()

    if args.limit < 1 or args.limit > 1000:
        raise SystemExit("--limit must be between 1 and 1000")

    endpoint, payload = build(args.action, args.limit)
    print("Endpoint:", endpoint)
    print("Payload:")
    print(json.dumps(payload, indent=2))

    if args.action == "domain_intersection":
        print("Scope: shared organic keywords containing the input phrase (case-insensitive).")
        print("This is domain-level evidence, not a crawl of ranking URLs or a keyword-gap API.")

    if not args.execute:
        print("\nDRY RUN ONLY. Add --execute to make the paid Labs request.")
        return

    client = DataForSEOClient()
    response, cache_hit = cached_post(client, endpoint, payload, force=args.force)
    out = RAW_DIR / "labs" / f"{KEYWORD_SLUG}_{args.action}.json"
    save_json(response, out)
    print("CACHE HIT - no new paid request was made." if cache_hit else "API request completed and cached.")
    print(f"Saved: {out}")
    print("Reported request cost (USD):", response.get("cost"))


if __name__ == "__main__":
    main()
