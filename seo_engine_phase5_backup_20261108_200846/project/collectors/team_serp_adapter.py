"""Use the teammate's original Google search and extraction functions without Excel writes."""
from __future__ import annotations

import importlib.util
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.settings import RAW_DIR, settings, KEYWORD_SLUG
from collectors.team_serp_pagination import next_page_url, is_challenge, merge_unique
from collectors.tracked_serp import discovery_state
from collectors.serp_diagnostics import search_context, extraction_audit, run_summary

SOURCE = Path(__file__).resolve().parents[1] / 'scripts' / 'team_serp' / 'SEO_SERP_Monitor_aviator.py'


def load_team_module():
    spec = importlib.util.spec_from_file_location('teammate_aviator_original', SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Cannot load original teammate collector: {SOURCE}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def convert_results(rows: list[dict[str, Any]], keyword: str, url: str) -> dict[str, Any]:
    organic = []
    for i, row in enumerate(rows, 1):
        if not row.get('url') or not row.get('domain'):
            continue
        organic.append({
            'type': 'organic', 'rank_group': i, 'rank_absolute': i,
            'domain': row['domain'], 'url': row['url'],
            'title': row.get('title', ''), 'description': '',
            'website_name': row.get('name', ''),
            'source_result_key': row.get('key'),
        })
    return {
        'status': 'ok', 'engine': 'google', 'keyword': keyword,
        'datetime': datetime.now(timezone.utc).isoformat(),
        'search_url': url, 'organic_results_count': len(organic),
        'items_count': len(organic), 'organic_results': organic,
        'serp_features': [], 'collection_method': 'playwright_local_browser',
        'collector_variant': 'teammate_original_functions',
        'location_coordinate': None,
        'location_note': 'Google gl=za; not precise coordinate emulation',
        'depth_requested': settings.serp_depth, 'depth_collected': len(organic),
    }


def capture_serp_diagnostics(page: Any, keyword: str, *, stage: str = "before_extraction",
                             label: str = "", run_id: str | None = None,
                             team: Any = None) -> dict[str, Any]:
    """Save one isolated raw SERP capture per run/page, without changing results.

    HTML and screenshots are private local evidence and are not served by the UI.
    """
    safe_keyword = re.sub(r"[^a-zA-Z0-9_-]+", "_", keyword).strip("_") or "keyword"
    safe_label = re.sub(r"[^a-zA-Z0-9_-]+", "_", label).strip("_") or "page"
    dest = RAW_DIR.parent / "diagnostics" / "google" / safe_keyword / (run_id or "manual")
    dest.mkdir(parents=True, exist_ok=True)
    image_path = dest / f"{safe_label}_serp.png"
    html_path = dest / f"{safe_label}_serp.html"
    metadata_path = dest / f"{safe_label}_metadata.json"
    browser_observed = {}
    capture_errors = []
    try:
        browser_observed = page.evaluate("""() => ({
          language: navigator.language,
          languages: navigator.languages,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
          userAgent: navigator.userAgent,
          documentLanguage: document.documentElement.lang
        })""")
    except Exception as exc:
        capture_errors.append(f"browser_observed: {type(exc).__name__}: {exc}")
    configured = search_context(
        getattr(page, "url", "") or "", keyword=keyword,
        gl=getattr(team, "GOOGLE_GL", "za"), hl=getattr(team, "GOOGLE_HL", "en"),
        locale="en-ZA", timezone_id=getattr(team, "TIMEZONE", "Africa/Johannesburg"),
        headless=getattr(team, "HEADLESS", False), viewport={"width": 1366, "height": 900},
        profile_kind="fresh_isolated" if "fresh_profile" in label else "persistent",
        browser_observed=browser_observed)
    # A non-reversible identifier helps distinguish persistent vs isolated
    # browser profiles without exposing the local Windows path or cookies.
    profile_path = str(getattr(team, "PROFILE_DIR", ""))
    configured["configured"]["profile_identifier"] = (
        hashlib.sha256(str(Path(profile_path).resolve()).encode("utf-8")).hexdigest()[:16]
        if profile_path else None
    )
    metadata = {
        "keyword": keyword, "engine": "google", "stage": stage,
        "datetime": datetime.now(timezone.utc).isoformat(),
        "final_url": getattr(page, "url", None),
        "screenshot_path": str(image_path), "html_path": str(html_path),
        "metadata_path": str(metadata_path), "context": configured,
        "location_coordinate_applied": False,
        "organic_h3_count": None, "heading_candidates": None,
        "capture_errors": capture_errors,
    }
    try:
        metadata["organic_h3_count"] = page.locator("h3").count()
    except Exception as exc:
        capture_errors.append(f"heading_count: {type(exc).__name__}: {exc}")
    # The candidate list is evidence, not a second organic-ranking parser.
    try:
        metadata["heading_candidates"] = page.evaluate("""() => Array.from(document.querySelectorAll('h3')).map((h, i) => {
          const a = h.closest('a');
          return {index: i + 1, title: (h.innerText || '').trim(),
                  href: a ? a.href : null,
                  ancestor_text: (h.parentElement?.parentElement?.innerText || '').slice(0, 200)};
        })""")
    except Exception as exc:
        capture_errors.append(f"heading_candidates: {type(exc).__name__}: {exc}")
    try:
        page.screenshot(path=str(image_path), full_page=True, timeout=15000)
    except Exception as exc:
        capture_errors.append(f"screenshot: {type(exc).__name__}: {exc}")
    try:
        html_path.write_text(page.content(), encoding="utf-8")
    except Exception as exc:
        capture_errors.append(f"html: {type(exc).__name__}: {exc}")
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return metadata



def lightweight_serp_validation(page: Any, rows: list[dict], *, keyword: str, team: Any) -> dict:
    """Production validation: inspect DOM headings in memory, never save raw HTML.

    An unavailable DOM audit is reported as unverified, not a successful match.
    This does not alter the scraper's organic result sequence.
    """
    context = search_context(
        getattr(page, "url", "") or "", keyword=keyword,
        gl=getattr(team, "GOOGLE_GL", "za"), hl=getattr(team, "GOOGLE_HL", "en"),
        locale="en-ZA", timezone_id=getattr(team, "TIMEZONE", "Africa/Johannesburg"),
        headless=getattr(team, "HEADLESS", False), viewport={"width": 1366, "height": 900},
    )
    try:
        headings = page.evaluate("""() => Array.from(document.querySelectorAll('h3')).map((h, i) => {
          const a = h.closest('a');
          return {index: i + 1, title: (h.innerText || '').trim(),
                  href: a ? a.href : null,
                  ancestor_text: (h.parentElement?.parentElement?.innerText || '').slice(0, 200)};
        })""")
        audit = extraction_audit(rows, headings)
    except Exception as exc:
        audit = extraction_audit(rows, None, capture_error=f"DOM validation unavailable: {type(exc).__name__}")
    return {"context": context, "audit": audit}


def collect_once(keyword: str, *, fresh_profile_test: bool = False, depth: int = 50,
                 max_search_depth: int = 100, tracked_domain: str | None = None) -> dict[str, Any]:
    """Collect at least depth organic results, extending to find the tracked site.

    A challenge or missing next-page link ends collection; it is never bypassed.
    """
    if not 1 <= depth <= max_search_depth <= 100:
        raise ValueError('Require 1 <= depth <= max_search_depth <= 100')
    tracked_domain = tracked_domain or settings.our_domain
    team = load_team_module()
    team.KEYWORD = keyword
    team.NUMBER_OF_ORGANIC_RESULTS = max_search_depth
    if fresh_profile_test:
        isolated_profile = RAW_DIR.parent / "browser_profiles" / "fresh_profile_comparison"
        isolated_profile.mkdir(parents=True, exist_ok=True)
        team.PROFILE_DIR = str(isolated_profile)
    page = None
    results: list[dict[str, Any]] = []
    visited: set[str] = set()
    visited_order: list[str] = []
    page_manifest: list[dict[str, Any]] = []
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    page_snapshots_dir = RAW_DIR / "serp" / "pages" / re.sub(r"[^a-zA-Z0-9_-]+", "_", keyword) / run_id
    page_snapshots_dir.mkdir(parents=True, exist_ok=True)
    debug_enabled = settings.serp_diagnostics_enabled
    pages_completed = 0
    stop_reason = "unknown"
    initial_url = ""
    try:
        page = team.search_google(keyword)
        initial_url = page.url
        for page_number in range(1, 11):  # hard upper bound
            if is_challenge(page):
                stop_reason = "search_challenge"
                break
            if page.url in visited:
                stop_reason = "pagination_loop"
                break
            visited.add(page.url)
            visited_order.append(page.url)
            # Full evidence is captured only when explicitly enabled.
            if debug_enabled:
                diagnostics = capture_serp_diagnostics(page, keyword,
                    label=("fresh_profile_test_" if fresh_profile_test else "") + f"page_{page_number}",
                    run_id=run_id, team=team)
            else:
                diagnostics = {}
            rows = team.extract_organic_results(page)
            if debug_enabled:
                audit = extraction_audit(rows, diagnostics.get("heading_candidates"),
                    capture_error="; ".join(diagnostics.get("capture_errors") or []) or None)
                if diagnostics.get("metadata_path"):
                    diagnostics["extraction_audit"] = audit
                    Path(diagnostics["metadata_path"]).write_text(
                        json.dumps(diagnostics, indent=2, ensure_ascii=False), encoding="utf-8")
            else:
                lightweight = lightweight_serp_validation(page, rows, keyword=keyword, team=team)
                audit = lightweight["audit"]
                diagnostics = {"context": lightweight["context"]}
            before = len(results)
            results, duplicates = merge_unique(results, rows, max_search_depth)
            discovery = discovery_state(results, tracked_domain, depth, max_search_depth)
            manifest_row = {
                "page": page_number, "url": page.url, "organic_extracted": len(rows),
                "new_unique": len(results) - before, "duplicate_count": duplicates,
                "diagnostic_flags": (audit.get("flags", []) +
                    (["search_context_mismatch"] if diagnostics.get("context", {}).get("context_warning") else []) +
                    (["capture_incomplete"] if diagnostics.get("capture_errors") else [])),
                "validation": {k: audit.get(k) for k in ("status", "extracted_count", "heading_candidate_count", "flags")},
                "search_context": diagnostics.get("context"),
                "tracked_site_found": discovery['status'] == 'found',
                "tracked_site_observed_rank": discovery['rank'],
            }
            if debug_enabled:
                manifest_row.update({
                    "diagnostic_metadata": diagnostics.get("metadata_path"),
                    "diagnostic_screenshot": diagnostics.get("screenshot_path"),
                    "diagnostic_html": diagnostics.get("html_path"),
                    "extraction_audit": {k: audit.get(k) for k in ("status", "extracted_count", "heading_candidate_count", "flags", "suspicious_results")},
                })
            page_manifest.append(manifest_row)
            # Save page-local results before merging, including the exact page URL.
            page_path = page_snapshots_dir / f"page_{page_number:02d}.json"
            page_path.write_text(json.dumps({"keyword": keyword, **manifest_row, "organic_results": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
            pages_completed += 1
            if discovery['complete']:
                stop_reason = "tracked_site_found_with_neighbours"
                break
            if len(results) >= max_search_depth:
                stop_reason = "maximum_search_depth_reached"
                break
            next_url, next_reason = next_page_url(page, visited, initial_url)
            if not next_url:
                stop_reason = next_reason
                break
            try:
                page.goto(next_url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(1800)
            except Exception as exc:
                stop_reason = "navigation_failed"
                break
        else:
            stop_reason = "page_limit_reached"
        if not results:
            raise RuntimeError(f"No organic results collected; reason={stop_reason}")
        output = convert_results(results, keyword, initial_url)
        tracked = discovery_state(results, tracked_domain, depth, max_search_depth)
        tracked['search_exhausted'] = not tracked['complete']
        tracked['stop_reason'] = stop_reason
        output.update({
            "status": "ok" if tracked['complete'] else "partial",
            "depth_requested": depth,
            "maximum_search_depth": max_search_depth,
            "depth_collected": len(results),
            "tracked_site": tracked,
            "pages_completed": pages_completed,
            "stop_reason": stop_reason,
            "pagination_urls": visited_order,
            "page_manifest": page_manifest,
            "validation": {
                "status": "review_required" if any(p["diagnostic_flags"] for p in page_manifest) else "checks_passed",
                "flags": sorted({flag for p in page_manifest for flag in p["diagnostic_flags"]}),
                "pages_checked": len(page_manifest),
            },
            "serp_diagnostics_enabled": debug_enabled,
            "page_snapshots_directory": str(page_snapshots_dir),
            "rank_semantics": "observed_organic_sequence; may be incomplete if source extraction misses results",
        })
        if fresh_profile_test:
            output["profile_test"] = "fresh_profile_comparison"
        if debug_enabled:
            output["diagnostics"] = run_summary(page_manifest, run_id=run_id, stop_reason=stop_reason)
            output["diagnostics_directory"] = str(RAW_DIR.parent / "diagnostics" / "google" /
                (re.sub(r"[^a-zA-Z0-9_-]+", "_", keyword).strip("_") or "keyword") / run_id)
            report_path = Path(output["diagnostics_directory"]) / "run_report.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps({
                "keyword": keyword, "run_id": run_id, "datetime": output["datetime"],
                "search_url": initial_url, "pages": page_manifest,
                "diagnostics": output["diagnostics"], "tracked_site": tracked,
                "stop_reason": stop_reason,
                "note": "No Google results were altered or chosen for similarity to another search."
            }, indent=2, ensure_ascii=False), encoding="utf-8")
        return output
    finally:
        if page is not None:
            try:
                page.close()
            except Exception:
                pass
        team.BROWSER.close()


def save_success(data: dict[str, Any]) -> Path:
    path = RAW_DIR / 'serp' / f'{KEYWORD_SLUG}_google_playwright.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)
    return path


def save_diagnostic(data: dict[str, Any]) -> Path:
    path = RAW_DIR / 'serp' / f'{KEYWORD_SLUG}_google_playwright_diagnostic.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return path
