from analysis.advanced_evidence import analyze_intersection
from analysis.recommendations import (
    build_recommendation_evidence_audit,
    generate_recommendations,
)


def _query(keyword, ours_url, benchmark_url, our_rank=8, benchmark_rank=2):
    return {
        "keyword": keyword,
        "our_rank": our_rank,
        "benchmark_rank": benchmark_rank,
        "search_volume": 120,
        "ours_result": {"domain": "example.org", "rank": our_rank, "title": keyword.title(), "url": ours_url},
        "benchmark_result": {"domain": "rival.example", "rank": benchmark_rank, "title": keyword.title(), "url": benchmark_url},
    }


def test_intersection_retains_exact_same_domain_result_pages_and_rejects_foreign_hosts():
    data = {
        "scope": "domain_keyword_intersection",
        "analysis_keyword": "solar inverter",
        "target1": "example.org",
        "target2": "rival.example",
        "items": [{
            "keyword": "solar inverter guide",
            "our_rank": 8,
            "benchmark_rank": 2,
            "search_volume": 120,
            "first_domain_serp_element": {
                "rank_group": 8,
                "rank_absolute": 10,
                "domain": "blog.example.org",
                "title": "Solar Inverter Guide",
                "url": "https://blog.example.org/guides/inverter?utm_source=private",
            },
            "second_domain_serp_element": {
                "rank_group": 2,
                "domain": "rival.example",
                "title": "Solar Inverter Guide",
                "url": "https://rival.example/guide",
            },
        }, {
            "keyword": "solar inverter sizing",
            "our_rank": 9,
            "benchmark_rank": 3,
            "first_domain_serp_element": {"rank_group": 9, "domain": "attacker.example", "url": "https://attacker.example/"},
            "second_domain_serp_element": {"rank_group": 3, "domain": "rival.example", "url": "https://rival.example/"},
        }],
    }
    result = analyze_intersection(data, keyword="solar inverter", our_domain="example.org",
                                  benchmark_domain="rival.example")
    assert len(result["related_generic_queries"]) == 1
    row = result["related_generic_queries"][0]
    assert row["ours_result"]["rank"] == 8
    assert row["ours_result"]["url"] == "https://blog.example.org/guides/inverter"
    assert row["benchmark_result"]["url"] == "https://rival.example/guide"


def test_existing_query_page_is_recommended_in_place_not_as_a_duplicate():
    urls = {"ours": "https://example.org/solar-inverter", "benchmark": "https://rival.example/solar-inverter"}
    advanced = {"keyword_intersection": {"status": "usable", "top_generic_benchmark_leads": [],
        "related_generic_queries": [_query("solar inverter guide", "https://blog.example.org/guides/inverter",
                                            "https://rival.example/guide")]}}
    recs = generate_recommendations(keyword="solar inverter", ranking_urls=urls,
                                    advanced_evidence=advanced, onpage={})
    rec = next(row for row in recs if row["id"].startswith("existing-query-page-"))
    assert rec["target_url"] == "https://blog.example.org/guides/inverter"
    assert "do not create a duplicate" in " ".join(rec["actions"]).lower()
    assert "solar inverter guide" in rec["evidence"].lower()
    assert "generic-query-coverage" not in {row["id"] for row in recs}
    assert "aviator" not in str(recs).lower()


def test_existing_trial_resource_is_surfaced_only_when_not_linked_from_target():
    urls = {"ours": "https://lingo.example/language-learning", "benchmark": "https://rival.example/language-learning"}
    advanced = {"keyword_intersection": {"status": "usable", "top_generic_benchmark_leads": [],
        "related_generic_queries": [_query("language learning software demo",
                                            "https://lingo.example/demo", "https://rival.example/software")]}}
    evidence = [{"evidence_id": "ENR_LINKS", "metric_or_observation": "outgoing_internal_link_inventory",
                 "page": {"side": "ours", "url": urls["ours"]},
                 "value": [{"source_url": urls["ours"], "destination_url": "https://lingo.example/about",
                            "direction": "outgoing_from_selected_page"}]}]
    recs = generate_recommendations(keyword="language learning software", ranking_urls=urls,
                                    advanced_evidence=advanced, onpage={}, enriched_page_evidence=evidence)
    rec = next(row for row in recs if row["id"].startswith("existing-trial-resource-"))
    assert rec["target_url"] == urls["ours"]
    assert "https://lingo.example/demo" in rec["evidence"]
    assert "create another page" in " ".join(rec["actions"]).lower()
    assert "hollywoodbets" not in str(recs).lower()


def test_related_internal_links_use_distinct_source_and_destination_pages():
    target = "https://example.org/solar-inverter"
    evidence = [
        {"evidence_id": "ENR_HEADINGS", "metric_or_observation": "rendered_heading_inventory",
         "page": {"side": "ours", "url": target},
         "value": [{"level": "h2", "text": "Inverter Sizing Guide"},
                   {"level": "h2", "text": "Solar Installation"}]},
        {"evidence_id": "ENR_LINKS", "metric_or_observation": "outgoing_internal_link_inventory",
         "page": {"side": "ours", "url": target},
         "value": [{"source_url": target, "destination_url": "https://example.org/guides/inverter-sizing",
                    "direction": "outgoing_from_selected_page"},
                   {"source_url": target, "destination_url": "https://example.org/guides/solar-installation",
                    "direction": "outgoing_from_selected_page"}]},
    ]
    recs = generate_recommendations(keyword="solar inverter",
        ranking_urls={"ours": target, "benchmark": "https://rival.example/solar-inverter"},
        advanced_evidence={}, onpage={}, enriched_page_evidence=evidence)
    rec = next(row for row in recs if row["id"] == "internal-resource-cluster")
    action = " ".join(rec["actions"])
    assert "https://example.org/guides/inverter-sizing" in action
    assert f"to {target}" in action
    assert "incoming" in rec["evidence"].lower() or "does not include" in rec["evidence"].lower()


def test_faq_and_backlink_candidates_remain_in_internal_audit_without_demand_or_prospects():
    audit = build_recommendation_evidence_audit(keyword="solar inverter",
        ranking_urls={"ours": "https://example.org/solar-inverter", "benchmark": "https://rival.example/solar-inverter"},
        advanced_evidence={"backlinks": {"page": {"referring_domains": {"ours": 5, "competitor": 8}}},
                           "keyword_intersection": {"related_generic_queries": []}},
        enriched_page_evidence=[{"metric_or_observation": "outgoing_internal_link_inventory",
            "page": {"side": "benchmark", "url": "https://rival.example/solar-inverter"},
            "value": [{"destination_url": "https://rival.example/frequently-asked-questions"}]}])
    candidates = {row["candidate"]: row for row in audit["withheld_opportunities"]}
    assert candidates["FAQ or common-question content"]["status"] == "withheld_incomplete_observation"
    assert candidates["Specific editorial backlink prospects"]["status"] == "withheld_incomplete_observation"
    assert candidates["Incoming internal links to the tracked page"]["status"] == "direction_not_observed"
