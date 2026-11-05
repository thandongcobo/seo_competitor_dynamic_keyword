"""Non-invasive, per-observation Google SERP context and extraction diagnostics.

Diagnostics never decide which Google observation is 'correct', never reorder
results, and never trigger additional searches. Raw HTML stays local/private.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse, urlsplit, unquote
import re


def search_context(final_url: str, *, keyword: str, gl: str, hl: str, pws: str = "0",
                   locale: str = "en-ZA", timezone_id: str = "Africa/Johannesburg",
                   headless: bool = False, viewport: dict | None = None,
                   profile_kind: str = "persistent", browser_observed: dict | None = None) -> dict:
    """Describe configured context separately from what Google's URL confirms."""
    parsed = urlparse(final_url or "")
    query = parse_qs(parsed.query)
    expected = {"q": keyword, "gl": gl, "hl": hl, "pws": pws}
    checks = {}
    for key, value in expected.items():
        actual = query.get(key, [None])[0]
        checks[key] = ("not_in_final_url" if actual is None else
                       "match" if actual.casefold() == value.casefold() else "mismatch")
    return {
        "configured": {"keyword": keyword, "country_gl": gl, "language_hl": hl,
                       "personalization_pws": pws, "locale": locale, "timezone": timezone_id,
                       "headless": headless, "viewport": viewport,
                       "profile_type": profile_kind},
        "observed": {"final_url": final_url, "hostname": parsed.hostname,
                     "url_parameters": {k: query.get(k, [None])[0] for k in expected},
                     "browser": browser_observed or {}},
        "url_parameter_checks": checks,
        "context_warning": (parsed.hostname not in ("www.google.com", "google.com") or
                            any(v == "mismatch" for v in checks.values())),
        "note": "gl targets a country; it does not verify precise physical location or search intent.",
    }


def _normalize_url(url: str) -> str:
    """Normalize a direct destination URL without discarding meaningful queries."""
    parsed = urlsplit(str(url or ""))
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if not host or parsed.scheme.lower() not in ("http", "https"):
        return ""
    return host + parsed.path.rstrip("/") + ("?" + parsed.query if parsed.query else "")


def _google_link_destination(href: str) -> tuple[str, bool]:
    """Return a verifiable destination, or signal an opaque Google redirect.

    /goto?url=CAES... is an opaque token, *not* a URL. Never pretend to
    decode it. /url?q=https%3A... and similar explicit URLs are resolvable.
    """
    parsed = urlsplit(str(href or ""))
    host = (parsed.hostname or "").lower()
    if host not in ("google.com", "www.google.com") or parsed.path not in ("/goto", "/url"):
        return href, False
    params = parse_qs(parsed.query)
    for key in ("url", "q", "adurl"):
        for candidate in params.get(key, []):
            destination = unquote(candidate)
            if _normalize_url(destination):
                return destination, False
    return "", True


def _displayed_domains(ancestor_text: str) -> set[str]:
    """Domains visibly shown in the result snippet, not inferred from title."""
    domains = set()
    for match in re.finditer(r"https?://[^\s<>\u203a]+", str(ancestor_text or ""), re.I):
        parsed = urlsplit(match.group(0).rstrip(".,;:)]}"))
        if parsed.hostname:
            domains.add(parsed.hostname.lower().removeprefix("www."))
    return domains


def _clean_title(value: object) -> str:
    return " ".join(str(value or "").casefold().split()).strip(" .")


def _match_heading(row: dict, headings: list[dict], used: set[int]) -> tuple[str, int | None]:
    """Match one row to one heading, distinguishing URL proof from DOM evidence.

    A linked title plus the displayed domain is useful evidence for opaque
    Google /goto redirects, but does not independently verify the destination
    URL. Duplicate ambiguous headings are not silently marked verified.
    """
    destination = _normalize_url(row.get("url", ""))
    row_title = _clean_title(row.get("title"))
    host = urlsplit(str(row.get("url") or "")).hostname
    domain = host.lower().removeprefix("www.") if host else ""
    if not destination or not row_title:
        return "unmatched", None
    candidates = []
    for index, heading in enumerate(headings):
        if index in used or _clean_title(heading.get("title")) != row_title:
            continue
        href = str(heading.get("href") or "")
        if not href:
            continue
        linked_destination, opaque = _google_link_destination(href)
        if not opaque:
            if _normalize_url(linked_destination) == destination:
                candidates.append((index, "direct_or_decoded_url"))
            continue
        if domain and domain in _displayed_domains(heading.get("ancestor_text", "")):
            candidates.append((index, "opaque_redirect_title_and_displayed_domain"))
    # Even two matching opaque headings could represent different pages.
    if len(candidates) != 1:
        return ("ambiguous" if candidates else "unmatched"), None
    index, method = candidates[0]
    return method, index


def extraction_audit(rows: list[dict], headings: list[dict] | None, *, capture_error: str | None = None) -> dict:
    """Audit extracted rows without modifying ranks or assuming redirect tokens decode."""
    flags: list[str] = []
    suspicious = []
    excluded_feature_headings = []
    if headings is not None:
        for heading in headings:
            title = _clean_title(heading.get("title"))
            if title in ("ai mode replied:", "ai mode replied", "ai overview",
                         "generative ai is experimental"):
                excluded_feature_headings.append({
                    "heading_index": heading.get("index"),
                    "title": heading.get("title"),
                    "linked_title": bool(heading.get("href")),
                })
    for index, row in enumerate(rows, 1):
        title = _clean_title(row.get("title"))
        if any(phrase in title for phrase in ("ai mode replied", "ai overview", "generative ai is experimental")):
            suspicious.append({"observed_sequence": index, "title": row.get("title"),
                               "url": row.get("url"), "reason": "possible_ai_feature"})
    if suspicious:
        flags.append("possible_non_organic_results_extracted")
    missing: list[str] = []
    match_details: list[dict] = []
    opaque_count = 0
    if headings is None:
        flags.append("heading_evidence_unavailable")
    else:
        used: set[int] = set()
        for sequence, row in enumerate(rows, 1):
            method, matched_index = _match_heading(row, headings, used)
            if matched_index is not None:
                used.add(matched_index)
            if method == "opaque_redirect_title_and_displayed_domain":
                opaque_count += 1
            if method in ("unmatched", "ambiguous"):
                missing.append(row.get("url"))
            match_details.append({
                "observed_sequence": sequence, "url": row.get("url"),
                "match_method": method,
                "heading_index": headings[matched_index].get("index") if matched_index is not None else None,
            })
        if missing:
            flags.append("some_result_urls_not_matched_to_heading_links")
    return {
        "status": "review_required" if flags else "evidence_captured_not_manually_verified",
        "extracted_count": len(rows),
        "heading_candidate_count": len(headings) if headings is not None else None,
        "flags": flags,
        "suspicious_results": suspicious,
        "excluded_feature_headings_observed": excluded_feature_headings,
        "heading_link_mismatches": missing,
        "heading_matches": match_details,
        "opaque_redirect_domain_matches": opaque_count,
        "capture_error": capture_error,
        "note": ("Opaque Google redirect destinations cannot be decoded from their tokens; "
                 "linked heading title and visibly displayed domain are corroborating DOM evidence, "
                 "not independent proof of the final URL or absolute Google rank. "
                 "Unmatched or ambiguous results require manual HTML/screenshot review."),
    }


def run_summary(pages: list[dict], *, run_id: str, stop_reason: str) -> dict:
    flags = []
    for page in pages:
        for flag in page.get("diagnostic_flags", []):
            if flag not in flags:
                flags.append(flag)
    return {"run_id": run_id, "pages_diagnosed": len(pages),
            "review_required": bool(flags), "flags": flags, "stop_reason": stop_reason,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "interpretation": "Variation between searches is allowed. Diagnose context and extraction for each observed SERP independently."}


def compare_observations(previous: dict, current: dict, *, limit: int = 20) -> dict:
    """Compare observations without treating SERP agreement as a correctness test."""
    old = (previous.get("organic_results") or [])[:limit]
    new = (current.get("organic_results") or [])[:limit]
    old_urls = [str(r.get("url") or "") for r in old if isinstance(r, dict) and r.get("url")]
    new_urls = [str(r.get("url") or "") for r in new if isinstance(r, dict) and r.get("url")]
    old_set, new_set = set(old_urls), set(new_urls)
    old_context = (previous.get("page_manifest") or [{}])[0].get("search_context") or {}
    new_context = (current.get("page_manifest") or [{}])[0].get("search_context") or {}
    old_config = old_context.get("configured")
    new_config = new_context.get("configured")
    changes = {}
    if isinstance(old_config, dict) and isinstance(new_config, dict):
        changes = {key: {"previous": old_config.get(key), "current": new_config.get(key)}
                   for key in sorted(set(old_config) | set(new_config))
                   if old_config.get(key) != new_config.get(key)}
    return {
        "previous_collected_at": previous.get("datetime"),
        "current_collected_at": current.get("datetime"),
        "comparison_limit": limit,
        "previous_results_compared": len(old_urls),
        "current_results_compared": len(new_urls),
        "shared_exact_urls": len(old_set & new_set),
        "url_overlap_fraction_of_union": round(len(old_set & new_set) / len(old_set | new_set), 3) if old_set | new_set else None,
        "first_result_changed": (old_urls[0] != new_urls[0]) if old_urls and new_urls else None,
        "configured_context_comparable": isinstance(old_config, dict) and isinstance(new_config, dict),
        "configured_context_changes": changes,
        "conclusion": "Observed variation is not evidence of incorrect search context; inspect page-level captures and context warnings to investigate causes.",
    }
