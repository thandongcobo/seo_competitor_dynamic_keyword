"""Extract comparable browser-rendered content from a selected ranking page.

Semantic main/article containers are preferred. When a site renders its primary
content in generic containers, a conservative structural fallback accepts only
visible, distributed, non-UI text that meets the same word-count requirement.
"""
from __future__ import annotations

EXTRACTION_VERSION = "rendered-main-innertext-v2"

JS_EXTRACT = r'''() => {
  const count = s => (s || '').trim().split(/\s+/).filter(Boolean).length;
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const excluded = 'nav,footer,header,aside,[role="navigation"],[role="menu"],[role="menubar"],[role="tablist"],[role="dialog"],button,input,select,textarea,[hidden],[aria-hidden="true"],script,style,noscript,svg';
  const blockSelector = 'p,li,dt,dd,blockquote,pre,td,th,div,section,article';
  const blockTags = new Set(['P','LI','DT','DD','BLOCKQUOTE','PRE','TD','TH','DIV','SECTION','ARTICLE']);
  const uiPattern = /(?:^|[\s_-])(navigation|nav|menu|tab|cookie|consent|banner|popup|modal|dialog|overlay|toast|notification|skeleton|placeholder|loader|loading|breadcrumb|toolbar|pagination|alert)(?:$|[\s_-])|__tab(?:$|[\s_-])/i;
  const shellClassPattern = /^(?:(?:site|global|page|primary|main)[_-])?(?:header|footer|sidebar)$/i;
  const errorStatePattern = /(?:error displaying|data failed loading|failed to load|failed loading|please reload|please turn javascript on|enable javascript to view|access denied|verify you(?:'|’)re human|temporarily unavailable|content is loading)/i;
  const visible = el => {
    if (!el || !el.isConnected || el.closest('[hidden],[aria-hidden="true"]')) return false;
    const st = getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden' || st.visibility === 'collapse') return false;
    return el.getClientRects().length > 0;
  };
  const hasUiMetadata = el => {
    const metadata = [el.id, el.getAttribute('role'), el.getAttribute('aria-label'),
      el.getAttribute('data-testid')].filter(Boolean).join(' ');
    const classes = Array.from(el.classList || []);
    return el.matches(excluded) || uiPattern.test(metadata) ||
      classes.some(token => uiPattern.test(token) || shellClassPattern.test(token));
  };
  const hasUiAncestor = (el, stopAt=null) => {
    for (let node=el; node && node!==stopAt && node!==document.body; node=node.parentElement) {
      if (hasUiMetadata(node)) return true;
    }
    return false;
  };
  const selectorFor = el => {
    const path = [];
    for (let node=el; node && node!==document.body; node=node.parentElement) {
      if (node.id) {
        path.unshift('#' + CSS.escape(node.id));
        return path.join(' > ');
      }
      let part=node.tagName.toLowerCase();
      const uniqueClass=Array.from(node.classList || []).find(token => {
        try { return document.querySelectorAll(node.tagName.toLowerCase()+'.'+CSS.escape(token)).length===1; }
        catch (_) { return false; }
      });
      if (uniqueClass) part+='.'+CSS.escape(uniqueClass);
      else if (node.parentElement) {
        const siblings=[...node.parentElement.children].filter(x=>x.tagName===node.tagName);
        if (siblings.length>1) part+=':nth-of-type('+(siblings.indexOf(node)+1)+')';
      }
      path.unshift(part);
      const candidate=path.join(' > ');
      try { if (document.querySelectorAll(candidate).length===1) return candidate; } catch (_) {}
    }
    return path.join(' > ');
  };
  const visibleText = el => {
    const nodes = [...el.querySelectorAll('*')].filter(node => hasUiMetadata(node));
    const originals = [];
    let text = '';
    try {
      for (const node of nodes) {
        originals.push([node, node.getAttribute('style')]);
        node.style.setProperty('display', 'none', 'important');
      }
      text = clean(el.innerText);
    } finally {
      for (let j=originals.length-1; j>=0; j--) {
        const [node, style] = originals[j];
        if (style === null) node.removeAttribute('style');
        else node.setAttribute('style', style);
      }
    }
    return text;
  };
  const headingCount = el => [...el.querySelectorAll('h1,h2,h3')].filter(visible).length;
  const semanticElements = [...document.querySelectorAll('main,[role="main"],article')]
    .filter(el => visible(el) && !hasUiMetadata(el));
  const semanticStats = semanticElements.map((el, index) => {
    const text = visibleText(el);
    return {index, tag:el.tagName.toLowerCase(), selector:selectorFor(el), text,
      words:count(text), headings:headingCount(el), type:'semantic',
      excluded_nodes:[...el.querySelectorAll('*')].filter(node => hasUiMetadata(node)).length};
  });

  // Use semantic candidates first whenever one contains enough usable content.
  const mains = semanticStats.filter(x => x.tag === 'main');
  const semanticPool = mains.length ? mains : semanticStats;
  const semanticQualified = semanticPool.filter(x => x.words >= 100 && !errorStatePattern.test(x.text));
  semanticQualified.sort((a,b) => (b.words >= 60 ? 1:0) - (a.words >= 60 ? 1:0) ||
    b.headings-a.headings || b.words-a.words);

  const genericStats = [];
  if (!semanticQualified.length) {
    for (const el of document.querySelectorAll('div,section')) {
      if (!visible(el) || hasUiMetadata(el) || hasUiAncestor(el.parentElement)) continue;
      // Avoid measuring the whole application shell when it cannot meet the
      // existing content threshold after navigation/UI text is removed.
      if (count(clean(el.innerText)) < 100) continue;
      const text = visibleText(el);
      const words = count(text);
      if (words < 100 || errorStatePattern.test(text)) continue;

      // Require several independent text blocks. This rejects a long menu,
      // repeated placeholder, or one large shell string while supporting SPA
      // result lists whose rows are implemented with ordinary divs.
      const blockTexts = new Set();
      let blockWordCount = 0;
      const qualifiedBlocks = [];
      const blocks = [el, ...el.querySelectorAll(blockSelector)];
      for (const block of blocks) {
        if (!visible(block) || hasUiMetadata(block) || hasUiAncestor(block.parentElement, el)) continue;
        const blockText = clean(block.innerText);
        const blockWords = count(blockText);
        if (blockWords < 4) continue;
        const hasSubstantiveChild = [...block.children].some(child => blockTags.has(child.tagName) &&
          visible(child) && !hasUiMetadata(child) && count(clean(child.innerText)) >= 4);
        if (hasSubstantiveChild) continue;
        const key = blockText.toLowerCase();
        if (!blockTexts.has(key)) {
          blockTexts.add(key);
          blockWordCount += blockWords;
          qualifiedBlocks.push({selector:selectorFor(block), tag:block.tagName.toLowerCase(),
            text:blockText, word_count:blockWords});
        }
      }
      if (blockTexts.size < 3 || blockWordCount < Math.min(60, Math.floor(words * 0.35))) continue;

      const interactiveText = [...el.querySelectorAll('a,button,[role="button"]')]
        .filter(node => visible(node) && !hasUiAncestor(node.parentElement, el))
        .map(node => clean(node.innerText)).join(' ');
      const interactiveWordRatio = words ? count(interactiveText) / words : 1;
      if (interactiveWordRatio > 0.85) continue;

      let depth = 0;
      for (let node=el; node && node!==document.body; node=node.parentElement) depth++;
      genericStats.push({tag:el.tagName.toLowerCase(), selector:selectorFor(el), text, words,
        headings:headingCount(el), type:'nonsemantic', depth,
        content_blocks:qualifiedBlocks,
        excluded_nodes:[...el.querySelectorAll('*')].filter(node => hasUiMetadata(node)).length,
        quality_signals:{distinct_content_blocks:blockTexts.size,
          content_block_word_count:blockWordCount,
          interactive_word_ratio:Number(interactiveWordRatio.toFixed(3)),
          minimum_word_count:100}});
    }
  }

  // Select the smallest generic container that passes the content checks;
  // this avoids promoting app/body wrappers that merely contain the page.
  genericStats.sort((a,b) => a.words-b.words || b.depth-a.depth ||
    b.quality_signals.distinct_content_blocks-a.quality_signals.distinct_content_blocks);
  const semanticChosen = semanticQualified[0] || null;
  const genericChosen = genericStats[0] || null;
  const fallbackSemantic = semanticPool.slice().sort((a,b) => b.words-a.words)[0] || null;
  const chosen = semanticChosen || genericChosen || fallbackSemantic;
  const body = clean(document.body?.innerText || '');
  const stableText = chosen?.type === 'nonsemantic'
    ? clean(chosen.text).replace(/\b\d{1,2}:\d{2}(?::\d{2})?\b/g, '[time]')
    : (chosen?.text || '');
  const completeCandidate = Boolean(chosen && chosen.words >= 100 &&
    (chosen === semanticChosen || chosen === genericChosen));
  return {
    seo_content_word_count:chosen ? chosen.words : null,
    seo_content_text:chosen ? chosen.text : null,
    seo_content_status:completeCandidate ? 'candidate' : 'unverified',
    seo_content_method:'rendered-main-innertext-v2',
    seo_content_selector:chosen?.selector || null,
    seo_content_tag:chosen?.tag || null,
    seo_content_candidate_type:chosen?.type || null,
    seo_content_blocks:chosen?.type === 'nonsemantic' ? (chosen.content_blocks || []) : [],
    seo_content_candidate_count:semanticStats.length + genericStats.length,
    seo_content_excluded_nodes:chosen?.excluded_nodes ?? null,
    seo_content_heading_count:chosen?.headings ?? null,
    seo_content_text_prefix:stableText.slice(0,220),
    seo_content_quality_signals:chosen?.quality_signals || null,
    seo_content_body_words:count(body),
    seo_content_reason:!chosen ? 'no_visible_main_landmark' :
      completeCandidate && chosen.type === 'nonsemantic' ? 'visible_nonsemantic_content_candidate' :
      completeCandidate ? 'visible_main_candidate' : 'insufficient_visible_main_text'
  };
}'''


def extract_main_content(page):
    """Run one shared semantic-first extractor on the live rendered DOM."""
    return page.evaluate(JS_EXTRACT)
