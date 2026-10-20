import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1] / 'llm_foundation'

@pytest.fixture
def modules(monkeypatch):
    pkg = types.ModuleType('llm_foundation')
    pkg.__path__ = [str(ROOT)]
    monkeypatch.setitem(sys.modules, 'llm_foundation', pkg)
    contracts = types.ModuleType('llm_foundation.contracts')
    contracts.SPECIALIST_OUTPUT = {'type':'object', 'properties': {'findings': {'type':'array', 'items': {'type':'object', 'properties': {'counterevidence': {'type':'string'}}}}}}
    contracts.EXECUTIVE_OUTPUT = {'type':'object'}
    monkeypatch.setitem(sys.modules, 'llm_foundation.contracts', contracts)
    for name in ('validate','output_repair'):
        sys.modules.pop('llm_foundation.' + name, None)
    from llm_foundation import validate, output_repair
    return validate, output_repair

def evidence():
    return {'evidence': {'technical': {'detailed_analysis': {'investigations': [{'measurement': {'display': '6 s'}, 'affected_resources': ['script.js']}]}, 'mobile_audits': {'ours': {'scores': {'performance': 28}}}}}}

def test_bracket_and_dot_indices(modules):
    validate, _ = modules
    assert validate.path_exists(evidence(), 'evidence.technical.detailed_analysis.investigations[0].measurement.display')
    assert validate.path_exists(evidence(), 'evidence.technical.detailed_analysis.investigations.0.measurement')
    assert not validate.path_exists(evidence(), 'evidence.technical.detailed_analysis.investigations[2].measurement')
    assert not validate.path_exists(evidence(), 'evidence.technical.detailed_analysis.investigations[abc]')

def test_repair_exact_prefix_and_null(modules):
    validate, repair = modules
    original = {'findings': [{'counterevidence': None, 'evidence_paths': ['evidence.detailed_analysis.investigations[0].measurement', 'evidence.serp.technical.mobile_audits.ours.scores.performance']}]}
    fixed, log = repair.repair_output(original, evidence(), 'technical')
    assert len(log) == 3
    assert original['findings'][0]['counterevidence'] is None
    assert validate.validate_output(fixed, evidence()) == []

def test_unknown_reference_rejected(modules):
    validate, repair = modules
    original = {'findings': [{'counterevidence': 'none', 'evidence_paths': ['evidence.detailed_analysis.investigations[3].measurement']}]}
    fixed, log = repair.repair_output(original, evidence(), 'technical')
    assert log == []
    assert validate.validate_output(fixed, evidence())

def test_missing_fields_not_fabricated(modules):
    _, repair = modules
    original = {'findings': [{'evidence_paths': []}]}
    fixed, log = repair.repair_output(original, evidence(), 'technical')
    assert fixed == original and not log

def test_onpage_prefix(modules):
    _, repair = modules
    source = {'evidence': {'onpage': {'comparison': {'title_keyword_match': {'ours': False}}}}}
    fixed, log = repair.repair_output({'findings':[{'evidence_paths':['evidence.comparison.title_keyword_match']}]}, source, 'onpage')
    assert fixed['findings'][0]['evidence_paths'][0] == 'evidence.onpage.comparison.title_keyword_match'
    assert len(log) == 1
