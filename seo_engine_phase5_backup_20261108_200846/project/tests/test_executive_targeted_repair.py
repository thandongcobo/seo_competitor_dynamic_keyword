"""Offline tests: preserve original Gemma response, repair only invalid fields."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from llm_foundation.executive_synthesis import (
    build_packet, infer, parse_response, validate_executive, _repair_locations,
    _apply_repair_patch, ExecutiveSynthesisError,
)

ROOT = Path(__file__).resolve().parents[1]


def evidence():
    root = ROOT / 'output/results/aviator'
    canonical = json.loads((root / 'llm_foundation/canonical_evidence.json').read_text(encoding='utf-8'))
    specialists = {task: json.loads((root / 'llm_outputs' / (task + '_validated.json')).read_text(encoding='utf-8'))
                   for task in ('onpage', 'backlinks', 'technical', 'competition')}
    return build_packet(canonical, specialists)


def responses():
    source = Path(__file__).parent / 'fixtures' / 'executive_targeted_repair_raw.json'
    return [parse_response(row['raw_response']) for row in json.loads(source.read_text(encoding='utf-8'))['attempts']]


def fake_client(outputs):
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=outputs.pop(0)),finish_reason='stop')])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), calls


def test_actual_first_response_localizes_two_invalid_sections():
    packet = evidence()
    first = responses()[0]
    errors = validate_executive(first, packet)
    assert errors
    assert set(_repair_locations(errors, first)) == {'executive_summary', 'implementation_plans[1]'}


def test_actual_second_response_localizes_citation_problem():
    packet = evidence()
    second = responses()[1]
    errors = validate_executive(second, packet)
    assert errors
    assert _repair_locations(errors, second) == ['key_findings[4].why_it_matters']


def test_first_response_targeted_repair_preserves_all_other_findings_and_plans():
    packet = evidence()
    first = responses()[0]
    replacement = copy.deepcopy(first['implementation_plans'][1])
    replacement['rationale'] = replacement['rationale'].replace('internal link density','internal link count')
    replacement['implementation_steps'] = [x.replace('link density','relevant internal links') for x in replacement['implementation_steps']]
    patch = {'repairs': [
        {'path':'executive_summary','value':first['executive_summary'].replace('internal link density','internal link count')},
        {'path':'implementation_plans[1]','value':replacement},
    ]}
    corrected = _apply_repair_patch(first, patch, _repair_locations(validate_executive(first,packet), first))
    assert validate_executive(corrected, packet) == []
    assert corrected['key_findings'] == first['key_findings']
    assert corrected['implementation_plans'][0] == first['implementation_plans'][0]
    assert len(corrected['implementation_plans']) == len(first['implementation_plans'])


def test_infer_uses_patch_instead_of_regenerating_full_response():
    packet = evidence()
    original = responses()[1]
    new_text = 'Compare page-level backlink quality and verify whether the difference is relevant to the selected keyword.'
    patch = {'repairs':[{'path':'key_findings[4].why_it_matters','value':new_text}]}
    client, calls = fake_client([json.dumps(original), json.dumps(patch)])
    published, meta = infer(packet,client,'offline-test','skills','instructions',attempts=2)
    assert len(calls) == 2
    assert 'ALLOWED_PATHS' in calls[1]['messages'][1]['content']
    assert 'key_findings[4].why_it_matters' in calls[1]['messages'][1]['content']
    assert len(published['key_findings']) == len(original['key_findings'])
    assert published['key_findings'][0] == original['key_findings'][0]
    assert published['implementation_plans'] == original['implementation_plans']
    assert published['key_findings'][4]['why_it_matters'] == new_text
    assert meta['repair_audit']['changed_paths'] == ['key_findings[4].why_it_matters']
    assert json.loads(meta['validated_response_json'])['key_findings'][4]['why_it_matters'] == new_text
    assert json.loads(meta['raw_response']) == original
    assert json.loads(meta['original_raw_response']) == original


def test_unapproved_patch_rejected_without_mutating_original():
    original = responses()[1]
    frozen = copy.deepcopy(original)
    with pytest.raises(ValueError,match='unapproved'):
        _apply_repair_patch(original, {'repairs':[{'path':'proposed_decisions[0]','value':original['proposed_decisions'][0]}]}, ['key_findings[4].why_it_matters'])
    assert original == frozen


def test_whole_response_replacement_rejected():
    original = responses()[1]
    with pytest.raises(ValueError,match='only a repairs array'):
        _apply_repair_patch(original, original, ['key_findings[4].why_it_matters'])


def test_repair_must_not_delete_plan_or_change_structure():
    original = responses()[0]
    patch = {'repairs':[{'path':'implementation_plans[1]','value':{'title':'New'}}]}
    with pytest.raises(ValueError,match='changed object fields'):
        _apply_repair_patch(original,patch,['implementation_plans[1]'])


def test_invalid_patch_fails_closed_and_keeps_raw_responses():
    packet = evidence()
    original = responses()[1]
    client, calls = fake_client([json.dumps(original),json.dumps({'repairs':[{'path':'executive_summary','value':'changed'}]})])
    with pytest.raises(ExecutiveSynthesisError) as error:
        infer(packet,client,'offline-test','skills','instructions',attempts=2)
    assert len(error.value.raw_responses) == 2
    assert error.value.raw_responses[0]['kind'] == 'initial'
    assert error.value.raw_responses[1]['kind'] == 'targeted_repair'


def test_other_keyword_and_domains_no_hardcoded_repair_targets():
    packet = evidence()
    packet['keyword'] = 'online slots'
    packet['tracked']['domain'] = 'sample-one.example'
    packet['benchmark']['domain'] = 'sample-two.example'
    packet['tracked']['url'] = 'https://sample-one.example/slots'
    packet['benchmark']['url'] = 'https://sample-two.example/slots'
    result = responses()[1]
    errors = validate_executive(result,packet)
    assert _repair_locations(errors,result) == ['key_findings[4].why_it_matters']


def test_full_repair_of_first_real_response_retains_two_plans():
    packet = evidence()
    original = responses()[0]
    replacement = copy.deepcopy(original['implementation_plans'][1])
    replacement['rationale'] = replacement['rationale'].replace('internal link density', 'internal link count')
    replacement['implementation_steps'] = [s.replace('link density', 'relevant internal links') for s in replacement['implementation_steps']]
    patch = {'repairs': [
        {'path': 'executive_summary', 'value': original['executive_summary'].replace('internal link density', 'internal link count')},
        {'path': 'implementation_plans[1]', 'value': replacement},
    ]}
    client, calls = fake_client([json.dumps(original), json.dumps(patch)])
    published, meta = infer(packet, client, 'offline-test', 'skills', 'instructions', attempts=2)
    assert len(calls) == 2
    assert len(published['implementation_plans']) == 2
    assert published['implementation_plans'][0] == original['implementation_plans'][0]
    assert published['key_findings'] == original['key_findings']
    assert meta['repair_audit']['changed_paths'] == ['executive_summary', 'implementation_plans[1]']


def test_published_explanations_use_selected_keyword_and_domains():
    packet = evidence()
    packet['keyword'] = 'online slots'
    packet['tracked']['domain'] = 'sample-one.example'
    packet['benchmark']['domain'] = 'sample-two.example'
    from llm_foundation.structured_facts import publish_verified_response
    validated = responses()[1]
    # The example response is not fully validated; this checks only that the
    # supplementary publisher derives names and keyword from the packet.
    published, _ = publish_verified_response(validated, packet)
    combined = json.dumps(published['verified_factual_findings'] + published['recommended_improvements'] + published['potential_ranking_explanations'])
    assert 'online slots' in combined
    assert 'sample-one.example' in combined or 'sample-two.example' in combined
    assert 'Aviator targeting' not in combined
    assert 'Hollywoodbets has' not in combined
