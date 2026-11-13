"""No-network regression tests for safe fallback and reusable history search."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

from llm_foundation.evidence_recovery import build_evidence_registry, recover_invalid_task
from llm_foundation.focused_recommendations import task_packet, validate_task
from scripts.run_llm_focused_recommendations import generate_task
from scripts.search_investigation_history import search_history

FIXTURES = Path(__file__).parent / 'fixtures' / 'evidence_recovery'


def sample(task='backlinks'):
    packet = json.loads((FIXTURES / 'executive_evidence_packet.json').read_text(encoding='utf-8'))
    return task_packet(packet, task)


def response(filename):
    return json.loads(json.loads((FIXTURES / filename).read_text(encoding='utf-8'))['raw_response'])


def test_registry_has_metric_and_scope_without_domain_constants():
    scoped = sample()
    registry = build_evidence_registry(scoped)
    rows = [r for r in registry if r['fact_id'] == 'BL_DOMAIN' and r['metric'] == 'backlinks']
    assert {r['value'] for r in rows} == {1806871, 578056}
    assert {r['side'] for r in rows} == {'ours', 'benchmark'}
    assert all(r['scope'] == 'domain' for r in rows)


def test_actual_failed_onpage_keeps_two_valid_plans_and_three_findings():
    scoped = sample('onpage')
    raw = response('onpage_attempt_2.json')
    errors = validate_task(raw, scoped, 'onpage')
    recovered, audit = recover_invalid_task(raw, errors, scoped, 'onpage')
    assert audit['status'] == 'recovered_with_review'
    assert len(recovered['implementation_plans']) == 2
    assert len(recovered['finding_dispositions']) == 3
    assert recovered['finding_dispositions'][1]['outcome'] == 'investigate'
    assert audit['quarantined_plans'][0]['original'] == raw['implementation_plans'][1]
    assert not validate_task(recovered, scoped, 'onpage')


def test_actual_failed_backlinks_isolated_without_approving_targets():
    scoped = sample()
    raw = response('backlinks_attempt_b.json')
    errors = validate_task(raw, scoped, 'backlinks')
    recovered, audit = recover_invalid_task(raw, errors, scoped, 'backlinks')
    assert recovered is not None
    assert not recovered['implementation_plans']
    assert all(row['outcome'] == 'investigate' for row in recovered['finding_dispositions'])
    assert '10 new' in json.dumps(audit)
    assert '10 new' not in json.dumps(recovered)
    assert not validate_task(recovered, scoped, 'backlinks')


def test_unlocalized_or_missing_finding_does_not_recover():
    scoped = sample()
    raw = response('backlinks_attempt_b.json')
    raw['finding_dispositions'].pop()
    errors = validate_task(raw, scoped, 'backlinks')
    candidate, audit = recover_invalid_task(raw, errors, scoped, 'backlinks')
    assert candidate is None and audit['status'] == 'not_recovered'


def test_unknown_numeric_zero_never_approved():
    scoped = sample()
    raw = response('backlinks_attempt_b.json')
    raw['finding_dispositions'][0]['reason'] = '0 links are needed.'
    errors = validate_task(raw, scoped, 'backlinks')
    candidate, audit = recover_invalid_task(raw, errors, scoped, 'backlinks')
    assert candidate is not None and '0 links are needed' not in json.dumps(candidate)
    assert '0 links are needed' in json.dumps(audit)
    assert not validate_task(candidate, scoped, 'backlinks')


def test_retry_exhaustion_reanalyses_saved_evidence_without_third_llm_call(tmp_path):
    scoped = sample('onpage')
    raw = response('onpage_attempt_2.json')
    calls = []
    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(raw)), finish_reason='stop')])
    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    result, attempts = generate_task(client, 'local', 'onpage', scoped, 2, 120, 2048, tmp_path, allow_partial_recovery=True)
    assert attempts == len(calls) == 2
    assert len(result['implementation_plans']) == 2
    assert (tmp_path / 'onpage_evidence_recovery_audit.json').exists()
    assert (tmp_path / 'onpage_attempt_2.json').exists()


def test_history_search_retrieves_only_matching_saved_keyword_and_pages(tmp_path):
    def save(ident, keyword, urls, created, report_status='draft_ready', offline_status='completed'):
        base = tmp_path / ident
        base.mkdir()
        (base / 'selection.json').write_text(json.dumps({
            'investigation_id': ident, 'keyword': keyword, 'created_at': created,
            'ours': {'url': urls[0]}, 'benchmark': {'url': urls[1]}}), encoding='utf-8')
        (base / 'offline_execution.json').write_text(json.dumps({'status':offline_status}), encoding='utf-8')
        run = 'c'*32
        (base / 'reporting').mkdir()
        (base / 'reporting' / 'status.json').write_text(json.dumps({'status':report_status,'run_id':run}), encoding='utf-8')
        reports = base / 'reporting' / 'runs' / run / 'reports'
        reports.mkdir(parents=True)
        (reports / 'brief.pdf').write_bytes(b'%PDF-test')
    save('a'*32, 'keyword-one', ('https://alpha.example/page', 'https://beta.example/page'), '2026-11-02')
    save('b'*32, 'keyword-two', ('https://gamma.example/', 'https://delta.example/'), '2026-11-03')
    save('c'*32, 'keyword-one', ('https://alpha.example/page', 'https://beta.example/page'), '2026-11-04', report_status='failed')
    save('d'*32, 'keyword-one', ('https://alpha.example/page', 'https://beta.example/page'), '2026-11-05', report_status='not_started', offline_status='selected_not_analyzed')
    found = search_history(tmp_path, keyword='KEYWORD-ONE', url_a='https://www.alpha.example/page/', url_b='https://beta.example/page')
    assert len(found) == 1 and found[0]['investigation_id'] == 'a'*32
    assert found[0]['reports']['brief.pdf'].startswith('a'*32)
    assert search_history(tmp_path, keyword='unknown') == []


def test_isolated_zero_in_reason_is_reanalysed_without_discarding_valid_plan():
    scoped = sample()
    # Fully supported, scoped plan and disposition, then inject an invalid
    # numeric rationale in only one explanatory field.
    def plan(fid, fact):
        return {'title': 'Audit sources', 'rationale': 'Review the documented evidence.',
                'owner': 'SEO', 'priority': 'medium', 'implementation_steps': ['Review source records.'],
                'success_measure': 'Document evidence checks.', 'uncertainty': 'Ranking cause unverified.',
                'evidence_ids': [fact], 'specialist_finding_ids': [fid],
                'simple_explanation': 'The counts differ.', 'technical_explanation': 'Review exact source scope.'}
    def disp(fid, idx, fact):
        return {'specialist_finding_id': fid, 'outcome': 'action', 'plan_indices': [idx],
                'simple_explanation': 'Compare the saved observations.',
                'technical_explanation': 'Review original source evidence.',
                'next_step': 'Check the relevant source.', 'reason': 'Evidence comparison warrants review.',
                'evidence_ids': [fact]}
    original = {'schema_version': '1.0', 'task': 'backlinks',
                'implementation_plans': [plan('BACKLINKS_01', 'BL_PAGE'), plan('BACKLINKS_02', 'BL_DOMAIN')],
                'finding_dispositions': [disp('BACKLINKS_01', 0, 'BL_PAGE'), disp('BACKLINKS_02', 1, 'BL_DOMAIN')]}
    assert not validate_task(original, scoped, 'backlinks')
    invalid = copy.deepcopy(original)
    invalid['finding_dispositions'][0]['reason'] = '0 links are required.'
    recovered, audit = recover_invalid_task(invalid, validate_task(invalid, scoped, 'backlinks'), scoped, 'backlinks')
    assert recovered is not None and len(recovered['implementation_plans']) == 2
    assert recovered['finding_dispositions'][0]['outcome'] == 'action'
    assert audit['sanitized_fields'][0]['original'] == '0 links are required.'
    assert not validate_task(recovered, scoped, 'backlinks')


def test_dashboard_marks_unresolved_all_plan_recovery_needs_review(tmp_path, monkeypatch):
    from scripts import reporting_jobs
    import llm_foundation.quality_repair as repair
    import llm_foundation.recommendation_quality as quality_mod
    import scripts.generate_executive_pdf as renderer
    ident, run_id = 'a'*32, 'b'*32
    base = tmp_path / ident
    base.mkdir()
    selection = {'keyword': 'other search', 'ours': {'url': 'https://first.example/page'},
                 'benchmark': {'url': 'https://second.example/page'}}
    canonical = tmp_path / 'canonical.json'
    comparison = tmp_path / 'comparison.json'
    canonical.write_text('{}', encoding='utf-8')
    comparison.write_text('{}', encoding='utf-8')
    specialists = {}
    for task in ('onpage', 'backlinks', 'technical', 'competition'):
        p = tmp_path / f'{task}.json'
        p.write_text('{}', encoding='utf-8')
        specialists[task] = p
    evidence = {'keyword': 'other search', 'selection': selection, 'canonical': canonical,
                'comparison': comparison, 'specialists': specialists}
    states = []
    monkeypatch.setattr(reporting_jobs, '_base', lambda _id: base)
    monkeypatch.setattr(reporting_jobs, '_update', lambda _id, **changes: states.append(changes))
    monkeypatch.setattr(repair, 'evidence_errors', lambda data, packet: [])
    monkeypatch.setattr(quality_mod, 'audit_recommendations', lambda *a, **k: {
        'blocking_count': 0, 'review_count': 0})
    monkeypatch.setattr(renderer, 'report_consistency_errors', lambda *a: [])
    def fake_command(command, *, cwd, log_path, limit=2400):
        assert 'scripts.run_llm_focused_recommendations' in command
        out = Path(command[command.index('--output-dir') + 1]) / 'llm_outputs'
        out.mkdir(parents=True)
        (out / 'executive_validated.json').write_text('{"implementation_plans":[]}', encoding='utf-8')
        (out / 'executive_evidence_packet.json').write_text('{"specialist_findings":[]}', encoding='utf-8')
        (out / 'focused_run_metadata.json').write_text(json.dumps({
            'evidence_recovery': {'backlinks': ['BACKLINKS_01']}}), encoding='utf-8')
    monkeypatch.setattr(reporting_jobs, '_run_command', fake_command)
    reporting_jobs._execute(ident, run_id, evidence)
    assert states[-1]['status'] == 'needs_review'
    assert states[-1]['files'] == {}
    assert not (base / 'reporting' / 'runs' / run_id / 'reports').exists()


def test_dashboard_history_is_read_only_and_keyword_independent():
    root = Path(__file__).resolve().parents[1]
    html = (root / 'frontend/index.html').read_text(encoding='utf-8')
    js = (root / 'frontend/js/app.js').read_text(encoding='utf-8')
    server = (root / 'scripts/serve_dashboard.py').read_text(encoding='utf-8')
    assert 'investigation-history-form' in html
    assert '/api/investigations/history?' in js
    assert "parsed_serp.path == '/api/investigations/history'" in server
    assert 'data-page="monitoring"' in html
    assert 'no new requests' in html.lower()
