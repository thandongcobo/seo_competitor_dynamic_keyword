"""Read-only live visibility diagnostic for the exact URLs in comparison JSON."""
from __future__ import annotations
import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from collectors.main_content import extract_main_content
from config.settings import settings

# No content strings are returned or written, only structural statistics.
JS_DIAGNOSTIC = r'''() => {
 const clean = s => (s || '').replace(/\s+/g,' ').trim();
 const count = s => clean(s) ? clean(s).split(' ').length : 0;
 const excluded = 'nav,footer,header,aside,[role="navigation"],[role="menu"],[role="menubar"],[role="dialog"],button,input,select,textarea,[hidden],[aria-hidden="true"],script,style,noscript,svg';
 const visible = el => {
   if (!el || !el.isConnected || el.closest('[hidden],[aria-hidden="true"]')) return false;
   const st = getComputedStyle(el);
   return st.display !== 'none' && st.visibility !== 'hidden' && st.visibility !== 'collapse' && !!el.getClientRects().length;
 };
 const ancestorHidden = (el, root) => {
   while (el && el !== root.parentElement) {
     if (!visible(el)) return true;
     el = el.parentElement;
   }
   return false;
 };
 const candidates = [...document.querySelectorAll('main,[role="main"],article')].filter(visible);
 const result = candidates.map((el, i) => {
   const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
   let legacyWords = 0, strictWords = 0, hiddenAncestorWords = 0, excludedWords = 0;
   while (walker.nextNode()) {
     const n = walker.currentNode, parent = n.parentElement;
     const words = count(n.nodeValue);
     if (!words || !parent) continue;
     if (parent.closest(excluded)) { excludedWords += words; continue; }
     if (!visible(parent)) continue;
     legacyWords += words;
     if (ancestorHidden(parent, el)) hiddenAncestorWords += words;
     else strictWords += words;
   }
   const direct = [...el.children].map((child, j) => ({
     child_index:j, tag:child.tagName.toLowerCase(),
     role:child.getAttribute('role') || null,
     rendered_words:count(child.innerText),
     visible:visible(child),
     excluded:child.matches(excluded),
     descendant_navigation:child.querySelectorAll('nav,[role="navigation"],[role="menu"]').length
   })).sort((a,b)=>b.rendered_words-a.rendered_words).slice(0,12);
   return {candidate_index:i,tag:el.tagName.toLowerCase(),
     id:el.id || null, role:el.getAttribute('role') || null,
     rendered_innertext_words:count(el.innerText),
     html_text_words:count(el.textContent),
     legacy_textnode_words:legacyWords,
     strict_ancestor_visible_words:strictWords,
     hidden_ancestor_words: hiddenAncestorWords,
     excluded_textnode_words:excludedWords,
     headings:el.querySelectorAll('h1,h2,h3').length,
     navigation_nodes:el.querySelectorAll('nav,[role="navigation"],[role="menu"]').length,
     top_direct_children:direct};
 });
 return {body_innertext_words:count(document.body?.innerText),
         document_ready_state:document.readyState,
         candidate_count:result.length, candidates:result};
}'''


def slugify(keyword: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', keyword.lower()).strip('_')


def get_targets(data: dict, keyword: str) -> dict:
    if str(data.get('keyword', '')).casefold() != keyword.casefold():
        raise ValueError('Comparison JSON keyword does not match requested keyword')
    targets = data.get('primary_ranking_urls') or {}
    for side in ('ours', 'benchmark'):
        url = targets.get(side)
        parsed = urlsplit(url or '')
        if parsed.scheme not in ('https', 'http') or not parsed.netloc:
            raise ValueError(f'Missing or invalid primary SERP ranking URL: {side}')
    return {side: targets[side] for side in ('ours', 'benchmark')}


def run_diagnostic(keyword: str, *, comparison_path: Path, output_path: Path, browser_path: str,
                   waits=(0, 2500, 5000)) -> dict:
    from playwright.sync_api import sync_playwright
    data = json.loads(comparison_path.read_text(encoding='utf-8'))
    targets = get_targets(data, keyword)
    output = {'keyword': keyword, 'generated_utc': datetime.now(timezone.utc).isoformat(),
              'source': str(comparison_path), 'note': 'Statistics only. No page text or HTML saved.', 'pages': {}}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=browser_path, headless=True)
        try:
            for side, url in targets.items():
                page = browser.new_page(viewport={'width': 1366, 'height': 768}, locale='en-ZA')
                entry = {'ranking_url': url, 'snapshots': []}
                output['pages'][side] = entry
                try:
                    response = page.goto(url, wait_until='domcontentloaded', timeout=60000)
                    entry['http_status'] = response.status if response else None
                    entry['final_url'] = page.url
                    entry['exact_url_match'] = page.url.rstrip('/') == url.rstrip('/')
                    start = time.monotonic()
                    for delay in waits:
                        remaining = delay / 1000 - (time.monotonic() - start)
                        if remaining > 0:
                            page.wait_for_timeout(round(remaining * 1000))
                        measurement = page.evaluate(JS_DIAGNOSTIC)
                        extractor = extract_main_content(page)
                        entry['snapshots'].append({
                            'target_ms': delay, 'actual_elapsed_ms': round((time.monotonic()-start)*1000),
                            **measurement,
                            'current_extractor_words': extractor.get('seo_content_word_count'),
                            'current_extractor_status': extractor.get('seo_content_status'),
                            'current_extractor_selector': extractor.get('seo_content_selector'),
                        })
                except Exception as exc:
                    entry['error'] = f'{type(exc).__name__}: {str(exc)[:240]}'
                finally:
                    page.close()
        finally:
            browser.close()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2), encoding='utf-8')
    return output


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Diagnose visible vs hidden main-content measurements')
    parser.add_argument('--keyword', default='aviator')
    parser.add_argument('--input', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    slug = slugify(args.keyword)
    if not slug:
        parser.error('Keyword cannot be empty')
    root = Path(__file__).resolve().parents[1]
    source = args.input or root / 'output' / 'results' / slug / f'{slug}_comparison.json'
    dest = args.output or root / 'output' / 'results' / slug / f'{slug}_visibility_diagnostic.json'
    if not source.is_file():
        parser.error(f'Comparison JSON not found: {source}')
    browser_path = settings.playwright_browser_path
    if not browser_path:
        parser.error('Browser path not configured in PLAYWRIGHT_BROWSER_PATH')
    result = run_diagnostic(args.keyword, comparison_path=source, output_path=dest, browser_path=browser_path)
    print(f'Diagnostic saved: {dest}')
    for side, item in result['pages'].items():
        final = item['snapshots'][-1] if item['snapshots'] else {}
        print(f"{side}: exact_url={item.get('exact_url_match')}; body_words={final.get('body_innertext_words')}; extractor_words={final.get('current_extractor_words')}; error={item.get('error')}")
    print('Please share the generated visibility diagnostic JSON; it contains structural counts only.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
