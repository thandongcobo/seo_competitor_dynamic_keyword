"""Offline regressions for shared numeric/citation correction; no network or LLM."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

from llm_foundation.grounded_retry import diagnose_errors, repair_unambiguous_citations
from llm_foundation.focused_recommendations import task_packet, validate_task
from scripts.run_llm_focused_recommendations import generate_task, _retry_guidance


def fixture():
    packet = {
        'schema_version': '1.0', 'keyword': 'sample search', 'market': 'Example',
        'search_engine': 'google',
        'tracked': {'domain': 'alpha.example', 'url': 'https://alpha.example/page', 'position': 2},
        'benchmark': {'domain': 'beta.example', 'url': 'https://beta.example/page', 'position': 1},
        'limitations': ['Snapshot only'],
        'facts': [
            {'id': 'SERP', 'statement': 'Observed rankings', 'values': {'ours': 2, 'benchmark': 1}},
            {'id': 'BL_PAGE', 'statement': 'Page backlinks', 'values': {'ours': {'backlinks': 180}, 'benchmark': {'backlinks': 250}}},
            {'id': 'BL_DOMAIN', 'statement': 'Domain backlinks', 'values': {'ours': {'backlinks': 1806871}, 'benchmark': {'backlinks': 578056}}},
        ],
        'specialist_findings': [
            {'id': 'BACKLINKS_01', 'task': 'backlinks', 'finding': {'observation': 'Page counts differ.', 'evidence_paths': ['evidence.backlinks.page.ours']}},
            {'id': 'BACKLINKS_02', 'task': 'backlinks', 'finding': {'observation': 'Domain counts differ.', 'evidence_paths': ['evidence.backlinks.domain.ours']}},
        ],
        'specialist_fact_links': {'BACKLINKS_01': ['BL_PAGE', 'SERP'], 'BACKLINKS_02': ['BL_DOMAIN', 'SERP']},
    }
    def plan(fid, fact):
        return {'title': 'Audit link sources', 'rationale': 'Verify sources before outreach.',
                'owner': 'SEO team', 'priority': 'medium',
                'implementation_steps': ['Review relevant sources.'],
                'success_measure': 'Document verified findings.',
                'uncertainty': 'No ranking cause established.',
                'evidence_ids': [fact], 'specialist_finding_ids': [fid],
                'simple_explanation': 'The counts differ.',
                'technical_explanation': 'Compare source coverage.'}
    def disposition(fid, idx, fact):
        return {'specialist_finding_id': fid, 'outcome': 'action', 'plan_indices': [idx],
                'simple_explanation': 'Counts differ.', 'technical_explanation': 'Check sources.',
                'next_step': 'Audit before editing.', 'reason': 'Descriptive evidence.',
                'evidence_ids': [fact]}
    response = {'schema_version': '1.0', 'task': 'backlinks',
                'implementation_plans': [plan('BACKLINKS_01', 'BL_PAGE'), plan('BACKLINKS_02', 'SERP')],
                'finding_dispositions': [disposition('BACKLINKS_01', 0, 'BL_PAGE'),
                                         disposition('BACKLINKS_02', 1, 'BL_DOMAIN')]}
    return task_packet(packet, 'backlinks'), response


def test_existing_numeric_fact_missing_citation_is_diagnosed_and_safely_cited():
    scoped, result = fixture()
    result['implementation_plans'][1]['rationale'] = 'The domain-wide backlink totals are 1,806,871 versus 578,056.'
    errors = validate_task(result, scoped, 'backlinks')
    assert any('1,806,871' in e for e in errors)
    diag = diagnose_errors(errors, result, scoped)
    assert any(d.get('classification') == 'number_missing_correct_citation' and d['permitted_matching_fact_ids'] == ['BL_DOMAIN'] for d in diag)
    original = copy.deepcopy(result)
    fixed, audit = repair_unambiguous_citations(result, errors, scoped)
    assert result == original
    assert audit and audit[0]['added_fact_id'] == 'BL_DOMAIN'
    assert fixed['implementation_plans'][1]['evidence_ids'] == ['SERP', 'BL_DOMAIN']
    assert not validate_task(fixed, scoped, 'backlinks')


def test_number_present_but_outside_finding_scope_does_not_auto_repair():
    scoped, result = fixture()
    result['implementation_plans'][0]['rationale'] = 'The domain-wide backlink total is 1,806,871.'
    errors = validate_task(result, scoped, 'backlinks')
    diagnosis = diagnose_errors(errors, result, scoped)
    assert any(d.get('classification') == 'number_supported_by_other_scope' for d in diagnosis)
    fixed, audit = repair_unambiguous_citations(result, errors, scoped)
    assert fixed == result and audit == []


def test_arbitrary_targets_are_never_auto_accepted():
    scoped, result = fixture()
    result['implementation_plans'][1]['success_measure'] = 'Acquire 10 new referring domains in 90 days.'
    errors = validate_task(result, scoped, 'backlinks')
    assert any('numeric claim 10' in e for e in errors)
    diagnosis = diagnose_errors(errors, result, scoped)
    assert any(d.get('classification') == 'number_not_in_evidence' for d in diagnosis)
    fixed, audit = repair_unambiguous_citations(result, errors, scoped)
    assert fixed == result and audit == []


def test_numeric_zero_not_silently_reinterpreted_as_identifier():
    scoped, result = fixture()
    result['finding_dispositions'][0]['reason'] = '0 new links are needed.'
    errors = validate_task(result, scoped, 'backlinks')
    assert any('numeric claim 0' in e for e in errors)
    diag = diagnose_errors(errors, result, scoped)
    assert any(d.get('number') == '0' and d['classification'] == 'number_not_in_evidence' for d in diag)
    assert not repair_unambiguous_citations(result, errors, scoped)[1]


def test_wrong_metric_scope_not_citation_repaired():
    scoped, result = fixture()
    result['implementation_plans'][1]['rationale'] = 'The page-level backlinks total is 1,806,871.'
    errors = validate_task(result, scoped, 'backlinks')
    fixed, audit = repair_unambiguous_citations(result, errors, scoped)
    assert fixed == result and audit == []


def test_correction_instructions_include_fact_mapping_and_original_field():
    scoped, result = fixture()
    result['implementation_plans'][1]['rationale'] = 'The domain-wide backlink total is 1,806,871.'
    errors = validate_task(result, scoped, 'backlinks')
    guidance = _retry_guidance(errors, result, scoped)
    assert 'EXACT EVIDENCE DIAGNOSIS' in guidance
    assert 'BL_DOMAIN' in guidance
    assert 'implementation_plans[1].rationale' in guidance
    assert 'sample search' not in guidance


def test_generated_task_uses_audited_citation_fix_without_second_request(tmp_path, monkeypatch):
    scoped, result = fixture()
    result['implementation_plans'][1]['rationale'] = 'The domain-wide backlink total is 1,806,871.'
    calls = []
    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(result)), finish_reason='stop')])
    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    parsed, count = generate_task(client, 'fake', 'backlinks', scoped, 2, 120, 2048, tmp_path)
    assert count == 1 and len(calls) == 1
    assert parsed['implementation_plans'][1]['evidence_ids'] == ['SERP', 'BL_DOMAIN']
    raw = json.loads((tmp_path / 'backlinks_attempt_1.json').read_text(encoding='utf-8'))
    assert json.loads(raw['raw_response']) == result
    audit = json.loads((tmp_path / 'backlinks_citation_repair_audit.json').read_text(encoding='utf-8'))
    assert audit['validated'] is True
    assert audit['changes'][0]['type'] == 'citation_only'


def test_invalid_output_still_fails_after_retry_and_saves_diagnostics(tmp_path):
    scoped, result = fixture()
    result['implementation_plans'][1]['success_measure'] = 'Gain 90 links within 10 days.'
    class Completions:
        def create(self, **kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(result)), finish_reason='stop')])
    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    try:
        generate_task(client, 'fake', 'backlinks', scoped, 2, 120, 2048, tmp_path)
    except ValueError as exc:
        assert 'failed validation' in str(exc)
    else:
        raise AssertionError('Invalid numerical targets were accepted')
    for i in (1, 2):
        saved = json.loads((tmp_path / f'backlinks_attempt_{i}_diagnostics.json').read_text(encoding='utf-8'))
        assert saved['grounded_diagnostics']
    assert not (tmp_path / 'backlinks_citation_repair_audit.json').exists()


def test_full_thousands_numbers_are_not_truncated_before_punctuation():
    from llm_foundation.executive_synthesis import _numeric_claims
    text = 'Domain-wide backlink totals are 1,806,871 versus 578,056.'
    assert [number for number, _ in _numeric_claims(text)] == ['1,806,871', '578,056']
    text = 'LCP 24,907.98 ms; TBT 2,122.5 ms.'
    assert [number for number, _ in _numeric_claims(text)] == ['24,907.98', '2,122.5']
    assert [number for number, _ in _numeric_claims('Add 3-5 links.')] == ['3', '5']
