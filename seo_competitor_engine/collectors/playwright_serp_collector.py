from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import Page, sync_playwright

from config.settings import RAW_DIR, settings, KEYWORD_SLUG

GOOGLE_SEARCH_URL = "https://www.google.com/search"
BING_SEARCH_URL = "https://www.bing.com/search"
BLOCK_MARKERS = (
    "unusual traffic",
    "our systems have detected unusual traffic",
    "captcha",
    "verify you are a human",
    "not a robot",
    "sorry/index",
    "automated queries",
    "too many requests",
)


def _browser_profile_dir() -> Path:
    path = RAW_DIR.parent / "browser_profile"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _extract_google_target(href: str) -> str:
    if not href:
        return ""
    parsed = urlparse(href)
    if parsed.netloc.endswith("google.com") and parsed.path == "/url":
        q = parse_qs(parsed.query)
        target = q.get("q", q.get("url", [""]))
        if target:
            return unquote(target[0])
    return href


def _is_result_url(url: str) -> bool:
    if not url or not url.startswith(("http://", "https://")):
        return False
    host = (urlparse(url).hostname or "").lower()
    blocked_hosts = {
        "google.com",
        "www.google.com",
        "accounts.google.com",
        "support.google.com",
        "policies.google.com",
        "bing.com",
        "www.bing.com",
        "cc.bingj.com",
    }
    return host not in blocked_hosts and not host.endswith(".google.com") and not host.endswith(".bing.com")


def _looks_blocked(text: str, title: str = "") -> bool:
    haystack = f"{title}\n{text}".lower()
    return any(marker in haystack for marker in BLOCK_MARKERS)


def _parse_google(page: Page, engine: str, keyword: str) -> dict[str, Any]:
    html = page.content()
    soup = BeautifulSoup(html, "lxml")
    organic: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Extract visible result headings using Playwright locators, as in the
    # teammate's implementation. Preserve original on-screen order.
    excluded_modules = ("#tads", "#tadsb", "#bottomads", "[data-pla]", "div[data-text-ad]")
    for heading in page.locator("h3").all():
        try:
            if not heading.is_visible():
                continue
            title = heading.inner_text(timeout=2000).strip()
            if not title:
                continue
            link = heading.locator("xpath=ancestor::a[@href][1]")
            if not link.count():
                continue
            href = link.first.get_attribute("href") or ""
            url = _extract_google_target(href)
            if not _is_result_url(url):
                continue
            block = heading.locator("xpath=ancestor::div[.//a[@href]][1]")
            if not block.count():
                block = heading
            # Avoid ad blocks, but never guess organic rankings from an ad.
            ad_found = False
            for selector in excluded_modules:
                if heading.locator(f"xpath=ancestor::*[self::div or self::section][contains(@id, 'tads')]").count():
                    ad_found = True
                    break
                if block.first.locator(selector).count():
                    ad_found = True
                    break
            if ad_found:
                continue
            text = block.first.inner_text(timeout=2000).strip()
            if text.lower().startswith(("sponsored", "advertisement")):
                continue
            parsed = urlparse(url)
            identity = (parsed.hostname or "").lower() + parsed.path.rstrip("/")
            if identity in seen:
                continue
            seen.add(identity)
            organic.append({
                "type": "organic",
                "rank_group": len(organic) + 1,
                "rank_absolute": None,
                "domain": (parsed.hostname or "").lower(),
                "url": url,
                "title": title,
                "description": text.replace(title, "", 1).strip()[:1000],
                "raw_text": text[:1500],
            })
        except Exception:
            continue

    features: list[dict[str, Any]] = []
    feature_labels = [
        ("people_also_ask", "People also ask"),
        ("video", "Videos"),
        ("image", "Images"),
        ("news", "Top stories"),
        ("ai_overview", "AI Overview"),
    ]
    page_text = soup.get_text(" ", strip=True)
    for feature_type, label in feature_labels:
        if label.lower() in page_text.lower():
            features.append({"type": feature_type, "label": label})

    return {
        "engine": engine,
        "keyword": keyword,
        "datetime": datetime.now(timezone.utc).isoformat(),
        "search_url": page.url,
        "organic_results_count": len(organic),
        "capture_scope": "first_page",
        "requested_depth": settings.serp_depth,
        "organic_results": organic[: settings.serp_depth],
        "serp_features": features,
        "items_count": len(organic[: settings.serp_depth]) + len(features),
        "collection_method": "playwright_local_browser",
        "location_coordinate": settings.location_coordinate,
        "device": "desktop",
        "browser_profile": str(_browser_profile_dir()),
    }


def _parse_bing(page: Page, engine: str, keyword: str) -> dict[str, Any]:
    html = page.content()
    soup = BeautifulSoup(html, "lxml")
    organic: list[dict[str, Any]] = []
    seen: set[str] = set()

    for li in soup.select("li.b_algo"):
        a = li.select_one("h2 a")
        if not a:
            continue
        url = a.get("href", "")
        if not _is_result_url(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        title = a.get_text(" ", strip=True)
        paragraph = li.select_one(".b_caption p")
        description = paragraph.get_text(" ", strip=True) if paragraph else ""
        organic.append({
            "type": "organic",
            "rank_group": len(organic) + 1,
            "rank_absolute": len(organic) + 1,
            "domain": (urlparse(url).hostname or "").lower(),
            "url": url,
            "title": title,
            "description": description[:1000],
        })

    return {
        "engine": engine,
        "keyword": keyword,
        "datetime": datetime.now(timezone.utc).isoformat(),
        "search_url": page.url,
        "organic_results_count": len(organic),
        "organic_results": organic[: settings.serp_depth],
        "serp_features": [],
        "items_count": len(organic[: settings.serp_depth]),
        "collection_method": "playwright_local_browser",
        "location_coordinate": settings.location_coordinate,
        "device": "desktop",
        "browser_profile": str(_browser_profile_dir()),
    }


def collect_engine_serp(engine: str, keyword: str) -> dict[str, Any]:
    """One browser visit, no challenge retry or automated pagination."""
    engine = engine.lower()
    if engine not in ("google", "bing"):
        raise ValueError("engine must be google or bing")
    browser_path = settings.playwright_browser_path
    if not browser_path:
        raise RuntimeError("Chrome/Edge not found. Set PLAYWRIGHT_BROWSER_PATH in .env")
    query_params = {"q": keyword}
    if engine == "google":
        query_params.update({"hl": "en", "gl": "za", "num": "20", "pws": "0"})
        base_url = GOOGLE_SEARCH_URL
    else:
        query_params.update({"cc": "ZA", "count": "10"})
        base_url = BING_SEARCH_URL
    search_url = base_url + "?" + "&".join(f"{k}={quote_plus(v)}" for k, v in query_params.items())
    profile = _browser_profile_dir()
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=False,
            **({"channel": "chrome"} if "chrome" in Path(browser_path).name.lower() else {"executable_path": browser_path}),
            viewport={"width": 1366, "height": 900},
            args=["--no-first-run", "--no-default-browser-check"],
            locale="en-ZA",
            timezone_id="Africa/Johannesburg",
        )
        try:
            page = context.new_page()
            page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
            # Handle a normal consent prompt if present; never solve challenges.
            try:
                consent = page.get_by_role("button", name=re.compile(r"^(Accept all|I agree)$", re.I)).first
                if consent.count() and consent.is_visible():
                    consent.click(timeout=3000)
            except Exception:
                pass
            try:
                page.locator("h3").first.wait_for(timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(2500)
            text = page.locator("body").inner_text(timeout=10000)
            if "/sorry/" in page.url or _looks_blocked(text, page.title()):
                return {"status": "blocked", "reason": "Search engine presented a challenge; collection stopped.",
                        "engine": engine, "keyword": keyword, "search_url": page.url,
                        "datetime": datetime.now(timezone.utc).isoformat(),
                        "collection_method": "playwright_local_browser"}
            data = _parse_google(page, engine, keyword) if engine == "google" else _parse_bing(page, engine, keyword)
            count = len(data["organic_results"])
            data["organic_results"] = data["organic_results"][:10]
            data["organic_results_count"] = len(data["organic_results"])
            data["capture_scope"] = "first_page"
            data["requested_depth"] = settings.serp_depth
            data["location_method"] = "local_network_ip_with_google_country_hint"
            if count < 5:
                return {"status": "incomplete", "reason": f"Only {count} organic results parsed (minimum 5)",
                        "engine": engine, "keyword": keyword, "search_url": page.url,
                        "datetime": data["datetime"], "collection_method": "playwright_local_browser"}
            return {"status": "ok", **data}
        finally:
            context.close()


def save_engine_serp(engine: str, data: dict[str, Any]) -> Path:
    import json
    folder = RAW_DIR / "serp"
    folder.mkdir(parents=True, exist_ok=True)
    safe_keyword = re.sub(r"[^a-zA-Z0-9_-]+", "_", settings.keyword).strip("_")
    filename = f"{safe_keyword}_{engine}_playwright.json"
    if data.get("status") != "ok":
        filename = f"{safe_keyword}_{engine}_playwright_diagnostic.json"
    path = folder / filename
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)
    return path
