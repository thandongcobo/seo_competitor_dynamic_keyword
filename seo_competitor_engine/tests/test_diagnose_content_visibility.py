from scripts.diagnose_content_visibility import get_targets, slugify, JS_DIAGNOSTIC
import pytest


def test_keyword_slug():
    assert slugify('Aviator Game!') == 'aviator_game'


def test_only_saved_serp_urls_used():
    data = {'keyword':'aviator','primary_ranking_urls':{'ours':'https://www.hollywoodbets.net/aviator','benchmark':'https://www.betway.co.za/aviator'}}
    assert get_targets(data,'aviator') == data['primary_ranking_urls']
    with pytest.raises(ValueError): get_targets(data,'roulette')


def test_missing_target_rejected():
    with pytest.raises(ValueError): get_targets({'keyword':'aviator','primary_ranking_urls':{'ours':'https://example.org'}},'aviator')


def test_diagnostic_collects_counts_not_page_text():
    assert 'hidden_ancestor_words' in JS_DIAGNOSTIC
    assert 'strict_ancestor_visible_words' in JS_DIAGNOSTIC
    assert 'top_direct_children' in JS_DIAGNOSTIC
    assert 'innerHTML' not in JS_DIAGNOSTIC
