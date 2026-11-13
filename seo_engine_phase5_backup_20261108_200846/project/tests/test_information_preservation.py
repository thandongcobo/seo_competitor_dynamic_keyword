"""Preserve original specialist findings without promoting speculation into facts."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

from llm_foundation.information_preservation import specialist_records, build_preservation_report, validate_plans
from llm_foundation.executive_synthesis import build_packet, build_prompt, infer, parse_response, validate_executive
from llm_foundation.structured_facts import publish_verified_response

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'output/results/aviator'
TASKS = ('onpage','backlinks','technical','competition')


def saved():
    canonical = json.loads((SOURCE/'llm_foundation/canonical_evidence.json').read_text(encoding='utf-8'))
    specialists = {task: json.loads((SOURCE/'llm_outputs'/f'{task}_validated.json').read_text(encoding='utf-8')) for task in TASKS}
    return canonical, specialists


def test_all_real_aviator_specialist_findings_retained():
    canonical, specialists = saved()
    packet = build_packet(canonical, specialists)
    assert len(packet['specialist_findings']) == sum(len(s['findings']) for s in specialists.values()) == 11
    assert len(packet['facts']) == 10  # Includes lexical similarity and verified per-query rank gaps.
    for row in packet['specialist_findings']:
        assert row['finding'] == specialists[row['task']]['findings'][int(row['id'].split('_')[-1])-1]
    _, prompt, tokens = build_prompt(packet, 'Evidence only', 'Generate detailed plans')
    assert tokens > 0 and 'recommended_action' in prompt and 'implementation_plans' in prompt
    historical = json.loads((SOURCE/'llm_outputs/executive_model_raw.json').read_text(encoding='utf-8'))
    raw = parse_response(historical['raw_response'])
    published, _ = publish_verified_response(raw, packet)
    report = build_preservation_report(specialists, published)
    assert report['all_original_findings_preserved']
    assert report['missing_or_changed_ids'] == []
    assert published['executive_summary'] == raw['executive_summary']
    assert published['key_findings'] == raw['key_findings']
    assert published['proposed_decisions'] == raw['proposed_decisions']
    assert not published['implementation_plans']  # historical model did not generate plans


def test_plan_references_and_steps_must_be_valid():
    canonical, specialists = saved()
    packet = build_packet(canonical, specialists)
    plan = {'title':'Review Aviator title', 'rationale':'Title difference warrants investigation',
            'owner':'SEO', 'priority':'investigate',
            'implementation_steps':['Verify current rendered title', 'Draft accurate title for review'],
            'success_measure':'Approved title appears in HTML after deployment',
            'uncertainty':'No ranking lift can be guaranteed',
            'evidence_ids':['ON_TITLE'], 'specialist_finding_ids':['ONPAGE_01']}
    assert not validate_plans([plan], packet)
    assert validate_plans([{**plan,'specialist_finding_ids':['FAKE']}],packet)
    assert validate_plans([{**plan,'evidence_ids':['FAKE']}],packet)
    assert validate_plans([{**plan,'implementation_steps':[]}],packet)


def test_inference_preserves_validated_model_text():
    canonical, specialists = saved()
    packet = build_packet(canonical, specialists)
    obj = json.loads((SOURCE/'llm_outputs/executive_model_raw.json').read_text(encoding='utf-8'))
    class Client:
        chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=obj['raw_response']),finish_reason='stop')])))
    result, meta = infer(packet,Client(),'saved-fixture','Short skills','Short instructions',attempts=1)
    original=parse_response(obj['raw_response'])
    assert result['executive_summary']==original['executive_summary']
    assert result['key_findings']==original['key_findings']
    assert len(result['specialist_findings'])==11
    assert meta['status']=='validated'


def test_detailed_implementation_plan_survives_publication():
    canonical, specialists = saved()
    packet = build_packet(canonical, specialists)
    raw = parse_response(json.loads((SOURCE/'llm_outputs/executive_model_raw.json').read_text())['raw_response'])
    raw['implementation_plans'] = [{
        'title':'Review page title for Aviator relevance',
        'rationale':'Saved title keyword presence differs between the exact ranking pages.',
        'owner':'SEO and Content', 'priority':'investigate',
        'implementation_steps':['Inspect current title and canonical URL.',
                                'Draft an accurate keyword-specific title for approval.',
                                'Deploy approved metadata and verify the rendered page.'],
        'success_measure':'Approved title verified in rendered HTML; monitor relevant query CTR.',
        'uncertainty':'Ranking effect is not established by the saved comparison.',
        'evidence_ids':['ON_TITLE'], 'specialist_finding_ids':['ONPAGE_01']}
    ]
    assert not validate_executive(raw, packet)
    published, _ = publish_verified_response(raw, packet)
    assert published['implementation_plans'] == raw['implementation_plans']
    report = build_preservation_report(specialists, published)
    assert report['implementation_plan_count'] == 1
    assert 'ONPAGE_01' in report['findings_referenced_by_implementation_plans']
