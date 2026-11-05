from __future__ import annotations

import argparse
import json

from collectors.dataforseo_client import DataForSEOClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Test DataForSEO credentials without running SEO data collection.")
    parser.add_argument("--execute", action="store_true", help="Actually call DataForSEO. Without this flag, only show what would happen.")
    args = parser.parse_args()

    if not args.execute:
        print("DRY RUN: would call GET /v3/appendix/user_data")
        print("Run with --execute when your .env credentials are ready.")
        return

    client = DataForSEOClient()
    data = client.get("/v3/appendix/user_data")
    print(json.dumps({
        "status_code": data.get("status_code"),
        "status_message": data.get("status_message"),
        "tasks_error": data.get("tasks_error"),
    }, indent=2))
    print("Connection successful if status_code is 20000.")


if __name__ == "__main__":
    main()
