"""Offline integration tests against real saved evidence; mock ONLY LLM responses."""
import argparse
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from llm_foundation.executive_synthesis import build_packet, validate_executive
from llm_foundation.focused_recommendations import (
    TASKS, task_packet, task_request, fingerprint, validate_task, merge_tasks)
from scripts.run_llm_focused_recommendations import run
from analysis.recommendation_classification import TIER_1, TIER_2

ROOT = Path(__file__).resolve().parents[1]


def evidence():
    base = ROOT / 'output/results/aviator'
    canonical = json.loads((base / 'llm_foundation/canonical_evidence.json').read_text(encoding='utf-8'))
    specialists = {task: json.loads((base / 'llm_outputs' / f'{task}_validated.json').read_text(encoding='utf-8')) for task in TASKS}
    return build_packet(canonical, specialists)


def task_result(scoped, task):
    rows = []
    plans = []
    for finding in scoped['specialist_findings']:
        fid = finding['id']
        facts = scoped['specialist_fact_links'].get(fid, [])
        if facts and not plans:
            plans.append({'title': 'Review captured SEO difference', 'rationale': 'Saved evidence warrants review.',
                          'owner': 'SEO and engineering', 'priority': 'investigate',
                          'implementation_steps': ['Review the cited evidence for both selected URLs.',
                                                   'Document an approved change and repeat the same measurement.'],
                          'success_measure': 'A verified comparison and documented decision.',
                          'uncertainty': 'No ranking causation has been established.',
                          'evidence_ids': [facts[0]], 'specialist_finding_ids': [fid],
                          'simple_explanation': 'We found a difference worth checking before making a change.',
                          'technical_explanation': 'Review source measurements and verify the proposed modification using the same collection method.'})
            outcome, indices = 'action', [0]
        else:
            outcome, indices = 'investigate', []
        rows.append({'specialist_finding_id': fid, 'outcome': outcome, 'plan_indices': indices,
                     'simple_explanation': 'The difference needs verification before changes are approved.',
                     'technical_explanation': 'Inspect the original captured source paths and compare the selected ranking URLs.',
                     'next_step': 'Verify the source evidence and document next steps.',
                     'reason': 'Measured evidence is limited and ranking causation is unverified.',
                     'evidence_ids': facts[:1]})
    return {'schema_version': '1.0', 'task': task, 'implementation_plans': plans, 'finding_dispositions': rows}


def test_four_scoped_prompts_and_outputs_validate():
    packet = evidence()
    for task in TASKS:
        scoped = task_packet(packet, task)
        prompt, body = task_request(scoped, task)
        assert packet['keyword'] in body
        assert packet['tracked']['url'] in body
        assert 'implementation_plans' in prompt
        assert all(f['task'] == task for f in scoped['specialist_findings'])
        assert not validate_task(task_result(scoped, task), scoped, task)


def test_aviator_prompt_covers_actionable_content_links_authority_and_performance():
    packet = evidence()
    prompts = {task: task_request(task_packet(packet, task), task)[0] for task in TASKS}
    onpage = prompts['onpage'].casefold()
    assert 'existing-page' in onpage and 'outgoing destinations' in onpage
    assert 'headings' in onpage and 'content passages' in onpage
    assert 'title' in onpage and 'faq' in onpage
    backlinks = prompts['backlinks'].casefold()
    assert 'page-level' in backlinks and 'domain-level' in backlinks
    assert 'referring-domain identities' in backlinks
    technical = prompts['technical'].casefold()
    assert 'lighthouse diagnostics' in technical and 'security' in technical
    competition = prompts['competition'].casefold()
    assert 'exact ranking urls' in competition and 'existing coverage' in competition
    assert 'do not prescribe word counts' in prompts['onpage'].casefold()
    assert 'match' in prompts['onpage'].casefold() and 'outperform' in prompts['onpage'].casefold()


def test_full_deterministic_merge_preserves_all_findings():
    packet = evidence()
    outputs = {task: task_result(task_packet(packet, task), task) for task in TASKS}
    merged = merge_tasks(packet, outputs)
    assert len(merged['specialist_findings']) == len(packet['specialist_findings']) == 11
    assert len(merged['finding_dispositions']) == 11
    assert len(merged['implementation_plans']) == 4
    assert {r['specialist_finding_id'] for r in merged['finding_dispositions']} == {r['id'] for r in packet['specialist_findings']}
    assert all(r['plan_indices'] == [i] for i, task in enumerate(TASKS) for r in merged['finding_dispositions'] if r['outcome'] == 'action' and r['specialist_finding_id'].startswith(task.upper()))
    # Published output contains supplemental sections beyond the model's input schema.
    assert merged['verified_factual_findings']
    assert all(p.get('evidence_tier') in {TIER_1, TIER_2} or
               p.get('classification_status') == 'excluded_from_user_facing_recommendations'
               for p in merged['implementation_plans'])
    assert all(p['evidence_provenance']['evidence_ids'] == p['evidence_ids'] for p in merged['implementation_plans'])
    assert all(p['validation_status'] == 'validated_citations_numeric_scope_and_lineage' for p in merged['implementation_plans'])
    assert all(d['evidence_tier'] in {TIER_1, TIER_2} for d in merged['proposed_decisions'])


def test_unknown_or_cross_specialist_evidence_fails():
    packet = evidence()
    scoped = task_packet(packet, 'onpage')
    result = task_result(scoped, 'onpage')
    result['implementation_plans'][0]['evidence_ids'] = ['BL_PAGE']
    assert validate_task(result, scoped, 'onpage')


def test_missing_finding_fails_closed():
    packet = evidence()
    scoped = task_packet(packet, 'technical')
    result = task_result(scoped, 'technical')
    result['finding_dispositions'].pop()
    assert any('missing specialist findings' in x for x in validate_task(result, scoped, 'technical'))


def test_prompt_changes_with_investigation_and_no_domain_hardcoding():
    packet = evidence()
    packet['keyword'] = 'different keyword'
    packet['tracked']['domain'] = 'alpha.example'
    packet['tracked']['url'] = 'https://alpha.example/first'
    packet['benchmark']['domain'] = 'beta.example'
    packet['benchmark']['url'] = 'https://beta.example/second'
    scoped = task_packet(packet, 'technical')
    _, body = task_request(scoped, 'technical')
    assert 'different keyword' in body
    assert 'alpha.example' in body and 'beta.example' in body
    assert scoped['tracked']['domain'] == 'alpha.example'
    # Historical specialist prose remains verbatim and may contain old domain names.


def test_cached_resumable_run_uses_only_four_requests(tmp_path):
    packet = evidence()
    requests = []
    def create(**kwargs):
        body = json.loads(kwargs['messages'][1]['content'])
        task = body['task']
        requests.append(task)
        response = task_result(task_packet(packet, task), task)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(response)), finish_reason='stop')])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    args = argparse.Namespace(keyword='aviator', output_dir=tmp_path, tasks=None, dry_run=False,
                              force=False, pdf=False, attempts=2, timeout=120, max_output_tokens=3072)
    result = run(args, client=client, model='offline-test-model')
    assert requests == list(TASKS)
    assert len(result['implementation_plans']) == 4
    assert (tmp_path / 'llm_outputs/executive_validated.json').exists()
    assert list(tmp_path.glob('**/information_preservation_report.json'))
    result2 = run(args, client=client, model='offline-test-model')
    assert requests == list(TASKS)  # all four outputs resumed without requests
    assert result2 == result


def test_partial_task_run_then_resume(tmp_path):
    packet = evidence()
    requested = []
    def create(**kwargs):
        task = json.loads(kwargs['messages'][1]['content'])['task']
        requested.append(task)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(task_result(task_packet(packet, task), task))), finish_reason='stop')])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    args = argparse.Namespace(keyword='aviator', output_dir=tmp_path, tasks=['onpage'], dry_run=False,
                              force=False, pdf=False, attempts=2, timeout=120, max_output_tokens=3072)
    assert run(args, client=client, model='offline-test-model') is None
    args.tasks = None
    assert run(args, client=client, model='offline-test-model')
    assert requested == list(TASKS)


def test_dry_run_makes_no_request(tmp_path):
    args = argparse.Namespace(keyword='aviator', output_dir=tmp_path, tasks=None, dry_run=True,
                              force=False, pdf=False, attempts=2, timeout=120, max_output_tokens=3072)
    assert run(args) is None
    assert len(list((tmp_path / 'llm_outputs/focused_tasks').glob('*_request_preview.json'))) == 4


def test_pdf_generation_from_merged_focused_results(tmp_path):
    pytest.importorskip('reportlab')
    packet = evidence()
    def create(**kwargs):
        task = json.loads(kwargs['messages'][1]['content'])['task']
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps(task_result(task_packet(packet, task), task))), finish_reason='stop')])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    args = argparse.Namespace(keyword='aviator', output_dir=tmp_path, tasks=None, dry_run=False,
                              force=False, pdf=True, attempts=2, timeout=120, max_output_tokens=3072)
    assert run(args, client=client, model='offline-test-model')
    pdf = tmp_path / 'aviator_executive_report.pdf'
    assert pdf.exists() and pdf.stat().st_size > 1000


def test_gateway_failure_preserves_prior_task_and_allows_resume(tmp_path):
    packet = evidence()
    calls = []
    def first_create(**kwargs):
        task = json.loads(kwargs['messages'][1]['content'])['task']
        calls.append(task)
        if task == 'backlinks':
            raise RuntimeError('504 Gateway Time-out')
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps(task_result(task_packet(packet, task), task))), finish_reason='stop')])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=first_create)))
    args = argparse.Namespace(keyword='aviator', output_dir=tmp_path, tasks=None, dry_run=False,
                              force=False, pdf=False, attempts=2, timeout=120, max_output_tokens=3072)
    with pytest.raises(RuntimeError, match='504'):
        run(args, client=client, model='offline-test-model')
    assert (tmp_path / 'llm_outputs/focused_tasks/onpage_validated.json').exists()
    assert json.loads((tmp_path / 'llm_outputs/focused_tasks/backlinks_status.json').read_text())['status'] == 'failed'
    def second_create(**kwargs):
        task = json.loads(kwargs['messages'][1]['content'])['task']
        calls.append(task)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps(task_result(task_packet(packet, task), task))), finish_reason='stop')])
    client.chat.completions.create = second_create
    assert run(args, client=client, model='offline-test-model')
    assert calls.count('onpage') == 1  # not repeated after gateway failure
    assert calls.count('backlinks') == 2
