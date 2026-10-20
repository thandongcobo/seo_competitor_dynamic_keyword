from __future__ import annotations

import argparse

from collectors.dataforseo_client import load_json, save_json
from collectors.request_cache import cached_get
from collectors.dataforseo_client import DataForSEOClient
from collectors.serp_collector import extract_task_id, get_serp_advanced
from config.settings import RAW_DIR, settings, KEYWORD_SLUG


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch a previously created SERP task result.")
    parser.add_argument("--engine", choices=["google", "bing"], default="google")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    task_path = RAW_DIR / "serp" / f"{KEYWORD_SLUG}_{args.engine}_task.json"
    if not task_path.exists():
        raise SystemExit(f"Missing {task_path}. Run collect_serp first.")
    task_response = load_json(task_path)
    task_id = extract_task_id(task_response)
    endpoint = f"/v3/serp/{args.engine}/organic/task_get/advanced/{task_id}"

    if not args.execute:
        print("DRY RUN ONLY.")
        print("Endpoint:", endpoint)
        return

    client = DataForSEOClient()
    response, cache_hit = cached_get(client, endpoint, force=args.force)
    out = RAW_DIR / "serp" / f"{KEYWORD_SLUG}_{args.engine}_result.json"
    save_json(response, out)
    print("CACHE HIT - no new GET was made." if cache_hit else "SERP result retrieved and cached.")
    print(f"Saved SERP result: {out}")


if __name__ == "__main__":
    main()
