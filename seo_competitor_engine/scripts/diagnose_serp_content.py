"""Read-only diagnostic of exact SERP ranking URLs, using the project's Playwright settings.

python -m scripts.diagnose_serp_content --keyword aviator
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


def _host(url):
    return (urlsplit(str(url or '')).hostname or '').lower().removeprefix('www.')


def _slug(keyword):
    from config.settings import keyword_slug
    return keyword_slug(keyword)


def load_targets(path, keyword):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if str(data.get('keyword', '')).casefold().strip() != keyword.casefold().strip():
        raise ValueError('Comparison JSON keyword does not match requested keyword')
    urls = data.get('primary_ranking_urls') or {}
    ours, benchmark = urls.get('ours'), urls.get('benchmark')
    if not all(isinstance(u, str) and urlsplit(u).scheme in ('http', 'https') and _host(u) for u in (ours, benchmark)):
        raise ValueError('Both exact SERP ranking URLs must exist in primary_ranking_urls')
    if _host(ours) == _host(benchmark):
        raise ValueError('Expected distinct comparison domains')
    return {'ours': ours, 'benchmark': benchmark}


JS = r'''() => {
 const norm = s => (s || '').replace(/\s+/g, ' ').trim();
 const words = s => norm(s) ? norm(s).split(' ').length : 0;
 const candidates = [...document.querySelectorAll('main, [role="main"], article')];
 const visible = el => !!(el.getClientRects().length) && getComputedStyle(el).visibility !== 'hidden';
 const unique = [...new Set(candidates)];
 const describe = el => {
   const text = norm(el.innerText);
   const clone = el.cloneNode(true);
   clone.querySelectorAll('nav, footer, header, aside, [role="navigation"], [role="contentinfo"], script, style, noscript').forEach(x => x.remove());
   const clean = norm(clone.textContent);
   return {tag: el.tagName.toLowerCase(), id: (el.id || '').slice(0,80),
     classes: [...el.classList].slice(0,6), visible: visible(el),
     rendered_words: words(text), stripped_words: words(clean),
     headings: el.querySelectorAll('h1,h2,h3').length,
     navigation_nodes: el.querySelectorAll('nav,footer,header,aside,[role="navigation"],[role="contentinfo"]').length,
     text_chars: text.length};
 };
 const body = norm(document.body?.innerText);
 return {title: document.title, body_words: words(body),
   h1_count: [...document.querySelectorAll('h1')].filter(visible).length,
   main_candidates: unique.slice(0,35).map(describe),
   main_candidates_total: unique.length,
   html_main_max_words: Math.max(0,...unique.map(x => words(x.textContent))),
   rendered_main_max_words: Math.max(0,...unique.map(x => words(x.innerText))),
   document_ready_state: document.readyState,
   blocked: /unusual traffic|verify you are a human|captcha|automated queries/i.test(body.slice(0,1500))};
}'''


def capture(url, browser_path, locale, timeout_ms=45000):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=browser_path)
        try:
            context = browser.new_context(viewport={'width':1366,'height':768}, locale=locale)
            page = context.new_page()
            response = page.goto(url, wait_until='domcontentloaded', timeout=timeout_ms)
            observations = []
            for delay in (0, 2500, 2500):
                if delay:
                    page.wait_for_timeout(delay)
                reading = page.evaluate(JS)
                reading['elapsed_wait_ms'] = sum((0, 2500, 2500)[:len(observations)+1])
                observations.append(reading)
            final = page.url
            return {'requested_url':url, 'final_url':final, 'http_status':response.status if response else None,
                    'exact_url_match':url.rstrip('/') == final.rstrip('/'),
                    'same_host':_host(url) == _host(final), 'observations':observations}
        finally:
            browser.close()


def summarize(result, side):
    lines = [f'[{side.upper()}]', f"SERP URL: {result.get('requested_url')}",
             f"Final URL: {result.get('final_url')}", f"HTTP status: {result.get('http_status')}",
             f"Exact URL match: {result.get('exact_url_match')}", f"Same host: {result.get('same_host')}"]
    if result.get('error'):
        lines.append('ERROR: ' + result['error'])
    for sample in result.get('observations', []):
        lines.append(f"  At {sample['elapsed_wait_ms']} ms: body_words={sample['body_words']}; html_main_max={sample['html_main_max_words']}; rendered_main_max={sample['rendered_main_max_words']}; h1={sample['h1_count']}; ready={sample['document_ready_state']}; blocked={sample['blocked']}")
        for i, c in enumerate(sample['main_candidates'], 1):
            lines.append(f"    Candidate {i}: {c['tag']} id={c['id']!r} classes={c['classes']}; visible={c['visible']}; rendered_words={c['rendered_words']}; stripped_words={c['stripped_words']}; headings={c['headings']}; navigation_nodes={c['navigation_nodes']}")
        if sample['main_candidates_total'] > len(sample['main_candidates']):
            lines.append('    Additional candidates omitted from text report')
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description='Read-only main-content diagnostic for exact saved SERP URLs')
    ap.add_argument('--keyword', required=True)
    ap.add_argument('--input', type=Path, help='Optional comparison JSON path')
    ap.add_argument('--no-browser', action='store_true', help='Inspect saved normalized page measurements only')
    args = ap.parse_args(argv)
    from config.settings import ROOT, settings
    slug = _slug(args.keyword)
    source = args.input or ROOT / 'output' / 'results' / slug / f'{slug}_comparison.json'
    targets = load_targets(source, args.keyword)
    out_dir = ROOT / 'output' / 'results' / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    data = json.loads(source.read_text(encoding='utf-8'))
    old_pages = data.get('page_level_evidence') or {}
    lines = ['PHASE 2 CONTENT DIAGNOSTIC', f'Keyword: {args.keyword}',
             f'Generated UTC: {datetime.now(timezone.utc).isoformat()}',
             'Targets sourced ONLY from primary_ranking_urls in the existing comparison JSON.',
             'No page text, cookies, credentials, or HTML exported.', '']
    for side, url in targets.items():
        previous = old_pages.get(side) or {}
        lines += [f'[{side.upper()} — SAVED NORMALIZED MEASUREMENTS]',
                  f"ranking_url={previous.get('ranking_url')}",
                  f"word_count={previous.get('word_count')}",
                  f"main_word_count={previous.get('main_word_count')}",
                  f"rendered_word_count={previous.get('rendered_word_count')}",
                  f"rendered_main_word_count={previous.get('rendered_main_word_count')}",
                  f"extraction_status={previous.get('extraction_status')}", '']
        if args.no_browser:
            continue
        if not settings.playwright_browser_path:
            raise RuntimeError('No Chrome/Edge executable detected; configure PLAYWRIGHT_BROWSER_PATH')
        try:
            result = capture(url, settings.playwright_browser_path, settings.language_code)
        except Exception as exc:
            result = {'requested_url':url, 'error':f'{type(exc).__name__}: {exc}'}
        lines += summarize(result, side) + ['']
    lines += ['INTERPRETATION NOTES:',
              '- Different HTML and rendered main counts can arise from hidden DOM nodes or different selection rules.',
              '- The largest main/article container may include navigation; stripped_words is diagnostic only.',
              '- A stable count does not prove that the correct SEO content was extracted.',
              '- A redirect or cross-host final URL requires review; do not silently substitute a different page.',
              '- No source data, normalized JSON, or collector scripts were changed.']
    output = out_dir / f'{slug}_phase2_content_diagnostic.txt'
    output.write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(f'Diagnostic saved: {output}')
    print('Share this text file for review. No paid API requests made.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
