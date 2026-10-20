"""Offline integration test: run Phase 2 on saved-style normalized fixtures."""
import json
from types import SimpleNamespace


def test_run_analysis_produces_json_and_readable_recommendations(tmp_path, monkeypatch):
    from scripts import run_analysis as runner
    processed = tmp_path / "processed"
    output = tmp_path / "results"
    processed.mkdir()
    monkeypatch.setattr(runner, "PROCESSED_DIR", processed)
    monkeypatch.setattr(runner, "RESULTS_DIR", output)
    monkeypatch.setattr(runner, "KEYWORD_SLUG", "aviator")
    monkeypatch.setattr(runner, "settings", SimpleNamespace(
        keyword="aviator", our_domain="hollywoodbets.net",
        benchmark_competitor_domain="betway.co.za", location_coordinate="0,0,100",
        labs_location_name="South Africa"))
    urls = {"ours": "https://www.hollywoodbets.net/aviator", "benchmark": "https://www.betway.co.za/aviator"}
    def save(name, data):
        (processed / name).write_text(json.dumps(data), encoding="utf-8")
    save("serp_google.json", {"engine": "google", "keyword": "aviator", "organic_results_count": 2,
        "organic_results": [
            {"domain": "betway.co.za", "rank_group": 1, "url": urls["benchmark"]},
            {"domain": "hollywoodbets.net", "rank_group": 2, "url": urls["ours"]}]})
    for side in ("ours", "benchmark"):
        save(f"page_{side}.json", {"ranking_url": urls[side], "requested_url": urls[side],
            "url_alignment": "matched", "crawl_failed": False, "extraction_status": "complete",
            "word_count": 650, "title": "Aviator", "headings": {"h1": ["Aviator"]},
            "text_sample": "Aviator game play online", "main_word_count": 625})
        save(f"backlinks_{side}_page_summary.json", {"target": urls[side], "scope": "page",
            "target_verified": True, "rank": 18 if side == "ours" else 36,
            "referring_domains": 1184 if side == "ours" else 1259})
        save(f"backlinks_{side}_domain_summary.json", {"target": "hollywoodbets.net" if side == "ours" else "betway.co.za",
            "scope": "domain", "rank": 70 if side == "ours" else 65})
        save(f"lighthouse_{side}_mobile.json", {"status": "usable", "ranking_url": urls[side],
            "target_verified": True, "final_url_verified": True, "scores": {"performance": 28 if side == "ours" else 16},
            "lab_metrics": {"largest_contentful_paint_ms": 25000 if side == "ours" else 19510,
                            "total_blocking_time_ms": 2122 if side == "ours" else 3273}})
    save("domain_intersection.json", {"scope": "domain_keyword_intersection", "analysis_keyword": "aviator",
        "target1": "hollywoodbets.net", "target2": "betway.co.za", "total_count": 1,
        "items": [{"keyword": "play aviator", "our_rank": 2, "benchmark_rank": 1, "search_volume": 6600}]})
    runner.main()
    report = json.loads((output / "aviator_comparison.json").read_text(encoding="utf-8"))
    assert report["schema_version"] == "0.5"
    assert report["primary_ranking_urls"] == urls
    assert report["advanced_evidence"]["keyword_intersection"]["returned"] == 1
    assert report["advanced_evidence"]["backlinks"]["domain"]["rank"]["ours"] == 70
    assert any(f["category"] == "lighthouse" for f in report["findings"])
    assert any(r["id"] == "page-link-profile" for r in report["recommendations"])
    assert (output / "aviator_recommendations.txt").exists()
