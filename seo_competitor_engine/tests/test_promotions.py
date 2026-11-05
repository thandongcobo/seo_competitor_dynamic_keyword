import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from monitoring import promotions, store


@pytest.fixture
def isolated_database(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="promotion-test-", dir=store.ROOT) as folder:
        monkeypatch.setattr(store, "DB_PATH", Path(folder) / "monitoring.sqlite3")
        yield


def capture_with_banner():
    return {
        "image_inventory": [{
            "src": "https://cdn.example.test/campaign/summer-banner.jpg?cache=1",
            "href": "https://brand.example.test/offer",
            "alt": "Summer offer",
            "visible": True,
            "rendered_width": 800,
            "rendered_height": 300,
            "section": "main",
        }],
        "promotion_image_crops": [{"image_index": 0, "path": "capture/promotion_images/image_0000.png"}],
    }


def test_ocr_text_classifies_banner_as_review_candidate(monkeypatch):
    fake = SimpleNamespace(pytesseract=SimpleNamespace(tesseract_cmd=""), get_tesseract_version=lambda: "5.0")
    monkeypatch.setitem(__import__("sys").modules, "pytesseract", fake)
    result = promotions.analyze_capture(capture_with_banner(), ocr=lambda _path: "Get 50 FREE spins - Claim your bonus")
    assert result["status"] == "available"
    candidate = result["candidates"][0]
    assert candidate["confidence"] == "high"
    assert "bonus" in candidate["extracted_text"].lower()
    assert candidate["review_status"] == "needs_review"
    assert candidate["target_url"] == "https://brand.example.test/offer"


def test_missing_local_ocr_still_surfaces_banner_for_manual_review(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "pytesseract", None)
    result = promotions.analyze_capture(capture_with_banner())
    assert result["status"] == "unavailable"
    assert result["candidates"]
    assert result["candidates"][0]["confidence"] == "medium"


def test_promotion_history_and_conservative_not_seen_state(isolated_database):
    page_id = store.register("https://brand.example.test/aviator", "aviator", active=True)
    candidate = promotions._image_candidates(
        capture_with_banner()["image_inventory"], {0: "capture/promo.png"}, {0: "Get 50 free spins"}
    )[0]
    store.record_promotions(page_id, "snap-1", "2026-10-15T08:00:00Z", {"status": "available", "candidates": [candidate]})

    updated = dict(candidate, extracted_text="Get 75 free spins", title="Get 75 free spins")
    store.record_promotions(page_id, "snap-2", "2026-10-16T08:00:00Z", {"status": "available", "candidates": [updated]})
    row = store.promotions_for_domain("brand.example.test")[0]
    assert row["first_seen_at"] == "2026-10-15T08:00:00Z"
    assert row["last_seen_at"] == "2026-10-16T08:00:00Z"
    assert len(row["history"]) == 1

    store.record_promotions(page_id, "snap-3", "2026-10-17T08:00:00Z", {"status": "available", "candidates": []})
    assert store.promotions_for_domain("brand.example.test")[0]["status"] == "possibly_rotated"
    store.record_promotions(page_id, "snap-4", "2026-10-18T08:00:00Z", {"status": "available", "candidates": []})
    assert store.promotions_for_domain("brand.example.test")[0]["status"] == "not_detected"


def test_same_public_destination_keeps_promotion_identity_when_asset_url_rotates(isolated_database):
    page_id = store.register("https://brand.example.test/promotions", "aviator", active=True)
    first = promotions._image_candidates(capture_with_banner()["image_inventory"], {0: "capture/one.png"}, {0: "Get 50 free spins"})[0]
    first["target_url"] = "https://brand.example.test/offer"
    store.record_promotions(page_id, "snap-1", "2026-10-15T08:00:00Z", {"status": "available", "candidates": [first]})
    changed_image = dict(first, fingerprint="rotated-asset-fingerprint", source_url="https://cdn.example.test/new/banner.jpg",
                         extracted_text="Get 75 free spins", title="Get 75 free spins")
    store.record_promotions(page_id, "snap-2", "2026-10-16T08:00:00Z", {"status": "available", "candidates": [changed_image]})
    rows = store.promotions_for_page(page_id)
    assert len(rows) == 1
    assert rows[0]["first_seen_at"] == "2026-10-15T08:00:00Z"
    assert rows[0]["extracted_text"] == "Get 75 free spins"
    assert rows[0]["history"][-1]["event"] == "version_changed"


def test_ocr_unavailable_does_not_age_out_existing_candidate(isolated_database):
    page_id = store.register("https://brand.example.test/aviator", "aviator", active=True)
    candidate = promotions._image_candidates(
        capture_with_banner()["image_inventory"], {0: "capture/promo.png"}, {}
    )[0]
    store.record_promotions(page_id, "snap-1", "2026-10-15T08:00:00Z", {"status": "available", "candidates": [candidate]})
    store.record_promotions(page_id, "snap-2", "2026-10-16T08:00:00Z", {"status": "unavailable", "candidates": []})
    assert store.promotions_for_domain("brand.example.test")[0]["status"] == "current"


def test_text_promo_candidates_extract_fields_and_context():
    snapshot = {
        "final_url": "https://brand.example.test/aviator",
        "rendered_text_blocks": [{
            "tag": "p", "text": "Get R100 Free Bet when you deposit R50. Use code AV100 by 31 October 2026.",
            "section": "offers", "heading": "Aviator welcome offer",
            "related_links": [{"text": "Offer details", "url": "https://brand.example.test/aviator-offer"}],
        }],
    }
    result = promotions.analyze_capture(snapshot, ocr=lambda _path: "")
    candidate = result["candidates"][0]
    assert candidate["source_type"] == "text"
    assert candidate["confidence"] == "high"
    assert candidate["heading"] == "Aviator welcome offer"
    assert candidate["target_url"] == "https://brand.example.test/aviator-offer"
    assert candidate["details"]["amounts"] == ["R100", "R50"]
    assert candidate["details"]["promo_codes"] == ["AV100"]
    assert candidate["details"]["dates"] == ["31 October 2026"]


def test_generic_marketing_text_is_not_a_promotion_candidate():
    result = promotions.analyze_capture({"rendered_page_text": "Win every day with our team. Join us and enjoy the game."})
    assert result["candidates"] == []
    assert result["text_scan_complete"] is True


def test_high_confidence_candidate_investigates_landing_and_terms():
    calls = []
    def fake_fetch(url, *, source_url):
        calls.append(url)
        if url.endswith("/terms"):
            return {"status": "captured", "source_url": url, "title": "Terms", "text_excerpt": "New customers only. Minimum deposit R50.",
                    "details": {"amounts": ["R50"], "percentages": [], "promo_codes": [], "dates": [],
                                "eligibility_or_terms": ["New customers only."], "evidence_excerpts": ["Minimum deposit R50."], "source_url": url}}
        return {"status": "captured", "source_url": url, "title": "Offer", "text_excerpt": "Get R100 free bet.",
                "terms_url": "https://brand.example.test/terms",
                "details": {"amounts": ["R100"], "percentages": [], "promo_codes": [], "dates": [],
                            "eligibility_or_terms": [], "evidence_excerpts": ["Get R100 free bet."], "source_url": url}}
    analysis = {"candidates": [{"confidence": "high", "target_url": "https://brand.example.test/offer", "details": {"amounts": [], "percentages": [], "promo_codes": [], "dates": [], "eligibility_or_terms": [], "evidence_excerpts": []}}]}
    result = promotions.investigate_candidates(analysis, source_url="https://brand.example.test/page", fetch=fake_fetch)
    candidate = result["candidates"][0]
    assert calls == ["https://brand.example.test/offer", "https://brand.example.test/terms"]
    assert candidate["investigation"]["status"] == "captured"
    assert candidate["details"]["amounts"] == ["R100", "R50"]
    assert candidate["details"]["eligibility_or_terms"] == ["New customers only."]
    assert candidate["details"]["terms_url"] == "https://brand.example.test/terms"
    assert candidate["review_status"] == "auto_investigated"


def test_public_page_fetch_extracts_terms_link_and_offer_fields(monkeypatch):
    class Response:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}
        encoding = "utf-8"
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def iter_content(self, _size):
            return [b"<html><head><title>Aviator Offer</title></head><body><h1>Get R100 Free Bet</h1><p>New customers only. Use code AVI100 by 31 October 2026.</p><a href='/terms'>Terms and conditions</a></body></html>"]
    monkeypatch.setattr(store, "validate_public_host", lambda url: url)
    monkeypatch.setattr(promotions.requests, "get", lambda *args, **kwargs: Response())
    result = promotions.fetch_public_offer_page("https://brand.example.test/offer", source_url="https://brand.example.test/page")
    assert result["status"] == "captured"
    assert result["title"] == "Aviator Offer"
    assert result["details"]["amounts"] == ["R100"]
    assert result["details"]["promo_codes"] == ["AVI100"]
    assert result["terms_url"] == "https://brand.example.test/terms"


def test_medium_or_offsite_candidates_are_not_auto_fetched():
    calls = []
    analysis = {"candidates": [
        {"confidence": "medium", "target_url": "https://brand.example.test/offer"},
        {"confidence": "high", "target_url": "https://other.example.test/offer"},
    ]}
    result = promotions.investigate_candidates(analysis, source_url="https://brand.example.test/page",
                                               fetch=lambda *args, **kwargs: calls.append(args[0]))
    assert calls == []
    assert [x["investigation"]["status"] for x in result["candidates"]] == ["review_required", "skipped"]


def test_text_candidates_persist_and_age_independent_of_ocr(isolated_database):
    page_id = store.register("https://brand.example.test/aviator", "aviator", active=True)
    candidate = promotions._text_candidates({"final_url": "https://brand.example.test/aviator", "rendered_text_blocks": [
        {"text": "Get R100 Free Bet when you deposit R50.", "related_links": [{"text": "Details", "url": "https://brand.example.test/offer"}]}
    ]})[0]
    store.record_promotions(page_id, "snap-1", "2026-10-15T08:00:00Z", {"status": "unavailable", "text_scan_complete": True, "image_scan_complete": False, "candidates": [candidate]})
    saved = store.promotions_for_domain("brand.example.test")[0]
    assert saved["source_type"] == "text"
    assert saved["details"]["amounts"] == ["R100", "R50"]
    store.record_promotions(page_id, "snap-2", "2026-10-16T08:00:00Z", {"status": "unavailable", "text_scan_complete": True, "image_scan_complete": False, "candidates": []})
    assert store.promotions_for_domain("brand.example.test")[0]["status"] == "possibly_rotated"
    store.update_promotion_review(saved["id"], "confirmed")
    store.record_promotions(page_id, "snap-3", "2026-10-17T08:00:00Z", {"status": "unavailable", "text_scan_complete": True, "image_scan_complete": False, "candidates": [candidate]})
    assert store.promotions_for_domain("brand.example.test")[0]["review_status"] == "confirmed"


def test_absence_requires_two_successful_scans_and_is_not_called_ended(isolated_database):
    page_id = store.register("https://brand.example.test/aviator", "aviator", active=True)
    candidate = promotions._text_candidates({"rendered_text_blocks": [{"text": "Get R100 Free Bet when you deposit R50."}]})[0]
    store.record_promotions(page_id, "snap-1", "2026-10-15T08:00:00Z", {"text_scan_complete": True, "candidates": [candidate]})
    empty = {"text_scan_complete": True, "candidates": []}
    store.record_promotions(page_id, "snap-2", "2026-10-16T08:00:00Z", empty)
    assert store.promotions_for_page(page_id)[0]["status"] == "possibly_rotated"
    store.record_promotions(page_id, "snap-3", "2026-10-17T08:00:00Z", empty)
    row = store.promotions_for_page(page_id)[0]
    assert row["status"] == "not_detected"
    assert row["history"][-1]["event"] == "not_detected"
    assert "does not prove" in row["history"][-1]["note"]


def test_monitor_url_validation_rejects_private_and_credential_urls():
    with pytest.raises(ValueError):
        store.validate_public_url("http://127.0.0.1/admin")
    with pytest.raises(ValueError):
        store.validate_public_url("https://user:secret@brand.example.test/page")
    assert store.validate_public_url("https://brand.example.test/page") == "https://brand.example.test/page"


def test_capture_host_validation_requires_public_dns_addresses(monkeypatch):
    monkeypatch.setattr(store.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("8.8.8.8", 443))])
    assert store.validate_public_host("https://brand.example.test/page").endswith("/page")
    monkeypatch.setattr(store.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("10.0.0.5", 443))])
    with pytest.raises(ValueError):
        store.validate_public_host("https://brand.example.test/page")


def test_promotion_records_are_scoped_to_selected_url(isolated_database):
    first = store.register("https://brand.example.test/aviator", "aviator", active=True)
    second = store.register("https://brand.example.test/casino", "aviator", active=True)
    candidate = promotions._text_candidates({"final_url": "https://brand.example.test/aviator", "rendered_text_blocks": [
        {"text": "Get R100 Free Bet when you deposit R50."}
    ]})[0]
    store.record_promotions(first, "snap-1", "2026-10-15T08:00:00Z", {"text_scan_complete": True, "candidates": [candidate]})
    assert len(store.promotions_for_page(first)) == 1
    assert store.promotions_for_page(second) == []
