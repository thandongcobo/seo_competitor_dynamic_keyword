from analysis.advanced_evidence import analyze_intersection, analyze_backlinks, analyze_technical
from analysis.comparison_engine import build_findings
from analysis.keywords import compare_ranked_keywords
from analysis.onpage import compare_pages


def test_intersection_dynamic_keyword_and_brand_segmentation():
    data = {"scope": "domain_keyword_intersection", "analysis_keyword": "aviator",
            "target1": "hollywoodbets.net", "target2": "betway.co.za", "total_count": 3,
            "items": [
                {"keyword": "play aviator", "our_rank": 3, "benchmark_rank": 1, "search_volume": 6000},
                {"keyword": "aviator hollywoodbets", "our_rank": 1, "benchmark_rank": 9, "search_volume": 2000},
                {"keyword": "aviator betway", "our_rank": 10, "benchmark_rank": 1, "search_volume": 1000}]}
    r = analyze_intersection(data, keyword="aviator", our_domain="hollywoodbets.net", benchmark_domain="betway.co.za")
    assert (r["returned"], r["ours_ahead"], r["benchmark_ahead"]) == (3, 1, 2)
    assert r["generic_benchmark_ahead"] == 1
    assert r["top_generic_benchmark_leads"][0]["keyword"] == "play aviator"
    assert analyze_intersection(data, keyword="roulette", our_domain="hollywoodbets.net", benchmark_domain="betway.co.za")["status"] == "unavailable"


def test_intersection_rejects_wrong_domains_and_nonmatches():
    d = {"scope": "domain_keyword_intersection", "analysis_keyword": "roulette",
         "target1": "wrong.com", "target2": "betway.co.za", "items": []}
    assert analyze_intersection(d, keyword="roulette", our_domain="hollywoodbets.net", benchmark_domain="betway.co.za")["status"] == "unavailable"
    d["target1"] = "hollywoodbets.net"
    d["items"] = [{"keyword": "aviator", "our_rank": 2, "benchmark_rank": 1}]
    assert analyze_intersection(d, keyword="roulette", our_domain="hollywoodbets.net", benchmark_domain="betway.co.za")["returned"] == 0


def test_backlinks_separate_page_and_domain_and_missing_values():
    p1 = {"rank": 18, "referring_domains": 1184, "dofollow": None}
    p2 = {"rank": 36, "referring_domains": 1259, "dofollow": None}
    d1 = {"scope": "domain", "target": "hollywoodbets.net", "rank": 70}
    d2 = {"scope": "domain", "target": "betway.co.za", "rank": 65}
    r = analyze_backlinks(p1, p2, d1, d2, "hollywoodbets.net", "betway.co.za")
    assert r["page"]["rank"]["competitor_minus_ours"] == 18
    assert r["domain"]["rank"]["competitor_minus_ours"] == -5
    assert r["page"]["dofollow"]["competitor_minus_ours"] is None
    d2["target"] = "wrong.co.za"
    assert not analyze_backlinks(p1, p2, d1, d2, "hollywoodbets.net", "betway.co.za")["domain"]


def test_technical_preserves_lcp_even_when_overall_score_better():
    data = {"ours": {"mobile": {"scores": {"performance": 28}, "lab_metrics": {"largest_contentful_paint_ms": 25000}}},
            "benchmark": {"mobile": {"scores": {"performance": 16}, "lab_metrics": {"largest_contentful_paint_ms": 19510}}}}
    r = analyze_technical(data)["mobile"]
    assert r["scores"]["performance"]["ours"] > r["scores"]["performance"]["benchmark"]
    assert r["lab_metrics"]["largest_contentful_paint_ms"]["ours"] > r["lab_metrics"]["largest_contentful_paint_ms"]["benchmark"]


def test_keyword_samples_not_claimed_as_actual_absence():
    r = compare_ranked_keywords({"items": [{"keyword": "A"}]}, {"items": [{"keyword": "B"}]})
    assert r["competitor_only_count"] == 1
    assert "may still rank" in r["coverage_warning"]


def test_onpage_missing_content_not_false_similarity():
    a = {"title": "Aviator", "meta_description": "", "headings": {"h1": ["Aviator"]}, "word_count": 100}
    b = {"title": "", "meta_description": "", "headings": {"h1": []}, "word_count": 200}
    r = compare_pages(a, b, "aviator")
    assert r["content_token_jaccard"] is None
    assert r["title_keyword_match"] == {"ours": True, "competitor": False}


def test_findings_use_advanced_and_do_not_call_sample_a_true_gap():
    advanced = {"keyword_intersection": {"status": "usable", "returned": 3, "ours_ahead": 1,
                "benchmark_ahead": 2, "generic_ours_ahead": 0, "generic_benchmark_ahead": 1, "warnings": []},
                "backlinks": {"page": {"rank": {"ours": 18, "competitor": 36},
                               "referring_domains": {"ours": 1184, "competitor": 1259}},
                              "domain": {"rank": {"ours": 70, "competitor": 65}}, "warnings": []},
                "technical": {}}
    findings = build_findings({}, keyword_gap={"competitor_only_count": 100}, advanced_evidence=advanced)
    assert "keyword_intersection" in [f["category"] for f in findings]
    assert "keyword_coverage" not in [f["category"] for f in findings]
    assert "Domain-wide ranks" in next(f["evidence"] for f in findings if f["category"] == "backlinks")


def test_opportunity_relevance_filters_third_party_and_unknown_names():
    from analysis.advanced_evidence import classify_opportunity_relevance
    domains = ("hollywoodbets.net", "betway.co.za")
    assert classify_opportunity_relevance("play aviator", "aviator", domains)[0] == "relevant_generic"
    assert classify_opportunity_relevance("aviator next spribegaming com", "aviator", domains)[0] == "third_party_navigational"
    assert classify_opportunity_relevance("supersportbet aviator", "aviator", domains)[0] == "needs_review"
    assert classify_opportunity_relevance("aviator betway login", "aviator", domains)[0] == "tracked_brand"
    assert classify_opportunity_relevance("how to play roulette", "roulette", domains)[0] == "relevant_generic"


def test_intersection_retains_review_but_excludes_unrelated_query_from_recommendations():
    from analysis.advanced_evidence import analyze_intersection
    data = {"scope": "domain_keyword_intersection", "analysis_keyword": "aviator",
            "target1": "hollywoodbets.net", "target2": "betway.co.za", "total_count": 3,
            "items": [
                {"keyword": "play aviator", "our_rank": 2, "benchmark_rank": 1, "search_volume": 6600},
                {"keyword": "aviator next spribegaming com", "our_rank": 9, "benchmark_rank": 4, "search_volume": 880},
                {"keyword": "supersportbet aviator", "our_rank": 14, "benchmark_rank": 11, "search_volume": 480},
            ]}
    r = analyze_intersection(data, keyword="aviator", our_domain="hollywoodbets.net", benchmark_domain="betway.co.za")
    assert r["returned"] == 3
    assert r["generic_benchmark_ahead"] == 3
    assert [x["keyword"] for x in r["top_generic_benchmark_leads"]] == ["play aviator"]
    assert len(r["excluded_opportunities"]) == 1
    assert len(r["review_opportunities"]) == 1
