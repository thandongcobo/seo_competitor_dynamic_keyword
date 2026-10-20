from __future__ import annotations

import argparse

from analysis.backlinks import compare_backlink_summaries
from analysis.comparison_engine import build_findings
from analysis.intent import assess_intent_alignment
from analysis.keywords import compare_ranked_keywords
from analysis.onpage import compare_pages
from analysis.rankings import compare_rankings, extract_serp_candidates
from collectors.request_cache import request_fingerprint
from collectors.serp_collector import build_serp_task
from config.settings import CACHE_DIR, PROCESSED_DIR, RAW_DIR, RESULTS_DIR, settings
from normalization.serp import normalize_serp
from normalization.pages import normalize_page
from collectors.playwright_collector import parse_page_html
from collectors.playwright_serp_collector import _is_result_url, _extract_google_target
from normalization.labs import normalize_search_intent, normalize_ranked_keywords
from normalization.backlinks import normalize_backlink_summary


def ok(message: str) -> None:
    print(f"PASS: {message}")


def phase1() -> None:
    for path in [RAW_DIR, PROCESSED_DIR, RESULTS_DIR, CACHE_DIR]:
        assert path.exists(), f"Missing directory: {path}"
    a = request_fingerprint("POST", "/demo", [{"b": 2, "a": 1}])
    b = request_fingerprint("POST", "/demo", [{"a": 1, "b": 2}])
    assert a == b
    ok("project folders exist and duplicate request fingerprinting is deterministic")


def phase2() -> None:
    payload = build_serp_task("aviator", "-29.7359502,31.0699179,200", "en", depth=50)
    assert payload[0]["depth"] == 50
    assert payload[0]["location_coordinate"] == "-29.7359502,31.0699179,200"
    assert _is_result_url("https://example.com/page")
    assert _extract_google_target("https://www.google.com/url?q=https%3A%2F%2Fexample.com%2Fpage") == "https://example.com/page"
    raw = {"tasks": [{"result": [{"items": [
        {"type": "organic", "rank_group": 2, "rank_absolute": 3, "domain": "betway.co.za", "url": "https://betway.co.za/aviator", "title": "Aviator", "description": "Play"},
        {"type": "ai_overview", "rank_absolute": 2},
        {"type": "organic", "rank_group": 5, "rank_absolute": 6, "domain": "hollywoodbets.net", "url": "https://hollywoodbets.net/aviator", "title": "Aviator", "description": "Play"},
    ]}]}]}
    norm = normalize_serp(raw, "aviator", "google")
    assert norm["organic_results_count"] == 2
    assert len(norm["serp_features"]) == 1
    comparison = compare_rankings(norm, "hollywoodbets.net", "betway.co.za")
    assert comparison["position_gap"] == 3
    candidates = extract_serp_candidates(norm, "hollywoodbets.net", "betway.co.za", 5)
    assert any(row["domain"] == "betway.co.za" for row in candidates)
    ok("SERP coordinate config, Playwright result URL parsing, organic rank_group handling and dynamic candidate discovery work")


def phase3() -> None:
    intent_raw = {"tasks": [{"result": [{"items": [{"keyword": "aviator", "keyword_intent": {"label": "transactional", "probability": 0.91}, "secondary_keyword_intents": []}]}]}]}
    ranked_raw = {"tasks": [{"result": [{"total_count": 2, "items": [
        {"keyword_data": {"keyword": "aviator game", "keyword_info": {"search_volume": 1000}, "search_intent_info": {"main_intent": "transactional"}}, "ranked_serp_element": {"serp_item": {"rank_group": 3, "url": "https://example.com/a", "etv": 123.4}}},
        {"keyword_data": {"keyword": "aviator strategy", "keyword_info": {"search_volume": 500}}, "ranked_serp_element": {"serp_item": {"rank_group": 8, "url": "https://example.com/b"}}},
    ]}]}]}
    intent = normalize_search_intent(intent_raw)
    ranked = normalize_ranked_keywords(ranked_raw, "example.com")
    assert intent["main_intent"] == "transactional"
    assert ranked["items"][0]["search_volume"] == 1000
    ok("Labs normalization for search intent and ranked keywords works")


def phase4() -> None:
    raw = {"tasks": [{"result": [{"rank": 55, "backlinks": 200, "referring_domains": 40, "referring_main_domains": 35, "referring_pages": 180, "dofollow": 150}]}]}
    norm = normalize_backlink_summary(raw, "https://example.com/aviator")
    other = dict(norm)
    other["referring_domains"] = 65
    result = compare_backlink_summaries(norm, other)
    assert result["referring_domains"]["competitor_minus_ours"] == 25
    ok("Backlinks normalization and comparison calculations work")


def phase5() -> None:
    html = """
    <html><head><title>Play Aviator Online</title>
    <meta name='description' content='Play Aviator now'>
    <link rel='canonical' href='https://example.com/aviator'>
    <script type='application/ld+json'>{\"@type\":\"Game\"}</script></head>
    <body><h1>Aviator</h1><h2>How it works</h2><p>Play Aviator and learn the rules.</p>
    <a href='/games'>Games</a><a href='https://outside.example/page'>Outside</a></body></html>
    """
    page = parse_page_html(html, requested_url="https://example.com/aviator", final_url="https://example.com/aviator", status_code=200)
    normalized = normalize_page(page)
    assert normalized["h1_count"] == 1
    assert normalized["internal_link_count"] == 1
    assert normalized["external_link_count"] == 1
    assert normalized["structured_data_count"] == 1
    ok("Playwright page parser extracts on-page fields")


def phase6() -> None:
    serp = {"engine": "google", "keyword": "aviator", "organic_results": [
        {"domain": "betway.co.za", "rank_group": 2, "url": "https://betway.co.za/a"},
        {"domain": "hollywoodbets.net", "rank_group": 5, "url": "https://hollywoodbets.net/a"},
    ]}
    ranking = compare_rankings(serp, "hollywoodbets.net", "betway.co.za")
    assert ranking["position_gap"] == 3
    ours_kw = {"items": [{"keyword": "aviator", "rank_group": 5, "search_volume": 5000}]}
    comp_kw = {"items": [
        {"keyword": "aviator", "rank_group": 2, "search_volume": 5000},
        {"keyword": "play aviator", "rank_group": 3, "search_volume": 2500},
    ]}
    keyword_gap = compare_ranked_keywords(ours_kw, comp_kw)
    backlink_gap = compare_backlink_summaries(
        {"rank": 40, "backlinks": 100, "referring_domains": 20, "referring_main_domains": 15, "referring_pages": 80, "dofollow": 70},
        {"rank": 60, "backlinks": 300, "referring_domains": 50, "referring_main_domains": 40, "referring_pages": 200, "dofollow": 220},
    )
    ours_page = {"title": "Aviator", "meta_description": "Aviator game", "headings": {"h1": ["Aviator"]}, "word_count": 700, "internal_link_count": 8, "structured_data_count": 0, "text_sample": "Learn how Aviator works"}
    comp_page = {"title": "Play Aviator Online", "meta_description": "Play Aviator now", "headings": {"h1": ["Play Aviator"]}, "word_count": 900, "internal_link_count": 20, "structured_data_count": 1, "text_sample": "Play now register and start"}
    onpage = compare_pages(ours_page, comp_page, "aviator")
    intent = assess_intent_alignment({"main_intent": "transactional", "intent_probability": 0.91}, onpage)
    findings = build_findings({"google": ranking}, {"both_found": False}, keyword_gap, backlink_gap, onpage, intent, [{"domain": "betway.co.za", "benchmark": True, "nearest_serp_rank": 2}])
    assert findings
    assert all(f.get("confidence") in {"high", "medium", "low"} for f in findings)
    ok("analysis engine produces category-based, evidence-labelled findings")


PHASES = {"1": phase1, "2": phase2, "3": phase3, "4": phase4, "5": phase5, "6": phase6}


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline phase tests. These do not call DataForSEO or spend credits.")
    parser.add_argument("--phase", choices=["1", "2", "3", "4", "5", "6", "all"], default="all")
    args = parser.parse_args()
    selected = list(PHASES) if args.phase == "all" else [args.phase]
    for phase in selected:
        print(f"\n=== PHASE {phase} OFFLINE TEST ===")
        PHASES[phase]()
    print("\nALL SELECTED PHASE TESTS PASSED")


if __name__ == "__main__":
    main()
