"""Offline-only regression checks for historical executive/report schema compatibility."""
from pathlib import Path

from scripts.run_investigation_offline import historical_pdf_missing_sections


def test_old_executive_can_be_identified_without_inventing_content():
    old = {'executive_summary': 'Historical summary', 'key_findings': [{'statement': 'Observed'}]}
    assert historical_pdf_missing_sections(old) == [
        'implementation plans', 'specialist finding dispositions'
    ]
    assert 'implementation_plans' not in old


def test_missing_verified_facts_is_explicit():
    data = {'implementation_plans': [{'title': 'Audit'}],
            'finding_dispositions': [{'specialist_finding_id': 'X'}]}
    assert historical_pdf_missing_sections(data) == ['verified factual findings']


def test_new_executive_schema_is_eligible_for_existing_quality_gates():
    data = {'implementation_plans': [{'title': 'Audit'}],
            'finding_dispositions': [{'specialist_finding_id': 'X'}],
            'verified_factual_findings': [{'statement': 'Observed'}]}
    assert historical_pdf_missing_sections(data) == []


def test_key_findings_are_accepted_when_verified_facts_are_not_separate():
    data = {'implementation_plans': [{'title': 'Audit'}],
            'finding_dispositions': [{'specialist_finding_id': 'X'}],
            'key_findings': [{'statement': 'Observed'}]}
    assert historical_pdf_missing_sections(data) == []


def test_offline_comparison_remains_independent_of_legacy_pdf():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'scripts/run_investigation_offline.py').read_text(encoding='utf-8')
    js = (root / 'frontend/js/app.js').read_text(encoding='utf-8')
    assert "'processing_status': 'completed'" in source
    assert "'status': ('completed' if report_result['status'] in ('completed', 'not_requested') else 'report_failed')" in source
    assert "'historical_pdf_warning': (" in source
    assert "'pdf_path': str(pdf_path.relative_to(base)) if pdf_path else None" in source
    assert 'historical_pdf_warning' in js
    assert 'await refreshReportingState(manualInvestigationId)' in js
