"""Extract comparable browser-rendered content from the actual SERP ranking page.

The browser's live innerText is the word-count authority. Navigation and UI
subtrees are hidden *temporarily*, then restored before returning. This is not
a semantic guarantee that every visible word is relevant to the keyword.
"""
from __future__ import annotations

EXTRACTION_VERSION = "rendered-main-innertext-v2"

JS_EXTRACT = r'''() => {
  const count = s => (s || '').trim().split(/\s+/).filter(Boolean).length;
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const excluded = 'nav,footer,header,aside,[role="navigation"],[role="menu"],[role="menubar"],[role="dialog"],button,input,select,textarea,[hidden],[aria-hidden="true"],script,style,noscript,svg';
  const visible = el => {
    if (!el || !el.isConnected || el.closest('[hidden],[aria-hidden="true"]')) return false;
    const st = getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden' || st.visibility === 'collapse') return false;
    return el.getClientRects().length > 0;
  };
  const candidates = [...document.querySelectorAll('main,[role="main"],article')].filter(visible);
  const stats = candidates.map((el, i) => {
    const nodes = [...el.querySelectorAll(excluded)];
    // Read the *live* DOM: detached clones do not inherit the page's CSS.
    // Inline styles are restored exactly, even if innerText throws.
    const originals = [];
    let text = '';
    try {
      for (const node of nodes) {
        originals.push([node, node.getAttribute('style')]);
        node.style.setProperty('display', 'none', 'important');
      }
      text = clean(el.innerText);
    } finally {
      for (let j = originals.length - 1; j >= 0; j--) {
        const [node, style] = originals[j];
        if (style === null) node.removeAttribute('style');
        else node.setAttribute('style', style);
      }
    }
    const sameTagSiblings = [...el.parentElement.children].filter(x => x.tagName === el.tagName);
    const selector = el.id ? '#' + CSS.escape(el.id) :
      el.tagName.toLowerCase() + ':nth-of-type(' + (sameTagSiblings.indexOf(el) + 1) + ')';
    return {index:i, tag:el.tagName.toLowerCase(), id:el.id || '', selector,
      words:count(text), text, headings:el.querySelectorAll('h1,h2,h3').length,
      excluded_nodes:nodes.length};
  });
  const mains = stats.filter(x => x.tag === 'main');
  const pool = mains.length ? mains : stats;
  pool.sort((a,b) => (b.words >= 60 ? 1:0) - (a.words >= 60 ? 1:0) || b.headings-a.headings || b.words-a.words);
  const chosen = pool[0] || null;
  const body = clean(document.body?.innerText || '');
  return {
    seo_content_word_count:chosen ? chosen.words : null,
    seo_content_text:chosen ? chosen.text : null,
    seo_content_status:chosen && chosen.words >= 100 ? 'candidate' : 'unverified',
    seo_content_method:'rendered-main-innertext-v2',
    seo_content_selector:chosen?.selector || null,
    seo_content_tag:chosen?.tag || null,
    seo_content_candidate_count:stats.length,
    seo_content_excluded_nodes:chosen?.excluded_nodes ?? null,
    seo_content_heading_count:chosen?.headings ?? null,
    seo_content_text_prefix:chosen?.text.slice(0,220) || '',
    seo_content_body_words:count(body),
    seo_content_reason:chosen ? (chosen.words >= 100 ? 'visible_main_candidate' : 'insufficient_visible_main_text') : 'no_visible_main_landmark'
  };
}'''


def extract_main_content(page):
    """Run the same live-DOM extraction on every selected SERP URL."""
    return page.evaluate(JS_EXTRACT)
