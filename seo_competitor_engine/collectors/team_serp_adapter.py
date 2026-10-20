"""Use the teammate's original Google search and extraction functions without Excel writes."""
from __future__ import annotations

import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.settings import RAW_DIR, settings, KEYWORD_SLUG
from collectors.team_serp_pagination import next_page_url, is_challenge, merge_unique

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


def capture_serp_diagnostics(page: Any, keyword: str, *, stage: str = "before_extraction", label: str = "") -> dict[str, Any]:
    """Save rendered Google page before parsing; never modify raw ranking data.

    The HTML may contain session information. Keep diagnostics local/private.
    """
    safe_keyword = re.sub(r"[^a-zA-Z0-9_-]+", "_", keyword).strip("_") or "keyword"
    if label:
        safe_keyword += "_" + re.sub(r"[^a-zA-Z0-9_-]+", "_", label)
    dest = RAW_DIR.parent / "diagnostics" / "google"
    dest.mkdir(parents=True, exist_ok=True)
    image_path = dest / f"{safe_keyword}_serp.png"
    html_path = dest / f"{safe_keyword}_serp.html"
    metadata_path = dest / f"{safe_keyword}_metadata.json"
    metadata = {
        "keyword": keyword,
        "engine": "google",
        "stage": stage,
        "datetime": datetime.now(timezone.utc).isoformat(),
        "final_url": getattr(page, "url", None),
        "screenshot_path": str(image_path),
        "html_path": str(html_path),
        "location_coordinate_applied": False,
        "location_note": "Google gl=za; not precise coordinate emulation",
        "organic_h3_count": None,
        "capture_errors": [],
    }
    try:
        metadata["organic_h3_count"] = page.locator("h3").count()
    except Exception as exc:
        metadata["capture_errors"].append(f"heading_count: {type(exc).__name__}: {exc}")
    try:
        page.screenshot(path=str(image_path), full_page=True, timeout=15000)
    except Exception as exc:
        metadata["capture_errors"].append(f"screenshot: {type(exc).__name__}: {exc}")
    try:
        html_path.write_text(page.content(), encoding="utf-8")
    except Exception as exc:
        metadata["capture_errors"].append(f"html: {type(exc).__name__}: {exc}")
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return metadata


def collect_once(keyword: str, *, fresh_profile_test: bool = False, depth: int = 50) -> dict[str, Any]:
    """Collect up to depth organic results across available pages.

    A challenge or missing next-page link ends collection; it is never bypassed.
    """
    team = load_team_module()
    team.KEYWORD = keyword
    team.NUMBER_OF_ORGANIC_RESULTS = max(1, depth)
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
            diagnostics = capture_serp_diagnostics(page, keyword, label=("fresh_profile_test_" if fresh_profile_test else "") + f"page_{page_number}")
            rows = team.extract_organic_results(page)
            before = len(results)
            results, duplicates = merge_unique(results, rows, depth)
            manifest_row = {
                "page": page_number, "url": page.url, "organic_extracted": len(rows),
                "new_unique": len(results) - before, "duplicate_count": duplicates,
                "diagnostic_metadata": diagnostics.get("screenshot_path"),
            }
            page_manifest.append(manifest_row)
            # Save page-local results before merging, including the exact page URL.
            page_path = page_snapshots_dir / f"page_{page_number:02d}.json"
            page_path.write_text(json.dumps({"keyword": keyword, **manifest_row, "organic_results": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
            pages_completed += 1
            if len(results) >= depth:
                stop_reason = "requested_depth_reached"
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
        output.update({
            "status": "ok" if stop_reason == "requested_depth_reached" else "partial",
            "depth_requested": depth,
            "depth_collected": len(results),
            "pages_completed": pages_completed,
            "stop_reason": stop_reason,
            "pagination_urls": visited_order,
            "page_manifest": page_manifest,
            "page_snapshots_directory": str(page_snapshots_dir),
            "rank_semantics": "observed_organic_sequence; may be incomplete if source extraction misses results",
        })
        if fresh_profile_test:
            output["profile_test"] = "fresh_profile_comparison"
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
