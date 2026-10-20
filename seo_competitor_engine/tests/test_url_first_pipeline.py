from __future__ import annotations

from scripts.resolve_pages import targets_from_resolved, normalized_url, require_target
from scripts.collect_backlinks import resolve_target
from scripts.crawl_pages import crawl_output_filename


def _resolved():
    return {
        "keyword": "aviator", "our_domain": "hollywoodbets.net", "benchmark_domain": "betway.co.za",
        "engines": {"google": {"comparison": {
            "our_url": "https://www.hollywoodbets.net/aviator", "our_position": 2,
            "benchmark_url": "https://www.betway.co.za/aviator", "benchmark_position": 1,
        }}},
    }


def test_target_manifest_uses_exact_serp_urls():
    t = targets_from_resolved(_resolved(), "google")
    assert t["ours"]["ranking_url"] == "https://www.hollywoodbets.net/aviator"
    assert t["benchmark"]["ranking_url"] == "https://www.betway.co.za/aviator"
    assert t["benchmark"]["rank"] == 1


def test_backlinks_ignores_env_page_override(monkeypatch):
    import scripts.collect_backlinks as b
    from types import SimpleNamespace
    monkeypatch.setattr(b, "settings", SimpleNamespace(our_page_url="https://hollywoodbets.net/WRONG", competitor_page_url="https://betway.co.za/WRONG", our_domain="hollywoodbets.net", benchmark_competitor_domain="betway.co.za"))
    monkeypatch.setattr(b, "require_target", lambda side, engine: targets_from_resolved(_resolved(), engine)[side])
    assert resolve_target("ours", "page") == "https://www.hollywoodbets.net/aviator"
    assert resolve_target("benchmark", "page") == "https://www.betway.co.za/aviator"
    assert resolve_target("benchmark", "domain") == b.settings.benchmark_competitor_domain


def test_no_domain_fallback_when_serp_page_missing(monkeypatch):
    import scripts.collect_backlinks as b
    def missing(side, engine):
        raise ValueError("Missing SERP ranking URL")
    monkeypatch.setattr(b, "require_target", missing)
    import pytest
    with pytest.raises(ValueError, match="Missing SERP"):
        resolve_target("benchmark", "page")


def test_google_and_bing_priority_files_are_separate():
    url = "https://www.betway.co.za/aviator"
    assert crawl_output_filename("aviator", "google", "benchmark", url, True) != crawl_output_filename("aviator", "bing", "benchmark", url, True)
    assert normalized_url("https://www.betway.co.za/aviator/") == normalized_url(url)
