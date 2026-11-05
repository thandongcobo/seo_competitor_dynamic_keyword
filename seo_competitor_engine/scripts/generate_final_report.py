"""Generate the final Markdown report from a keyword-scoped comparison JSON.

Usage: python -m scripts.generate_final_report --keyword aviator
No external dependencies or API calls.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from analysis.final_report import generate_report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate an evidence-based SEO Markdown report (offline)")
    parser.add_argument("--keyword", required=True, help="Keyword previously analysed")
    parser.add_argument("--input", type=Path, help="Optional explicit comparison JSON path")
    parser.add_argument("--output", type=Path, help="Optional explicit Markdown output path")
    args = parser.parse_args(argv)

    # Import from existing project for the exact same keyword slug convention.
    from config.settings import keyword_slug

    slug = keyword_slug(args.keyword)
    root = Path(__file__).resolve().parents[1]
    default_dir = root / "output" / "results" / slug
    source = args.input or default_dir / f"{slug}_comparison.json"
    destination = args.output or default_dir / f"{slug}_full_seo_report.md"
    if not source.is_file():
        print(f"ERROR: comparison JSON not found: {source}", file=sys.stderr)
        print("Run the analysis stage first, or pass --input PATH.", file=sys.stderr)
        return 2
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
        actual = str(data.get("keyword") or "").strip().casefold()
        requested = args.keyword.strip().casefold()
        if actual != requested:
            raise ValueError(f"Keyword mismatch: file contains {actual!r}, requested {requested!r}")
        report = generate_report(data, source_name=source.name)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: report generation failed: {exc}", file=sys.stderr)
        return 1
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(report, encoding="utf-8")
    print("Final SEO report generated:", destination)
    print("Keyword:", args.keyword)
    print("Sections: 9 | Recommendations:", len(data.get("recommendations") or []))
    print("Offline: no API requests or credits used")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
