"""Offline browser checks for semantic-first generic main-content selection."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from collectors.main_content import extract_main_content
from collectors.playwright_collector import _content_quality, _full_page_inventory
from config.settings import settings
from scripts.investigation_collection import _page_matches


ROOT = Path(__file__).resolve().parents[1]
SPORTY_HTML = ROOT / "output/playwright_competitor_live_test/20261112T065301Z_f0b510b7/capture/rendered_page.html"
HOLLYWOOD_INCOMPLETE = ROOT / "data/diagnostics/page_crawls/900732a317a23a59/20261111T075304198495Z_4e6c88bd76d2/page.html"
AVIATOR_JSON = ROOT / "data/raw/pages/aviator_google_ours.json"
SPORTY_URL = "https://www.sportybet.co.za/za/m/lucky-numbers"

pytestmark = pytest.mark.skipif(
    not settings.playwright_browser_path or not Path(settings.playwright_browser_path).is_file(),
    reason="An installed Chrome/Edge browser is required for the offline DOM fixture",
)


def _offline_html(path: Path) -> str:
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    for node in soup.select("script,iframe,link,style,object,embed,video,audio,source"):
        node.decompose()
    for node in soup.find_all(True):
        for attr in ("src", "srcset", "poster"):
            node.attrs.pop(attr, None)
    return str(soup)


def _extract(html: str) -> dict:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path=settings.playwright_browser_path
        )
        page = browser.new_page()
        # The fixture is local data. Fail closed if the browser tries any request.
        page.route("**/*", lambda route: route.abort())
        page.set_content(html, wait_until="domcontentloaded")
        result = extract_main_content(page)
        browser.close()
    return result


def _extract_inventory(html: str) -> dict:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path=settings.playwright_browser_path
        )
        page = browser.new_page()
        page.route("**/*", lambda route: route.abort())
        page.set_content(html, wait_until="domcontentloaded")
        result = extract_main_content(page)
        result["_source_selectors_match_text"] = page.evaluate("""items => items.map(item => {
          const node=document.querySelector(item.selector);
          const clean=value=>(value||'').replace(/\\s+/g,' ').trim();
          return Boolean(node && clean(node.innerText)===clean(item.text));
        })""", result.get("seo_content_blocks") or [])
        result.update(_full_page_inventory(page, result.get("seo_content_blocks")))
        browser.close()
    return result


def test_saved_sportybet_content_is_selected_and_page_match_accepts_it():
    extracted = _extract(_offline_html(SPORTY_HTML))
    assert extracted["seo_content_status"] == "candidate"
    assert extracted["seo_content_candidate_type"] == "nonsemantic"
    assert extracted["seo_content_word_count"] >= 100
    assert extracted["seo_content_selector"]
    assert extracted["seo_content_reason"] == "visible_nonsemantic_content_candidate"
    signals = extracted["seo_content_quality_signals"]
    assert signals["distinct_content_blocks"] >= 3
    assert signals["interactive_word_ratio"] <= 0.85
    assert _content_quality(extracted) == (True, "standardized_visible_nonsemantic_candidate")

    # Exercise the same URL/identity/completeness predicate used by the collection adapter.
    item = {"keyword": "lucky numbers", "target": SPORTY_URL}
    record = {
        "keyword": "lucky numbers", "requested_url": SPORTY_URL,
        "ranking_url": SPORTY_URL, "final_url": SPORTY_URL,
        "extraction_status": "complete", "crawl_failed": False, "blocked": False,
        **extracted,
    }
    assert _page_matches(item, record)


def test_selected_generic_content_blocks_are_in_full_page_inventory():
    html = _offline_html(SPORTY_HTML)
    result = _extract_inventory(html)
    blocks = result["rendered_text_blocks"]
    texts = [block["text"] for block in blocks]
    selected_text = result["seo_content_text"]

    assert result["seo_content_selector"] == "div.lotteries-list-wrapper"
    assert len(blocks) == 14  # one existing semantic block plus 13 selected listing blocks
    listing_blocks = [block for block in blocks if block.get("evidence_scope") == "main_content_candidate"]
    assert len(listing_blocks) == 13
    assert result["_source_selectors_match_text"] == [True] * 13
    assert any("UK 39's" in text for text in texts)
    assert any("UK 15's" in text for text in texts)
    assert any("Brunchtime" in text for text in texts)
    assert any("EuroMillions" in text for text in texts)
    assert all(block["text"] in selected_text for block in listing_blocks)
    assert all(block["source_selector"] and block["section"].startswith("main-content:")
               for block in listing_blocks)
    assert len({block["text"].casefold() for block in listing_blocks}) == len(listing_blocks)
    assert all("loading" not in block["text"].casefold() and "please reload" not in block["text"].casefold()
               for block in listing_blocks)

    previous = json.loads((ROOT / "output/playwright_sportybet_live_verification/20261112T084517Z_fd574e00/collector_output.json").read_text(encoding="utf-8"))
    assert len(previous["rendered_text_blocks"]) == 1


def test_saved_aviator_record_remains_a_complete_matching_page():
    record = json.loads(AVIATOR_JSON.read_text(encoding="utf-8"))
    assert record["extraction_status"] == "complete"
    assert record["seo_content_word_count"] >= 100
    assert record["seo_content_selector"] == "#main-content"
    item = {"keyword": record["keyword"], "target": record["ranking_url"]}
    assert _page_matches(item, record)


def test_saved_incomplete_hollywoodbets_error_capture_stays_rejected():
    extracted = _extract(_offline_html(HOLLYWOOD_INCOMPLETE))
    assert extracted["seo_content_status"] != "candidate"
    assert extracted["seo_content_word_count"] is None or extracted["seo_content_word_count"] < 100
    assert _content_quality(extracted)[0] is False


def test_generic_javascript_rendered_container_is_selected():
    sentence = "This guide explains the verified lottery schedule and how each draw works for readers. "
    html = f"""<!doctype html><html><body><div id="application"></div><script>
      const root = document.querySelector('#application');
      const section = document.createElement('div');
      section.append(Object.assign(document.createElement('h1'), {{textContent:'Lottery draw guide'}}));
      for (let i=0; i<3; i++) {{
        const block=document.createElement('div');
        block.textContent={json.dumps(sentence * 7)} + ' Section ' + i + ' covers a different practical detail.';
        section.append(block);
      }}
      root.append(section);
    </script></body></html>"""
    extracted = _extract(html)
    assert extracted["seo_content_status"] == "candidate"
    assert extracted["seo_content_candidate_type"] == "nonsemantic"
    assert extracted["seo_content_word_count"] >= 100


def test_semantic_main_remains_preferred_over_generic_wrapper():
    words = " ".join(["Useful", "page", "content", "describes", "the", "product"] * 25)
    html = f"<html><body><div id='app'><main><h1>Product guide</h1><p>{words}</p></main></div></body></html>"
    extracted = _extract(html)
    assert extracted["seo_content_status"] == "candidate"
    assert extracted["seo_content_candidate_type"] == "semantic"
    assert extracted["seo_content_selector"] == "main"


@pytest.mark.parametrize("html", [
    "<html><body><nav>" + "Home Casino Sports Login Promotions ".__mul__(40) + "</nav></body></html>",
    "<html><body><div class='skeleton-placeholder'>" + "Loading content please wait ".__mul__(50) + "</div></body></html>",
    "<html><body><div class='error-panel'>Error displaying Lucky Numbers " + "Please reload the page ".__mul__(30) + "</div></body></html>",
    "<html><body><main>Error displaying Lucky Numbers " + "Please reload the page ".__mul__(30) + "</main></body></html>",
])
def test_navigation_loading_and_error_states_are_not_candidates(html: str):
    extracted = _extract(html)
    assert extracted["seo_content_status"] != "candidate"
    assert _content_quality(extracted)[0] is False
