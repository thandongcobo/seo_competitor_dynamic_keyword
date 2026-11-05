"""Read-only Playwright rendering diagnostic for a resolved SERP ranking page.

Runs separately from the production crawler; no API calls, no captcha bypass,
no clicks, and no modifications to raw/processed SEO data.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from playwright.sync_api import sync_playwright
from config.settings import DATA_DIR, PROCESSED_DIR, settings, keyword_slug

BLOCK_MARKERS = (
    "unusual traffic", "captcha", "verify you are a human", "not a robot",
    "too many requests", "access denied", "automated queries",
)
SCHEDULE = (0, 3, 8, 15, 25)


def public_url(value: str | None) -> str:
    """Strip query, fragment, userinfo: avoid exposing session or token values."""
    if not value:
        return ""
    try:
        u = urlsplit(value)
        if u.scheme not in ("http", "https"):
            return "[non-http URL]"
        hostname = u.hostname or ""
        port = f":{u.port}" if u.port else ""
        return urlunsplit((u.scheme, hostname + port, u.path or "/", "", ""))
    except Exception:
        return "[invalid URL]"


def target_from_resolved(data: dict[str, Any], engine: str, side: str) -> str:
    comparison = ((data.get("engines") or {}).get(engine) or {}).get("comparison") or {}
    key = "our_url" if side == "ours" else "benchmark_url"
    value = comparison.get(key)
    if not isinstance(value, str) or not value.startswith(("https://", "http://")):
        raise ValueError(f"No valid {side} URL for {engine} in resolved_candidates.json")
    return value


def choose_target(keyword: str, engine: str, side: str, override: str | None) -> str:
    if override:
        if not override.startswith(("https://", "http://")):
            raise ValueError("--url must be http:// or https://")
        return override
    path = DATA_DIR / "processed" / keyword_slug(keyword) / "resolved_candidates.json"
    if not path.exists():
        raise FileNotFoundError(f"Ranking URL source not found: {path}; run resolve first")
    return target_from_resolved(json.loads(path.read_text(encoding="utf-8")), engine, side)


def _counts_from_frame(frame: Any) -> dict[str, Any]:
    """DOM-only counts, no text content or browser secrets in report."""
    try:
        return frame.evaluate("""() => {
          const text = (document.body?.innerText || '').trim();
          const count = el => (el?.innerText || '').trim().split(/\\s+/).filter(Boolean).length;
          const main = document.querySelector('main, [role="main"], article, #main, #content');
          return {words: text ? text.split(/\\s+/).length : 0,
                  main_words: main ? count(main) : null,
                  h1: document.querySelectorAll('h1').length,
                  h2: document.querySelectorAll('h2').length,
                  links: document.querySelectorAll('a[href]').length,
                  scripts: document.querySelectorAll('script').length,
                  iframes: document.querySelectorAll('iframe').length,
                  title: (document.title || '').slice(0, 160)};
        }""")
    except Exception as exc:
        return {"error": type(exc).__name__}


def frame_inventory(page: Any) -> list[dict[str, Any]]:
    items = []
    for frame in page.frames[:40]:
        items.append({"url": public_url(frame.url), "is_main": frame == page.main_frame,
                      "dom": _counts_from_frame(frame)})
    return items


def take_snapshot(page: Any, elapsed: float) -> dict[str, Any]:
    counts = _counts_from_frame(page.main_frame)
    body = ""
    try:
        body = page.locator("body").inner_text(timeout=2000).lower()[:3000]
    except Exception:
        pass
    return {"elapsed_seconds": round(elapsed, 1), "url": public_url(page.url),
            "blocked_marker_detected": any(x in body for x in BLOCK_MARKERS),
            "main_document": counts,
            "frames": frame_inventory(page)}


def summary_text(report: dict[str, Any]) -> str:
    lines = ["=== PLAYWRIGHT RENDERING DIAGNOSTIC ===",
             f"Keyword: {report['keyword']} | Engine: {report['engine']} | Side: {report['side']}",
             f"Requested URL: {report['requested_url']}",
             f"Final URL: {report.get('final_url', '')}",
             f"HTTP status: {report.get('http_status')}",
             f"Navigation error: {report.get('navigation_error') or 'none'}",
             "", "=== CONTENT OVER TIME ==="]
    for snap in report.get("snapshots", []):
        dom = snap.get("main_document", {})
        lines.append(f"t={snap['elapsed_seconds']}s | words={dom.get('words')} | main_words={dom.get('main_words')} | "
                     f"h1={dom.get('h1')} | links={dom.get('links')} | frames={len(snap.get('frames', []))} | "
                     f"blocked_marker={snap.get('blocked_marker_detected')}")
    lines.append("\n=== FINAL FRAME INVENTORY ===")
    for frame in report.get("frames_final", []):
        dom = frame.get("dom", {})
        lines.append(f"{'MAIN' if frame['is_main'] else 'IFRAME'} {frame['url']} | "
                     f"words={dom.get('words')} main_words={dom.get('main_words')}")
    lines.extend(["", "=== NETWORK / BROWSER ===",
                  f"Requests by type: {report.get('request_types', {})}",
                  f"Failed request counts by reason: {report.get('failed_request_reasons', {})}",
                  f"Failed request hosts: {report.get('failed_request_hosts', {})}",
                  f"HTTP 4xx/5xx counts: {report.get('http_error_counts', {})}",
                  f"HTTP error hosts: {report.get('http_error_hosts', {})}",
                  f"Page errors: {report.get('page_error_count', 0)}",
                  f"Console errors: {report.get('console_error_count', 0)}",
                  "", "=== FILES ===",
                  f"Screenshot: {report.get('screenshot_path') or 'not saved'}",
                  f"HTML: {report.get('html_path') or 'not saved (opt-in: --save-html)'}",
                  "", "Interpretation: navigation/footer words may appear before main content. "
                  "Iframe text may be gameplay rather than SEO landing-page content.",
                  "Do not share raw screenshots/HTML without reviewing for private information."])
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> Path:
    target = choose_target(args.keyword, args.engine, args.side, args.url)
    browser_path = settings.playwright_browser_path
    if not browser_path or not Path(browser_path).exists():
        raise RuntimeError("Chrome/Edge not found. Set PLAYWRIGHT_BROWSER_PATH in .env")
    lat, lon, *_ = settings.location_coordinate.split(",")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = DATA_DIR / "diagnostics" / "rendering" / keyword_slug(args.keyword) / f"{args.engine}_{args.side}_{stamp}"
    folder.mkdir(parents=True, exist_ok=True)
    profile = DATA_DIR / ("browser_profile" if args.use_production_profile else "diagnostic_browser_profile")
    profile.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "keyword": args.keyword, "engine": args.engine, "side": args.side,
        "requested_url": public_url(target), "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "browser_profile": "production" if args.use_production_profile else "isolated_diagnostic",
        "snapshots": [], "request_types": {}, "failed_request_reasons": {},
        "http_error_counts": {}, "page_error_count": 0, "console_error_count": 0,
    }
    request_types: Counter[str] = Counter()
    failed_reasons: Counter[str] = Counter()
    http_errors: Counter[str] = Counter()
    http_error_hosts: Counter[str] = Counter()
    failed_request_hosts: Counter[str] = Counter()
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(profile), executable_path=browser_path, headless=not args.headed,
            viewport={"width": 1366, "height": 768}, locale=settings.language_code,
            geolocation={"latitude": float(lat), "longitude": float(lon)},
            permissions=["geolocation"],
        )
        try:
            page = context.new_page()
            page.on("request", lambda req: request_types.update([req.resource_type]))
            def on_failed(req: Any) -> None:
                failed_reasons.update([(req.failure or "unknown")[:70] if isinstance(req.failure, str) else "unknown"])
                failed_request_hosts.update([urlsplit(public_url(req.url)).hostname or "unknown"])

            def on_response(resp: Any) -> None:
                if resp.status >= 400:
                    http_errors.update([str(resp.status)])
                    http_error_hosts.update([urlsplit(public_url(resp.url)).hostname or "unknown"])

            page.on("requestfailed", on_failed)
            page.on("response", on_response)
            page.on("pageerror", lambda exc: report.__setitem__("page_error_count", report["page_error_count"] + 1))
            page.on("console", lambda msg: report.__setitem__("console_error_count", report["console_error_count"] + 1) if msg.type == "error" else None)
            try:
                response = page.goto(target, wait_until="domcontentloaded", timeout=args.timeout_ms)
                report["http_status"] = response.status if response else None
            except Exception as exc:
                report["navigation_error"] = f"{type(exc).__name__}: navigation failed or timed out"
            start = time.monotonic()
            for sec in SCHEDULE:
                delay = sec - (time.monotonic() - start)
                if delay > 0:
                    page.wait_for_timeout(int(delay * 1000))
                report["snapshots"].append(take_snapshot(page, time.monotonic() - start))
                print(f"Snapshot {sec}s: {report['snapshots'][-1]['main_document'].get('words')} words")
            report["final_url"] = public_url(page.url)
            report["frames_final"] = frame_inventory(page)
            try:
                screenshot = folder / "final_page.png"
                page.screenshot(path=str(screenshot), full_page=True, timeout=15000)
                report["screenshot_path"] = str(screenshot)
            except Exception as exc:
                report["screenshot_error"] = type(exc).__name__
            if args.save_html:
                try:
                    html = folder / "final_page.html"
                    html.write_text(page.content(), encoding="utf-8")
                    report["html_path"] = str(html)
                except Exception as exc:
                    report["html_error"] = type(exc).__name__
            report["request_types"] = dict(request_types)
            report["failed_request_reasons"] = dict(failed_reasons)
            report["http_error_counts"] = dict(http_errors)
            report["http_error_hosts"] = dict(http_error_hosts)
            report["failed_request_hosts"] = dict(failed_request_hosts)
        finally:
            context.close()
    report_path = folder / "diagnostic.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    text_path = folder / "diagnostic_report.txt"
    text_path.write_text(summary_text(report), encoding="utf-8")
    print("\nReport:", text_path)
    print("JSON:", report_path)
    print("Screenshot:", report.get("screenshot_path", "unavailable"))
    return text_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose rendered page content without modifying production crawl outputs")
    parser.add_argument("--keyword", default=settings.keyword)
    parser.add_argument("--engine", choices=("google", "bing"), default="google")
    parser.add_argument("--side", choices=("ours", "benchmark"), default="benchmark")
    parser.add_argument("--url", help="Optional explicit URL; otherwise read resolved_candidates.json")
    parser.add_argument("--timeout-ms", type=int, default=45000)
    parser.add_argument("--headed", action="store_true", help="Show browser window (diagnostic only)")
    parser.add_argument("--save-html", action="store_true", help="Opt in to saving potentially sensitive rendered HTML")
    parser.add_argument("--use-production-profile", action="store_true", help="Use existing crawler profile; close other browsers/crawlers first")
    args = parser.parse_args()
    if args.timeout_ms < 5000 or args.timeout_ms > 120000:
        parser.error("--timeout-ms must be between 5000 and 120000")
    try:
        run(args)
    except Exception as exc:
        raise SystemExit(f"Diagnostic failed: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
