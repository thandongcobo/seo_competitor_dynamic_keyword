"""Offline execution must reuse real evidence and never collect new data."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import serp_investigations as si
from scripts.run_investigation_offline import retry_report, run
from config.settings import ROOT


def _new(tmp_path, a='https://www.hollywoodbets.net/aviator', b='https://www.betway.co.za/aviator', keyword='aviator'):
    return si.create_page_investigation(keyword, a, b)['investigation_id']


def test_offline_replay_preserves_exact_urls_and_original_sources(tmp_path):
    source = ROOT / 'data/raw/labs/aviator_ranked_ours.json'
    before = source.read_bytes()
    with patch.object(si, 'INVESTIGATIONS', tmp_path):
        investigation_id = _new(tmp_path)
        result = run(investigation_id)
        base = tmp_path / investigation_id
        comparison = json.loads((base / result['comparison_path']).read_text())
        assert comparison['primary_ranking_urls'] == {
            'ours': 'https://www.hollywoodbets.net/aviator',
            'benchmark': 'https://www.betway.co.za/aviator'}
        assert comparison['findings']
        assert (base / result['pdf_path']).read_bytes().startswith(b'%PDF')
        assert result['requests_made'] == result['llm_inference_requests'] == 0
        assert result['historical_serp_datetime']
        assert len(result['source_provenance']) >= 13
        assert result['pdf_status'] == result['technical_appendix_status'] == 'generated'
        assert result['executive_mode'] == 'deterministic_comparison_recommendations'
        assert not (base / 'results/llm_outputs/executive_validated.json').exists()
        assert result['investigation_metadata']['investigation_id'] == investigation_id
        assert result['investigation_metadata']['tracked_page']['url'] == 'https://www.hollywoodbets.net/aviator'
        comparison = json.loads((base / result['comparison_path']).read_text(encoding='utf-8'))
        assert len(comparison['recommendations']) == 9
        assert sum(r['evidence_tier'] == 'tier_1_strong_evidence' for r in comparison['recommendations']) == 3
        assert sum(r['evidence_tier'] == 'tier_2_moderate_evidence' for r in comparison['recommendations']) == 6
        with pytest.raises(ValueError, match='already'):
            run(investigation_id)
    assert source.read_bytes() == before


def test_missing_evidence_rejected_without_outputs(tmp_path):
    with patch.object(si, 'INVESTIGATIONS', tmp_path):
        investigation_id = _new(tmp_path, a='https://www.hollywoodbets.net/other')
        with pytest.raises(ValueError, match='incomplete'):
            run(investigation_id)
        assert not (tmp_path / investigation_id / 'results').exists()


def test_unrelated_keyword_rejected_without_outputs(tmp_path):
    with patch.object(si, 'INVESTIGATIONS', tmp_path):
        investigation_id = _new(tmp_path, keyword='completely different keyword 2026')
        with pytest.raises(ValueError, match='incomplete'):
            run(investigation_id)
        assert not (tmp_path / investigation_id / 'results').exists()


def test_reversed_pages_can_use_existing_comparison_without_mislabelled_pdf(tmp_path):
    with patch.object(si, 'INVESTIGATIONS', tmp_path):
        investigation_id = _new(tmp_path, 'https://www.betway.co.za/aviator', 'https://www.hollywoodbets.net/aviator')
        result = run(investigation_id)
        comparison = json.loads((tmp_path / investigation_id / result['comparison_path']).read_text())
        assert comparison['primary_ranking_urls']['ours'] == 'https://www.betway.co.za/aviator'
        assert comparison['ranking_summary']['google']['our_position'] == 1
        assert result['pdf_path']
        assert result['pdf_status'] == result['technical_appendix_status'] == 'generated'
        assert result['investigation_metadata']['tracked_page']['rank'] == 1


def test_pdf_failure_preserves_comparison_and_report_only_retry(tmp_path):
    from scripts import run_analysis
    from hashlib import sha256
    with patch.object(si, 'INVESTIGATIONS', tmp_path):
        investigation_id = _new(tmp_path)
        with patch('scripts.generate_executive_pdf.build_management_pdf', side_effect=RuntimeError('synthetic PDF failure')):
            failed = run(investigation_id)
        base = tmp_path / investigation_id
        comparison_path = base / failed['comparison_path']
        comparison_before = sha256(comparison_path.read_bytes()).hexdigest()
        comparison = json.loads(comparison_path.read_text(encoding='utf-8'))
        assert failed['status'] == 'report_failed'
        assert failed['processing_status'] == 'completed'
        assert failed['pdf_status'] == 'failed'
        assert failed['technical_appendix_status'] == 'generated'
        assert len(comparison['recommendations']) > 0
        assert not (base / 'results/aviator_executive_report.pdf').exists()
        appendix_before = sha256((base / failed['technical_appendix_path']).read_bytes()).hexdigest()
        with patch.object(run_analysis, 'main', side_effect=AssertionError('analysis must not rerun')):
            retried = retry_report(investigation_id)
        assert retried['status'] == 'completed'
        assert retried['pdf_status'] == retried['technical_appendix_status'] == 'generated'
        assert sha256(comparison_path.read_bytes()).hexdigest() == comparison_before
        assert sha256((base / retried['technical_appendix_path']).read_bytes()).hexdigest() == appendix_before
        assert (base / retried['pdf_path']).read_bytes().startswith(b'%PDF')


def test_dashboard_offline_execution_and_pdf_download(tmp_path):
    import threading
    from http.server import ThreadingHTTPServer
    from urllib.request import Request, urlopen
    from scripts.serve_dashboard import Handler
    with patch.object(si, 'INVESTIGATIONS', tmp_path):
        investigation_id = _new(tmp_path)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}/api/investigations/{investigation_id}'
        try:
            with urlopen(Request(base + '/run-offline', data=b'{}', method='POST')) as response:
                assert response.status == 200
                report = json.load(response)
            assert report['status'] == 'completed'
            with urlopen(base + '/offline-result') as response:
                assert json.load(response)['investigation_id'] == investigation_id
            with urlopen(base + '/report.pdf') as response:
                assert response.headers['Content-Type'] == 'application/pdf'
                assert response.read(4) == b'%PDF'
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
