import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_foundation.quality_repair import (apply_patch, flagged_targets, repair_with_client,
                                           evidence_errors, quality_fingerprint)
from llm_foundation.recommendation_quality import audit_recommendations
from scripts.repair_recommendation_quality import run

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/recommendation_quality_saved_output.json'
PACKET = ROOT / 'tests/fixtures/quality_repair_evidence_packet.json'


def evidence():
    return json.loads(PACKET.read_text(encoding='utf-8'))


def result():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


class FakeCompletions:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        raw = next(self.responses)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(raw)), finish_reason='stop')])


class FakeClient:
    def __init__(self, responses):
        self.completions = FakeCompletions(responses)
        self.chat = SimpleNamespace(completions=self.completions)


def test_original_fixture_is_valid_but_quality_flagged():
    r, p = result(), evidence()
    assert evidence_errors(r, p) == []
    report = audit_recommendations(r, expected_findings=[f['id'] for f in p['specialist_findings']])
    assert report['blocking_count'] == 5
    assert set(flagged_targets(report)) == {'implementation_plans[1]', 'implementation_plans[2]',
                                            'implementation_plans[5]', 'implementation_plans[6]'}


def test_patch_is_strict_and_does_not_mutate_original():
    r = result()
    old = copy.deepcopy(r)
    for fields in ({'evidence_ids': []}, {'specialist_finding_ids': []}, {'implementation_steps': []}):
        with pytest.raises(ValueError):
            apply_patch(r, 'implementation_plans[1]', {'fields': fields})
    with pytest.raises(ValueError):
        apply_patch(r, 'implementation_plans[1]', {'fields': {'rationale': ''}})
    with pytest.raises(ValueError):
        apply_patch(r, 'implementation_plans[1]', {'other': {}})
    assert r == old


def test_blocking_repair_preserves_every_plan_and_finding():
    r, p = result(), evidence()
    before = copy.deepcopy(r)
    patches = [
        {'fields': {
            'rationale': 'The benchmark page has more outgoing internal links. Inspect whether these links help users navigate and separately assess the tracked page inbound link profile.',
            'technical_explanation': 'The tracked page has 9 outgoing internal links versus 28 on the benchmark page. These are not inbound-link measurements. Audit destinations and contextual relevance, and separately evaluate the inbound internal-link graph.',
            'implementation_steps': [
                'Audit the benchmark page outgoing link destinations and placement before making changes.',
                'Separately identify relevant internal pages that could link to the tracked landing page.',
                'Add only useful contextual links after review of navigation and site architecture.',
                'Verify link targets, anchor text and crawlability after deployment.'
            ],
            'success_measure': 'Verify that approved links work and relevant pages are discoverable; do not infer ranking impact from a raw count.',
            'simple_explanation': 'The competitor page has more navigation links. We should check whether any useful navigation improvements are appropriate, without assuming more links means better rankings.'
        }},
        {'fields': {'rationale': 'The benchmark page has more page-level backlinks and referring domains. This warrants investigation of relevant link opportunities; closing a numerical gap is not proven necessary for rankings.'}},
        {'fields': {'rationale': 'Saved domain-level rankings show gaps for instructional queries. Investigate the exact ranking URLs and search intent before deciding whether additional content is warranted.'}}
    ]
    client = FakeClient(patches)
    fixed, audit = repair_with_client(r, p, client, 'mock-model')
    assert audit['before']['blocking_count'] == 3
    assert audit['after']['blocking_count'] == 0
    assert len(client.completions.calls) == 3
    assert evidence_errors(fixed, p) == []
    assert len(fixed['implementation_plans']) == len(before['implementation_plans']) == 7
    assert fixed['specialist_findings'] == before['specialist_findings']
    assert fixed['finding_dispositions'] == before['finding_dispositions']
    for idx in (0, 3, 4, 5):
        assert fixed['implementation_plans'][idx] == before['implementation_plans'][idx]
    assert r == before


def test_rejected_patch_keeps_original_and_records_failure():
    r, p = result(), evidence()
    client = FakeClient([{'fields': {'evidence_ids': []}} for _ in range(3)])
    fixed, audit = repair_with_client(r, p, client, 'mock-model', attempts=1)
    assert fixed == r
    assert audit['after']['blocking_count'] == 3
    assert any(x.get('status') == 'unresolved' for x in audit['repairs'])


def test_preview_does_not_connect_to_model(tmp_path):
    args = SimpleNamespace(input=FIXTURE, packet=PACKET, output_dir=tmp_path,
                           include_review=False, execute=False)
    report = run(args)
    assert report['blocking_count'] == 3
    assert (tmp_path / 'quality_repair_preview.json').exists()
    assert not (tmp_path / 'executive_quality_repaired.json').exists()


def test_fingerprint_depends_on_model_and_input():
    r, p = result(), evidence()
    a = quality_fingerprint(r, p, 'model-a', False)
    assert a != quality_fingerprint(r, p, 'model-b', False)
    assert a != quality_fingerprint(r, p, 'model-a', True)
