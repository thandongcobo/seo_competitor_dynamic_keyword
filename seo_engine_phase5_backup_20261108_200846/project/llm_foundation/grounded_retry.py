"""Conservative, keyword-independent numeric/citation diagnostics for focused LLM tasks.

Evidence values are measurements, never automatic authority for an arbitrary claim.
Only a citation can be added automatically, and only if its numeric value AND
metric scope are unambiguous and the specialist-finding lineage permits it.
Every change is audited and the original response must still pass all validators.
"""
from __future__ import annotations

import copy
from decimal import Decimal, InvalidOperation
import re

_PATH = re.compile(r"(?P<root>implementation_plans|finding_dispositions)\[(?P<index>\d+)\](?:\.(?P<field>[a-zA-Z_]+)(?:\[(?P<subindex>\d+)\])?)?")
_NUMBER = re.compile(r"numeric claim (?P<number>\d[\d,]*(?:\.\d+)?)\b")
_TEXT_NUMBERS = re.compile(r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\w,]|\.\d)")


def _number(text):
    try:
        return Decimal(str(text).replace(',', ''))
    except (InvalidOperation, ValueError):
        return None


def _numbers(value):
    if isinstance(value, bool) or value is None:
        return set()
    if isinstance(value, (int, float, Decimal)):
        number = _number(value)
        return {number} if number is not None else set()
    if isinstance(value, dict):
        return set().union(*(_numbers(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_numbers(v) for v in value)) if value else set()
    return set()


def _value_at(response, match):
    try:
        row = response[match['root']][int(match['index'])]
        if match['field'] is not None:
            row = row[match['field']]
        if match['subindex'] is not None:
            row = row[int(match['subindex'])]
        return row
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _links(scoped, root, index, response):
    try:
        row = response[root][index]
    except (KeyError, IndexError, TypeError):
        return [], [], []
    if not isinstance(row, dict):
        return [], [], []
    mapping = scoped.get('specialist_fact_links') or {}
    if root == 'implementation_plans':
        findings = row.get('specialist_finding_ids') or []
    else:
        findings = [row.get('specialist_finding_id')]
    allowed = sorted({fact for fid in findings for fact in mapping.get(fid, [])})
    return list(row.get('evidence_ids') or []), allowed, findings


def diagnose_errors(errors, response, scoped):
    """Produce precise, read-only feedback; never claim that matching numbers prove semantics."""
    facts = scoped.get('facts') or []
    numeric_index = {f['id']: _numbers(f.get('values')) for f in facts if isinstance(f, dict) and f.get('id')}
    result = []
    for error in errors:
        match = _PATH.search(str(error))
        if not match:
            result.append({'error': str(error), 'classification': 'unlocalized',
                           'instruction': 'Retain valid fields and correct the stated validation issue.'})
            continue
        groups = match.groupdict()
        root, index = groups['root'], int(groups['index'])
        cited, allowed, findings = _links(scoped, root, index, response)
        current = _value_at(response, groups)
        entry = {'error': str(error), 'path': match.group(), 'current_value': current,
                 'cited_fact_ids': cited, 'permitted_fact_ids': allowed,
                 'specialist_finding_ids': findings}
        number_match = _NUMBER.search(str(error))
        if number_match:
            token = number_match['number']
            n = _number(token)
            matching = sorted(fid for fid, nums in numeric_index.items() if n in nums)
            permitted_matching = [fid for fid in matching if fid in allowed]
            entry.update(classification=('number_not_in_evidence' if not matching else
                         'number_supported_by_other_scope' if not permitted_matching else
                         'number_missing_correct_citation' if not set(permitted_matching).intersection(cited) else
                         'number_needs_context_review'), number=token,
                         matching_fact_ids=matching, permitted_matching_fact_ids=permitted_matching)
            if not matching:
                entry['instruction'] = ('Remove or reword this unsupported numeric assertion. '
                                        'If it is a procedural identifier, make its meaning explicit; '
                                        'do not misrepresent a target as observed data.')
            elif not permitted_matching:
                entry['instruction'] = ('The number occurs in approved evidence but NOT in facts linked '
                                        'to this plan/finding. Remove the claim or explicitly revise '
                                        'specialist coverage and linked dispositions only when semantically justified.')
            elif not set(permitted_matching).intersection(cited):
                entry['instruction'] = ('The number appears in permitted facts. Cite the matching fact '
                                        'only if the sentence accurately describes its metric and scope; '
                                        'otherwise remove or correct the assertion.')
            else:
                entry['instruction'] = ('Check exact measurement type, units and scope; matching a '
                                        'number alone does not prove this assertion is valid.')
        else:
            entry['classification'] = 'lineage_or_structure'
            entry['instruction'] = ('Keep fact citations within the union of the linked specialist findings. '
                                    'Do not add an unrelated finding solely to make an invalid claim pass.')
        result.append(entry)
    return result


def _metric_scope(text, fact_id):
    """Narrow whitelist for safe citation-only correction; otherwise request model review."""
    if not isinstance(text, str):
        return False
    s = text.lower()
    if fact_id == 'BL_DOMAIN':
        return bool(re.search(r'\b(?:domain[- ](?:wide|level)|entire domain|site[- ]wide)\b', s)
                    and re.search(r'\b(?:backlinks?|referring domains?)\b', s))
    if fact_id == 'BL_PAGE':
        return bool(re.search(r'\b(?:page[- ]level|exact[- ]page|ranking page)\b', s)
                    and re.search(r'\b(?:backlinks?|referring domains?)\b', s))
    if fact_id == 'SERP':
        return bool(re.search(r'\b(?:serp|organic rank|google position)\b', s))
    # No auto-fixing arbitrary metric scopes; require explicit human/model review.
    return False


def repair_unambiguous_citations(response, errors, scoped):
    """Add only a uniquely supported and lineage-permitted citation; never rewrite claims.

    Return (copy, audit). All modifications remain provisional until validate_task
    succeeds. This cannot fix cross-specialist link errors or unsupported numbers.
    """
    fixed = copy.deepcopy(response)
    audit = []
    facts = {f['id']: _numbers(f.get('values')) for f in scoped.get('facts', []) if isinstance(f, dict)}
    for issue in diagnose_errors(errors, response, scoped):
        if issue.get('classification') != 'number_missing_correct_citation':
            continue
        matching = issue['permitted_matching_fact_ids']
        if len(matching) != 1:
            continue
        fact_id = matching[0]
        match = _PATH.search(issue['path'])
        groups = match.groupdict()
        root, index = groups['root'], int(groups['index'])
        row = fixed[root][index]
        if not isinstance(row, dict) or fact_id in (row.get('evidence_ids') or []):
            continue
        value = _value_at(response, groups)
        if not _metric_scope(value, fact_id):
            continue
        # The cited number must occur exactly in this fact. Never infer from
        # similarity, magnitude, a neighboring metric or another investigation.
        if _number(issue['number']) not in facts.get(fact_id, set()):
            continue
        # A mixed-metric sentence needs model review, not a mechanical citation.
        cited_numbers = set().union(*(facts.get(fid, set()) for fid in row.get('evidence_ids') or []))
        text_numbers = {_number(m.group()) for m in _TEXT_NUMBERS.finditer(value)}
        if not text_numbers.issubset(facts[fact_id] | cited_numbers):
            continue
        if not isinstance(row.get('evidence_ids'), list):
            continue
        row['evidence_ids'].append(fact_id)
        audit.append({'path': f'{root}[{index}].evidence_ids', 'added_fact_id': fact_id,
                      'trigger_path': issue['path'], 'matched_number': issue['number'],
                      'type': 'citation_only', 'requires_full_revalidation': True})
    return fixed, audit
