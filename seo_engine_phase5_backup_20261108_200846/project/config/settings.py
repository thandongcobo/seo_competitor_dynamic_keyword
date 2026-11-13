from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def detect_browser_executable() -> str:
    configured = os.getenv("PLAYWRIGHT_BROWSER_PATH", "").strip()
    if configured:
        return configured

    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return ""


@dataclass(frozen=True)
class Settings:
    dataforseo_login: str = os.getenv("DATAFORSEO_LOGIN", "")
    dataforseo_password: str = os.getenv("DATAFORSEO_PASSWORD", "")

    keyword: str = os.getenv("SEO_KEYWORD", os.getenv("KEYWORD", "aviator"))
    language_code: str = os.getenv("LANGUAGE_CODE", "en")

    # SERP uses a precise coordinate target. Format: lat,lon,radius.
    location_coordinate: str = os.getenv(
        "LOCATION_COORDINATE",
        "-29.7359502,31.0699179,200",
    )

    # Labs has its own location capability and is kept independent from the
    # precise SERP coordinate. South Africa is the default domain-intelligence
    # context for this MVP.
    labs_location_name: str = os.getenv("LABS_LOCATION_NAME", "South Africa")

    our_domain: str = os.getenv("OUR_DOMAIN", "hollywoodbets.net")
    benchmark_competitor_domain: str = os.getenv("BENCHMARK_COMPETITOR_DOMAIN", "betway.co.za")

    our_page_url: str = os.getenv("OUR_PAGE_URL", "")
    competitor_page_url: str = os.getenv("COMPETITOR_PAGE_URL", "")

    # Detailed SERP screenshots, HTML and historical comparisons are opt-in.
    serp_diagnostics_enabled: bool = os.getenv("SERP_DIAGNOSTICS_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")

    serp_depth: int = int(os.getenv("SERP_DEPTH", "50"))
    competitor_window: int = int(os.getenv("COMPETITOR_WINDOW", "5"))
    candidate_crawl_limit: int = int(os.getenv("CANDIDATE_CRAWL_LIMIT", "12"))

    # Page capture waits for navigation, then polls rendered content until it
    # is substantive and stable or the bounded render window expires.
    playwright_navigation_timeout_ms: int = int(os.getenv("PLAYWRIGHT_NAVIGATION_TIMEOUT_MS", "60000"))
    playwright_render_timeout_seconds: int = int(os.getenv("PLAYWRIGHT_RENDER_TIMEOUT_SECONDS", "45"))
    playwright_render_minimum_seconds: int = int(os.getenv("PLAYWRIGHT_RENDER_MINIMUM_SECONDS", "4"))
    playwright_render_stability_seconds: int = int(os.getenv("PLAYWRIGHT_RENDER_STABILITY_SECONDS", "2"))

    playwright_browser_path: str = detect_browser_executable()


settings = Settings()


def keyword_slug(keyword: str) -> str:
    """Safe, stable keyword filename; prevents traversal and filename collisions."""
    import hashlib
    normalized = " ".join(keyword.strip().lower().split())
    base = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")[:70] or "keyword"
    if normalized == base:
        return base
    return f"{base}_{hashlib.sha256(normalized.encode()).hexdigest()[:8]}"


KEYWORD_SLUG = keyword_slug(settings.keyword)


DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed" / KEYWORD_SLUG
RESULTS_DIR = ROOT / "output" / "results" / KEYWORD_SLUG
CACHE_DIR = DATA_DIR / "cache"

for path in [RAW_DIR, PROCESSED_DIR, RESULTS_DIR, CACHE_DIR]:
    path.mkdir(parents=True, exist_ok=True)


def validate_settings() -> list[str]:
    errors: list[str] = []
    if not settings.dataforseo_login or not settings.dataforseo_password:
        errors.append("DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD are required for paid API collection.")
    if not settings.keyword.strip():
        errors.append("KEYWORD cannot be empty.")
    if settings.serp_depth < 10:
        errors.append("SERP_DEPTH must be at least 10.")
    if settings.competitor_window < 1:
        errors.append("COMPETITOR_WINDOW must be at least 1.")
    if settings.candidate_crawl_limit < 1:
        errors.append("CANDIDATE_CRAWL_LIMIT must be at least 1.")
    if not 10000 <= settings.playwright_navigation_timeout_ms <= 180000:
        errors.append("PLAYWRIGHT_NAVIGATION_TIMEOUT_MS must be between 10000 and 180000.")
    if not 4 <= settings.playwright_render_timeout_seconds <= 180:
        errors.append("PLAYWRIGHT_RENDER_TIMEOUT_SECONDS must be between 4 and 180.")
    if not 1 <= settings.playwright_render_minimum_seconds <= settings.playwright_render_timeout_seconds:
        errors.append("PLAYWRIGHT_RENDER_MINIMUM_SECONDS must be at least 1 and no greater than PLAYWRIGHT_RENDER_TIMEOUT_SECONDS.")
    if not 1 <= settings.playwright_render_stability_seconds <= 30:
        errors.append("PLAYWRIGHT_RENDER_STABILITY_SECONDS must be between 1 and 30.")
    return errors
