import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('request_optimizer_patch', ROOT / 'llm_foundation' / 'request_optimizer.py')
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def packet(task):
    section = {
        'onpage': {'pages': {'ours': {'title': 'Aviator'}, 'benchmark': {'title': 'Aviator Betway'}}, 'comparison': {'title_keyword_match': {'ours': True, 'competitor': True}}},
        'backlinks': {'page': {'ours': {'rank': 18}, 'benchmark': {'rank': 36}}},
        'technical': {'mobile_audits': {'ours': {'scores': {}}, 'benchmark': {'scores': {}}}, 'detailed_analysis': {'status': 'usable'}},
        'competition': None,
    }
    evidence = {'serp': {'ranking_summary': {'our_position': 2, 'benchmark_position': 1}}}
    if task == 'competition':
        evidence['keywords'] = {'intersection': {'status': 'usable'}}
        evidence['competitor_discovery'] = {'candidates': []}
    else:
        evidence[task if task != 'technical' else 'technical'] = section[task]
    return {'schema_version': '1.0', 'task': task, 'investigation': {'keyword': 'aviator'}, 'tracked_website': {'domain': 'hollywoodbets.net'}, 'competitors': [{'domain': 'betway.co.za'}], 'evidence_quality': {}, 'evidence': evidence}


@pytest.mark.parametrize('task,required', [
    ('onpage', 'evidence.onpage.comparison.title_keyword_match'),
    ('backlinks', 'evidence.backlinks'),
    ('technical', 'evidence.technical'),
    ('competition', 'evidence.keywords'),
])
def test_prompt_contains_exact_path_rule(task, required):
    compact, system, prompt, estimate = mod.prepare_request(task, packet(task), skills='Follow evidence.', instructions='Analyse.', max_input_tokens=5000)
    assert required in prompt
    assert required.split('.')[1] in compact['evidence']
    assert estimate > 0


def test_onpage_missing_evidence_still_rejected():
    with pytest.raises(ValueError, match='Missing onpage evidence'):
        mod.prepare_request('onpage', {'evidence': {}}, skills='', instructions='')
