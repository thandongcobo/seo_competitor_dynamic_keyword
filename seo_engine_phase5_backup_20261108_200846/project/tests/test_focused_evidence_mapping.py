"""Offline regression tests for evidence lineage in focused recommendations."""
import copy
import json
from pathlib import Path

from llm_foundation.executive_synthesis import build_packet
from llm_foundation.focused_recommendations import task_packet, task_request, validate_task

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'output' / 'results' / 'aviator'


def saved_packet(with_similarity=True):
    canonical = json.loads((BASE / 'llm_foundation' / 'canonical_evidence.json').read_text(encoding='utf-8'))
    if not with_similarity:
        canonical['evidence']['onpage']['comparison'].pop('content_token_jaccard', None)
    specialists = {name: json.loads((BASE / 'llm_outputs' / f'{name}_validated.json').read_text(encoding='utf-8'))
                   for name in ('onpage', 'backlinks', 'technical', 'competition')}
    return build_packet(canonical, specialists)


def sample_onpage(scoped):
    plans = []
    dispositions = []
    for finding in scoped['specialist_findings']:
        fid = finding['id']
        refs = scoped['specialist_fact_links'].get(fid, [])
        if refs:
            index = len(plans)
            plans.append({'title': 'Investigate captured difference',
                          'rationale': 'Measured difference merits checking, without assuming ranking causation.',
                          'owner': 'SEO', 'priority': 'investigate',
                          'implementation_steps': ['Inspect the original evidence for the two selected URLs.',
                                                   'Compare intent and document a justified action before deployment.'],
                          'success_measure': 'Documented evidence review and decision.',
                          'uncertainty': 'Ranking effect and content quality are not established.',
                          'evidence_ids': refs[:1], 'specialist_finding_ids': [fid],
                          'simple_explanation': 'A difference deserves further review.',
                          'technical_explanation': 'Verify the measurement and assess search intent before editing.'})
            outcome, indices = 'action', [index]
        else:
            outcome, indices = 'investigate', []
        dispositions.append({'specialist_finding_id': fid, 'outcome': outcome,
                             'plan_indices': indices, 'evidence_ids': refs[:1],
                             'simple_explanation': 'We will investigate the difference.',
                             'technical_explanation': 'Inspect saved evidence and collect missing supporting measurements.',
                             'next_step': 'Check original data and document any evidence gap.',
                             'reason': 'Only evidence-backed changes can be approved.'})
    return {'schema_version': '1.0', 'task': 'onpage',
            'implementation_plans': plans, 'finding_dispositions': dispositions}


def test_saved_similarity_promoted_only_from_canonical_measurement():
    packet = saved_packet()
    fact = next(x for x in packet['facts'] if x['id'] == 'ON_CONTENT_SIMILARITY')
    assert fact['values']['content_token_jaccard'] == 0.14285714285714285
    scoped = task_packet(packet, 'onpage')
    assert scoped['specialist_fact_links']['ONPAGE_03'] == ['ON_CONTENT_SIMILARITY']
    assert not validate_task(sample_onpage(scoped), scoped, 'onpage')


def test_missing_similarity_is_not_invented_and_can_be_investigated():
    packet = saved_packet(with_similarity=False)
    assert 'ON_CONTENT_SIMILARITY' not in {f['id'] for f in packet['facts']}
    scoped = task_packet(packet, 'onpage')
    assert scoped['specialist_fact_links']['ONPAGE_03'] == []
    result = sample_onpage(scoped)
    row = next(r for r in result['finding_dispositions'] if r['specialist_finding_id'] == 'ONPAGE_03')
    assert row['outcome'] == 'investigate' and row['plan_indices'] == [] and row['evidence_ids'] == []
    assert not validate_task(result, scoped, 'onpage')


def test_unmapped_finding_cannot_be_promoted_using_unrelated_fact():
    scoped = task_packet(saved_packet(with_similarity=False), 'onpage')
    result = sample_onpage(scoped)
    row = next(r for r in result['finding_dispositions'] if r['specialist_finding_id'] == 'ONPAGE_03')
    row.update(outcome='action', plan_indices=[0], evidence_ids=['ON_TITLE'])
    result['implementation_plans'][0]['specialist_finding_ids'].append('ONPAGE_03')
    assert validate_task(result, scoped, 'onpage')


def test_orphan_plan_or_conflicting_disposition_is_rejected():
    scoped = task_packet(saved_packet(), 'onpage')
    result = sample_onpage(scoped)
    row = next(r for r in result['finding_dispositions'] if r['specialist_finding_id'] == 'ONPAGE_03')
    row['outcome'] = 'investigate'
    assert any('investigation or deferred' in e for e in validate_task(result, scoped, 'onpage'))


def test_prompt_explicitly_handles_missing_mappings_and_dynamic_domains():
    packet = saved_packet(with_similarity=False)
    packet['keyword'] = 'arbitrary query'
    packet['tracked']['domain'] = 'alpha.example'
    packet['benchmark']['domain'] = 'beta.example'
    scoped = task_packet(packet, 'onpage')
    system, body = task_request(scoped, 'onpage')
    assert 'arbitrary query' in body and 'alpha.example' in body and 'beta.example' in body
    assert 'If its mapping is empty' in system
    assert 'plan_indices=[]' in system
    assert 'ONPAGE_03' not in system
