"""Narrow, auditable repairs for LLM response formatting only."""
from __future__ import annotations
from copy import deepcopy
from .validate import path_exists

MISSING_COUNTEREVIDENCE = "Not available in supplied evidence."

def _candidate_paths(task, path):
    if task == 'technical':
        if path.startswith('evidence.detailed_analysis.'):
            yield 'evidence.technical.' + path[len('evidence.'):]
        if path.startswith('evidence.mobile_audits.'):
            yield 'evidence.technical.' + path[len('evidence.'):]
        if path.startswith('evidence.serp.technical.'):
            yield 'evidence.technical.' + path[len('evidence.serp.technical.'):]
    elif task == 'onpage':
        if path.startswith(('evidence.comparison.', 'evidence.pages.')):
            yield 'evidence.onpage.' + path[len('evidence.'):]
    elif task == 'backlinks':
        if path.startswith(('evidence.page.', 'evidence.domain.')):
            yield 'evidence.backlinks.' + path[len('evidence.'):]
    elif task == 'competition':
        if path.startswith('evidence.intersection.'):
            yield 'evidence.keywords.' + path[len('evidence.'):]

def repair_output(result, evidence, task):
    """Return (copy, repair log). Never guess a measurement or synthesize a path."""
    repaired = deepcopy(result)
    changes = []
    if not isinstance(repaired, dict) or not isinstance(repaired.get('findings'), list):
        return repaired, changes
    for idx, finding in enumerate(repaired['findings']):
        if not isinstance(finding, dict):
            continue
        if finding.get('counterevidence', object()) is None:
            finding['counterevidence'] = MISSING_COUNTEREVIDENCE
            changes.append({'finding': idx, 'field': 'counterevidence', 'type': 'null_to_missing_statement'})
        paths = finding.get('evidence_paths')
        if not isinstance(paths, list):
            continue
        for j, path in enumerate(paths):
            if not isinstance(path, str) or path_exists(evidence, path):
                continue
            candidates = list(dict.fromkeys(p for p in _candidate_paths(task, path) if path_exists(evidence, p)))
            if len(candidates) == 1:
                paths[j] = candidates[0]
                changes.append({'finding': idx, 'field': 'evidence_paths', 'index': j,
                                'type': 'path_prefix', 'from': path, 'to': candidates[0]})
    return repaired, changes
