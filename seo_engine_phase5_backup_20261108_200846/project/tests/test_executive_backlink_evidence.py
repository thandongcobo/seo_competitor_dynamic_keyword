"""Regression checks using real saved Aviator evidence and rejected Gemma outputs.
No network, Google, DataForSEO, Lighthouse or Gemma requests.
"""
import json
from pathlib import Path
from llm_foundation.executive_synthesis import build_packet, validate_executive

TASKS = ('onpage', 'backlinks', 'technical', 'competition')


def _packet():
    root = Path('output/results/aviator')
    canonical = json.loads((root / 'llm_foundation' / 'canonical_evidence.json').read_text(encoding='utf-8'))
    specialists = {task: json.loads((root / 'llm_outputs' / f'{task}_validated.json').read_text(encoding='utf-8')) for task in TASKS}
    return build_packet(canonical, specialists)


def _gemma_response(attempt):
    path = Path(__file__).with_name('fixtures') / 'executive_model_raw_invalid_20261022.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    raw = data['attempts'][attempt - 1]['raw_response'].strip()
    if raw.startswith('```json'):
        raw = raw[7:].strip()
    if raw.endswith('```'):
        raw = raw[:-3].strip()
    return json.loads(raw)


def test_saved_backlink_totals_promoted_to_approved_facts():
    packet = _packet()
    facts = {row['id']: row for row in packet['facts']}
    assert facts['BL_DOMAIN']['values']['ours']['backlinks'] == 1806871
    assert facts['BL_DOMAIN']['values']['benchmark']['backlinks'] == 578056
    assert facts['BL_PAGE']['values']['ours']['backlinks'] == 1853
    assert facts['BL_PAGE']['values']['benchmark']['backlinks'] == 2809
    assert facts['BL_DOMAIN']['values']['ours']['referring_domains'] == 8050


def test_real_second_response_no_missing_backlink_total_errors():
    errors = validate_executive(_gemma_response(2), _packet())
    assert not any('1,806,871' in e or '578,056' in e for e in errors), errors


def test_real_first_response_still_rejects_link_density_claim():
    errors = validate_executive(_gemma_response(1), _packet())
    assert any('density' in e.lower() for e in errors), errors


def test_unobserved_backlink_number_is_rejected():
    packet = _packet()
    response = _gemma_response(2)
    response['executive_summary'] = 'The tracked domain has 9,999,999 backlinks.'
    response['executive_summary_evidence_ids'] = ['BL_DOMAIN']
    errors = validate_executive(response, packet)
    assert any('9,999,999' in e for e in errors), errors


def test_missing_backlink_totals_not_invented():
    root = Path('output/results/aviator')
    canonical = json.loads((root / 'llm_foundation' / 'canonical_evidence.json').read_text(encoding='utf-8'))
    for scope in ('domain', 'page'):
        for side in ('ours', 'benchmark'):
            canonical['evidence']['backlinks'][scope][side].pop('backlinks', None)
    specialists = {task: json.loads((root / 'llm_outputs' / f'{task}_validated.json').read_text(encoding='utf-8')) for task in TASKS}
    packet = build_packet(canonical, specialists)
    fact = next(f for f in packet['facts'] if f['id'] == 'BL_DOMAIN')
    assert fact['values']['ours']['backlinks'] is None
    errors = validate_executive(_gemma_response(2), packet)
    assert any('1,806,871' in e for e in errors), errors


def test_real_second_response_still_requires_serp_citation_for_rank_claim():
    errors = validate_executive(_gemma_response(2), _packet())
    assert any('key_findings[4]' in e and 'numeric claim 1' in e for e in errors), errors
