"""Keyword-aware CLI dispatcher. Each stage runs independently; paid calls require --execute."""
from __future__ import annotations
import argparse
import os
import subprocess
import sys

STAGES = {
    "serp": "scripts.collect_team_serp",
    "resolve": "scripts.resolve_pages",
    "labs": "scripts.collect_labs",
    "backlinks": "scripts.collect_backlinks",
    "crawl": "scripts.crawl_pages",
    "lighthouse": "scripts.collect_lighthouse",
    "normalize": "scripts.normalize_data",
    "analyze": "scripts.run_analysis",
}

def main():
    p = argparse.ArgumentParser(description="Run a single keyword-scoped pipeline stage")
    p.add_argument("--keyword", required=True)
    p.add_argument("--stage", required=True, choices=STAGES)
    p.add_argument("stage_args", nargs=argparse.REMAINDER)
    args = p.parse_args()
    if not args.keyword.strip():
        p.error("--keyword cannot be empty")
    env = dict(os.environ, SEO_KEYWORD=args.keyword.strip(), SEO_NAMESPACE_OUTPUT="1")
    extra = args.stage_args[1:] if args.stage_args[:1] == ['--'] else args.stage_args
    cmd = [sys.executable, '-m', STAGES[args.stage], *extra]
    print('Keyword:', args.keyword, '| Stage:', args.stage, '| Command:', ' '.join(cmd), flush=True)
    raise SystemExit(subprocess.call(cmd, env=env))

if __name__ == '__main__':
    main()
