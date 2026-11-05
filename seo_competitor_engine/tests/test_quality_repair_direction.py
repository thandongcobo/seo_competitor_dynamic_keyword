"""Regression tests for scoped internal-link repair instructions and retries."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

from llm_foundation.quality_repair import repair_request, repair_with_client, evidence_errors
from llm_foundation.recommendation_quality import audit_recommendations

ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / 'tests/fixtures/recommendation_quality_saved_output.json'
PACKET = ROOT / 'tests/fixtures/quality_repair_evidence_packet.json'


def load():
    return json.loads(RESULT.read_text(encoding='utf-8')), json.loads(PACKET.read_text(encoding='utf-8'))


class FakeCompletions:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(next(self.responses))), finish_reason='stop')])


class FakeClient:
    def __init__(self, responses):
        self.completions = FakeCompletions(responses)
        self.chat = SimpleNamespace(completions=self.completions)


def test_internal_link_repair_prompt_identifies_offending_fields_and_scope():
    result, packet = load()
    issues = [i for i in audit_recommendations(result)['issues']
              if i['path'] == 'implementation_plans[1]']
    system, body = repair_request(result, packet, 'implementation_plans[1]', issues)
    context = json.loads(body)
    fields = {d['field'] for d in context['field_diagnostics']}
    assert 'rationale' in fields or 'technical_explanation' in fields or 'implementation_steps[1]' in fields
    assert any('outgoing' in x.lower() and 'incoming' in x.lower()
               for x in context['issue_specific_instructions'])
    assert 'every editable field' in system.lower()
    assert context['approved_facts_cited_by_target']


def test_prompt_is_keyword_and_domain_independent():
    result, packet = load()
    packet = copy.deepcopy(packet)
    packet['keyword'] = 'example query'
    packet['tracked'] = {'domain': 'alpha.example', 'url': 'https://alpha.example/page'}
    packet['benchmark'] = {'domain': 'beta.example', 'url': 'https://beta.example/page'}
    issues = [i for i in audit_recommendations(result)['issues']
              if i['path'] == 'implementation_plans[1]']
    system, body = repair_request(result, packet, 'implementation_plans[1]', issues)
    assert json.loads(body)['keyword'] == 'example query'
    assert 'aviator' not in system.lower()
    assert 'hollywoodbets' not in system.lower()


def test_repair_retry_explains_remaining_fields_and_preserves_other_objects():
    result, packet = load()
    original = copy.deepcopy(result)
    # First response changes the rationale but leaves the problematic success measure
    # and technical explanation in place. It must be rejected, not published.
    partial = {'fields': {'rationale': 'The observed numbers describe outgoing navigation links only.'}}
    complete = {'fields': {
        'rationale': 'The captured pages have different outgoing navigation-link counts; investigate link usefulness, not authority.',
        'technical_explanation': 'The recorded 9 versus 28 values count links on each page, not inbound links. Review link destinations, anchors, and user relevance; collect separate incoming-link data if needed.',
        'implementation_steps': [
            'Audit outgoing link destinations, placement and anchor text on both pages.',
            'Separately investigate internal pages that might link to the tracked page if an inbound audit is justified.',
            'Add only useful contextual navigation after checking user intent and site structure.',
            'Verify all changed links and crawlability after deployment.'
        ],
        'success_measure': 'Verify improved navigation and working links, not an unmeasured ranking benefit.',
        'simple_explanation': 'The competitor page has more navigation links. Review whether our visitors need more useful links; the counts do not prove a ranking advantage.'
    }}
    backlink = {'fields': {'rationale': 'The benchmark has more page-level links. Investigate their quality and relevance; matching the count is not a proven ranking requirement.'}}
    competition = {'fields': {'rationale': 'The historical query gaps justify investigating the exact ranking URLs and user intent, not assuming that existing content lacks quality.'}}
    client = FakeClient([partial, complete, backlink, competition])
    events = []
    fixed, audit = repair_with_client(result, packet, client, 'mock-model', attempts=2, on_event=events.append)
    assert audit['all_blocking_resolved'] is True
    assert audit['after']['blocking_count'] == 0
    assert len(client.completions.calls) == 4
    assert 'still_flagged_fields' in client.completions.calls[1]['messages'][1]['content']
    assert any(e['kind'] == 'rejected' for e in events)
    assert evidence_errors(fixed, packet) == []
    assert result == original
    assert fixed['specialist_findings'] == original['specialist_findings']
    assert fixed['finding_dispositions'] == original['finding_dispositions']
    for i in (0, 3, 4, 5):
        assert fixed['implementation_plans'][i] == original['implementation_plans'][i]
