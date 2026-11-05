"""Local OCR and conservative promotion-candidate extraction for captures."""
from __future__ import annotations

import hashlib
import os
import re
import requests
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from bs4 import BeautifulSoup

PROMOTION_TERMS = (
    "bonus", "free", "offer", "promotion", "promo", "cashback", "cash back",
    "deposit", "earn", "win", "prize", "claim", "reward", "competition",
    "limited time", "share bets", "welcome", "voucher", "spin", "bet saver",
)
PROMO_ASSET_TERMS = ("banner", "promo", "offer", "bonus", "campaign", "betinfluencer", "advert")
EXCLUDED_ASSET_TERMS = ("logo", "icon", "flag", "sprite", "avatar", "sponsor")
TEXT_PROMOTION_TERMS = (
    "bonus", "free bet", "free bets", "free spins", "cashback", "cash back",
    "deposit match", "promo code", "promotion code", "special offer", "limited-time offer",
    "limited time offer", "claim your", "bet saver", "odds boost", "boosted odds",
    "welcome offer", "win cash", "earn cash", "get a free", "get your bonus", "voucher",
    "bonus spins", "jackpot", "% off", "discount", "match offer",
)
_CURRENCY_RE = re.compile(r"\b(?:R|ZAR)\s?\d[\d,.]*(?:\s?(?:million|m|k))?\b", re.I)
_PERCENT_RE = re.compile(r"\b\d{1,3}(?:\.\d+)?\s?%")
_CODE_RE = re.compile(r"\b(?:promo(?:tion)?\s+code|use\s+code|enter\s+code)\s*[:#-]?\s*([A-Z0-9][A-Z0-9-]{2,15})\b", re.I)
_DATE_RE = re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{4})\b", re.I)


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (value or "").lower()))


def _fingerprint(image: dict, text: str) -> str:
    source = str(image.get("src") or "")
    parsed = urlsplit(source)
    stable_source = urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", ""))
    basis = stable_source or _normalize(text)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _image_label(image: dict) -> str:
    label = str(image.get("alt") or image.get("title") or "").strip()
    if label:
        return label
    name = unquote(Path(urlsplit(str(image.get("src") or "")).path).stem)
    name = re.sub(r"^\d+[_-]+", "", name)
    name = re.sub(r"[_-]\d{2,4}[_-]\d{2,4}$", "", name)
    name = re.sub(r"[_-]+", " ", name).strip()
    return name[:110] or "Promotional banner candidate"


def _ocr_text(image_path: str) -> str:
    import pytesseract
    from PIL import Image

    command = os.getenv("TESSERACT_CMD", "").strip()
    if command:
        pytesseract.pytesseract.tesseract_cmd = command
    with Image.open(image_path) as image:
        return pytesseract.image_to_string(image, config="--psm 11")


def analyze_capture(snapshot: dict, *, ocr=_ocr_text) -> dict:
    """Find text and banner promotion candidates using transparent local rules."""
    text_candidates = _text_candidates(snapshot)
    inventory = snapshot.get("image_inventory") or []
    crop_by_index = {
        int(item.get("image_index")): item.get("path")
        for item in (snapshot.get("promotion_image_crops") or [])
        if item.get("path") and str(item.get("image_index", "")).isdigit()
    }
    if not crop_by_index:
        return {"status": "no_candidate_images", "message": "Text scan completed; no banner-sized image crops were saved for OCR.", "text_scan_complete": True, "image_scan_complete": False, "candidates": text_candidates}

    try:
        # Import and verify the local executable before processing candidates.
        import pytesseract
        command = os.getenv("TESSERACT_CMD", "").strip()
        if command:
            pytesseract.pytesseract.tesseract_cmd = command
        pytesseract.get_tesseract_version()
    except Exception as exc:
        image_candidates = _image_candidates(inventory, crop_by_index, {})
        return {
            "status": "unavailable",
            "message": "Text scan completed. Install Tesseract to read banner text; image candidates are still listed for manual review.",
            "error_type": type(exc).__name__,
            "text_scan_complete": True,
            "image_scan_complete": False,
            "candidates": _merge_candidates(text_candidates, image_candidates),
        }

    recognized = {}
    errors = 0
    for index, path in crop_by_index.items():
        try:
            recognized[index] = ocr(path)
        except Exception:
            errors += 1
    candidates = _merge_candidates(text_candidates, _image_candidates(inventory, crop_by_index, recognized))
    return {
        "status": "available" if not errors else "partial",
        "message": "OCR ran locally; promotion labels are candidates for human review." if not errors else "Some banner images could not be read; review the saved artwork.",
        "ocr_errors": errors,
        "text_scan_complete": True,
        "image_scan_complete": not errors,
        "candidates": candidates,
    }


def _text_promo_signals(text: str) -> list[str]:
    lower = text.lower()
    return [term for term in TEXT_PROMOTION_TERMS if term in lower]


def _candidate_links(block: dict, section_blocks: list[dict]) -> list[dict]:
    candidates = []
    direct = block.get("href")
    if direct:
        candidates.append({"text": block.get("text") or "", "url": direct})
    candidates.extend(item for item in (block.get("related_links") or []) if isinstance(item, dict))
    if not candidates:
        candidates.extend({"text": item.get("text") or "", "url": item.get("href")}
                          for item in section_blocks if item.get("href"))
    unique = {}
    for item in candidates:
        url = str(item.get("url") or "").strip()
        if url.startswith(("http://", "https://")):
            unique.setdefault(url, {"text": str(item.get("text") or "")[:180], "url": url})
    preferred = sorted(unique.values(), key=lambda item: (
        0 if re.search(r"offer|promo|bonus|claim|terms|condition|reward", item["url"] + " " + item["text"], re.I) else 1,
        len(item["text"]) == 0,
    ))
    return preferred[:5]


def _text_candidates(snapshot: dict) -> list[dict]:
    blocks = [item for item in (snapshot.get("rendered_text_blocks") or []) if isinstance(item, dict) and item.get("text")]
    # A composed card is the canonical evidence unit for its nested semantic
    # nodes; scanning both creates duplicate candidates for the same offer.
    if any(item.get("evidence_scope") == "composed_card" for item in blocks):
        blocks = [item for item in blocks if item.get("evidence_scope") != "composed_card_child"]
    if not blocks:
        text = snapshot.get("rendered_page_text") or snapshot.get("seo_content_text") or ""
        blocks = [{"text": sentence.strip(), "tag": "text", "section": "Public page"}
                  for sentence in re.split(r"(?<=[.!?])\s+|\n+", text) if sentence.strip()]
    crop_by_index = {
        int(item.get("image_index")): item.get("path")
        for item in (snapshot.get("promotion_image_crops") or [])
        if item.get("path") and str(item.get("image_index", "")).isdigit()
    }
    grouped = {}
    for item in blocks:
        grouped.setdefault(item.get("section") or "", []).append(item)
    seen = set()
    seen_fingerprints = set()
    candidates = []
    for block in blocks:
        text = " ".join(str(block.get("text") or "").split())[:2000]
        normalized = _normalize(text)
        if len(normalized) < 12 or normalized in seen:
            continue
        signals = _text_promo_signals(text)
        promotion_context = bool(block.get("promotion_context"))
        if not signals and not promotion_context:
            continue
        seen.add(normalized)
        currency = list(dict.fromkeys(_CURRENCY_RE.findall(text)))
        percentages = list(dict.fromkeys(_PERCENT_RE.findall(text)))
        codes = list(dict.fromkeys(match.group(1).upper() for match in _CODE_RE.finditer(text)))
        dates = list(dict.fromkeys(_DATE_RE.findall(text)))
        signal_groups = sum(bool(group) for group in (currency, percentages, codes, dates))
        confidence = "high" if signals and (signal_groups or len(signals) >= 2) else "medium"
        related = _candidate_links(block, grouped.get(block.get("section") or "", []))
        seed = "url:" + related[0]["url"] if related else "text:" + normalized
        fingerprint = hashlib.sha256(("text:" + seed).encode("utf-8")).hexdigest()
        if fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(fingerprint)
        details = extract_offer_details(text, source_url=snapshot.get("final_url") or snapshot.get("requested_url") or "")
        associated_image = next((ref for ref in block.get("image_refs", [])
                                 if ref.get("image_index") in crop_by_index and ref.get("url")), None)
        fingerprint = (_fingerprint({"src": associated_image["url"]}, text) if associated_image
                       else hashlib.sha256(("text:" + seed).encode("utf-8")).hexdigest())
        candidates.append({
            "fingerprint": fingerprint,
            "title": text[:110],
            "extracted_text": text,
            "source_url": snapshot.get("final_url") or snapshot.get("requested_url") or "",
            "target_url": related[0]["url"] if related else "",
            "related_links": related,
            "placement": block.get("section") or "Public page",
            "heading": block.get("heading") or "",
            "confidence": confidence,
            "reason": ("promotion-labelled card with offer wording" if promotion_context and signals
                       else "content inside a promotion-labelled card; review" if promotion_context
                       else "promotion wording" + (" plus offer details" if signal_groups else " detected in rendered page text")),
            "review_status": "needs_review",
            "source_type": "text",
            "signals": signals,
            "image_index": associated_image.get("image_index") if associated_image else None,
            "image_path": crop_by_index.get(associated_image.get("image_index")) if associated_image else None,
            "details": details,
            "investigation": {"status": "not_started", "reason": "Only high-confidence candidates with a same-host public link are investigated automatically."},
        })
    return candidates[:40]


def _merge_candidates(text_candidates: list[dict], image_candidates: list[dict]) -> list[dict]:
    result = list(text_candidates)
    by_target = {item.get("target_url"): item for item in result if item.get("target_url")}
    by_image_index = {item.get("image_index"): item for item in result if item.get("image_index") is not None}
    for image in image_candidates:
        match = (by_target.get(image.get("target_url")) if image.get("target_url") else None) or by_image_index.get(image.get("image_index"))
        if match:
            match["source_type"] = "text+image"
            match["image_path"] = image.get("image_path")
            match["image_index"] = image.get("image_index")
            match["image_text"] = image.get("extracted_text") or ""
            match["confidence"] = "high" if "high" in (match["confidence"], image["confidence"]) else "medium"
            match["reason"] += "; matching banner candidate also detected"
        else:
            image["source_type"] = "image"
            image["details"] = extract_offer_details(image.get("extracted_text") or "")
            image["investigation"] = {"status": "not_started", "reason": "Only high-confidence candidates are investigated automatically."}
            result.append(image)
    return result


def extract_offer_details(text: str, *, source_url: str = "") -> dict:
    """Extract explicit offer fields and short source excerpts; never infer missing terms."""
    text = " ".join((text or "").split())
    sentences = re.split(r"(?<=[.!?])\s+", text)
    evidence = [sentence[:500] for sentence in sentences if _text_promo_signals(sentence)][:8]
    eligibility_terms = ("new customers", "existing customers", "18+", "eligible", "minimum odds", "minimum deposit", "terms and conditions", "selected customers", "first deposit")
    eligibility = [sentence[:400] for sentence in sentences if any(term in sentence.lower() for term in eligibility_terms)][:8]
    return {
        "amounts": list(dict.fromkeys(_CURRENCY_RE.findall(text)))[:10],
        "percentages": list(dict.fromkeys(_PERCENT_RE.findall(text)))[:10],
        "promo_codes": list(dict.fromkeys(match.group(1).upper() for match in _CODE_RE.finditer(text)))[:10],
        "dates": list(dict.fromkeys(_DATE_RE.findall(text)))[:10],
        "time_windows": list(dict.fromkeys(m.group(0) for m in re.finditer(r'\b\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s*(?:-|–|to)\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)\b|\b\d{1,2}:\d{2}\s*(?:-|–|to)\s*\d{1,2}:\d{2}\b', text, re.I)))[:10],
        "eligibility_or_terms": eligibility,
        "evidence_excerpts": evidence,
        "source_url": source_url,
    }


def _safe_investigation_target(target_url: str, source_url: str) -> str | None:
    from .store import validate_public_url
    try:
        target = validate_public_url(urljoin(source_url, target_url))
        source_host = (urlsplit(source_url).hostname or "").lower()
        target_host = (urlsplit(target).hostname or "").lower()
        if target_host != source_host:
            return None
        return target
    except ValueError:
        return None


def fetch_public_offer_page(url: str, *, source_url: str, timeout: int = 8, max_bytes: int = 1_000_000) -> dict:
    """Fetch one bounded same-host public page without following redirects."""
    safe_url = _safe_investigation_target(url, source_url)
    if not safe_url:
        return {"status": "skipped", "reason": "The linked page is not on the monitored public host."}
    from .store import validate_public_host
    try:
        safe_url=validate_public_host(safe_url)
    except ValueError:
        return {"status": "skipped", "reason": "The linked host could not be verified as public."}
    try:
        with requests.get(safe_url, timeout=timeout, allow_redirects=False, stream=True,
                          headers={"User-Agent": "SEOCompetitorChangeMonitor/1.0"}) as response:
            if 300 <= response.status_code < 400:
                return {"status": "skipped", "reason": "The public link redirects; redirects are not followed during promotion investigation."}
            if response.status_code != 200:
                return {"status": "unavailable", "reason": f"Public page returned HTTP {response.status_code}.", "source_url": safe_url}
            content_type = response.headers.get("content-type", "").lower()
            if "html" not in content_type and "text/plain" not in content_type:
                return {"status": "skipped", "reason": "Linked resource is not an HTML/text page.", "source_url": safe_url}
            chunks, total = [], 0
            for chunk in response.iter_content(65536):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    return {"status": "skipped", "reason": "Linked page exceeds the 1 MB investigation limit.", "source_url": safe_url}
                chunks.append(chunk)
            html = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
        soup = BeautifulSoup(html, "lxml")
        for node in soup(["script", "style", "noscript", "svg", "form"]):
            node.decompose()
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        page_text = " ".join(soup.get_text(" ", strip=True).split())[:20000]
        if re.search(r"\b(sign in|log in|login required|please log in)\b", (title + " " + page_text[:1200]), re.I):
            return {"status": "skipped", "reason": "The linked page appears to require sign-in or may be an access page.", "source_url": safe_url}
        terms_url = next((urljoin(safe_url, anchor.get("href")) for anchor in soup.find_all("a", href=True)
                          if re.search(r"terms|conditions|rules", anchor.get_text(" ", strip=True) + " " + anchor.get("href", ""), re.I)
                          and urlsplit(urljoin(safe_url, anchor.get("href"))).hostname == urlsplit(safe_url).hostname), None)
        return {"status": "captured", "source_url": safe_url, "title": title,
                "text_excerpt": page_text[:4000], "details": extract_offer_details(page_text, source_url=safe_url),
                "terms_url": terms_url}
    except requests.RequestException as exc:
        return {"status": "unavailable", "reason": f"Could not retrieve linked public page ({type(exc).__name__}).", "source_url": safe_url}


def investigate_candidates(analysis: dict, *, source_url: str, fetch=fetch_public_offer_page, previous_candidates=None) -> dict:
    """Automatically inspect at most three strong candidates and merge source evidence."""
    started = 0
    from datetime import datetime, timezone
    from .intelligence import enrich
    prior={c.get('fingerprint'):c.get('investigation') or {} for c in previous_candidates or []}
    prior_items={c.get('fingerprint'):c for c in previous_candidates or []}
    candidates=analysis.get('candidates') or []
    for candidate in sorted(candidates,key=lambda c:prior.get(c.get('fingerprint'),{}).get('checked_at','')):
        if candidate.get("confidence") != "high":
            candidate["investigation"] = {"status": "review_required", "reason": "Candidate confidence is not high enough for automatic link investigation."}
            continue
        target = candidate.get("target_url")
        if not target:
            candidate["investigation"] = {"status": "no_public_link", "reason": "No related public link was captured for this candidate."}
            continue
        safe_target = _safe_investigation_target(target, source_url)
        if not safe_target:
            candidate["investigation"] = {"status": "skipped", "reason": "Automatic investigation is limited to links on the same public host."}
            continue
        if started >= 3:
            old=prior_items.get(candidate.get('fingerprint')) or {}
            old_investigation=old.get('investigation') or {}
            if old_investigation.get('status')=='captured' and old.get('extracted_text')==candidate.get('extracted_text') and old.get('target_url')==candidate.get('target_url'):
                candidate['investigation']={**old_investigation,'refresh_pending':True}
                candidate['details']=_merge_details(candidate.get('details') or {},old.get('details') or {})
                candidate['details']['terms_url']=(old.get('details') or {}).get('terms_url','')
                continue
            candidate["investigation"] = {"status": "queued_limit", "reason": "Per-capture automatic investigation limit reached.",
                                          'checked_at':prior.get(candidate.get('fingerprint'),{}).get('checked_at','')}
            continue
        try:
            result = fetch(safe_target, source_url=source_url)
        except Exception as exc:
            result = {'status':'unavailable','reason':f'Public detail retrieval failed ({type(exc).__name__}).'}
        result['checked_at']=datetime.now(timezone.utc).isoformat()
        result['refresh_pending']=False
        result['offer_details']=dict(result.get('details') or {})
        if result.get("status") == "captured" and result.get("terms_url"):
            safe_terms = _safe_investigation_target(result['terms_url'], source_url)
            if safe_terms and safe_terms != safe_target:
                try: terms_result = fetch(safe_terms, source_url=source_url)
                except Exception as exc: terms_result = {'status':'unavailable','reason':f'Terms retrieval failed ({type(exc).__name__}).'}
                result['terms_page'] = terms_result
                if terms_result.get('status') == 'captured':
                    result['details'] = _merge_details(result.get('details') or {}, terms_result.get('details') or {})
        candidate["investigation"] = result
        if result.get("status") == "captured":
            candidate["details"] = _merge_details(candidate.get("details") or {}, result.get("details") or {})
            candidate["details"]["terms_url"] = result.get("terms_url") or ""
            candidate["review_status"] = "auto_investigated"
        started += 1
    analysis["auto_investigated_count"] = started
    analysis['candidates']=[enrich({**c,'page_url':source_url}) for c in candidates]
    return analysis


def _merge_details(first: dict, second: dict) -> dict:
    merged = dict(first)
    for key in ("amounts", "percentages", "promo_codes", "dates", "time_windows", "eligibility_or_terms", "evidence_excerpts"):
        merged[key] = list(dict.fromkeys((first.get(key) or []) + (second.get(key) or [])))
    merged["source_url"] = first.get("source_url") or second.get("source_url") or ""
    merged["investigated_source_url"] = second.get("source_url") or ""
    return merged


def _image_candidates(inventory: list[dict], crops: dict[int, str], recognized: dict[int, str]) -> list[dict]:
    candidates = []
    seen = set()
    for index, image in enumerate(inventory):
        if index not in crops:
            continue
        asset_description = " ".join(str(image.get(key) or "") for key in ("src", "alt", "title")).lower()
        if any(term in asset_description for term in EXCLUDED_ASSET_TERMS) and not any(term in asset_description for term in PROMO_ASSET_TERMS):
            continue
        text = " ".join((recognized.get(index) or "").split())
        normalized_text = _normalize(text)
        promo_hits = [term for term in PROMOTION_TERMS if term in text.lower()]
        hinted = any(term in asset_description for term in PROMO_ASSET_TERMS)
        width = int(image.get("rendered_width") or 0)
        height = max(1, int(image.get("rendered_height") or 1))
        wide_banner = width / height >= 1.55
        # Wide creatives are surfaced as low-confidence candidates so sponsorship
        # artwork can be reviewed without being mislabeled as a definite offer.
        if not (promo_hits or hinted or wide_banner):
            continue
        fingerprint = _fingerprint(image, text)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        confidence = "high" if len(promo_hits) >= 2 else "medium" if promo_hits or hinted else "low"
        candidates.append({
            "fingerprint": fingerprint,
            "title": text[:110] or _image_label(image),
            "extracted_text": text[:2000],
            "source_url": image.get("src") or "",
            "target_url": image.get("href") or "",
            "image_path": crops[index],
            "image_index": index,
            "placement": image.get("section") or "Public page",
            "confidence": confidence,
            "reason": "promotional wording detected" if promo_hits else "promotion-like asset name" if hinted else "banner-shaped creative; confirm whether it is an offer",
            "review_status": "needs_review",
        })
    return candidates
