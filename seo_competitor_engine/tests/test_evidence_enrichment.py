"""Offline checks for bounded, provenance-bearing specialist evidence."""
import copy
import json
from pathlib import Path

from llm_foundation.enrichment import enrich_comparison
from llm_foundation.executive_synthesis import build_packet
from llm_foundation.focused_recommendations import TASK_FACTS, task_packet
from llm_foundation.foundation import canonicalize
from normalization.pages import normalize_page

ROOT = Path(__file__).resolve().parents[1]
TASKS = ('onpage', 'backlinks', 'technical', 'competition')


def saved_aviator():
    base = ROOT / 'output/results/aviator'
    comparison = json.loads((base / 'aviator_comparison.json').read_text(encoding='utf-8'))
    canonical = canonicalize(comparison)
    canonical['enriched_evidence'] = enrich_comparison(comparison, base / 'aviator_comparison.json')
    specialists = {task: json.loads((base / 'llm_outputs' / f'{task}_validated.json').read_text(encoding='utf-8'))
                   for task in TASKS}
    return canonical, specialists


def test_normalizer_preserves_qualitative_page_source_fields():
    raw = json.loads((ROOT / 'data/raw/pages/aviator_google_ours.json').read_text(encoding='utf-8'))
    normalized = normalize_page(raw)
    assert normalized['seo_content_text']
    assert normalized['internal_links']
    assert normalized['structured_data_blocks'] == raw['structured_data_blocks']
    assert normalized['canonical'] == raw['canonical']
    assert normalized['robots'] == raw['robots']


def test_saved_aviator_evidence_reaches_the_matching_focused_specialist():
    canonical, specialists = saved_aviator()
    packet = build_packet(canonical, specialists)
    assert len(packet['specialist_findings']) == 11
    for task in TASKS:
        scoped = task_packet(packet, task)
        enriched = [fact for fact in scoped['facts'] if fact['id'].startswith('ENR_')]
        assert enriched
        assert all(fact['keyword'] == 'aviator' for fact in enriched)
        assert all(fact['page'].get('selected_pages') or fact['page'].get('url') for fact in enriched)
        assert all(fact['provenance']['source_path'] and fact['provenance']['source_sha256'] for fact in enriched)
        assert all(len(json.dumps(fact, ensure_ascii=False)) < 12000 for fact in enriched)
    onpage = task_packet(packet, 'onpage')
    kinds = {fact['statement'].removeprefix('Saved ').split(' observation')[0]
             for fact in onpage['facts'] if fact['id'].startswith('ENR_')}
    assert {'rendered_heading_inventory', 'keyword_relevant_visible_passages',
            'outgoing_internal_link_inventory', 'structured_data_inventory'} <= kinds
    outgoing = next(f for f in onpage['facts'] if f['id'].startswith('ENR_') and
                    'outgoing_internal_link_inventory' in f['statement'])
    assert 'anchor text' in ' '.join(outgoing['limitations'])
    for finding in packet['specialist_findings']:
        task = finding['task']
        refs = packet['specialist_fact_links'][finding['id']]
        assert set(refs).issubset(set(TASK_FACTS[task]) | {'SERP'} | set(packet['enriched_fact_ids'][task]))


def test_enrichment_is_bounded_and_does_not_invent_links_or_topics(tmp_path):
    keyword = 'modular rainwater systems'
    urls = {'ours': 'https://alpha.example/solutions/rainwater',
            'benchmark': 'https://beta.example/guides/rainwater'}
    pages = {}
    for side, url in urls.items():
        pages[side] = {
            'requested_url': url, 'final_url': url, 'ranking_url': url,
            'seo_content_status': 'candidate', 'seo_content_method': 'rendered-main-innertext-v2',
            'seo_content_word_count': 8, 'seo_content_text': 'Modular rainwater systems collect and filter roof runoff. Storage tanks support garden irrigation.',
            'headings': {'h1': ['Modular rainwater systems'], 'h2': ['Collection and filtration']},
            'internal_links': [url.rsplit('/', 1)[0] + '/maintenance'],
            'structured_data_blocks': ['{"@type":"Article","headline":"Rainwater systems"}'],
            'robots': 'index,follow', 'url_alignment': 'matched', 'extraction_status': 'complete'}
    source = {'keyword': keyword, 'primary_ranking_urls': urls,
              'page_level_evidence': pages,
              'ranking_summary': {'google': {'our_position': 4, 'benchmark_position': 2,
                   'ranking_neighborhood': {'target': {'url': urls['ours'], 'title': 'Modular rainwater systems'},
                                            'above': [], 'below': []}}},
              'advanced_evidence': {'keyword_intersection': {'items': [
                  {'keyword': 'modular rainwater systems', 'our_rank': 4, 'benchmark_rank': 2,
                   'rank_gap': 2, 'search_volume': 10}]}}}
    enriched = enrich_comparison(source, tmp_path / 'generic_comparison.json')
    records = enriched['onpage']
    assert records and all(row['keyword'] == keyword for row in records)
    assert all(row['page'].get('url') in set(urls.values()) or row['page'].get('selected_pages') for row in records)
    links = next(row for row in records if row['metric_or_observation'] == 'outgoing_internal_link_inventory')
    assert links['value'][0]['direction'] == 'outgoing_from_selected_page'
    assert not any('incoming' in json.dumps(row['value']).lower() for row in records)
    assert len(json.dumps(enriched, ensure_ascii=False)) < 50000
    assert len(enriched['competition'][0]['value']) == 1


def test_enrichment_does_not_overwrite_existing_specialist_interpretations():
    canonical, specialists = saved_aviator()
    before = copy.deepcopy(specialists)
    packet = build_packet(canonical, specialists)
    assert packet['specialist_findings']
    assert specialists == before


def test_no_matching_saved_page_does_not_attach_other_keyword_or_url():
    synthetic = {'keyword': 'unseen topic',
                 'primary_ranking_urls': {'ours': 'https://alpha.example/a', 'benchmark': 'https://beta.example/b'},
                 'page_level_evidence': {'ours': {'keyword': 'unseen topic', 'ranking_url': 'https://alpha.example/a',
                     'final_url': 'https://alpha.example/a', 'extraction_status': 'incomplete'},
                     'benchmark': {'keyword': 'unseen topic', 'ranking_url': 'https://beta.example/b',
                     'final_url': 'https://beta.example/b', 'extraction_status': 'incomplete'}},
                 'ranking_summary': {'google': {'our_position': 1, 'benchmark_position': 2}},
                 'advanced_evidence': {}}
    result = enrich_comparison(synthetic, ROOT / 'output/results/aviator/not_saved.json')
    assert result['onpage'] == []


def test_relative_raw_data_root_keeps_valid_source_lineage(tmp_path, monkeypatch):
    keyword = 'modular rainwater systems'
    url = 'https://alpha.example/rainwater'
    raw_root = tmp_path / 'data' / 'raw'
    (raw_root / 'pages').mkdir(parents=True)
    raw = {'keyword': keyword, 'requested_url': url, 'final_url': url,
           'extraction_status': 'complete', 'internal_links': [url + '/maintenance']}
    (raw_root / 'pages' / 'page.json').write_text(json.dumps(raw), encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    source = {'keyword': keyword, 'primary_ranking_urls': {'ours': url},
              'page_level_evidence': {'ours': {'keyword': keyword, 'ranking_url': url,
                  'requested_url': url, 'final_url': url, 'extraction_status': 'complete',
                  'seo_content_status': 'candidate', 'seo_content_text': 'Rainwater storage and filtration.',
                  'headings': {'h1': ['Rainwater storage']}}},
              'ranking_summary': {}, 'advanced_evidence': {}}
    evidence = enrich_comparison(source, 'output/comparison.json', raw_data_root=Path('data/raw'))
    link_record = next(row for row in evidence['onpage']
                       if row['metric_or_observation'] == 'outgoing_internal_link_inventory')
    assert link_record['provenance']['source_path'].endswith('page.json')
