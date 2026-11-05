"""Offline execution must reuse real evidence and never collect new data."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import serp_investigations as si
from scripts.run_investigation_offline import run
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
        assert (base / 'results/llm_outputs/executive_validated.json').is_file()
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
        with pytest.raises(ValueError, match='PDF'):
            run(investigation_id)
        result = run(investigation_id, generate_pdf=False)
        comparison = json.loads((tmp_path / investigation_id / result['comparison_path']).read_text())
        assert comparison['primary_ranking_urls']['ours'] == 'https://www.betway.co.za/aviator'
        assert comparison['ranking_summary']['google']['our_position'] == 1
        assert result['pdf_path'] is None


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
