from __future__ import annotations

import argparse
import subprocess
import sys


def run(cmd: list[str]) -> None:
    print("\n>>>", " ".join(cmd))
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the complete MVP pipeline. Labs/Backlinks require --execute; SERP uses Playwright.")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--skip-bing", action="store_true")
    parser.add_argument("--skip-backlinks", action="store_true")
    parser.add_argument("--skip-playwright-pages", action="store_true")
    args = parser.parse_args()

    py = sys.executable

    # Ranking collection is always local Playwright; it does not spend DataForSEO credits.
    for engine in (["google"] if args.skip_bing else ["google", "bing"]):
        run([py, "-m", "scripts.collect_playwright_serp", "--engine", engine])

    # Resolve exact URLs before any API or page-level collector can run.
    run([py, "-m", "scripts.resolve_pages", "--engine", "google" if args.skip_bing else "all"])
    if not args.execute:
        print("\nSERP collection and URL resolution completed. Paid Labs/Backlinks were not called.")
        return

    for action in ["search_intent", "keyword_overview", "ranked_ours", "ranked_benchmark", "competitors_domain", "domain_intersection"]:
        run([py, "-m", "scripts.collect_labs", "--action", action, "--limit", "100", "--execute"])

    if not args.skip_backlinks:
        for side in ["ours", "benchmark"]:
            run([py, "-m", "scripts.collect_backlinks", "--side", side, "--level", "domain", "--type", "summary", "--execute"])
            run([py, "-m", "scripts.collect_backlinks", "--side", side, "--level", "page", "--type", "summary", "--execute"])

    if not args.skip_playwright_pages:
        run([py, "-m", "scripts.crawl_pages"])

    run([py, "-m", "scripts.normalize_data"])
    run([py, "-m", "scripts.run_analysis"])
    print("\nCOMPLETE MVP PIPELINE FINISHED")


if __name__ == "__main__":
    main()
