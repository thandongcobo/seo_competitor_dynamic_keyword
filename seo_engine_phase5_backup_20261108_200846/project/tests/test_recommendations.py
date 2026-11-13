from analysis.recommendations import generate_recommendations, format_recommendations_report
from analysis.recommendation_classification import TIER_1, TIER_2

URLS = {"ours": "https://www.hollywoodbets.net/aviator", "benchmark": "https://www.betway.co.za/aviator"}


def fixture_evidence():
    return {
        "backlinks": {"page": {"rank": {"ours": 18, "competitor": 36},
                               "referring_domains": {"ours": 1184, "competitor": 1259}},
                      "domain": {"rank": {"ours": 70, "competitor": 65}}},
        "keyword_intersection": {"status": "usable", "top_generic_benchmark_leads": [
            {"keyword": "play aviator", "our_rank": 2, "benchmark_rank": 1, "search_volume": 6600}]},
        "technical": {"mobile": {"lab_metrics": {"largest_contentful_paint_ms": {"ours": 25000},
                                                   "total_blocking_time_ms": {"ours": 2122},
                                                   "cumulative_layout_shift": {"ours": 0.0}}}},
    }


def detailed_technical():
    return {"mobile": {"detailed_analysis": {"status": "usable", "scope": "exact_serp_pages_mobile_lab",
        "investigations": [{"area": "javascript_execution",
            "confidence": "investigation_only", "title": "Profile scripts",
            "supporting_observation": "Long task", "actions": ["Profile the identified scripts in Chrome Performance before editing load order."],
            "affected_resources": [{"url": "https://www.hollywoodbets.net/js/app.js", "total": 900}]}]}}}


def test_recommendations_are_evidence_based_and_unquantified():
    recs = generate_recommendations(keyword="aviator", ranking_urls=URLS,
                                    advanced_evidence=fixture_evidence(), onpage={},
                                    technical_comparison=detailed_technical())
    ids = {r["id"] for r in recs}
    assert "generic-query-coverage" in ids
    assert "technical-mobile-javascript_execution" in ids
    assert "page-link-profile" not in ids  # aggregate counts do not identify editorial prospects
    assert all(r["impact_estimate"]["quantified_rank_or_traffic_lift"] is None for r in recs)
    assert all(r["actions"] and r["success_check"] for r in recs)
    assert all(r["evidence_tier"] in {TIER_1, TIER_2} for r in recs)
    assert all(r["evidence_provenance"] and r["implementation_details"] and r["success_measurement"] for r in recs)
    assert [r["evidence_tier"] for r in recs] == sorted([r["evidence_tier"] for r in recs], key={TIER_1: 1, TIER_2: 2}.get)
    text = format_recommendations_report("aviator", URLS, [], recs, {})
    assert "play aviator" in text and "not a rank-lift forecast" in text


def test_no_recommendation_from_missing_or_mismatched_evidence():
    assert generate_recommendations(keyword="roulette", ranking_urls=URLS,
                                    advanced_evidence={}, onpage={}) == []
    assert generate_recommendations(keyword="roulette", ranking_urls={},
                                    advanced_evidence=fixture_evidence(), onpage={}) == []


def test_keyword_aware_onpage_recommendation():
    r = generate_recommendations(keyword="roulette", ranking_urls=URLS, advanced_evidence={},
        onpage={"title_keyword_match": {"ours": False, "competitor": True}})
    assert len(r) == 1
    assert "roulette" in r[0]["evidence"]


def test_triage_prioritizes_low_effort_verified_check_before_link_campaign():
    recs = generate_recommendations(keyword="aviator", ranking_urls=URLS,
        advanced_evidence=fixture_evidence(),
        onpage={"title_keyword_match": {"ours": False, "competitor": True},
                "meta_keyword_match": {"ours": False, "competitor": True}})
    ids = [r["id"] for r in recs]
    assert "page-link-profile" not in ids
    title = next(r for r in recs if r["id"] == "onpage-title_keyword_match")
    assert title["action_type"] == "verify_before_edit"
    assert title["implementation_effort"] == "low"
    assert title["evidence_confidence"] == "medium"
    assert title["target_url"] == URLS["ours"]
    assert title["impact_estimate"]["quantified_rank_or_traffic_lift"] is None
    meta = next(r for r in recs if r["id"] == "onpage-meta_keyword_match")
    assert "not a direct ranking boost" in meta["interpretation"]


def test_legacy_unfiltered_intersection_cannot_leak_third_party_queries():
    data = fixture_evidence()
    data["keyword_intersection"]["top_generic_benchmark_leads"] = [
        {"keyword": "aviator next spribegaming com", "our_rank": 9, "benchmark_rank": 4},
        {"keyword": "supersportbet aviator", "our_rank": 14, "benchmark_rank": 11},
        {"keyword": "play aviator", "our_rank": 2, "benchmark_rank": 1},
    ]
    recs = generate_recommendations(keyword="aviator", ranking_urls=URLS,
                                     advanced_evidence=data, onpage={})
    row = next(r for r in recs if r["id"] == "generic-query-coverage")
    assert "play aviator" in row["evidence"]
    assert "spribegaming" not in row["evidence"]
    assert "supersportbet" not in row["evidence"]


def test_keyword_dynamic_relevance_for_roulette():
    data = fixture_evidence()
    data["keyword_intersection"]["top_generic_benchmark_leads"] = [
        {"keyword": "play roulette online", "our_rank": 5, "benchmark_rank": 2},
        {"keyword": "roulette rivalbrand com", "our_rank": 5, "benchmark_rank": 2},
    ]
    recs = generate_recommendations(keyword="roulette", ranking_urls=URLS,
                                     advanced_evidence=data, onpage={})
    row = next(r for r in recs if r["id"] == "generic-query-coverage")
    assert "play roulette online" in row["evidence"]
    assert "rivalbrand" not in row["evidence"]


def test_meta_description_has_snippet_specific_caveat_not_title_caveat():
    recs = generate_recommendations(keyword="aviator", ranking_urls=URLS, advanced_evidence={},
        onpage={"meta_keyword_match": {"ours": False, "competitor": True}})
    assert len(recs) == 1
    caveat = recs[0]["limitations"].lower()
    assert "snippet" in caveat
    assert "higher rankings" in caveat
    assert "rewrite the displayed search-result title" not in caveat


def test_title_and_h1_keep_distinct_caveats():
    recs = generate_recommendations(keyword="aviator", ranking_urls=URLS, advanced_evidence={},
        onpage={"title_keyword_match": {"ours": False, "competitor": True},
                "h1_keyword_match": {"ours": False, "competitor": True}})
    by_id = {r["id"]: r for r in recs}
    assert "title" in by_id["onpage-title_keyword_match"]["limitations"].lower()
    assert "h1" in by_id["onpage-h1_keyword_match"]["limitations"].lower()


def test_triage_score_is_separate_from_tier_order_and_evidence_confidence():
    recs = generate_recommendations(keyword="aviator", ranking_urls=URLS,
        advanced_evidence=fixture_evidence(),
        onpage={"title_keyword_match": {"ours": False, "competitor": True}},
        technical_comparison=detailed_technical())
    title = next(r for r in recs if r["id"] == "onpage-title_keyword_match")
    technical = next(r for r in recs if r["id"] == "technical-mobile-javascript_execution")
    assert title["priority_score"] == 11
    assert technical["priority_score"] == 10
    assert technical["order"] < title["order"]  # Tier 1 precedes Tier 2 regardless of triage score.
    assert title["tie_break_explanation"] is None
    assert technical["tie_break_explanation"] is None
    report = format_recommendations_report("aviator", URLS, [], recs, {})
    assert "not proof of search-ranking causation" in report


def test_evidence_confidence_does_not_change_operational_priority_score():
    low = generate_recommendations(keyword="solar pump", ranking_urls=URLS,
        advanced_evidence={}, onpage={"title_keyword_match": {"ours": False, "competitor": True}})[0]
    high = dict(low, evidence_confidence="high")
    assert low["priority_score"] == high["priority_score"]
    assert "evidence confidence is reported separately" in low["priority_basis"]


def test_no_tie_does_not_claim_tie_break():
    recs = generate_recommendations(keyword="aviator", ranking_urls=URLS, advanced_evidence={},
        onpage={"title_keyword_match": {"ours": False, "competitor": True}})
    assert recs[0]["tie_break_explanation"] is None
    report = format_recommendations_report("aviator", URLS, [], recs, {})
    assert "Priority tie-break:" not in report
