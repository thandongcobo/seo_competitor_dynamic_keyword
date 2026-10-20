"""Structural and evidence-path validation; semantic correctness still requires review."""
from jsonschema import Draft202012Validator
from .contracts import SPECIALIST_OUTPUT, EXECUTIVE_OUTPUT

import re

_PATH_PART = re.compile(r"([^.\[\]]+)|\[(\d+)\]")

def path_exists(document, path):
    """Resolve dotted keys and either .0 or [0] list indexes."""
    if not isinstance(path, str) or not path or path.startswith('.') or path.endswith('.'):
        return False
    current = document
    for segment in path.split('.'):
        matches = list(_PATH_PART.finditer(segment))
        if not matches or ''.join(m.group(0) for m in matches) != segment:
            return False
        for m in matches:
            key, index = m.group(1), m.group(2)
            if key is not None and isinstance(current, dict) and key in current:
                current = current[key]
            elif key is not None and isinstance(current, list) and key.isdecimal() and int(key) < len(current):
                current = current[int(key)]
            elif index is not None and isinstance(current, list) and int(index) < len(current):
                current = current[int(index)]
            else:
                return False
    return True

def validate_output(result, evidence, *, executive=False):
    schema = EXECUTIVE_OUTPUT if executive else SPECIALIST_OUTPUT
    errors = [str(e) for e in Draft202012Validator(schema).iter_errors(result)]
    records = (result.get('key_findings',[])+result.get('proposed_decisions',[])) if executive else result.get('findings',[])
    for record in records:
        if isinstance(record,dict):
            for path in record.get('evidence_paths',[]):
                if not path_exists(evidence,path):
                    errors.append('Unknown evidence path: '+str(path))
    return errors
