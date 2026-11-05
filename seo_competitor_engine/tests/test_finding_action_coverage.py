"""Offline tests: coverage, two-audience explanations and domain independence."""
import copy
import json
from pathlib import Path

from llm_foundation.action_coverage import validate_action_coverage
from llm_foundation.executive_synthesis import build_packet, build_prompt, validate_executive
from llm_foundation.information_preservation import build_preservation_report
from llm_foundation.structured_facts import publish_verified_response

ROOT = Path(__file__).resolve().parents[1] / 'output' / 'results' / 'aviator'


def evidence():
    canonical = json.loads((ROOT / 'llm_foundation' / 'canonical_evidence.json').read_text())
    specialists = {task: json.loads((ROOT / 'llm_outputs' / f'{task}_validated.json').read_text())
                   for task in ('onpage', 'backlinks', 'technical', 'competition')}
    packet = build_packet(canonical, specialists)
    packet['require_action_coverage'] = True
    return packet, specialists


def complete_response(packet):
    # Synthetic test response only; all factual references come from saved real evidence.
    plan = {'title': 'Review page metadata', 'rationale': 'The captured page titles differ.',
            'owner': 'SEO', 'priority': 'investigate',
            'implementation_steps': ['Confirm the title tags on both exact ranking pages.',
                                     'Prepare a title proposal for review before deployment.'],
            'success_measure': 'Verify the approved title in rendered HTML.',
            'uncertainty': 'The ranking effect is not established.',
            'evidence_ids': ['ON_TITLE'], 'specialist_finding_ids': ['ONPAGE_01'],
            'simple_explanation': 'The pages describe their topic differently in search. Check which title is clearer for visitors.',
            'technical_explanation': 'Inspect rendered title elements and search-result appearance for the selected ranking URLs.'}
    rows = []
    for finding in packet['specialist_findings']:
        fid = finding['id']
        action = fid == 'ONPAGE_01'
        linked = packet['specialist_fact_links'].get(fid) or []
        rows.append({'specialist_finding_id': fid, 'outcome': 'action' if action else 'investigate',
                     'plan_indices': [0] if action else [],
                     'simple_explanation': 'This is a possible competitive difference, but it is not proof of a ranking cause.',
                     'technical_explanation': 'Review the cited source evidence and confirm page-specific relevance before changing implementation.',
                     'next_step': 'Inspect the cited evidence and document whether a change is justified.',
                     'reason': 'Supported metadata difference.' if action else 'Further verification is needed.',
                     'evidence_ids': ['ON_TITLE'] if action else linked})
    return {'schema_version': '1.0', 'status': 'usable', 'executive_summary': 'Review the captured title.',
            'executive_summary_evidence_ids': ['ON_TITLE'], 'key_findings': [],
            'proposed_decisions': [], 'limitations': [], 'implementation_plans': [plan],
            'finding_dispositions': rows}


def test_all_specialists_have_a_disposition_and_two_audience_explanations():
    packet, specialists = evidence()
    response = complete_response(packet)
    assert validate_executive(response, packet) == []
    published, _ = publish_verified_response(response, packet)
    report = build_preservation_report(specialists, published)
    assert report['all_original_findings_preserved']
    assert report['findings_without_disposition'] == []
    assert report['finding_action_coverage']['accounted_for'] == 11
    assert len(published['implementation_plans'][0]['simple_explanation']) > 30
    assert len(published['implementation_plans'][0]['technical_explanation']) > 30


def test_missing_finding_fails_coverage():
    packet, _ = evidence()
    response = complete_response(packet)
    response['finding_dispositions'].pop()
    assert any('missing specialist findings' in x for x in validate_executive(response, packet))


def test_action_without_linked_plan_rejected():
    packet, _ = evidence()
    response = complete_response(packet)
    response['finding_dispositions'][0]['plan_indices'] = []
    assert any('must link to an implementation plan' in x for x in validate_executive(response, packet))


def test_unsupported_fact_reference_rejected():
    packet, _ = evidence()
    response = complete_response(packet)
    response['finding_dispositions'][0]['evidence_ids'] = ['BL_DOMAIN']
    assert any('not linked to specialist finding' in x for x in validate_executive(response, packet))


def test_nontechnical_and_technical_plan_explanations_required():
    packet, _ = evidence()
    response = complete_response(packet)
    response['implementation_plans'][0].pop('simple_explanation')
    assert any('missing simple_explanation' in x for x in validate_executive(response, packet))


def test_other_keyword_domains_no_hardcoded_coverage():
    packet, _ = evidence()
    packet['keyword'] = 'different search term'
    packet['tracked']['domain'] = 'first.example'
    packet['benchmark']['domain'] = 'second.example'
    _, prompt, _ = build_prompt(packet, 'skills', 'instructions')
    assert 'different search term' in prompt
    assert 'first.example' in prompt and 'second.example' in prompt
    assert 'finding_dispositions' in prompt
    assert 'simple_explanation' in prompt and 'technical_explanation' in prompt
    assert validate_action_coverage(complete_response(packet), packet) == []


def test_targeted_repair_adds_coverage_without_discarding_plans():
    from types import SimpleNamespace
    from llm_foundation.executive_synthesis import infer
    packet, _ = evidence()
    complete = complete_response(packet)
    first = copy.deepcopy(complete)
    first.pop('finding_dispositions')
    first['implementation_plans'][0].pop('simple_explanation')
    first['implementation_plans'][0].pop('technical_explanation')
    plan_patch = copy.deepcopy(complete['implementation_plans'][0])
    patch = {'repairs': [
        {'path': 'finding_dispositions', 'value': complete['finding_dispositions']},
        {'path': 'implementation_plans[0]', 'value': plan_patch},
    ]}
    responses = [json.dumps(first), json.dumps(patch)]
    def create(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=responses.pop(0)), finish_reason='stop')])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    result, meta = infer(packet, client, 'offline-fixture', 'skills', 'instructions', attempts=2)
    assert meta['attempts'] == 2
    assert len(result['finding_dispositions']) == 11
    assert len(result['implementation_plans']) == 1
    assert json.loads(meta['raw_response']) == first
    assert set(meta['repair_audit']['changed_paths']) == {'finding_dispositions', 'implementation_plans[0]'}
