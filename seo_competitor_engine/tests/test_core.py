from analysis.rankings import compare_rankings
from analysis.backlinks import compare_backlink_summaries
from analysis.comparison_engine import build_findings
from analysis.intent import assess_intent_alignment
from analysis.onpage import compare_pages
from collectors.playwright_collector import parse_page_html
from collectors.request_cache import request_fingerprint


def test_ranking_gap():
    serp = {
        "engine": "google",
        "keyword": "aviator",
        "organic_results": [
            {"domain": "betway.co.za", "rank_group": 2, "url": "https://betway.co.za/a"},
            {"domain": "hollywoodbets.net", "rank_group": 5, "url": "https://hollywoodbets.net/a"},
        ],
    }
    result = compare_rankings(serp, "hollywoodbets.net", "betway.co.za")
    assert result["position_gap"] == 3


def test_backlink_gap():
    ours = {"rank": 40, "backlinks": 100, "referring_domains": 20, "referring_main_domains": 15, "referring_pages": 80, "dofollow": 70}
    comp = {"rank": 60, "backlinks": 300, "referring_domains": 50, "referring_main_domains": 40, "referring_pages": 200, "dofollow": 220}
    result = compare_backlink_summaries(ours, comp)
    assert result["referring_domains"]["competitor_minus_ours"] == 30


def test_request_fingerprint_is_order_independent():
    assert request_fingerprint("POST", "/x", [{"a": 1, "b": 2}]) == request_fingerprint("POST", "/x", [{"b": 2, "a": 1}])


def test_page_parser():
    page = parse_page_html(
        "<html><head><title>Aviator</title></head><body><h1>Aviator</h1><a href='/games'>Games</a></body></html>",
        requested_url="https://example.com/a",
        final_url="https://example.com/a",
        status_code=200,
    )
    assert page["h1_count"] == 1
    assert page["internal_link_count"] == 1


def test_findings_have_confidence():
    ranking = {"position_gap": 3}
    keyword_gap = {"competitor_only_count": 2, "shared_keyword_count": 0}
    backlink_gap = {"referring_domains": {"competitor_minus_ours": 10}}
    onpage = {"word_count": {"ours": 500, "competitor": 800}, "internal_link_count": {"ours": 5, "competitor": 10}}
    intent = {"assessment": "Competitor shows stronger heuristic alignment", "direction": "competitor", "confidence": "medium"}
    findings = build_findings(ranking, keyword_gap, backlink_gap, onpage, intent)
    assert findings
    assert all(x["confidence"] in {"high", "medium", "low"} for x in findings)


def test_cached_post_reuses_response(tmp_path, monkeypatch):
    import collectors.request_cache as rc

    monkeypatch.setattr(rc, "CACHE_DIR", tmp_path)

    class FakeClient:
        def __init__(self):
            self.calls = 0

        def post(self, path, payload):
            self.calls += 1
            return {"status_code": 20000, "cost": 0.012, "value": "fresh"}

    client = FakeClient()
    first, first_hit = rc.cached_post(client, "/v3/demo", [{"keyword": "aviator"}])
    second, second_hit = rc.cached_post(client, "/v3/demo", [{"keyword": "aviator"}])

    assert first_hit is False
    assert second_hit is True
    assert first == second
    assert client.calls == 1
