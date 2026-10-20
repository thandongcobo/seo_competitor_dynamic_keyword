"""One-shot Google SERP collection through the original teammate functions."""
from __future__ import annotations

import argparse
import os
import sys
# Parse keyword before loading config, so every module sees the same keyword.
_pre = argparse.ArgumentParser(add_help=False)
_pre.add_argument('--keyword')
_pre_args, _remaining = _pre.parse_known_args()
if _pre_args.keyword:
    os.environ['SEO_KEYWORD'] = _pre_args.keyword
    sys.argv = [sys.argv[0]] + _remaining
from datetime import datetime, timezone
from pathlib import Path

from collectors.team_serp_adapter import collect_once, save_diagnostic, save_success
from config.settings import RAW_DIR, settings, KEYWORD_SLUG


def main() -> None:
    parser = argparse.ArgumentParser(description='Run teammate original Google collector once; save engine-compatible JSON.')
    parser.add_argument('--refresh', action='store_true', help='Explicitly collect again even when successful JSON exists.')
    parser.add_argument('--depth', type=int, default=50, help='Maximum organic results to collect (1-50).')
    parser.add_argument('--fresh-profile-test', action='store_true', help='Run once with isolated new Chrome profile; save separate comparison JSON.')
    args = parser.parse_args()
    if not 1 <= args.depth <= 50:
        parser.error("--depth must be between 1 and 50")
    target = RAW_DIR / 'serp' / (f'{KEYWORD_SLUG}_google_fresh_profile_test.json' if args.fresh_profile_test else f'{KEYWORD_SLUG}_google_playwright.json')
    if target.exists() and not args.refresh:
        import json
        try:
            existing = json.loads(target.read_text(encoding='utf-8'))
            if existing.get('status') in ('ok', 'partial') and existing.get('organic_results'):
                print(f'Existing successful SERP retained: {target}')
                print('No Google request made. Use --refresh only if you intentionally want a new snapshot.')
                return
        except (OSError, ValueError):
            pass

    print(f'Collecting Google SERP once with original teammate search/parser for {settings.keyword!r}.')
    print('This uses Google gl=za, not the precise coordinate parameter.')
    try:
        result = collect_once(settings.keyword, fresh_profile_test=args.fresh_profile_test, depth=args.depth)
    except Exception as exc:
        diagnostic = {
            'status': 'blocked' if ('blocked' in type(exc).__name__.lower() or 'challenge' in str(exc).lower()) else 'failed',
            'reason': str(exc), 'engine': 'google', 'keyword': settings.keyword,
            'datetime': datetime.now(timezone.utc).isoformat(),
            'collection_method': 'playwright_local_browser',
        }
        print(f'Collection unsuccessful: {diagnostic["reason"]}')
        if args.fresh_profile_test:
            diagnostic_path = RAW_DIR / 'serp' / f'{KEYWORD_SLUG}_google_fresh_profile_test_error.json'
            diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
            diagnostic_path.write_text(__import__('json').dumps(diagnostic, indent=2), encoding='utf-8')
            print(f'Diagnostic: {diagnostic_path}')
        else:
            print(f'Diagnostic: {save_diagnostic(diagnostic)}')
        raise SystemExit(2)

    if args.fresh_profile_test:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(__import__('json').dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
        path = target
    else:
        # Preserve previous successful snapshot before writing the new one.
        if target.exists():
            import shutil
            from datetime import datetime as _dt
            archive = RAW_DIR / 'serp' / 'archive'
            archive.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, archive / f'{KEYWORD_SLUG}_google_{_dt.now().strftime("%Y%m%d_%H%M%S_%f")}.json')
        path = save_success(result)
    print(f'Diagnostics: data/diagnostics/google/{KEYWORD_SLUG}_page_1_serp.png (and later pages)')
    print(f"SERP STATUS: {result['status']}; organic results: {result['organic_results_count']}/{args.depth}; pages: {result['pages_completed']}; stop: {result['stop_reason']}")
    print(f'Saved: {path}')


if __name__ == '__main__':
    main()
