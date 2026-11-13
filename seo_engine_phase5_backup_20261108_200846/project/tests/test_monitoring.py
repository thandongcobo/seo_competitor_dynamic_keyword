import json
import tempfile
from pathlib import Path

from collectors.playwright_collector import _public_request_route
from monitoring import capture as capture_module, store
from monitoring.diff import compare,digest

def base():
    return {'title':'Aviator','meta_description':'Play Aviator','headings':{'h1':['Aviator']},'internal_links':['/a'], 'external_links':[], 'structured_data_blocks':[],'seo_content_text':'How to play Aviator'}

def test_first_comparison_has_no_events():
    assert compare({},base(),'old','new','page')

def test_identical_captures_have_no_events():
    x=base(); assert compare(x,x,'old','new','page')==[]

def test_title_and_added_content_are_detected():
    old=base(); new=base(); new['title']='Aviator online'; new['seo_content_text']+=' New FAQ'; events=compare(old,new,'old','new','page')
    assert {e['element_type'] for e in events}=={'title','seo_content_text'}
    assert all(e['category']=='modified' for e in events)

def test_reordering_lists_is_not_a_change():
    old=base(); new=base(); new['internal_links']=['/a']; assert compare(old,new,'old','new','page')==[]

def test_dynamic_dates_are_ignored():
    old=base(); new=base(); old['meta_description']='Updated 2026-10-14'; new['meta_description']='Updated 2026-10-15'; assert compare(old,new,'old','new','page')==[]

def test_digest_is_stable():
    assert digest(base())==digest(base())


def test_capture_pipeline_scans_public_page_text_and_persists_candidate(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="monitoring-capture-test-", dir=store.ROOT) as folder:
        root = Path(folder)
        monkeypatch.setattr(store, "DB_PATH", root / "monitoring.sqlite3")
        monkeypatch.setattr(store, "ARTIFACT_DIR", root / "artifacts")
        monkeypatch.setattr(store, "validate_public_host", lambda url: url)
        page_id = store.register("https://brand.example.test/aviator", "aviator")

        def fake_crawl(url, *, artifact_dir, public_only):
            assert public_only is True
            return {
                "requested_url": url,
                "final_url": url,
                "extraction_status": "complete",
                "rendered_page_text": "Get R100 Free Bet when you deposit R50. This welcome offer is available to eligible new customers. Read the terms before you claim the offer and check account eligibility. The promotion is subject to standard rules and a minimum qualifying deposit.",
                "rendered_text_blocks": [{"tag": "p", "text": "Get R100 Free Bet when you deposit R50. This welcome offer is available to eligible new customers. Read the terms before you claim the offer and check account eligibility. The promotion is subject to standard rules and a minimum qualifying deposit.", "heading": "Aviator offer", "section": "offers"}],
                "rendered_word_count": 44,
                "content_stable": True,
                "image_inventory": [],
                "promotion_image_crops": [],
            }

        monkeypatch.setattr(capture_module, "crawl_page", fake_crawl)
        result = capture_module.capture(page_id)
        candidates = store.promotions_for_page(page_id)
        assert result["status"] == "success"
        assert len(candidates) == 1
        assert candidates[0]["source_type"] == "text"
        assert candidates[0]["details"]["amounts"] == ["R100", "R50"]
        assert candidates[0]["review_status"] == "needs_review"


def test_capture_quality_gates_cross_host_or_tiny_capture():
    data = {"extraction_status": "complete", "final_url": "https://other.example.test/", "rendered_page_text": "Only a few words.", "content_stable": True}
    quality = capture_module._tracking_quality(data, "https://brand.example.test/")
    assert quality["eligible"] is False
    assert quality["same_host"] is False
    assert any("different host" in reason for reason in quality["reasons"])
    assert any("Very little" in reason for reason in quality["reasons"])


def test_ineligible_capture_is_saved_but_does_not_update_promotion_state(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="monitoring-quality-test-", dir=store.ROOT) as folder:
        root = Path(folder)
        monkeypatch.setattr(store, "DB_PATH", root / "monitoring.sqlite3")
        monkeypatch.setattr(store, "ARTIFACT_DIR", root / "artifacts")
        monkeypatch.setattr(store, "validate_public_host", lambda url: url)
        page_id = store.register("https://brand.example.test/page", "aviator")
        monkeypatch.setattr(capture_module, "crawl_page", lambda url, **kwargs: {
            "requested_url": url, "final_url": "https://other.example.test/page", "status_code": 200,
            "extraction_status": "complete", "rendered_page_text": "A very short page.",
            "content_stable": True, "image_inventory": [], "promotion_image_crops": [],
        })
        result = capture_module.capture(page_id)
        assert result["status"] == "success"
        assert result["tracking_eligible"] is False
        assert store.snapshots(page_id) == []
        assert store.page(page_id)["last_success_at"] is None


def test_public_browser_context_blocks_non_public_requests(monkeypatch):
    def check(url):
        if "127.0.0.1" in url:
            raise ValueError("not public")
        return url
    monkeypatch.setattr(store, "validate_public_host", check)

    class Request:
        def __init__(self, url): self.url = url
    class Route:
        def __init__(self, url): self.request = Request(url); self.action = None
        def abort(self, _reason): self.action = "blocked"
        def continue_(self): self.action = "continued"

    guard = _public_request_route(set())
    public = Route("https://brand.example.test/page")
    private = Route("http://127.0.0.1/admin")
    guard(public)
    guard(private)
    assert public.action == "continued"
    assert private.action == "blocked"
