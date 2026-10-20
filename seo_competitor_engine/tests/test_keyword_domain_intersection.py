from collectors.labs_collector import domain_intersection_payload
from normalization.labs import normalize_domain_intersection
from scripts.collect_labs import build
from collectors.request_cache import request_fingerprint
import pytest


def test_keyword_changes_payload_and_cache_key(monkeypatch):
    import scripts.collect_labs as cl
    from dataclasses import replace
    monkeypatch.setattr(cl, "settings", replace(cl.settings, keyword="aviator"))
    endpoint, a = build("domain_intersection", 100)
    assert a[0]["filters"] == [["keyword_data.keyword", "ilike", "%aviator%"]]
    assert a[0]["intersections"] is True
    assert a[0]["target1"] == "hollywoodbets.net"
    assert a[0]["target2"] == "betway.co.za"
    monkeypatch.setattr(cl, "settings", replace(cl.settings, keyword="roulette"))
    _, b = build("domain_intersection", 100)
    assert b[0]["filters"] == [["keyword_data.keyword", "ilike", "%roulette%"]]
    assert request_fingerprint("POST", endpoint, a) != request_fingerprint("POST", endpoint, b)


def test_keyword_with_spaces_and_dynamic_domains():
    task = domain_intersection_payload("ours.example", "competitor.example", "South Africa", "en", 50, keyword="  crash   game  ")[0]
    assert task["filters"] == [["keyword_data.keyword", "ilike", "%crash game%"]]
    assert task["target1"] == "ours.example"
    assert task["target2"] == "competitor.example"
    assert task["limit"] == 50


def test_reject_blank_and_wildcards():
    for keyword in ("", "   ", "a_b", "100%"):
        with pytest.raises(ValueError):
            domain_intersection_payload("a", "b", "South Africa", "en", keyword=keyword)


def test_normalization_scoped_and_ranks():
    api = {"tasks": [{"data": {"target1": "ours.example", "target2": "competitor.example"}, "result": [{
        "total_count": 5, "items": [
            {"keyword_data": {"keyword": "Aviator game", "keyword_info": {"search_volume": 100}},
             "first_domain_serp_element": {"rank_group": 3, "url": "https://ours.example/a"},
             "second_domain_serp_element": {"rank_group": 1, "url": "https://competitor.example/a"}},
            {"keyword_data": {"keyword": "roulette", "keyword_info": {"search_volume": 200}}},
        ]
    }]}]}
    normalized = normalize_domain_intersection(api, "aviator")
    assert normalized["items_count"] == 1
    assert normalized["total_count"] == 5
    assert normalized["excluded_nonmatching_items"] == 1
    assert normalized["items"][0]["ranking_leader"] == "benchmark"
    assert normalized["items"][0]["benchmark_rank"] == 1
    assert normalized["target1"] == "ours.example"


def test_empty_response_does_not_claim_no_rankings():
    normalized = normalize_domain_intersection({"tasks": [{"result": [{"total_count": 0, "items": []}]}]}, "aviator")
    assert normalized["items"] == []
    assert "does not prove" in normalized["coverage_note"]
