"""Validate Google pagination and aggregate organic results without hiding gaps."""
from __future__ import annotations

from urllib.parse import parse_qs, urljoin, urlparse

SELECTORS = (
    "a#pnnext", "a[aria-label='Next page']", "a[aria-label='Next']", "a:has-text('Next')"
)
CONTEXT_KEYS = ("gl", "hl", "pws")


def validate_next_url(initial_url: str, current_url: str, candidate: str, visited: set[str]) -> tuple[bool, str]:
    """Require an unvisited Google /search URL with same query and compatible context.

    Google may omit inherited context fields on Next links; reject conflicting values,
    and record missing fields in the page manifest for review.
    """
    dest = urljoin(current_url, candidate)
    parsed = urlparse(dest)
    base = urlparse(initial_url)
    current = urlparse(current_url)
    if parsed.scheme != "https" or parsed.hostname not in ("google.com", "www.google.com") or parsed.path != "/search":
        return False, "not_google_search"
    if dest in visited:
        return False, "already_visited"
    bq, cq, dq = (parse_qs(u.query) for u in (base, current, parsed))
    expected_query = bq.get("q", [None])[0]
    if not expected_query or dq.get("q", [None])[0] != expected_query:
        return False, "keyword_changed_or_missing"
    for key in CONTEXT_KEYS:
        expected = bq.get(key, cq.get(key, [None]))[0]
        actual = dq.get(key, [None])[0]
        if actual is not None and expected is not None and actual.lower() != expected.lower():
            return False, f"{key}_changed"
    # The destination must actually advance the result window; do not accept a
    # fresh search or an ambiguous repeated search as pagination.
    current_start = int(cq.get("start", ["0"])[0]) if cq.get("start", ["0"])[0].isdigit() else 0
    next_start = dq.get("start", [None])[0]
    if next_start is None or not next_start.isdigit() or int(next_start) <= current_start:
        return False, "missing_or_nonadvancing_start"
    return True, "valid"


def next_page_url(page, visited: set[str], initial_url: str | None = None) -> tuple[str | None, str]:
    initial_url = initial_url or page.url
    last_reason = "no_next_page"
    for selector in SELECTORS:
        try:
            links = page.locator(selector)
            for index in range(min(links.count(), 4)):
                href = links.nth(index).get_attribute("href")
                if not href:
                    continue
                absolute = urljoin(page.url, href)
                valid, reason = validate_next_url(initial_url, page.url, absolute, visited)
                if valid:
                    return absolute, "valid"
                last_reason = reason
        except Exception:
            continue
    return None, last_reason


def is_challenge(page) -> bool:
    if "/sorry/" in (page.url or ""):
        return True
    try:
        body = page.locator("body").inner_text(timeout=5000).lower()
    except Exception:
        return False
    return any(s in body for s in ("unusual traffic", "our systems have detected", "i'm not a robot", "recaptcha"))


def merge_unique(existing: list[dict], new: list[dict], max_results: int) -> tuple[list[dict], int]:
    """Append unique URLs in observed order; return duplicate count.

    The assigned rank is an observed sequence index, not a verified absolute
    Google position if the source page omitted organic results.
    """
    seen = {r.get("url") for r in existing}
    duplicates = 0
    for row in new:
        url = row.get("url")
        if not url or url in seen:
            duplicates += 1
            continue
        seen.add(url)
        existing.append({**row, "rank": len(existing) + 1})
        if len(existing) >= max_results:
            break
    return existing, duplicates
