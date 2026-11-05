"""Conservative, checkpointed field-level repair of quality-flagged SEO recommendations.

No collectors. This module never edits its input and never replaces unflagged plans.
The published original and complete raw model responses remain separate audit artifacts.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re

from .executive_synthesis import SCHEMA, parse_response, validate_executive
from .recommendation_quality import (audit_recommendations, internal_link_direction_matches,
    unmeasured_loss_fields, query_scope_ready, missing_post_change_verification,
    missing_technical_safeguards, audience_mismatch)

REPAIR_VERSION = 'quality-field-repair-v4-scope-and-depth'
TARGET = re.compile(r'^(implementation_plans|finding_dispositions)\[(\d+)\]$')
PLAN_FIELDS = frozenset(('title', 'rationale', 'implementation_steps', 'success_measure',
                         'uncertainty', 'simple_explanation', 'technical_explanation'))
FINDING_FIELDS = frozenset(('simple_explanation', 'technical_explanation', 'next_step', 'reason'))

# Use the exact same detector as the quality gate. A separate regex here used to
# disagree with the gate and allowed Gemma to miss required repair fields.
def _field_diagnostics(row, issues):
    if 'internal_link_direction' not in {issue.get('code') for issue in issues}:
        return []
    return internal_link_direction_matches(row)


def _required_field_targets(row, issues):
    """Return editable fields and individual list entries implicated by the gate."""
    diagnostics = _field_diagnostics(row, issues)
    fields = {item['field'] for item in diagnostics}
    codes = {issue.get('code') for issue in issues}
    if 'unmeasured_user_loss' in codes:
        fields.update(unmeasured_loss_fields(row))
    if 'domain_rank_scope' in codes and not query_scope_ready(row):
        fields.add('implementation_steps')
    if 'missing_post_change_verification' in codes and missing_post_change_verification(row):
        fields.add('implementation_steps')
    if 'missing_technical_safeguards' in codes and missing_technical_safeguards(row):
        fields.add('implementation_steps')
    if 'audience_explanation_mismatch' in codes and audience_mismatch(row):
        fields.add('simple_explanation')
    if 'generic_non_actionable_plan' in codes:
        fields.update(('title', 'rationale', 'implementation_steps', 'success_measure',
                       'simple_explanation', 'technical_explanation'))
    if 'arbitrary_implementation_target' in codes:
        fields.update(('implementation_steps', 'success_measure', 'rationale', 'uncertainty'))
    if 'unsupported_causal_ranking_claim' in codes:
        fields.update(('rationale', 'simple_explanation', 'technical_explanation', 'uncertainty'))
    if 'thin_technical_explanation' in codes:
        fields.add('technical_explanation')
    return sorted(fields)


def _top_level_field(field):
    return field.split('[', 1)[0]


def _verify_required_changes(before, patch, after, required_targets):
    """Require a substantive change to each implicated field/list item."""
    fields = patch['fields']
    missing = sorted({_top_level_field(field) for field in required_targets} - set(fields))
    unchanged = []
    for field in required_targets:
        root = _top_level_field(field)
        if root not in fields:
            continue
        if '[' in field:
            index = int(field.partition('[')[2].rstrip(']'))
            old_value = before[root][index]
            new_value = after[root][index]
        else:
            old_value = before[root]
            new_value = after[root]
        if old_value == new_value:
            unchanged.append(field)
    if missing or unchanged:
        raise ValueError('Incomplete field repair: ' + json.dumps({
            'required_targets': required_targets,
            'missing_patch_fields': missing,
            'unchanged_flagged_targets': unchanged,
            'still_flagged_fields': [{'field': target} for target in required_targets
                                     if _top_level_field(target) in missing or target in unchanged],
            'instruction': 'Return replacements for ALL listed fields; for a list, '
                           'return the full list while changing every flagged item.'
        }, ensure_ascii=False))


def _issue_specific_instructions(issues):
    codes = {issue.get('code') for issue in issues}
    instructions = []
    if 'internal_link_direction' in codes:
        instructions.append(
            'INTERNAL LINK SCOPE: The measured counts describe outgoing links present ON each '
            'captured page, not incoming links pointing TO the page. Review EVERY editable field '
            '(rationale, technical explanation, simple explanation, implementation steps, '
            'success measure, uncertainty, title). Remove or qualify every inference of incoming '
            'link volume, page authority, or link equity from those outgoing counts. '
            'You MAY propose an independent, separate incoming-link audit, explicitly stating its data has '
            'not been collected. Prefer checking useful outgoing destinations, placement, '
            'anchors, navigation and crawlability. Do not merely append a disclaimer while '
            'retaining the misleading inference elsewhere. Preserve valid details and steps.'
        )
    if 'unmeasured_user_loss' in codes:
        instructions.append('Replace claims of lost users/traffic with measured search visibility differences. '
                            'Do not imply lost clicks without actual click analytics.')
    if 'domain_rank_scope' in codes:
        instructions.append('BEFORE any new content step, explicitly verify the exact ranking URL for '
                            'EACH related query and confirm user intent and existing page coverage. '
                            'Domain-level ranking observations do not identify the ranking page.')
    if 'missing_post_change_verification' in codes:
        instructions.append('Add a repeatable post-change verification AFTER the final implementation step.')
    if 'missing_technical_safeguards' in codes:
        instructions.append('For code/script changes, add regression, business-critical functionality '
                            'and security/consent safeguards appropriate to the system.')
    if 'audience_explanation_mismatch' in codes:
        instructions.append('Align simplified and technical explanations: neither may promise an '
                            'unverified traffic or ranking outcome.')
    if 'generic_non_actionable_plan' in codes:
        instructions.append('Replace investigation-only wording with one specific implementation change supported by the cited facts. '
                            'Keep any audit as a prerequisite, then state the actual change and a measurable post-change check. '
                            'If no safe action is supported, do not convert it into a plan; preserve it as an unresolved disposition.')
    if 'arbitrary_implementation_target' in codes:
        instructions.append('Remove unsupported numeric quotas or thresholds. Specify observable success conditions without arbitrary counts.')
    if 'unsupported_ranking_causation' in codes:
        instructions.append('Rephrase observed differences as non-causal evidence and describe only a qualified hypothesis.')
    return instructions


def _core(result):
    """Published executive JSON has extra read-only factual/specialist attachments."""
    return {key: copy.deepcopy(value) for key, value in result.items() if key in SCHEMA['properties']}


def evidence_errors(result, packet):
    return validate_executive(_core(result), packet)


def _quality_audit(result, expected):
    focused = result.get('recommendation_engine') == 'four_specialist_focused_v4'
    return audit_recommendations(result, expected_findings=expected,
        require_actionable=focused, enforce_causation=focused,
        enforce_unmeasured_loss=focused)


def flagged_targets(report, include_review=False):
    targets = {}
    for issue in report.get('issues', []):
        if issue.get('severity') != 'blocking' and not include_review:
            continue
        path = issue.get('path', '')
        if isinstance(path, str) and TARGET.fullmatch(path):
            targets.setdefault(path, []).append(issue)
    return targets


def _locate(result, path):
    match = TARGET.fullmatch(path)
    if not match:
        raise ValueError('Only exact plan or finding-disposition entries can be repaired')
    section, index = match.group(1), int(match.group(2))
    row = result[section][index]
    if not isinstance(row, dict):
        raise ValueError('Repair target must be an object')
    return row, PLAN_FIELDS if section == 'implementation_plans' else FINDING_FIELDS


def repair_request(result, packet, path, issues):
    row, allowed = _locate(result, path)
    refs = set(row.get('evidence_ids') or [])
    facts = [fact for fact in packet.get('facts', []) if fact.get('id') in refs]
    finding_ids = set(row.get('specialist_finding_ids') or [])
    if path.startswith('finding_dispositions'):
        finding_ids.add(row.get('specialist_finding_id'))
    specialists = [f for f in packet.get('specialist_findings', []) if f.get('id') in finding_ids]
    context = {
        'keyword': packet.get('keyword'), 'tracked': packet.get('tracked'),
        'benchmark': packet.get('benchmark'), 'target_path': path,
        'target_object': row, 'quality_issues': issues,
        'approved_facts_cited_by_target': facts, 'original_specialist_findings': specialists,
        'permitted_fields': sorted(allowed),
        'field_diagnostics': _field_diagnostics(row, issues),
        'required_field_targets': _required_field_targets(row, issues),
        'required_patch_fields': sorted({_top_level_field(f) for f in _required_field_targets(row, issues)}),
        'issue_specific_instructions': _issue_specific_instructions(issues),
    }
    system = (
        'You are repairing ONLY a quality-flagged SEO recommendation object. Return a JSON object '
        'with exactly one key "fields", whose value is an object mapping permitted field names to replacements. '
        'Change the smallest number of fields necessary to fix all supplied quality issues, '
        'but inspect every editable field for the same error before returning a patch. '
        'Every required_field_target MUST be substantively corrected in this ONE patch. '
        'For implementation_steps[n], return the ENTIRE implementation_steps list and rewrite '
        'that specific step, preserving unrelated steps and the existing step count. '
        'For success_measure, replace the complete success_measure string. '
        'Do not submit a partial patch that fixes only one required field. '
        'Keep valid information, specificity, measurements and implementation steps. '
        'Never invent SEO data, traffic, Google ranking causes, or expected ranking improvements. '
        'Distinguish incoming internal links from links found on the current page; domain-level '
        'keyword ranks are not exact page ranks. Use conditional language for unverified conclusions. '
        'For technical steps, explain prerequisites, concrete execution, safeguards and verification. '
        'For business explanations, use plain English and qualify unverified effects. '
        'Do not edit identifiers, priorities, owners, evidence references, plan links, or any other objects. '
        'Preserve the original step count or add steps; do not silently discard established details. '
        'Return JSON only, no markdown.'
    )
    return system, json.dumps(context, ensure_ascii=False, separators=(',', ':'))


def apply_patch(result, path, patch):
    """Exact allowlist, same types, no deletions, no edits outside the target."""
    updated = copy.deepcopy(result)
    old, allowed = _locate(updated, path)
    if not isinstance(patch, dict) or set(patch) != {'fields'} or not isinstance(patch['fields'], dict):
        raise ValueError('Patch must contain exactly a fields object')
    fields = patch['fields']
    if not fields or not set(fields).issubset(allowed & set(old)):
        raise ValueError('Patch contains empty, protected or unknown fields')
    for key, value in fields.items():
        previous = old[key]
        if type(previous) is not type(value):
            raise ValueError('Patch changed field type: ' + key)
        if isinstance(value, str) and not value.strip():
            raise ValueError('Patch erased field: ' + key)
        if isinstance(value, list):
            if len(value) < len(previous) or not all(isinstance(x, str) and x.strip() for x in value):
                raise ValueError('Patch removed implementation steps or produced empty steps')
        old[key] = copy.deepcopy(value)
    return updated


def quality_fingerprint(result, packet, model, include_review):
    data = json.dumps({'version': REPAIR_VERSION, 'result': result, 'packet': packet,
                       'model': model, 'include_review': include_review},
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def repair_with_client(original, packet, client, model, *, attempts=2, include_review=False,
                       max_output_tokens=1800, timeout=120, on_event=None):
    """Repair flagged objects sequentially; audit every patch; never mutate original.

    on_event(event) receives original model text and a validated patch checkpoint.
    """
    if attempts < 1 or attempts > 3:
        raise ValueError('attempts must be between 1 and 3')
    baseline_errors = evidence_errors(original, packet)
    if baseline_errors:
        raise ValueError('Original response fails existing factual validation: ' + '; '.join(baseline_errors[:4]))
    expected = [f['id'] for f in packet.get('specialist_findings', [])]
    before = _quality_audit(original, expected)
    targets = flagged_targets(before, include_review)
    candidate = copy.deepcopy(original)
    audit_log = []
    for path, original_issues in targets.items():
        current_report = _quality_audit(candidate, expected)
        current = [issue for issue in current_report['issues'] if issue.get('path') == path and
                   (include_review or issue['severity'] == 'blocking')]
        if not current:
            continue
        system, body = repair_request(candidate, packet, path, current)
        target_row, _ = _locate(candidate, path)
        required_targets = _required_field_targets(target_row, current)
        feedback = ''
        success = False
        for attempt in range(1, attempts + 1):
            prompt = body + (('\nPREVIOUS_REPAIR_ERRORS: ' + feedback) if feedback else '')
            try:
                response = client.chat.completions.create(
                    model=model, messages=[{'role': 'system', 'content': system},
                                           {'role': 'user', 'content': prompt}],
                    temperature=0.1, max_tokens=max_output_tokens, timeout=timeout)
                choice = response.choices[0]
                raw = choice.message.content or ''
                event = {'path': path, 'attempt': attempt, 'raw_response': raw,
                         'finish_reason': choice.finish_reason}
                if on_event:
                    on_event({'kind': 'raw', **event})
                if choice.finish_reason == 'length':
                    raise ValueError('Model output truncated')
                patch = parse_response(raw)
                proposed = apply_patch(candidate, path, patch)
                revised_row, _ = _locate(proposed, path)
                _verify_required_changes(target_row, patch, revised_row, required_targets)
                errors = evidence_errors(proposed, packet)
                if errors:
                    raise ValueError('Evidence/schema validation: ' + '; '.join(errors[:6]))
                after_report = _quality_audit(proposed, expected)
                old_other = {(i['severity'], i['code'], i['path']) for i in current_report['issues'] if i.get('path') != path}
                new_other = {(i['severity'], i['code'], i['path']) for i in after_report['issues'] if i.get('path') != path}
                if not new_other.issubset(old_other):
                    raise ValueError('Repair introduced issues in previously unaffected objects')
                old_target = {(i['severity'], i['code']) for i in current}
                new_target = {(i['severity'], i['code']) for i in after_report['issues'] if i.get('path') == path and
                              (include_review or i['severity'] == 'blocking')}
                if not new_target < old_target:
                    remaining = [i for i in after_report['issues'] if i.get('path') == path and
                                 (include_review or i['severity'] == 'blocking')]
                    revised, _ = _locate(proposed, path)
                    guidance = {'remaining_issue_codes': [i['code'] for i in remaining],
                                'still_flagged_fields': _field_diagnostics(revised, remaining),
                                'instruction': 'Correct all remaining flagged wording in every affected field; '
                                               'do not just append a disclaimer.'}
                    raise ValueError('Repair did not strictly reduce flagged issues: ' +
                                     json.dumps(guidance, ensure_ascii=False))
                candidate = proposed
                success = True
                item = {'path': path, 'attempt': attempt, 'changed_fields': list(patch['fields']),
                        'required_field_targets': required_targets,
                        'fixed_issue_codes': sorted(code for _, code in old_target - new_target)}
                audit_log.append(item)
                if on_event:
                    on_event({'kind': 'accepted', 'record': item, 'candidate': copy.deepcopy(candidate)})
                break
            except (ValueError, TypeError, KeyError, IndexError, AttributeError, json.JSONDecodeError) as exc:
                feedback = str(exc)[:900]
                if on_event:
                    on_event({'kind': 'rejected', 'path': path, 'attempt': attempt, 'error': feedback})
        if not success:
            audit_log.append({'path': path, 'status': 'unresolved', 'last_error': feedback})
    after = _quality_audit(candidate, expected)
    return candidate, {'schema_version': '1.0', 'before': before, 'after': after,
                       'repairs': audit_log, 'all_blocking_resolved': after['blocking_count'] == 0,
                       'original_unchanged': True}
