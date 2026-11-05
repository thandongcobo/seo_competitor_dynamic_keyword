"""Regression tests for evidence-based numeric claims vs implementation syntax."""
import json
from pathlib import Path

from llm_foundation.executive_synthesis import build_packet, validate_executive, _numeric_claims


def aviator_packet():
    root = Path('output/results/aviator')
    canonical = json.loads((root / 'llm_foundation' / 'canonical_evidence.json').read_text(encoding='utf-8'))
    specialists = {task: json.loads((root / 'llm_outputs' / f'{task}_validated.json').read_text(encoding='utf-8'))
                   for task in ('onpage', 'backlinks', 'technical', 'competition')}
    return build_packet(canonical, specialists)


def result(plan_step=None, summary='Review the captured page titles.'):
    out = {'schema_version':'1.0','status':'usable', 'executive_summary':summary,
           'executive_summary_evidence_ids':['ON_TITLE'], 'key_findings':[],
           'proposed_decisions':[], 'limitations':[]}
    if plan_step is not None:
        out['implementation_plans'] = [{'title':'Review page title', 'rationale':'The title differs.',
                                        'owner':'SEO', 'priority':'medium',
                                        'implementation_steps':[plan_step],
                                        'success_measure':'Verify the title.',
                                        'uncertainty':'No causal ranking proof.',
                                        'evidence_ids':['ON_TITLE'],
                                        'specialist_finding_ids':['ONPAGE_01']}]
    return out


def test_dates_urls_colors_and_procedural_counts_are_not_measurements():
    s = ('Review the release dated 2026-10-08 and CSS color #38608A, '
         'then run 3 tests using https://example.org/v6.08/file.html and record outcomes.')
    assert _numeric_claims(s, implementation_step=True) == []


def test_non_metric_instructions_not_rejected():
    packet = aviator_packet()
    s = ('Review the release dated 2026-10-08 and CSS color #38608A, '
         'then run 3 tests using https://example.org/v6.08/file.html and record outcomes.')
    assert validate_executive(result(s), packet) == []


def test_unsupported_measured_lcp_in_step_rejected():
    packet = aviator_packet()
    errs = validate_executive(result('The tracked page LCP was 9999 ms; investigate the cause.'), packet)
    assert any('9999' in e and 'numeric claim' in e for e in errs), errs


def test_unsupported_measured_backlinks_in_step_rejected():
    packet = aviator_packet()
    errs = validate_executive(result('The page has 987654 referring domains; fix the links.'), packet)
    assert any('987654' in e for e in errs), errs


def test_unsupported_numeric_claim_in_summary_rejected():
    packet = aviator_packet()
    errs = validate_executive(result(summary='The page has 987654 backlinks.'), packet)
    assert any('987654' in e for e in errs), errs


def test_technical_identifier_in_summary_is_not_metric():
    packet = aviator_packet()
    errs = validate_executive(result(summary='Review the CSS color #38608A in the design system.'), packet)
    assert not any('numeric claim' in e for e in errs), errs


def test_non_numeric_unsupported_citation_still_rejected():
    packet = aviator_packet()
    r = result('Review the title for the target keyword.')
    r['executive_summary_evidence_ids'] = ['FAKE_ID']
    errs = validate_executive(r, packet)
    assert any('Unknown evidence ID' in e for e in errs), errs
