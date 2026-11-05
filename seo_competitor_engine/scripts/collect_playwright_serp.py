from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
from collectors.playwright_serp_collector import collect_engine_serp, save_engine_serp
from config.settings import RAW_DIR, settings, KEYWORD_SLUG


def main() -> None:
    parser = argparse.ArgumentParser(description="One-shot browser SERP collection")
    parser.add_argument("--engine", choices=["google", "bing"], required=True)
    args = parser.parse_args()
    safe_keyword = re.sub(r"[^a-zA-Z0-9_-]+", "_", settings.keyword).strip("_")
    previous = RAW_DIR / "serp" / f"{safe_keyword}_{args.engine}_playwright.json"
    if previous.exists():
        try:
            old = json.loads(previous.read_text(encoding="utf-8"))
            if old.get("status") == "ok" and len(old.get("organic_results") or []) >= 5:
                print(f"CACHED SUCCESS: {previous}")
                print("No browser request was made. Archive/rename the file before intentionally collecting a new snapshot.")
                return
        except (OSError, ValueError):
            pass
    print(f"One-shot {args.engine.upper()} search for {settings.keyword!r} using local Chrome.")
    print("Search country hint: ZA. This does not force precise GPS coordinates.")
    data = collect_engine_serp(args.engine, settings.keyword)
    path = save_engine_serp(args.engine, data)
    print(f"SERP STATUS: {data.get('status', 'unknown').upper()}")
    print(f"Saved: {path}")
    if data.get("status") != "ok":
        print(data.get("reason", "Capture not accepted"))
        raise SystemExit(2)
    print(f"Organic results: {len(data['organic_results'])}; scope: first page only")

if __name__ == "__main__":
    main()
