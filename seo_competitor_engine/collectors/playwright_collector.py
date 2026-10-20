from __future__ import annotations

from pathlib import Path
import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from config.settings import settings, DATA_DIR
from collectors.main_content import extract_main_content


BLOCK_MARKERS = (
    "unusual traffic",
    "our systems have detected unusual traffic",
    "captcha",
    "verify you are a human",
    "not a robot",
    "automated queries",
    "too many requests",
)


def _browser_profile_dir() -> Path:
    path = DATA_DIR / "browser_profile"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _is_internal(base_url: str, href: str) -> bool:
    try:
        return urlparse(urljoin(base_url, href)).netloc == urlparse(base_url).netloc
    except Exception:
        return False


def parse_page_html(
    html: str,
    *,
    requested_url: str,
    final_url: str,
    status_code: int | None,
    title: str | None = None,
) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    resolved_title = title if title is not None else ((soup.title.string or "").strip() if soup.title else "")

    meta_description = None
    md = soup.find("meta", attrs={"name": lambda v: v and v.lower() == "description"})
    if md:
        meta_description = md.get("content")

    canonical = None
    canonical_tag = soup.find(
        "link",
        attrs={"rel": lambda v: v and "canonical" in [x.lower() for x in (v if isinstance(v, list) else [v])]}
    )
    if canonical_tag:
        canonical = canonical_tag.get("href")

    robots = None
    robots_tag = soup.find("meta", attrs={"name": lambda v: v and v.lower() == "robots"})
    if robots_tag:
        robots = robots_tag.get("content")

    headings = {f"h{i}": [h.get_text(" ", strip=True) for h in soup.find_all(f"h{i}")] for i in range(1, 7)}
    links = [a.get("href") for a in soup.find_all("a") if a.get("href")]
    internal_links = [urljoin(final_url, href) for href in links if _is_internal(final_url, href)]
    external_links = [
        urljoin(final_url, href)
        for href in links
        if href.startswith(("http://", "https://")) and not _is_internal(final_url, href)
    ]

    schemas = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        text = script.get_text(strip=True)
        if text:
            schemas.append(text)

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    visible_text = " ".join(soup.get_text(" ", strip=True).split())
    word_count = len(visible_text.split())

    # The main document can have navigation text before its actual content renders.
    # These structural signals are only a fallback; live DOM innerText is preferred.
    main_candidates = soup.select('main, [role="main"], article')
    main_word_count = max(
        (len(" ".join(node.get_text(" ", strip=True).split()).split()) for node in main_candidates),
        default=0,
    )

    return {
        "requested_url": requested_url,
        "final_url": final_url,
        "status_code": status_code,
        "title": resolved_title,
        "title_length": len(resolved_title or ""),
        "meta_description": meta_description,
        "meta_description_length": len(meta_description or ""),
        "canonical": canonical,
        "robots": robots,
        "headings": headings,
        "h1_count": len(headings["h1"]),
        "word_count": word_count,
        "main_word_count": main_word_count,
        "internal_link_count": len(set(internal_links)),
        "external_link_count": len(set(external_links)),
        "internal_links": sorted(set(internal_links)),
        "external_links": sorted(set(external_links)),
        "structured_data_blocks": schemas,
        "structured_data_count": len(schemas),
        "text_sample": visible_text[:5000],
    }


def _looks_blocked(text: str, title: str = "") -> bool:
    haystack = f"{title}\n{text}".lower()
    return any(marker in haystack for marker in BLOCK_MARKERS)


def _content_quality(data: dict[str, Any]) -> tuple[bool, str]:
    """Check for substantive page content, not a navigation-only shell.

    Do not confuse this with stability: the browser must ALSO show stable
    content across observations before the crawl is considered complete.
    """
    body_words = data.get("rendered_word_count")
    if body_words is None:
        body_words = data.get("word_count", 0)
    seo_words = data.get("seo_content_word_count")
    seo_valid = data.get("seo_content_status") == "candidate"
    main_words = data.get("rendered_main_word_count")
    if main_words is None:
        main_words = data.get("main_word_count", 0)
    h1_count = data.get("rendered_h1_count")
    if h1_count is None:
        h1_count = data.get("h1_count", 0)

    if seo_valid and isinstance(seo_words, int) and seo_words >= 100:
        return True, "standardized_visible_main_candidate"
    # Public applications may render substantive page content only inside
    # accessible Web Component shadow roots, outside the ordinary <main> tree.
    if int(data.get("shadow_word_count") or 0) >= 60:
        return True, "stable_visible_shadow_dom_content"
    return False, "standardized_main_content_not_confirmed"


def _stable_render(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    """Allow minor dynamic text changes but not a meaningful content jump."""
    if previous.get("final_url") != current.get("final_url"):
        return False
    for key in ("rendered_word_count", "rendered_main_word_count", "seo_content_word_count"):
        a, b = int(previous.get(key) or 0), int(current.get(key) or 0)
        if abs(a - b) > max(5, round(max(a, b) * 0.05)):
            return False
    if previous.get("seo_content_selector") != current.get("seo_content_selector"):
        return False
    if previous.get("seo_content_text_prefix") != current.get("seo_content_text_prefix"):
        return False
    if previous.get("rendered_h1_count") != current.get("rendered_h1_count"):
        return False
    # A long navigation shell and the actual article can have similar lengths.
    # Require the beginning of the meaningful text to remain the same.
    if previous.get("readiness_text_prefix") != current.get("readiness_text_prefix"):
        return False
    if previous.get("shadow_word_count") != current.get("shadow_word_count"):
        return False
    if previous.get("shadow_text_prefix") != current.get("shadow_text_prefix"):
        return False
    return True


def _rendered_signals(page: Any) -> dict[str, Any]:
    """Read visible document and accessible open Shadow DOM text, not iframe content."""
    return page.evaluate(r"""() => {
        const clean = value => (value || '').replace(/\s+/g, ' ').trim();
        const roots=[document], shadowRoots=[], seen=new Set();
        for(let i=0;i<roots.length && i<500;i++) {
          const root=roots[i];
          for(const el of Array.from(root.querySelectorAll('*'))) {
            if(el.shadowRoot && !seen.has(el.shadowRoot)) { seen.add(el.shadowRoot); shadowRoots.push(el.shadowRoot); roots.push(el.shadowRoot); }
          }
        }
        const visible=el => { const r=el.getBoundingClientRect(), s=getComputedStyle(el);
          return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; };
        const visibleText=root => {
          const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
          const chunks=[]; let node;
          while((node=walker.nextNode())) {
            const parent=node.parentElement;
            if(!parent || /^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE)$/.test(parent.tagName) || !visible(parent)) continue;
            const value=clean(node.nodeValue); if(value) chunks.push(value);
          }
          return chunks.join(' ');
        };
        const shadowText=shadowRoots.map(visibleText).filter(Boolean).join(' ');
        const composedText=[visibleText(document),shadowText].filter(Boolean).join(' ');
        const mainCandidates = Array.from(document.querySelectorAll(
            'main, [role="main"], article'));
        const mainTexts = mainCandidates.map(el => clean(el.innerText));
        const mainText = mainTexts.sort((a,b) => b.length - a.length)[0] || '';
        const bodyText = clean(document.body?.innerText);
        const count = (s) => s ? s.split(/\s+/).length : 0;
        return {
            rendered_word_count: count(bodyText),
            rendered_main_word_count: count(mainText),
            composed_word_count: count(composedText),
            composed_text_prefix: composedText.slice(0, 220),
            shadow_word_count: count(shadowText),
            shadow_text_prefix: shadowText.slice(0, 220),
            open_shadow_root_count: shadowRoots.length,
            rendered_h1_count: Array.from(document.querySelectorAll('h1'))
                .filter((h) => clean(h.innerText).length > 0).length,
            readiness_text_prefix: (mainText || bodyText).slice(0, 220),
            body_blocked: ['unusual traffic', 'captcha', 'verify you are a human',
                'not a robot', 'automated queries', 'too many requests']
                .some((term) => (bodyText+' '+composedText).toLowerCase().includes(term))
        };
    }""")


def _load_lazy_content(page: Any) -> int:
    """Scroll the document and nested page panels to trigger below-fold lazy content."""
    try:
        regions = page.evaluate(r"""() => {
          const root=document.scrollingElement;
          const all=[root,...Array.from(document.querySelectorAll('body *'))]
            .filter((el,index,array)=>el && array.indexOf(el)===index &&
              el.scrollHeight>el.clientHeight+160 && el.clientHeight>160 && el.clientWidth>280)
            .sort((a,b)=>b.scrollHeight-b.clientHeight-(a.scrollHeight-a.clientHeight)).slice(0,12);
          window.__codexCaptureScrollTargets=all;
          return all.map(el=>({height:Math.min(el.scrollHeight,30000),viewport:el.clientHeight}));
        }""")
        steps = 0
        for index, region in enumerate(regions):
            height = min(int(region["height"]), 30000)
            viewport = max(250, int(region["viewport"] * 0.8))
            for position in range(0, height, viewport):
                page.evaluate("({index,position}) => { const el=window.__codexCaptureScrollTargets?.[index]; if(el) el.scrollTop=position; }", {"index": index, "position": position})
                page.wait_for_timeout(120)
                steps += 1
        page.evaluate("() => { for(const el of window.__codexCaptureScrollTargets||[]) el.scrollTop=0; window.scrollTo(0,0); }")
        page.wait_for_timeout(350)
        return steps
    except Exception:
        return 0


def _full_page_inventory(page: Any) -> dict[str, Any]:
    """Inventory visible document and open Shadow DOM text/assets, not iframe content."""
    return page.evaluate(r"""() => {
      const clean = value => (value || '').replace(/\s+/g, ' ').trim();
      const visible = el => { const r=el.getBoundingClientRect(), s=getComputedStyle(el);
        return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; };
      const roots=[document], shadowRoots=[], all=[], seenRoots=new Set();
      for(let i=0;i<roots.length && i<500;i++) {
        const root=roots[i];
        for(const el of Array.from(root.querySelectorAll('*'))) {
          all.push({el,root});
          if(el.shadowRoot && !seenRoots.has(el.shadowRoot)) { seenRoots.add(el.shadowRoot); shadowRoots.push(el.shadowRoot); roots.push(el.shadowRoot); }
        }
      }
      const deepText = el => {
        const chunks=[];
        const walk=node=>{
          if(node.nodeType===Node.TEXT_NODE) { const value=clean(node.nodeValue); if(value) chunks.push(value); return; }
          if(node.nodeType===Node.ELEMENT_NODE) {
            if(/^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE)$/.test(node.tagName) || !visible(node)) return;
            if(node.tagName==='SLOT') {
              const assigned=node.assignedNodes({flatten:true});
              for(const child of (assigned.length?assigned:Array.from(node.childNodes||[]))) walk(child);
              return;
            }
          }
          for(const child of Array.from(node.childNodes||[])) walk(child);
          if(node.nodeType===Node.ELEMENT_NODE && node.shadowRoot) walk(node.shadowRoot);
        };
        walk(el);
        const compact=[];
        for(const value of chunks) if(value.toLowerCase()!==compact.at(-1)?.toLowerCase()) compact.push(value);
        return clean(compact.join(' '));
      };
      const cardSelector='article,[role="article"],[class*="card" i],[class*="promo" i],[class*="offer" i],[data-testid*="promo" i],[data-testid*="offer" i],pr-promotion-item-v2';
      const specificCards=all.filter(({el})=>el.tagName.includes('-') && /promo|offer|banner/i.test(el.tagName) && /item|card|banner/i.test(el.tagName) && visible(el));
      const cards=specificCards.length?specificCards:all.filter(({el})=>el.matches?.(cardSelector) && visible(el));
      const cardIndex=new Map(cards.map(({el},index)=>[el,index]));
      const findCard=(el)=>{let current=el;while(current){if(cardIndex.has(current))return cardIndex.get(current);if(current.parentElement){current=current.parentElement;continue;}current=current.getRootNode?.().host||null;}return null;};
      const cardLinks=new Map(cards.map(({el},index)=>[index,[]]));
      for(const {el} of all) if(el.tagName==='A' && el.href) { const index=findCard(el); if(index!==null) cardLinks.get(index).push({text:clean(el.innerText)||clean(el.getAttribute('aria-label')),url:el.href}); }
      const imageElements=all.flatMap(({el,root})=>el.tagName==='IMG'?[{img:el,root}]:[]);
      const imageIndexByElement=new Map(imageElements.map(({img},index)=>[img,index]));
      const cardImages=new Map(cards.map(({el},index)=>[index,[]]));
      for(const {img} of imageElements) { const index=findCard(img); if(index!==null) cardImages.get(index).push({image_index:imageIndexByElement.get(img),url:img.currentSrc||img.src||'',alt:img.alt||''}); }
      const cardBlocks=[]; const cardTexts=new Set();
      for(let index=0;index<cards.length;index++) {
        const {el}=cards[index]; const text=deepText(el);
        const normalized=clean(text).toLowerCase();
        if(!text || normalized.length<12 || cardTexts.has(normalized)) continue;
        cardTexts.add(normalized);
        const links=cardLinks.get(index)||[];
        let parent=el.parentElement || el.getRootNode?.().host || null, heading='';
        while(parent && !heading) { heading=clean(parent.querySelector?.('h1,h2,h3,h4,[role="heading"]')?.innerText); parent=parent.parentElement || parent.getRootNode?.().host || null; }
        const identity=`${el.tagName} ${el.id||''} ${el.getAttribute('class')||''} ${el.getAttribute('data-testid')||''}`;
        cardBlocks.push({id:`promotion-card:${el.id||el.getAttribute('class')||el.tagName}:${index}`,tag:el.tagName.toLowerCase(),text,href:links[0]?.url||'',section:`promotion-card:${index}`,heading,related_links:links.slice(0,12),image_refs:cardImages.get(index)||[],promotion_context:/promo|offer|banner|campaign/i.test(identity),evidence_scope:'composed_card'});
      }
      const selector = 'h1,h2,h3,h4,h5,h6,p,li,blockquote,figcaption,button,a,summary,td,th,[role="heading"],[role="button"]';
      const semantic = all.filter(({el})=>el.matches?.(selector) && visible(el));
      const blocks = semantic.map(({el,root}, index) => {
        const owner=findCard(el);
        return ({
        id: `${el.tagName.toLowerCase()}:${clean(el.getAttribute('id') || el.getAttribute('class')).slice(0,80)}:${index}`,
        tag: el.tagName.toLowerCase(), text: clean(el.innerText) || deepText(el),
        href: el.tagName==='A' ? (el.href || '') : '',
        section: owner!==null?`promotion-card:${owner}`:clean(el.closest('section,article,main,[role=main]')?.id || el.closest('section,article,main,[role=main]')?.getAttribute('aria-label') || root.host?.id || root.host?.tagName || ''),
        heading: clean(el.closest('section,article')?.querySelector('h1,h2,h3,h4')?.innerText || ''),
        related_links: cardLinks.get(owner)||[],
        ...(owner!==null?{evidence_scope:'composed_card_child',card_key:`promotion-card:${owner}`}:{})
      });
      }).filter(x => x.text);
      const images = imageElements.map(({img}, index) => {
        const r=img.getBoundingClientRect();
        return {id: img.id || `image-${index}`, src: img.currentSrc || img.src || '', srcset: img.srcset || '',
          alt: img.alt || '', title: img.title || '', loading: img.loading || '', complete: img.complete,
          natural_width: img.naturalWidth || 0, natural_height: img.naturalHeight || 0,
          rendered_width: Math.round(r.width), rendered_height: Math.round(r.height),
          bounds: {x: Math.round(r.x), y: Math.round(r.y)},
          href: img.closest('a')?.href || '',
          visible: r.width>0 && r.height>0 && getComputedStyle(img).visibility!=='hidden',
          section: clean(img.closest('section,article,main,[role=main]')?.id || img.getRootNode()?.host?.tagName || '')};
      });
      const backgrounds=[];
      for (const {el} of all.slice(0,10000)) {
        const value=getComputedStyle(el).backgroundImage;
        if (value && value!=='none') for (const match of value.matchAll(/url\(["']?(.*?)["']?\)/g))
          backgrounds.push({url:new URL(match[1],document.baseURI).href,element:el.tagName.toLowerCase(),alt:el.getAttribute('aria-label')||''});
      }
      const walkerText=root=>{const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT),parts=[];let node;while((node=walker.nextNode())){const p=node.parentElement;if(p&&!/^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE)$/.test(p.tagName)&&visible(p)){const t=clean(node.nodeValue);if(t)parts.push(t);}}return parts.join(' ');};
      const composedText=[walkerText(document),...shadowRoots.map(walkerText)].filter(Boolean).join(' ');
      const composedWords=clean(composedText);
      const customWithoutOpenRoot=all.filter(({el})=>el.tagName.includes('-')&&!el.shadowRoot).map(({el})=>el.tagName.toLowerCase());
      return { rendered_page_text: composedWords,
        rendered_page_word_count: composedWords.split(/\s+/).filter(Boolean).length,
        rendered_text_blocks: [...blocks,...cardBlocks], image_inventory: images,
        background_image_inventory: backgrounds.slice(0,500),
        image_inventory_truncated: images.length>2000, document_height: document.documentElement.scrollHeight,
        shadow_dom_open_root_count:shadowRoots.length, shadow_dom_uninspected_custom_element_count:customWithoutOpenRoot.length,
        shadow_dom_uninspected_custom_elements:[...new Set(customWithoutOpenRoot)].slice(0,40),
        composed_card_count:cardBlocks.length };
    }""")


def _save_capture_artifacts(page: Any, folder: Path, image_inventory: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    artifacts: dict[str, Any] = {"artifact_errors": []}
    folder.mkdir(parents=True, exist_ok=True)
    try:
        html_path = folder / "rendered_page.html"
        html_path.write_text(page.content(), encoding="utf-8")
        artifacts["rendered_html_path"] = str(html_path)
    except Exception as exc:
        artifacts["artifact_errors"].append(f"html: {type(exc).__name__}: {exc}")
    try:
        viewport_path = folder / "viewport.png"
        page.screenshot(path=str(viewport_path), full_page=False, timeout=30000)
        artifacts["viewport_screenshot_path"] = str(viewport_path)
        screenshot_path = folder / "full_page.png"
        regions = page.evaluate(r"""() => {
          const root=document.scrollingElement;
          const all=[root,...Array.from(document.querySelectorAll('body *'))]
            .filter((el,index,array)=>el && array.indexOf(el)===index &&
              el.scrollHeight>el.clientHeight+160 && el.clientHeight>160 && el.clientWidth>280)
            .sort((a,b)=>b.scrollHeight-a.scrollHeight).slice(0,12);
          window.__codexCaptureScrollTargets=all;
          return all.map((el,index)=>{const r=el.getBoundingClientRect(); return {index,scrollHeight:el.scrollHeight,clientHeight:el.clientHeight,
            x:Math.round(r.x),y:Math.round(r.y),width:Math.round(r.width),height:Math.round(r.height)};});
        }""")
        primary = next((region for region in regions if region["scrollHeight"] > region["clientHeight"] + 160), None)
        if primary:
            from io import BytesIO
            from PIL import Image
            viewport = page.viewport_size or {"width": 1366, "height": 768}
            x=max(0,primary["x"]); y=max(0,primary["y"])
            width=max(1,min(primary["width"],viewport["width"]-x))
            height=max(1,min(primary["height"],viewport["height"]-y))
            total_height=min(primary["scrollHeight"],30000)
            strips=[]
            covered_until=0
            for offset in range(0,total_height,height):
                actual_offset=page.evaluate("({index,position}) => { const el=window.__codexCaptureScrollTargets?.[index]; if(!el) return 0; el.scrollTop=position; return el.scrollTop; }", {"index":primary["index"],"position":offset})
                page.wait_for_timeout(100)
                if strips and len(strips)==1:
                    page.evaluate(r"""() => {
                      window.__codexStitchHidden=[];
                      for(const el of document.querySelectorAll('body *')){
                        const position=getComputedStyle(el).position;
                        if(position==='fixed'||position==='sticky'){
                          window.__codexStitchHidden.push([el,el.style.visibility]);
                          el.style.visibility='hidden';
                        }
                      }
                    }""")
                shot=Image.open(BytesIO(page.screenshot(full_page=False,timeout=30000))).convert("RGB")
                strip=shot.crop((x,y,x+width,y+height))
                crop_start=max(0,covered_until-actual_offset)
                crop_end=min(height,max(0,total_height-actual_offset))
                if crop_end<=crop_start: continue
                strips.append(strip.crop((0,crop_start,width,crop_end)))
                covered_until=actual_offset+crop_end
            page.evaluate(r"""() => {
              for(const [el,value] of window.__codexStitchHidden||[]) el.style.visibility=value;
              delete window.__codexStitchHidden;
            }""")
            stitched=Image.new("RGB",(width,sum(strip.height for strip in strips)),"white")
            cursor=0
            for strip in strips:
                stitched.paste(strip,(0,cursor)); cursor+=strip.height
            stitched.save(screenshot_path)
            artifacts["screenshot_mode"]="stitched_full_page_v2"
            artifacts["screenshot_region_count"]=len(regions)
            artifacts["document_height"]=total_height
            artifacts["screenshot_dimensions"]=[width,cursor]
            page.evaluate("() => { for(const el of window.__codexCaptureScrollTargets||[]) el.scrollTop=0; window.scrollTo(0,0); }")
        else:
            page.screenshot(path=str(screenshot_path), full_page=True, timeout=30000)
            artifacts["screenshot_mode"]="document_full_page"
            artifacts["document_height"]=int(page.evaluate("() => document.documentElement.scrollHeight"))
        artifacts["screenshot_path"] = str(screenshot_path)
    except Exception as exc:
        artifacts["artifact_errors"].append(f"screenshot: {type(exc).__name__}: {exc}")
    # Save bounded crops of banner-sized public images so local OCR can inspect
    # text baked into creatives without making additional network requests.
    promotion_crops = []
    image_inventory = image_inventory or []
    for index, item in enumerate(image_inventory):
        if not item.get("visible") or not item.get("complete"):
            continue
        natural_width = int(item.get("natural_width") or 0)
        natural_height = int(item.get("natural_height") or 0)
        width = int(item.get("rendered_width") or natural_width)
        height = int(item.get("rendered_height") or natural_height)
        if width < 180 or height < 70 or natural_width < 180 or natural_height < 70:
            continue
        ratio = width / max(height, 1)
        text = " ".join(str(item.get(key) or "") for key in ("alt", "title", "src")).lower()
        banner_hint = any(word in text for word in ("banner", "promo", "offer", "bonus", "campaign", "betinfluencer"))
        if ratio < 1.25 and not banner_hint:
            continue
        if len(promotion_crops) >= 80:
            break
        try:
            crop_dir = folder / "promotion_images"
            crop_dir.mkdir(parents=True, exist_ok=True)
            crop_path = crop_dir / f"image_{index:04d}.png"
            page.locator("img").nth(index).screenshot(path=str(crop_path), timeout=12000)
            promotion_crops.append({"image_index": index, "path": str(crop_path)})
        except Exception as exc:
            artifacts["artifact_errors"].append(f"promotion image {index}: {type(exc).__name__}")
    artifacts["promotion_image_crops"] = promotion_crops
    return artifacts


def _wait_for_meaningful_render(page: Any, url: str, status: int | None,
                                timeout_seconds: int) -> tuple[dict[str, Any], bool, bool, str, int, float]:
    """Poll for substantive and stable DOM, with a strict maximum wait.

    The minimum observation period prevents early shell content from ending
    a crawl. Stability requires >=2 seconds of consistent rendered content.
    """
    start = time.monotonic()
    render_timeout = max(4, min(180, timeout_seconds))
    minimum_observation_seconds = max(1, min(settings.playwright_render_minimum_seconds, render_timeout))
    stability_seconds = max(1, min(30, settings.playwright_render_stability_seconds))
    deadline = start + render_timeout
    previous: dict[str, Any] | None = None
    stable_since: float | None = None
    best: dict[str, Any] | None = None
    best_score: tuple[int, int, int, int] = (-1, -1, -1, -1)
    blocked = False
    complete = False
    samples = 0
    reason = "main_content_not_confirmed"

    while True:
        samples += 1
        try:
            html = page.content()
            title = page.title()
            final_url = page.url
            signals = _rendered_signals(page)
            if signals.get("body_blocked") or _looks_blocked("", title) or "/sorry/" in final_url:
                blocked = True
                reason = "access_challenge_detected"
                break
            parsed = parse_page_html(html, requested_url=url, final_url=final_url,
                                     status_code=status, title=title)
            parsed.update(signals)
            parsed.update(extract_main_content(page))
            ready, candidate_reason = _content_quality(parsed)
            score = (int(ready), parsed.get("seo_content_word_count") or 0,
                     parsed["rendered_h1_count"], parsed["rendered_word_count"])
            if score > best_score:
                best, best_score = parsed, score

            now = time.monotonic()
            if previous is not None and _stable_render(previous, parsed):
                if stable_since is None:
                    stable_since = previous["_observed_at"]
            else:
                stable_since = None
            parsed["_observed_at"] = now
            previous = parsed

            if ready and now - start >= minimum_observation_seconds and \
                    stable_since is not None and now - stable_since >= stability_seconds:
                complete = True
                best = parsed
                reason = candidate_reason + "_stable"
                break
            reason = candidate_reason if not ready else "content_not_stable_yet"
        except Exception as exc:
            # A client-side navigation may detach the DOM during an observation.
            # Retry within the bounded window instead of treating it as success.
            reason = "render_observation_error:" + type(exc).__name__

        if time.monotonic() >= deadline:
            break
        page.wait_for_timeout(min(1000, max(1, int((deadline - time.monotonic()) * 1000))))

    if best is None:
        best = parse_page_html(page.content(), requested_url=url, final_url=page.url,
                               status_code=status, title=page.title())
    best.pop("_observed_at", None)
    # Never retain raw cleaned text for incomplete or blocked crawls.
    if not complete or blocked:
        best.pop("seo_content_text", None)
    return best, complete, blocked, reason, samples, round(time.monotonic() - start, 2)


def _diagnostic_dir(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    directory = DATA_DIR / "diagnostics" / "page_crawls" / digest
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _save_diagnostics(page: Any, url: str, reason: str) -> dict[str, Any]:
    """Diagnostics stay on disk; HTML can contain sensitive page/session data."""
    folder = _diagnostic_dir(url)
    paths: dict[str, Any] = {"diagnostic_directory": str(folder), "diagnostic_errors": []}
    try:
        screenshot = folder / "page.png"
        page.screenshot(path=str(screenshot), full_page=True, timeout=10000)
        paths["diagnostic_screenshot"] = str(screenshot)
    except Exception as exc:
        paths["diagnostic_errors"].append(f"screenshot: {type(exc).__name__}: {exc}")
    try:
        html = folder / "page.html"
        html.write_text(page.content(), encoding="utf-8")
        paths["diagnostic_html"] = str(html)
    except Exception as exc:
        paths["diagnostic_errors"].append(f"html: {type(exc).__name__}: {exc}")
    metadata = folder / "metadata.json"
    metadata.write_text(json.dumps({"requested_url": url, "final_url": page.url,
                                    "reason": reason, "timestamp": datetime.now(timezone.utc).isoformat()}, indent=2), encoding="utf-8")
    paths["diagnostic_metadata"] = str(metadata)
    return paths


def _public_request_route(verified_hosts: set[str]):
    def guard(route: Any) -> None:
        from monitoring.store import validate_public_host
        request = route.request
        parsed = urlparse(request.url)
        if parsed.scheme not in ("http", "https"):
            route.abort("blockedbyclient")
            return
        host = (parsed.hostname or "").lower()
        try:
            if host not in verified_hosts:
                validate_public_host(request.url)
                verified_hosts.add(host)
        except ValueError:
            route.abort("blockedbyclient")
            return
        route.continue_()
    return guard


def _looks_like_sign_in_wall(page: Any) -> bool:
    path = urlparse(page.url).path.lower()
    if any(part in path for part in ("/login", "/log-in", "/sign-in", "/signin", "/authenticate")):
        return True
    try:
        password_field = page.locator('input[type="password"]').count() > 0
        body = (page.locator("body").inner_text(timeout=2000) or "")[:3000].lower()
        return password_field and any(term in body for term in ("sign in", "log in", "login", "password"))
    except Exception:
        return False


def crawl_page(url: str, timeout_ms: int | None = None, artifact_dir: Path | None = None,
               public_only: bool = False) -> dict[str, Any]:
    browser_path = settings.playwright_browser_path
    if not browser_path:
        raise RuntimeError(
            "No installed Chrome/Edge executable was found. Set PLAYWRIGHT_BROWSER_PATH in .env "
            "or install Chrome/Edge. The project intentionally does not download Playwright Chromium."
        )
    latitude, longitude, *_radius = settings.location_coordinate.split(",")
    profile = None if public_only else _browser_profile_dir()
    navigation_timeout_ms = timeout_ms or settings.playwright_navigation_timeout_ms
    with sync_playwright() as p:
        browser = None
        if public_only:
            browser = p.chromium.launch(headless=True, executable_path=browser_path)
            context = browser.new_context(
                viewport={"width": 1366, "height": 768}, locale=settings.language_code,
                geolocation={"latitude": float(latitude), "longitude": float(longitude)},
                permissions=["geolocation"],
            )
        else:
            context = p.chromium.launch_persistent_context(
                str(profile),
                headless=True,
                executable_path=browser_path,
                viewport={"width": 1366, "height": 768},
                locale=settings.language_code,
                geolocation={"latitude": float(latitude), "longitude": float(longitude)},
                permissions=["geolocation"],
            )
        try:
            page = context.new_page()
            if public_only:
                page.route("**/*", _public_request_route(set()))
            response = page.goto(url, wait_until="domcontentloaded", timeout=navigation_timeout_ms)
            status = response.status if response else None
            if public_only and _looks_like_sign_in_wall(page):
                return {"requested_url": url, "final_url": page.url, "status_code": status,
                        "crawl_failed": True, "blocked": True, "extraction_status": "blocked",
                        "error": "The public page appears to require sign-in; authenticated content is not captured."}
            best, ready, blocked, quality_reason, samples, elapsed = _wait_for_meaningful_render(
                page, url, status, settings.playwright_render_timeout_seconds
            )
            if blocked:
                failure = {"requested_url": url, "final_url": page.url,
                           "status_code": status, "crawl_failed": True, "blocked": True,
                           "extraction_status": "blocked", "error": "Access challenge detected; collection stopped.",
                           "content_readiness_checked": True,
                           "readiness_samples": samples, "readiness_wait_seconds": elapsed}
                failure.update(_save_diagnostics(page, url, "blocked"))
                return failure
            scroll_steps = _load_lazy_content(page)
            best.update(_full_page_inventory(page))
            best["lazy_load_scroll_steps"] = scroll_steps
            if artifact_dir is not None:
                best.update(_save_capture_artifacts(page, artifact_dir, best.get("image_inventory")))
            best["extraction_status"] = "complete" if ready else "incomplete"
            if not ready:
                best["seo_content_status"] = "unverified"
            elif quality_reason == "stable_visible_shadow_dom_content":
                best["seo_content_status"] = "accessible_shadow_dom_content"
            else:
                best["seo_content_status"] = "verified_candidate"
            if not ready:
                best.pop("seo_content_text", None)
            best.pop("seo_content_text_prefix", None)
            best["crawl_failed"] = not ready
            best["content_quality_reason"] = quality_reason
            best["content_readiness_checked"] = True
            best["content_stable"] = ready
            best["readiness_samples"] = samples
            best["readiness_wait_seconds"] = elapsed
            best.pop("readiness_text_prefix", None)
            best.pop("body_blocked", None)
            if not ready:
                best["error"] = "Meaningful, stable main-page content was not confirmed within the bounded wait."
                best.update(_save_diagnostics(page, url, "incomplete:" + quality_reason))
            return best
        finally:
            context.close()
            if browser is not None:
                browser.close()
