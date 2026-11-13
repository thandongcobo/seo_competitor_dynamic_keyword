import hashlib
import json
import threading
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

import pytest

from scripts import comparison_history, serve_dashboard, serp_investigations


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _row(ident, title, tier, priority, url, *, limitations=''):
    return {
        'id': ident, 'title': title, 'target_url': url,
        'evidence': f'Captured page evidence supports {title.lower()}.',
        'interpretation': 'This may improve clarity and discoverability on the selected page.',
        'action_justification': 'The recorded action follows the captured page evidence.',
        'display_action': f'Improve the selected page for {title.lower()} and verify the rendered result.',
        'actions': [f'On {url}, update the recorded page element for {title.lower()}. Verify the saved page after implementation.'],
        'success_check': 'Re-capture the exact URL and confirm the updated page element.',
        'limitations': limitations,
        'evidence_provenance': {'source': 'saved exact-page capture', 'target_url': url,
                                'benchmark_url': 'https://competitor.example/page',
                                'evidence_ids': [f'EV-{ident}']},
        'validation_status': 'validated_rule_evidence', 'recovery_status': 'not_required',
        'evidence_tier': tier, 'priority_score': priority,
        'action_composition': {'proposed_copy': {'candidate': 'Grounded page improvement',
            'status': 'proposed_not_observed', 'validation': {'grounded': True},
            'source_evidence_ids': [f'EV-{ident}']}},
    }


def _create(root, ident, *, keyword='garden irrigation', competitor='greenfield.example',
            status='completed', report=True, valid=True):
    base = root / ident
    ours_url = f'https://hollywoodbets.net/{keyword.replace(" ", "-")}'
    other_url = f'https://{competitor}/page'
    selection = {'investigation_id': ident, 'keyword': keyword,
        'created_at': '2026-11-05T10:00:00+00:00', 'source': 'observed_google_playwright_serp',
        'serp_sha256': 'a' * 64, 'serp_snapshot_reference': 'data/raw/serp/synthetic.json',
        'ours': {'domain': 'hollywoodbets.net', 'url': ours_url, 'rank': 2},
        'benchmark': {'domain': competitor, 'url': other_url, 'rank': 1}}
    rows = [
        _row('strong', 'Improve irrigation title targeting', 'tier_1_strong_evidence', 10, ours_url),
        _row('higher-priority', 'Improve irrigation page coverage', 'tier_1_strong_evidence', 12, ours_url),
        _row('moderate', 'Clarify existing irrigation guidance', 'tier_2_moderate_evidence', 8, ours_url,
             limitations='The destination section is not verified and needs review before editing.'),
    ]
    if not valid:
        rows[0]['validation_status'] = 'failed_unsupported_claim'
    comparison_rel = f'results/{keyword.replace(" ", "-")}_comparison.json'
    comparison = {'investigation_id': ident, 'keyword': keyword,
        'primary_ranking_urls': {'ours': ours_url, 'benchmark': other_url},
        'recommendations': rows}
    comparison_path = base / comparison_rel
    _json(base / 'selection.json', selection)
    _json(comparison_path, comparison)
    report_hashes = {}
    report_paths = {'pdf_path': None, 'technical_appendix_path': None}
    report_outputs = []
    if report:
        pdf = base / 'results' / f'{keyword.replace(" ", "-")}_executive_report.pdf'
        appendix = base / 'results' / f'{keyword.replace(" ", "-")}_technical_appendix.md'
        pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.write_bytes(b'%PDF-1.4\nfixture')
        appendix.write_text('# Technical appendix\n', encoding='utf-8')
        report_hashes = {'pdf': _sha(pdf), 'appendix': _sha(appendix)}
        report_paths = {'pdf_path': pdf.relative_to(base).as_posix(),
                        'technical_appendix_path': appendix.relative_to(base).as_posix()}
        report_outputs = [{'path': pdf.relative_to(base).as_posix(), 'sha256': _sha(pdf)},
                          {'path': appendix.relative_to(base).as_posix(), 'sha256': _sha(appendix)}]
    offline = {'investigation_id': ident, 'keyword': keyword,
        'status': ('report_failed' if not report and status == 'completed' else status), 'processing_status': 'completed',
        'report_status': 'completed' if report else 'failed',
        'report_artifact_sha256': report_hashes,
        'selected_pages': {'ours': selection['ours'], 'benchmark': selection['benchmark']},
        'comparison_path': comparison_rel, 'completed_at': '2026-11-05T10:05:00+00:00',
        **report_paths}
    execution_path = base / 'offline_execution.json'
    _json(execution_path, offline)
    generation_outputs = [
        {'path': 'offline_execution.json', 'sha256': _sha(execution_path)},
        {'path': comparison_rel, 'sha256': _sha(comparison_path)},
        *report_outputs,
    ]
    stages = {
        'recommendation_generation': {'status': 'completed', 'completed_at': offline['completed_at'], 'outputs': generation_outputs},
        'validation_classification': {'status': 'completed', 'completed_at': offline['completed_at'], 'outputs': generation_outputs},
        'results_reporting': {'status': 'completed' if report else 'failed', 'outputs': report_outputs},
    }
    _json(base / 'workflow' / 'checkpoint.json', {'investigation_id': ident,
        'schema_version': '1.0', 'stages': stages})
    return base


@pytest.fixture
def history_root(tmp_path, monkeypatch):
    root = tmp_path / 'data' / 'investigations'
    root.mkdir(parents=True)
    good = _create(root, '1' * 32)
    _create(root, '2' * 32, keyword='mortgage calculator', competitor='finance.example')
    incomplete = _create(root, '3' * 32, keyword='incomplete test')
    cp_path = incomplete / 'workflow' / 'checkpoint.json'
    cp = json.loads(cp_path.read_text(encoding='utf-8'))
    cp['stages']['validation_classification']['status'] = 'running'
    _json(cp_path, cp)
    _create(root, '4' * 32, keyword='failed validation', valid=False)
    failed = root / ('4' * 32) / 'workflow' / 'checkpoint.json'
    cp = json.loads(failed.read_text(encoding='utf-8'))
    cp['stages']['validation_classification']['status'] = 'failed'
    _json(failed, cp)
    reportless = _create(root, '5' * 32, keyword='manual clinic hours', report=False)
    cp_path = reportless / 'workflow' / 'checkpoint.json'
    cp = json.loads(cp_path.read_text(encoding='utf-8'))
    # Phase 2.3 can persist recommendation records before a report renderer fails.
    cp['stages']['recommendation_generation']['status'] = 'not_started'
    cp['stages']['validation_classification']['status'] = 'not_started'
    _json(cp_path, cp)
    monkeypatch.setattr(serp_investigations, 'INVESTIGATIONS', root)
    monkeypatch.setattr(comparison_history.serp_investigations, 'INVESTIGATIONS', root)
    return root, good, reportless


def test_history_filters_success_only_and_orders_task7_tier_then_priority(history_root):
    root, _good, _ = history_root
    result = comparison_history.history(root=root)
    assert {row['investigation_id'] for row in result['comparisons']} == {'1' * 32, '2' * 32, '5' * 32}
    detail = comparison_history.comparison_detail('1' * 32, root=root)
    assert [row['id'] for row in detail['recommendations']] == ['higher-priority', 'strong', 'moderate']
    assert detail['tier_1_count'] == 2 and detail['tier_2_count'] == 1
    assert detail['recommendations'][0]['classification_version'] == 2
    assert detail['recommendations'][0]['actions'][0].startswith('On https://hollywoodbets.net/garden-irrigation')
    mortgage = comparison_history.comparison_detail('2' * 32, root=root)
    assert mortgage['keyword'] == 'mortgage calculator'
    assert mortgage['recommendations'][0]['target_url'] != detail['recommendations'][0]['target_url']


def test_report_failure_does_not_hide_valid_recommendations_and_missing_reports_fail_safely(history_root):
    root, _, failed = history_root
    result = comparison_history.history(root=root, keyword='manual clinic hours')
    assert result['total'] == 1
    record = result['comparisons'][0]
    assert record['recommendation_count'] == 3 and record['report_status'] == 'unavailable'
    detail = comparison_history.comparison_detail(record['investigation_id'], root=root)
    assert len(detail['recommendations']) == 3
    with pytest.raises(FileNotFoundError):
        comparison_history.artifact(record['investigation_id'], 'pdf', root=root)
    assert (failed / 'results' / 'manual-clinic-hours_comparison.json').is_file()
    # The authorized report-only retry can complete the report after the
    # bundled workflow recorded a failed processing stage. Keep the same saved
    # recommendation set visible without rerunning its analysis.
    execution_path = failed / 'offline_execution.json'
    execution = json.loads(execution_path.read_text(encoding='utf-8'))
    execution.update(status='completed', report_status='completed')
    _json(execution_path, execution)
    checkpoint_path = failed / 'workflow' / 'checkpoint.json'
    checkpoint = json.loads(checkpoint_path.read_text(encoding='utf-8'))
    checkpoint['stages']['evidence_processing'] = {'status': 'failed'}
    _json(checkpoint_path, checkpoint)
    assert comparison_history.history(root=root, keyword='manual clinic hours')['total'] == 1


def test_paths_identity_and_checkpoint_hashes_are_checked(history_root):
    root, good, _ = history_root
    comparison = good / 'results' / 'garden-irrigation_comparison.json'
    data = json.loads(comparison.read_text(encoding='utf-8'))
    data['keyword'] = 'mortgage calculator'
    _json(comparison, data)
    with pytest.raises(ValueError, match='integrity'):
        comparison_history.comparison_detail('1' * 32, root=root)
    data['keyword'] = 'garden irrigation'
    _json(comparison, data)
    execution_path = good / 'offline_execution.json'
    execution = json.loads(execution_path.read_text(encoding='utf-8'))
    execution['comparison_path'] = '../' + ('2' * 32) + '/results/mortgage-calculator_comparison.json'
    _json(execution_path, execution)
    with pytest.raises(ValueError, match='escapes'):
        comparison_history.comparison_detail('1' * 32, root=root)


def test_search_date_domain_url_keyword_sort_and_pagination(history_root):
    root, _, _ = history_root
    assert comparison_history.history(root=root, competitor='finance', keyword='mortgage')['total'] == 1
    assert comparison_history.history(root=root, url='https://hollywoodbets.net/mortgage-calculator')['total'] == 1
    assert comparison_history.history(root=root, date_from='2026-11-06')['total'] == 0
    page = comparison_history.history(root=root, sort='keyword', page_size=1)
    assert page['pages'] == 3 and len(page['comparisons']) == 1
    assert comparison_history.history(root=root, sort='oldest')['comparisons'][0]['keyword'] == 'garden irrigation'


@contextmanager
def _server(monkeypatch, root):
    monkeypatch.setattr(serp_investigations, 'INVESTIGATIONS', root)
    monkeypatch.setattr(comparison_history.serp_investigations, 'INVESTIGATIONS', root)
    server = ThreadingHTTPServer(('127.0.0.1', 0), serve_dashboard.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown(); thread.join(timeout=2); server.server_close()


def test_dashboard_history_detail_and_artifact_routes_are_read_only(history_root, monkeypatch):
    root, good, _ = history_root
    with _server(monkeypatch, root) as base:
        payload = json.loads(urlopen(base + '/api/comparisons/history?keyword=garden').read())
        assert payload['total'] == 1
        detail = json.loads(urlopen(base + f"/api/comparisons/{'1'*32}").read())
        assert detail['keyword'] == 'garden irrigation'
        with urlopen(base + f"/api/comparisons/{'1'*32}/artifacts/pdf") as response:
            assert response.headers['Content-Type'] == 'application/pdf'
            assert response.read().startswith(b'%PDF-')
        with urlopen(base + f"/api/comparisons/{'1'*32}/artifacts/appendix") as response:
            assert b'Technical appendix' in response.read()
        with pytest.raises(Exception):
            urlopen(base + f"/api/comparisons/{'5'*32}/artifacts/pdf")
    assert (good / 'results' / 'garden-irrigation_comparison.json').is_file()


def test_tampered_report_hash_is_not_exposed(history_root):
    root, good, _ = history_root
    pdf = good / 'results' / 'garden-irrigation_executive_report.pdf'
    pdf.write_bytes(b'%PDF-tampered')
    record = comparison_history.comparison_detail('1' * 32, root=root)
    assert record['recommendation_count'] == 3 and record['report_status'] == 'unavailable'
    with pytest.raises(FileNotFoundError):
        comparison_history.artifact('1' * 32, 'pdf', root=root)


def test_dashboard_navigation_and_recommendation_renderer_use_selected_id_and_full_detail():
    root = Path(__file__).resolve().parents[1]
    html = (root / 'frontend/index.html').read_text(encoding='utf-8')
    app = (root / 'frontend/js/app.js').read_text(encoding='utf-8')
    renderer = (root / 'frontend/js/recommendations.js').read_text(encoding='utf-8')
    assert 'data-page="history"' in html and 'id="history"' in html
    assert "api/comparisons/history" in app and "api/comparisons/${encodeURIComponent(investigationId)}" in app
    assert 'state.recommendations' not in app and 'Implementation details and evidence' in renderer
    assert 'Back to Comparison History' in html
    navigation = app[app.index('function showPage'):app.index("$$('.nav')")]
    assert 'fetch(' not in navigation
