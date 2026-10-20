"""Normalize Lighthouse lab audit results without conflating them with field CWV."""
from __future__ import annotations

from scripts.resolve_pages import normalized_url
from analysis.technical_diagnostics import extract_technical_diagnostics

CATEGORIES = ("performance", "accessibility", "best-practices", "seo")
AUDITS = {
    "first_contentful_paint_ms": "first-contentful-paint",
    "largest_contentful_paint_ms": "largest-contentful-paint",
    "speed_index_ms": "speed-index",
    "total_blocking_time_ms": "total-blocking-time",
    "cumulative_layout_shift": "cumulative-layout-shift",
    "interactive_ms": "interactive",
}


def normalize_lighthouse(raw: dict, *, keyword: str, side: str, device: str,
                         ranking_url: str) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("Expected a Lighthouse JSON object")
    requested = raw.get("requestedUrl")
    final = raw.get("finalDisplayedUrl") or raw.get("finalUrl")
    requested_match = normalized_url(requested) == normalized_url(ranking_url)
    final_match = normalized_url(final) == normalized_url(ranking_url)
    errors = []
    if raw.get("runtimeError"):
        errors.append(str(raw["runtimeError"].get("message") or "Lighthouse runtime error"))
    if not requested_match:
        errors.append("Lighthouse requested URL differs from captured SERP ranking URL")
    if not final_match:
        errors.append("Lighthouse final URL differs from captured SERP ranking URL (possible redirect)")
    categories = raw.get("categories") or {}
    scores = {}
    for key in CATEGORIES:
        score = (categories.get(key) or {}).get("score")
        scores[key] = round(score * 100) if isinstance(score, (int, float)) and 0 <= score <= 1 else None
    audits = raw.get("audits") or {}
    metrics = {}
    for output_key, audit_key in AUDITS.items():
        val = (audits.get(audit_key) or {}).get("numericValue")
        metrics[output_key] = val if isinstance(val, (int, float)) else None
    status = "usable" if not errors and any(v is not None for v in scores.values()) else "unusable"
    if status == "unusable" and not errors:
        errors.append("No valid category scores returned")
    return {
        "keyword": keyword, "side": side, "scope": "page", "engine": "google", "device": device,
        "ranking_url": ranking_url, "requested_url": requested, "final_url": final,
        "target_verified": requested_match, "final_url_verified": final_match,
        "status": status, "warnings": errors,
        "lighthouse_version": raw.get("lighthouseVersion"),
        "fetch_time": raw.get("fetchTime"),
        "scores": scores, "lab_metrics": metrics,
        "technical_diagnostics": extract_technical_diagnostics(audits) if status == "usable" else {},
        "metrics_note": "Lighthouse lab data; not CrUX field Core Web Vitals or Google's ranking signals.",
    }
