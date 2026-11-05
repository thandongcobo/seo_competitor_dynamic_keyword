"""Offline checks for the opt-in reporting bridge. No Gemma or paid API calls."""
import hashlib
import json
from pathlib import Path

import pytest
from scripts import reporting_jobs


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


@pytest.fixture
def case(tmp_path, monkeypatch):
    root = tmp_path / 'project'
    inv = root / 'data' / 'investigations'
    ident = 'a' * 32
    base = inv / ident
    canonical = {'investigation': {'keyword': 'aviator'},
                 'tracked_website': {'ranking_url': 'https://www.hollywoodbets.net/aviator'},
                 'competitors': [{'ranking_url': 'https://www.betway.co.za/aviator'}]}
    _json(root / 'output/results/aviator/llm_foundation/canonical_evidence.json', canonical)
    for task in reporting_jobs._TASKS:
        _json(root / 'output/results/aviator/llm_outputs' / f'{task}_validated.json', {'task': task})
    from llm_foundation import executive_synthesis
    monkeypatch.setattr(executive_synthesis, 'build_packet', lambda canonical, specialists: {
        'keyword': canonical['investigation']['keyword'],
        'tracked': {'url': canonical['tracked_website']['ranking_url']},
        'benchmark': {'url': canonical['competitors'][0]['ranking_url']},
        'specialist_findings': [{'id': name} for name in specialists],
    })
    _json(base / 'selection.json', {
        'keyword': 'aviator', 'source': 'manual_exact_webpage_urls',
        'ours': {'url': 'https://www.hollywoodbets.net/aviator', 'domain': 'hollywoodbets.net'},
        'benchmark': {'url': 'https://www.betway.co.za/aviator', 'domain': 'betway.co.za'},
    })
    _json(base / 'offline_execution.json', {'status': 'completed'})
    _json(base / 'results/aviator_comparison.json', {
        'primary_ranking_urls': {
            'ours': 'https://www.hollywoodbets.net/aviator',
            'benchmark': 'https://www.betway.co.za/aviator',
        }, 'ranking_summary': {'google': {'our_position': 2, 'benchmark_position': 1}},
    })
    monkeypatch.setattr(reporting_jobs, 'ROOT', root)
    monkeypatch.setattr(reporting_jobs.serp_investigations, 'INVESTIGATIONS', inv)
    reporting_jobs._ACTIVE.clear()
    yield ident, base, root
    reporting_jobs._ACTIVE.clear()


def test_preflight_accepts_exact_matching_saved_evidence(case):
    ident, _, _ = case
    result = reporting_jobs._preflight(ident, root=case[2])
    assert result['packet']['keyword'] == 'aviator'
    assert len(result['specialists']) == 4
    assert reporting_jobs.status(ident)['available'] is True


def test_preflight_rejects_other_url_and_keyword(case):
    ident, base, root = case
    selection = json.loads((base / 'selection.json').read_text())
    selection['benchmark']['url'] = 'https://www.betway.co.za/different'
    _json(base / 'selection.json', selection)
    with pytest.raises(ValueError, match='selected benchmark URL|different keyword or webpage'):
        reporting_jobs._preflight(ident, root=root)
    assert reporting_jobs.status(ident)['available'] is False


def test_missing_specialist_fails_closed(case):
    ident, _, root = case
    (root / 'output/results/aviator/llm_outputs/technical_validated.json').unlink()
    with pytest.raises(FileNotFoundError, match='technical'):
        reporting_jobs._preflight(ident, root=root)


def test_incomplete_offline_run_cannot_call_gemma(case, monkeypatch):
    ident, base, _ = case
    (base / 'offline_execution.json').unlink()
    with pytest.raises(ValueError, match='offline comparison'):
        reporting_jobs.start(ident)
    assert not (base / 'reporting/status.json').exists()


def test_status_after_restart_does_not_claim_running(case):
    ident, base, _ = case
    _json(base / 'reporting/status.json', {'status': 'running', 'run_id': 'b' * 32})
    assert reporting_jobs.status(ident)['status'] == 'interrupted'


def test_artifact_requires_current_run_and_matching_sha(case):
    ident, base, _ = case
    run = 'c' * 32
    reports = base / 'reporting/runs' / run / 'reports'
    pdf = reports / 'aviator_executive_report.pdf'
    appendix = reports / 'aviator_technical_appendix.md'
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b'%PDF-1.4 test')
    appendix.write_text('Test appendix')
    files = {}
    for kind, path in [('pdf', pdf), ('appendix', appendix)]:
        files[kind] = {'path': str(path.relative_to(base)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    _json(base / 'reporting/status.json', {'status': 'draft_ready', 'run_id': run, 'files': files})
    assert reporting_jobs.artifact(ident, 'pdf') == pdf
    assert reporting_jobs.approve(ident)['status'] == 'approved'
    pdf.write_bytes(b'tampered')
    with pytest.raises(FileNotFoundError, match='changed'):
        reporting_jobs.artifact(ident, 'pdf')


def test_approval_is_never_automatic(case):
    ident, base, _ = case
    _json(base / 'reporting/status.json', {'status': 'running', 'run_id': 'd' * 32})
    with pytest.raises(ValueError, match='completed'):
        reporting_jobs.approve(ident)


def test_dashboard_wiring_has_explicit_opt_in_and_does_not_touch_monitoring():
    patch = Path(__file__).resolve().parents[1]
    html = (patch / 'frontend/index.html').read_text(encoding='utf-8')
    js = (patch / 'frontend/js/app.js').read_text(encoding='utf-8')
    server = (patch / 'scripts/serve_dashboard.py').read_text()
    assert 'keyword-reporting-start' in html and 'keyword-reporting-approve' in html
    assert 'window.confirm' in js and 'reporting/files/' in js
    assert 'reporting_jobs.start' in server and 'reporting_jobs.approve' in server
    assert '/api/monitoring/capture' in js and "path == '/api/monitoring/pages'" in server


def test_focused_runner_supports_isolated_evidence_root():
    patch = Path(__file__).resolve().parents[1]
    text = (patch / 'scripts/run_llm_focused_recommendations.py').read_text()
    assert "--evidence-root" in text
    assert "Path(args.evidence_root).resolve()" in text


def test_worker_generates_scoped_draft_and_preserves_source(case, monkeypatch):
    """Exercise the orchestration with mocked subprocess outputs: zero model requests."""
    ident, base, root = case
    import scripts.generate_executive_pdf as renderer
    import llm_foundation.quality_repair as repair
    import llm_foundation.recommendation_quality as quality_mod
    monkeypatch.setattr(repair, 'evidence_errors', lambda result, packet: [])
    monkeypatch.setattr(renderer, 'report_consistency_errors', lambda result: [])
    monkeypatch.setattr(quality_mod, 'audit_recommendations', lambda result, expected_findings=None: {
        'blocking_count': 0, 'review_count': 0, 'issues': [], 'status': 'passed'})
    evidence = reporting_jobs._preflight(ident, root=root)
    def fake_command(command, *, cwd, log_path, limit=2400):
        if 'scripts.run_llm_focused_recommendations' in command:
            out = Path(command[command.index('--output-dir') + 1]) / 'llm_outputs'
            _json(out / 'executive_validated.json', {'implementation_plans': [{'title': 'test'}]})
            _json(out / 'executive_evidence_packet.json', {'specialist_findings': [{'id': 'a'}]})
        elif 'scripts.generate_executive_pdf' in command:
            out = Path(command[command.index('--output-dir') + 1])
            keyword = command[command.index('--keyword') + 1]
            executive = Path(command[command.index('--executive-json') + 1])
            comparison = Path(command[command.index('--input') + 1])
            out.mkdir(parents=True)
            (out / f'{keyword}_executive_report.pdf').write_bytes(b'%PDF-1.4 test')
            (out / f'{keyword}_technical_appendix.md').write_text('Technical details')
            _json(out / 'report_generation_manifest.json', {
                'source_executive_sha256': reporting_jobs._sha(executive),
                'source_comparison_sha256': reporting_jobs._sha(comparison),
                    'authoritative_recommendation_ids': [row.get('id') for row in
                        json.loads(comparison.read_text(encoding='utf-8')).get('recommendations', []) if row.get('id')],
            })
        else:
            pytest.fail('Unexpected command: ' + str(command))
    monkeypatch.setattr(reporting_jobs, '_run_command', fake_command)
    run_id = 'e' * 32
    _json(base / 'reporting/status.json', {'run_id': run_id, 'status': 'preparing', 'files': {}})
    before = reporting_jobs._sha(evidence['comparison'])
    reporting_jobs._execute(ident, run_id, evidence)
    state = reporting_jobs.status(ident)
    assert state['status'] == 'draft_ready'
    assert state['quality'] == {'blocking': 0, 'review': 0}
    assert reporting_jobs.artifact(ident, 'pdf').read_bytes().startswith(b'%PDF')
    assert reporting_jobs._sha(evidence['comparison']) == before
    assert reporting_jobs.approve(ident)['status'] == 'approved'


def test_failed_worker_does_not_publish_old_report(case, monkeypatch):
    ident, base, root = case
    evidence = reporting_jobs._preflight(ident, root=root)
    def fail(*args, **kwargs):
        raise TimeoutError('Mocked model timeout')
    monkeypatch.setattr(reporting_jobs, '_run_command', fail)
    run_id = 'f' * 32
    _json(base / 'reporting/status.json', {'run_id': run_id, 'status': 'preparing', 'files': {}})
    reporting_jobs._execute(ident, run_id, evidence)
    state = reporting_jobs.status(ident)
    assert state['status'] == 'failed' and not state['files']
    with pytest.raises(FileNotFoundError):
        reporting_jobs.artifact(ident, 'pdf')


def test_generic_keyword_and_webpage_pair(case):
    ident, base, root = case
    from config.settings import keyword_slug
    keyword = 'example search phrase'
    slug = keyword_slug(keyword)
    original = root / 'output/results/aviator'
    target = root / 'output/results' / slug
    original.rename(target)
    canonical_path = target / 'llm_foundation/canonical_evidence.json'
    canonical = json.loads(canonical_path.read_text())
    canonical['investigation']['keyword'] = keyword
    canonical['tracked_website']['ranking_url'] = 'https://example-one.test/a'
    canonical['competitors'][0]['ranking_url'] = 'https://example-two.test/b'
    _json(canonical_path, canonical)
    selection = json.loads((base / 'selection.json').read_text())
    selection['keyword'] = keyword
    selection['ours']['url'] = 'https://example-one.test/a'
    selection['benchmark']['url'] = 'https://example-two.test/b'
    _json(base / 'selection.json', selection)
    comparison = json.loads((base / 'results/aviator_comparison.json').read_text())
    comparison['primary_ranking_urls'] = {
        'ours': selection['ours']['url'], 'benchmark': selection['benchmark']['url']}
    (base / 'results/aviator_comparison.json').unlink()
    _json(base / 'results' / f'{slug}_comparison.json', comparison)
    result = reporting_jobs._preflight(ident, root=root)
    assert result['keyword'] == keyword
    assert result['slug'] == slug
    assert result['packet']['tracked']['url'] == 'https://example-one.test/a'
