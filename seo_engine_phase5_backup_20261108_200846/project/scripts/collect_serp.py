from __future__ import annotations

import argparse
import json

from collectors.dataforseo_client import DataForSEOClient, save_json
from collectors.request_cache import cached_post
from collectors.serp_collector import build_serp_task, post_serp_task, extract_task_id
from config.settings import RAW_DIR, settings, KEYWORD_SLUG


def main() -> None:
    parser = argparse.ArgumentParser(description="Create one controlled Google/Bing organic SERP task.")
    parser.add_argument("--engine", choices=["google", "bing"], default="google")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--force", action="store_true", help="Deliberately bypass the local paid-request cache.")
    args = parser.parse_args()

    payload = build_serp_task(
        settings.keyword,
        settings.location_coordinate,
        settings.language_code,
        depth=settings.serp_depth,
        priority=1,
        device="desktop",
        os="windows",
    )
    endpoint = f"/v3/serp/{args.engine}/organic/task_post"

    print("Endpoint:", endpoint)
    print("Payload:")
    print(json.dumps(payload, indent=2))

    if not args.execute:
        print("\nDRY RUN ONLY. Add --execute to create the paid SERP task.")
        return

    client = DataForSEOClient()
    response, cache_hit = cached_post(client, endpoint, payload, force=args.force)
    out = RAW_DIR / "serp" / f"{KEYWORD_SLUG}_{args.engine}_task.json"
    save_json(response, out)
    print("CACHE HIT - no new paid task was created." if cache_hit else "SERP task submitted and cached.")
    print(f"Saved: {out}")
    if not cache_hit:
        print("Task ID:", extract_task_id(response))
        print("Reported task cost (USD):", response.get("cost"))


if __name__ == "__main__":
    main()
