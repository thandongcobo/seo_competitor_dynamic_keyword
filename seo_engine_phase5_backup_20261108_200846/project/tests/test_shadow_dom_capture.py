from pathlib import Path

import pytest

from collectors.playwright_collector import _content_quality, _full_page_inventory, _rendered_signals, _stable_render
from config.settings import settings
from monitoring.promotions import _fingerprint, _merge_candidates, _text_candidates
from playwright.sync_api import sync_playwright


@pytest.mark.skipif(not settings.playwright_browser_path or not Path(settings.playwright_browser_path).is_file(),
                    reason="An installed Chrome/Edge browser is required for the DOM integration fixture")
def test_open_shadow_dom_promotion_text_and_links_are_captured():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=settings.playwright_browser_path)
        page = browser.new_page()
        page.set_content("""
          <h1>Promotions</h1><promo-widget></promo-widget>
          <script>
            customElements.define('promo-inner', class extends HTMLElement {
              connectedCallback() {
                const root=this.attachShadow({mode:'open'});
                root.innerHTML='<p>Daily bonus spins include 10% off selected games.</p>';
              }
            });
            customElements.define('promo-widget', class extends HTMLElement {
              connectedCallback() {
                const root=this.attachShadow({mode:'open'});
                root.innerHTML='<article class="promo-card"><h2>Daily Bonus Spins</h2><promo-inner></promo-inner><a href="https://example.test/offer">Offer details</a></article>';
              }
            });
          </script>
          <style>body{font:16px Arial} promo-widget, article, p, a{display:block;min-height:20px}</style>
        """)

        signals = _rendered_signals(page)
        inventory = _full_page_inventory(page)
        browser.close()

    assert signals["open_shadow_root_count"] == 2
    assert signals["rendered_h1_count"] == 1
    assert "Daily bonus spins" in signals["composed_text_prefix"]
    assert inventory["shadow_dom_open_root_count"] == 2
    assert inventory["composed_card_count"] >= 1
    candidates = _text_candidates({"final_url": "https://example.test/promotions", **inventory})
    assert any("Daily Bonus Spins" in item["extracted_text"] for item in candidates)
    candidate = next(item for item in candidates if "Daily Bonus Spins" in item["extracted_text"])
    assert candidate["target_url"] == "https://example.test/offer"
    assert candidate["source_type"] == "text"


def test_render_stability_includes_composed_shadow_text():
    base = {"final_url": "https://example.test", "rendered_word_count": 10,
            "rendered_main_word_count": 0, "seo_content_word_count": 0,
            "seo_content_selector": None, "seo_content_text_prefix": None,
            "rendered_h1_count": 0, "readiness_text_prefix": "page shell",
            "shadow_word_count": 10, "shadow_text_prefix": "page shell"}
    changed = dict(base, shadow_word_count=22, shadow_text_prefix="page shell new promotion")
    assert not _stable_render(base, changed)


def test_substantive_visible_shadow_content_can_satisfy_capture_readiness():
    ready, reason = _content_quality({"shadow_word_count": 100, "seo_content_status": "unverified"})
    assert ready is True
    assert reason == "stable_visible_shadow_dom_content"


def test_promotion_component_is_one_candidate_with_associated_artwork():
    blocks = [
        {"text": "Calling on all superfans; win up to R30,000.", "evidence_scope": "composed_card",
         "promotion_context": True, "image_refs": [{"image_index": 4, "url": "https://cdn.example.test/card.jpg"}]},
        {"text": "A daily reward card with 10% off and a voucher.", "evidence_scope": "composed_card",
         "promotion_context": True, "image_refs": [{"image_index": 5, "url": "https://cdn.example.test/card2.jpg"}]},
        {"text": "Calling on all superfans; win up to R30,000.", "evidence_scope": "composed_card_child"},
        {"text": "horse racing", "tag": "a"},
    ]
    candidates = _text_candidates({
        "final_url": "https://example.test/promotions",
        "rendered_text_blocks": blocks,
        "promotion_image_crops": [{"image_index": 4, "path": "crop.png"}, {"image_index": 5, "path": "crop2.png"}],
    })
    assert len(candidates) == 2
    by_image = {item["image_index"]: item for item in candidates}
    assert by_image[4]["confidence"] == "medium"
    assert by_image[4]["image_path"] == "crop.png"
    assert by_image[5]["image_path"] == "crop2.png"
    assert by_image[4]["fingerprint"] == _fingerprint({"src": "https://cdn.example.test/card.jpg"}, by_image[4]["extracted_text"])
    merged = _merge_candidates(candidates, [{"image_index": 4, "image_path": "crop.png", "extracted_text": "", "confidence": "medium"}])
    assert len(merged) == 2
    assert by_image[4]["source_type"] == "text+image"
