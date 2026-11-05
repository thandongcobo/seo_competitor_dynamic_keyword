from __future__ import annotations

from scripts.run_analysis import validate_page, validate_backlinks
from normalization.pages import normalize_page
from analysis.comparison_engine import build_findings

URL = "https://www.betway.co.za/aviator"


def _page(**kw):
    base = {"ranking_url": URL, "requested_url": URL, "final_url": URL,
            "word_count": 600, "extraction_status": "complete", "crawl_failed": False,
            "url_alignment": "matched", "title": "Aviator", "headings": {"h1": ["Aviator"]}}
    base.update(kw)
    return base


def test_good_page_retained():
    result, status = validate_page(_page(), URL, "benchmark")
    assert status == "usable" and result["title"] == "Aviator"


def test_other_url_cannot_be_misattributed():
    result, status = validate_page(_page(ranking_url="https://www.betway.co.za/home"), URL, "benchmark")
    assert not result and "different" in status


def test_redirect_and_thin_content_are_withheld():
    assert not validate_page(_page(url_alignment="redirected_from_ranking_url"), URL, "benchmark")[0]
    assert not validate_page(_page(word_count=148), URL, "benchmark")[0]
    assert not validate_page(_page(extraction_status="incomplete"), URL, "benchmark")[0]


def test_crawl_quality_survives_normalization():
    result = normalize_page(_page(content_quality_reason="text_and_structure", keyword="aviator"))
    assert result["extraction_status"] == "complete"
    assert result["content_quality_reason"] == "text_and_structure"
    assert result["ranking_url"] == URL


def test_backlinks_require_exact_page_target():
    base = {"scope": "page", "target_verified": True, "target": URL, "referring_domains": 20}
    assert validate_backlinks(base, URL, "benchmark")[1] == "usable"
    assert not validate_backlinks({**base, "scope": "domain"}, URL, "benchmark")[0]
    assert not validate_backlinks({**base, "target": "https://www.betway.co.za/"}, URL, "benchmark")[0]


def test_quality_limitations_are_reported_not_ranked_as_seo_weaknesses():
    findings = build_findings({}, evidence_quality={"page_benchmark": "limited content"})
    assert len(findings) == 1
    assert findings[0]["category"] == "evidence_limitation"
