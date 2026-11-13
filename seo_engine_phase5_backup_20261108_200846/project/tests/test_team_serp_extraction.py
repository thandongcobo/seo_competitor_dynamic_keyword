"""Regression tests for AI Overview leakage seen in captured 2026-10-21 SERPs.

The HTML below is a minimal, offline test fixture based on the observed DOM
structure; it is never used as production SERP data.
"""
from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

from collectors.serp_diagnostics import extraction_audit


SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "team_serp" / "SEO_SERP_Monitor_aviator.py"


def load_collector():
    spec = importlib.util.spec_from_file_location("collector_extraction_test", SOURCE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_known_feature_titles_are_excluded_without_excluding_articles_about_ai():
    collector = load_collector()
    assert collector.is_non_organic_heading("AI Mode replied:")
    assert collector.is_non_organic_heading(" AI Overview ")
    assert not collector.is_non_organic_heading("AI Overview: how it affects SEO")
    assert not collector.is_non_organic_heading("How to play Aviator")


def test_diagnostics_record_excluded_ai_headings_without_failing_valid_results():
    rows = [{"title": "Play Aviator", "url": "https://www.hollywoodbets.net/aviator"}]
    headings = [
        {"index": 1, "title": "Play Aviator", "href": "https://www.hollywoodbets.net/aviator"},
        {"index": 2, "title": "AI Mode replied:", "href": None},
    ]
    audit = extraction_audit(rows, headings)
    assert audit["status"] == "evidence_captured_not_manually_verified"
    assert audit["flags"] == []
    assert audit["excluded_feature_headings_observed"] == [
        {"heading_index": 2, "title": "AI Mode replied:", "linked_title": False}
    ]
    assert rows[0]["title"] == "Play Aviator"


def test_diagnostics_still_flag_ai_result_if_some_other_parser_emits_it():
    rows = [{"title": "AI Mode replied:", "url": "https://example.com"}]
    audit = extraction_audit(rows, [{"title": "AI Mode replied:", "href": None}])
    assert "possible_non_organic_results_extracted" in audit["flags"]
    assert audit["status"] == "review_required"


HTML = """
<html><body><div id="search">
  <div class="MjjYud"><div class="yuRUbf"><a href="https://www.betway.co.za/aviator">
    <h3 class="LC20lb MBeuO DKV0Md">Play Aviator | Betway</h3></a></div></div>
  <div class="AIOverview"><h3 class="MheKwc">AI Mode replied:</h3>
    <div><a href="https://www.merriam-webster.com/dictionary/aviator">AI citation</a></div>
  </div>
  <div class="MjjYud"><div class="yuRUbf"><a href="https://www.hollywoodbets.net/aviator">
    <h3 class="LC20lb MBeuO DKV0Md">Play Aviator | Hollywoodbets</h3></a></div></div>
  <div id="tads"><a href="https://ads.example.com/aviator"><h3>Sponsored game</h3></a></div>
  <div class="AIOverview"><a href="https://www.example.com/ai-citation">
    <h3>AI Overview</h3></a></div>
  <div class="MjjYud"><a href="https://www.example.com/ai-article">
    <h3>AI Overview: how it affects SEO</h3></a></div>
</div></body></html>
"""


def test_organic_extraction_never_borrows_ai_citation_link():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("Playwright is not installed")
    collector = load_collector()
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True, **({"executable_path": shutil.which("chromium")} if shutil.which("chromium") else {}))
        except Exception:
            pytest.skip("Chromium browser not installed for offline DOM test")
        try:
            page = browser.new_page()
            page.set_content(HTML)
            collector.NUMBER_OF_ORGANIC_RESULTS = 10
            results = collector.extract_organic_results(page)
        finally:
            browser.close()
    assert [(r["domain"], r["rank"]) for r in results] == [
        ("betway.co.za", 1), ("hollywoodbets.net", 2), ("example.com", 3)
    ]
    assert all(r["title"] != "AI Mode replied:" for r in results)
    assert all("merriam-webster.com" not in r["url"] for r in results)
    assert all("ads.example.com" not in r["url"] for r in results)


def test_unlinked_heading_does_not_resolve_neighboring_link():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("Playwright is not installed")
    collector = load_collector()
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True, **({"executable_path": shutil.which("chromium")} if shutil.which("chromium") else {}))
        except Exception:
            pytest.skip("Chromium browser not installed for offline DOM test")
        try:
            page = browser.new_page()
            page.set_content(HTML)
            heading = page.locator("h3.MheKwc")
            assert collector.get_result_href(page, heading, collector.find_result_block(heading)) == ""
        finally:
            browser.close()
