"""Offline tests: test-only SERP fixtures, never production ranking data."""
from unittest.mock import patch
from types import SimpleNamespace

from collectors.tracked_serp import discovery_state, domain_matches, tracked_position
from collectors import team_serp_adapter


def row(domain, rank):
    return {'domain': domain, 'url': f'https://{domain}/page-{rank}', 'title': f'Page {rank}'}


def test_boundary_safe_domain_matching():
    assert domain_matches('www.hollywoodbets.net', 'hollywoodbets.net')
    assert domain_matches('sports.hollywoodbets.net', 'hollywoodbets.net')
    assert not domain_matches('fakehollywoodbets.net', 'hollywoodbets.net')
    assert not domain_matches('hollywoodbets.net.evil.com', 'hollywoodbets.net')
    assert not domain_matches('hollywoodbets.com', 'hollywoodbets.net')


def test_preserves_observed_sequence_and_neighbours():
    rows = [row('betway.co.za', 1), row('hollywoodbets.net', 2), row('example.org', 3), row('other.org', 4)]
    original = [dict(r) for r in rows]
    state = discovery_state(rows, 'hollywoodbets.net', 4, 100)
    assert state['rank'] == 2
    assert state['ranking_url'] == 'https://hollywoodbets.net/page-2'
    assert state['results_above'] == 1 and state['results_below'] == 2
    assert state['complete']
    assert rows == original
    assert tracked_position(rows, 'example.org')['rank'] == 3


def test_missing_site_does_not_invent_rank():
    state = discovery_state([row('betway.co.za', 1)], 'hollywoodbets.net', 1, 100)
    assert state['status'] == 'not_found' and state['rank'] is None
    assert state['ranking_url'] is None and not state['complete']


def test_found_near_end_requires_more_results():
    rows = [row('other.org', 1), row('hollywoodbets.net', 2)]
    assert not discovery_state(rows, 'hollywoodbets.net', 2, 100)['complete']
    rows += [row('a.com', 3), row('b.com', 4)]
    assert discovery_state(rows, 'hollywoodbets.net', 2, 100)['complete']


class FakePage:
    def __init__(self, rows):
        self.pages = rows
        self.index = 0
        self.url = 'https://www.google.com/search?q=aviator&start=0'

    def goto(self, url, **kwargs):
        self.index += 1
        self.url = url

    def wait_for_timeout(self, ms):
        pass

    def close(self):
        pass


def test_collector_paginates_until_tracked_site_found(tmp_path):
    pages = [
        [row('example.org', 1), row('another.org', 2)],
        [row('hollywoodbets.net', 3), row('third.org', 4)],
        [row('fourth.org', 5), row('fifth.org', 6)],
    ]
    page = FakePage(pages)
    team = SimpleNamespace(
        search_google=lambda kw: page,
        extract_organic_results=lambda p: pages[p.index],
        BROWSER=SimpleNamespace(close=lambda: None),
    )
    def next_url(p, visited, initial_url):
        if p.index < 2:
            return f'https://www.google.com/search?q=aviator&start={(p.index+1)*10}', 'valid'
        return None, 'no_next_page'
    with patch.object(team_serp_adapter, 'load_team_module', return_value=team), \
         patch.object(team_serp_adapter, 'is_challenge', return_value=False), \
         patch.object(team_serp_adapter, 'capture_serp_diagnostics', return_value={}), \
         patch.object(team_serp_adapter, 'next_page_url', side_effect=next_url), \
         patch.object(team_serp_adapter, 'RAW_DIR', tmp_path):
        output = team_serp_adapter.collect_once('aviator', depth=2, max_search_depth=10,
                                                 tracked_domain='hollywoodbets.net')
    assert output['status'] == 'ok'
    assert output['stop_reason'] == 'tracked_site_found_with_neighbours'
    assert output['tracked_site']['rank'] == 3
    assert output['tracked_site']['results_below'] == 3
    assert output['pages_completed'] == 3
    assert [r['domain'] for r in output['organic_results']] == [r['domain'] for group in pages for r in group]


def test_collector_stops_when_no_more_pages_without_inventing_site(tmp_path):
    pages = [[row('other.org', 1), row('another.org', 2)]]
    page = FakePage(pages)
    team = SimpleNamespace(search_google=lambda kw: page,
                           extract_organic_results=lambda p: pages[p.index],
                           BROWSER=SimpleNamespace(close=lambda: None))
    with patch.object(team_serp_adapter, 'load_team_module', return_value=team), \
         patch.object(team_serp_adapter, 'is_challenge', return_value=False), \
         patch.object(team_serp_adapter, 'capture_serp_diagnostics', return_value={}), \
         patch.object(team_serp_adapter, 'next_page_url', return_value=(None, 'no_next_page')), \
         patch.object(team_serp_adapter, 'RAW_DIR', tmp_path):
        output = team_serp_adapter.collect_once('aviator', depth=2, max_search_depth=10)
    assert output['status'] == 'partial'
    assert output['tracked_site']['status'] == 'not_found'
    assert output['tracked_site']['rank'] is None
    assert output['stop_reason'] == 'no_next_page'
