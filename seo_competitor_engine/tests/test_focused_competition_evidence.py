"""Regression tests for generic per-keyword competition evidence and focused outputs.

All tests use saved canonical evidence; no network or LLM calls.
"""
import copy
import json
from pathlib import Path

from llm_foundation.executive_synthesis import build_packet
from llm_foundation.focused_recommendations import task_packet, task_request, validate_task, fingerprint

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'output' / 'results' / 'aviator'
TASKS = ('onpage', 'backlinks', 'technical', 'competition')


def saved_packet(canonical=None):
    if canonical is None:
        canonical = json.loads((BASE / 'llm_foundation' / 'canonical_evidence.json').read_text(encoding='utf-8'))
    specialists = {task: json.loads((BASE / 'llm_outputs' / f'{task}_validated.json').read_text(encoding='utf-8'))
                   for task in TASKS}
    return build_packet(canonical, specialists)


def competition_result(scoped, *, unsupported=False):
    plans = [{
        'title': 'Review related-query intent and ranking pages',
        'rationale': 'Saved related-query ranking differences warrant investigation.',
        'owner': 'SEO', 'priority': 'investigate',
        'implementation_steps': [
            'Verify the actual ranking URLs for the saved related queries.',
            'Compare relevant user intent and page content before proposing changes.',
        ],
        'success_measure': 'Ranking URLs verified and intent gaps documented.',
        'uncertainty': 'Domain-level keyword observations do not establish exact-page rankings or causation.',
        'evidence_ids': ['KW_QUERY_GAPS'], 'specialist_finding_ids': ['COMPETITION_02'],
        'simple_explanation': 'Some related searches show a larger ranking gap; check which pages actually rank.',
        'technical_explanation': 'Review historical domain-level query positions and verify the exact ranking URLs.',
    }]
    dispositions = []
    for finding in scoped['specialist_findings']:
        fid = finding['id']
        action = fid == 'COMPETITION_02'
        dispositions.append({
            'specialist_finding_id': fid, 'outcome': 'action' if action else 'investigate',
            'plan_indices': [0] if action else [],
            'simple_explanation': 'Review related keyword ranking evidence.',
            'technical_explanation': 'Compare saved DataForSEO domain rankings and verify exact ranking URLs.',
            'next_step': 'Inspect the ranking URLs and page relevance.',
            'reason': 'Observed rank gaps of 6 and 9 positions need page-level verification.' if action else 'Evidence requires further investigation.',
            'evidence_ids': ['KW_QUERY_GAPS'] if action else scoped['specialist_fact_links'].get(fid, [])[:1],
        })
    if unsupported:
        dispositions[1]['reason'] = 'A rank gap of 999 positions was observed.'
    return {'schema_version': '1.0', 'task': 'competition',
            'implementation_plans': plans, 'finding_dispositions': dispositions}


def test_canonical_rank_gaps_are_approved_without_conflating_aggregate_counts():
    packet = saved_packet()
    facts = {row['id']: row['values'] for row in packet['facts']}
    assert facts['KW_SHARED'] == {'generic_ours_ahead': 24, 'generic_benchmark_ahead': 31}
    rows = facts['KW_QUERY_GAPS']['queries']
    assert any(row['rank_gap'] == 6 and row['our_rank'] == 8 and row['benchmark_rank'] == 2 for row in rows)
    assert any(row['rank_gap'] == 9 and row['our_rank'] == 10 and row['benchmark_rank'] == 1 for row in rows)
    scoped = task_packet(packet, 'competition')
    assert scoped['specialist_fact_links']['COMPETITION_02'] == ['KW_QUERY_GAPS']
    assert scoped['specialist_fact_links']['COMPETITION_03'] == []
    assert not validate_task(competition_result(scoped), scoped, 'competition')


def test_unobserved_rank_gap_still_rejected():
    scoped = task_packet(saved_packet(), 'competition')
    errors = validate_task(competition_result(scoped, unsupported=True), scoped, 'competition')
    assert any('999' in e and 'numeric claim' in e for e in errors)


def test_missing_keyword_rows_are_not_fabricated():
    canonical = json.loads((BASE / 'llm_foundation' / 'canonical_evidence.json').read_text(encoding='utf-8'))
    canonical['evidence']['keywords']['intersection']['top_generic_benchmark_leads'] = []
    packet = saved_packet(canonical)
    assert 'KW_QUERY_GAPS' not in {row['id'] for row in packet['facts']}
    assert task_packet(packet, 'competition')['specialist_fact_links']['COMPETITION_02'] == []


def test_inconsistent_keyword_gap_is_not_approved():
    canonical = json.loads((BASE / 'llm_foundation' / 'canonical_evidence.json').read_text(encoding='utf-8'))
    canonical['evidence']['keywords']['intersection']['top_generic_benchmark_leads'] = [
        {'keyword': 'another topic', 'our_rank': 8, 'benchmark_rank': 2,
         'rank_gap': 99, 'relevance_class': 'relevant_generic'}]
    assert 'KW_QUERY_GAPS' not in {row['id'] for row in saved_packet(canonical)['facts']}


def test_other_keywords_and_domains_are_not_hardcoded():
    canonical = json.loads((BASE / 'llm_foundation' / 'canonical_evidence.json').read_text(encoding='utf-8'))
    canonical['investigation']['keyword'] = 'example topic'
    canonical['tracked_website'].update(domain='alpha.example', ranking_url='https://alpha.example/a')
    canonical['competitors'][0].update(domain='beta.example', ranking_url='https://beta.example/b')
    canonical['evidence']['keywords']['intersection']['top_generic_benchmark_leads'] = [
        {'keyword': 'example topic guide', 'our_rank': 7, 'benchmark_rank': 3,
         'rank_gap': 4, 'search_volume': 42, 'relevance_class': 'relevant_generic'}]
    packet = saved_packet(canonical)
    scoped = task_packet(packet, 'competition')
    assert scoped['facts'][-1]['values']['queries'][0]['rank_gap'] == 4
    system, body = task_request(scoped, 'competition')
    assert 'KW_QUERY_GAPS' in system
    assert 'alpha.example' in body and 'beta.example' in body
    assert 'example topic guide' in body


def test_other_three_tasks_keep_previous_prompt_fingerprint():
    packet = saved_packet()
    # The new competition-only facts must not alter scoped packets or prompts for
    # previously validated on-page, backlinks, or technical outputs.
    for task in ('onpage', 'backlinks', 'technical'):
        scoped = task_packet(packet, task)
        system, _ = task_request(scoped, task)
        assert 'KW_QUERY_GAPS' not in system
        assert 'KW_QUERY_GAPS' not in json.dumps(scoped)
        assert fingerprint(scoped, task, 'local-model') == fingerprint(copy.deepcopy(scoped), task, 'local-model')
