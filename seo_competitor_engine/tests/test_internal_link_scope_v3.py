"""Scope-sensitive internal link validation, using no live API requests."""
import copy
import json
from pathlib import Path
from llm_foundation.recommendation_quality import audit_recommendations, internal_link_direction_matches
from llm_foundation.quality_repair import _field_diagnostics, repair_request

FIXTURE = Path(__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'recommendation_quality_saved_output.json'


def original():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


def issue_codes(plan):
    return {i['code'] for i in audit_recommendations({'implementation_plans': [plan],
              'finding_dispositions': [], 'verified_factual_findings': [{}]})['issues']}


def test_original_unqualified_internal_link_inference_still_blocked():
    plan = original()['implementation_plans'][1]
    assert 'internal_link_direction' in issue_codes(plan)
    paths = {m['field'] for m in internal_link_direction_matches(plan)}
    assert 'implementation_steps[1]' in paths
    assert 'success_measure' in paths


def test_independent_incoming_link_audit_allowed_without_pretending_measured():
    plan = copy.deepcopy(original()['implementation_plans'][1])
    plan['rationale'] = 'The captured counts measure outgoing links. Review destinations and navigation relevance.'
    plan['technical_explanation'] = ('The captured counts measure outgoing links only. Independently crawl the site to '
                                    'identify incoming links to the target URL; these have not been measured yet.')
    plan['implementation_steps'][1] = ('Identify high-authority pages within example.test that could potentially link to '
                                       'the landing page through an independent incoming link audit. No inbound counts are available yet.')
    plan['success_measure'] = 'Check approved navigation changes and verify actual crawlability after release.'
    assert 'internal_link_direction' not in issue_codes(plan)
    assert internal_link_direction_matches(plan) == []


def test_disclaimer_alone_does_not_launder_unsupported_link_equity_claim():
    plan = copy.deepcopy(original()['implementation_plans'][1])
    plan['success_measure'] = 'Increase link equity flow and page authority distribution; this is not measured.'
    assert any(x['field'] == 'success_measure' for x in internal_link_direction_matches(plan))


def test_unqualified_inbound_claim_is_still_blocked():
    plan = copy.deepcopy(original()['implementation_plans'][1])
    plan['implementation_steps'][1] = 'High-authority pages will link to the target page to increase authority.'
    assert any(x['field'] == 'implementation_steps[1]' for x in internal_link_direction_matches(plan))


def test_outgoing_links_to_other_parts_are_not_misclassified():
    plan = copy.deepcopy(original()['implementation_plans'][1])
    plan['rationale'] = 'The competitor has more outgoing navigation links; assess relevance.'
    plan['technical_explanation'] = 'Check outgoing link targets and placement.'
    plan['implementation_steps'][1] = 'Inspect outgoing links to related game pages.'
    plan['success_measure'] = 'Verify navigation works after deployment.'
    assert 'internal_link_direction' not in issue_codes(plan)


def test_repair_diagnostics_align_with_validator():
    result = original()
    row = result['implementation_plans'][1]
    issues = [{'code':'internal_link_direction','severity':'blocking'}]
    assert _field_diagnostics(row, issues) == internal_link_direction_matches(row)
    sys, body = repair_request(result, {'facts': [], 'specialist_findings': [], 'keyword':'any'},
                               'implementation_plans[1]', issues)
    assert 'independent' in body.lower()
    assert 'implementation_steps[1]' in body
    assert 'Return JSON' in sys


def test_other_keyword_and_domain_do_not_change_scope_rules():
    plan = copy.deepcopy(original()['implementation_plans'][1])
    raw = json.dumps(plan).replace('aviator', 'sampletopic').replace('hollywoodbets.net','example.test')
    assert 'internal_link_direction' in issue_codes(json.loads(raw))


def test_actual_retry_style_wording_is_allowed_as_an_investigation():
    plan = copy.deepcopy(original()['implementation_plans'][1])
    plan['rationale'] = 'Observed outgoing links differ; assess usefulness rather than claiming link equity.'
    plan['technical_explanation'] = 'The counted links are outgoing only. Incoming links require a separate crawl.'
    plan['success_measure'] = 'Verify destinations and navigation after approved changes.'
    plan['implementation_steps'][1] = (
        'Identify high-authority pages within example.test that could potentially link to '
        'the landing page through an incoming link audit (note: incoming links were not measured in this dataset).'
    )
    assert 'internal_link_direction' not in issue_codes(plan)
