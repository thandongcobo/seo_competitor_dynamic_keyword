"""Read-only, keyword/URL-scoped retrieval of previously saved SEO investigations.

No API calls, scraping, Gemma inference or database migrations. This module
can also be imported by a future dashboard history endpoint.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def _json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeError):
        return None


def _url_key(url):
    if not isinstance(url, str):
        return ''
    try:
        parts = urlsplit(url.strip())
        if parts.scheme.lower() not in ('http', 'https') or not parts.hostname:
            return ''
        host = parts.hostname.lower().removeprefix('www.')
        path = (parts.path or '/').rstrip('/') or '/'
        return urlunsplit(('', host, path, parts.query, ''))
    except ValueError:
        return ''


def search_history(data_root, *, keyword=None, url_a=None, url_b=None, limit=50):
    """Return saved runs and verified artifact locations; never mix investigations.

    Both URLs, when supplied, match the saved exact-page selection regardless
    of A/B order. A report is returned only if its file is in that investigation.
    """
    root = Path(data_root)
    if not root.is_dir():
        return []
    wanted = (keyword or '').strip().casefold()
    a, b = _url_key(url_a), _url_key(url_b)
    matches = []
    for folder in root.iterdir():
        if not folder.is_dir() or len(folder.name) != 32 or any(c not in '0123456789abcdef' for c in folder.name):
            continue
        selection = _json(folder / 'selection.json')
        if not isinstance(selection, dict) or selection.get('investigation_id') != folder.name:
            continue
        if wanted and str(selection.get('keyword') or '').strip().casefold() != wanted:
            continue
        first = (selection.get('ours') or {}).get('url')
        second = (selection.get('benchmark') or {}).get('url')
        saved = {_url_key(first), _url_key(second)}
        if (a and a not in saved) or (b and b not in saved) or (a and b and a == b):
            continue
        reporting = _json(folder / 'reporting' / 'status.json') or {}
        offline = _json(folder / 'offline_execution.json') or {}
        run_id = reporting.get('run_id')
        run = folder / 'reporting' / 'runs' / run_id if isinstance(run_id, str) and len(run_id) == 32 and all(c in '0123456789abcdef' for c in run_id) else None
        reports = {}
        if run:
            # Return files only from this investigation and the exact saved run.
            report_dir = run / 'reports'
            if report_dir.is_dir():
                for candidate in report_dir.iterdir():
                    if candidate.is_file() and candidate.suffix.lower() in ('.pdf', '.md', '.json'):
                        reports[candidate.name] = str(candidate.relative_to(root))
        matches.append({'investigation_id': folder.name, 'keyword': selection.get('keyword'),
                        'created_at': selection.get('created_at'),
                        'page_a_url': first, 'page_b_url': second,
                        'offline_status': offline.get('status', selection.get('status', 'unknown')),
                        'reporting_status': reporting.get('status', 'not_started'),
                        'run_id': run_id, 'reports': reports})
    matches.sort(key=lambda r: str(r.get('created_at') or ''), reverse=True)
    return matches[:max(0, min(int(limit), 500))]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, default=Path(__file__).resolve().parents[1] / 'data' / 'investigations')
    parser.add_argument('--keyword', help='Exact saved keyword (case-insensitive)')
    parser.add_argument('--url-a', help='Optional exact saved ranking URL')
    parser.add_argument('--url-b', help='Optional second exact saved ranking URL')
    parser.add_argument('--limit', type=int, default=25)
    args = parser.parse_args(argv)
    print(json.dumps(search_history(args.data_root, keyword=args.keyword, url_a=args.url_a,
                                    url_b=args.url_b, limit=args.limit), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
