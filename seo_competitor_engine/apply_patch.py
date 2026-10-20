"""Integrate structured-fact publishing into the installed executive_synthesis.py.
Creates a backup and refuses unfamiliar layouts instead of replacing the module.
"""
from pathlib import Path
import shutil

p = Path('llm_foundation/executive_synthesis.py')
if not p.is_file():
    raise SystemExit('Run from SEO project root; missing ' + str(p))
s = p.read_text(encoding='utf-8')
if 'publish_verified_response(parsed,packet)' in s or 'publish_verified_response(parsed, packet)' in s:
    print('Structured-fact publishing already integrated; no changes made.')
    raise SystemExit(0)
needle = '   parsed=parse_response(choice.message.content)'
if s.count(needle) != 1:
    raise SystemExit('Unsupported executive_synthesis.py layout; original left unchanged.')
# Validate the raw response structurally and by evidence ID, then replace free-form
# metric claims with deterministic facts before final acceptance.
s = s.replace(needle, needle + "\n   raw_errors=[e.message for e in Draft202012Validator(SCHEMA).iter_errors(parsed)]\n   if raw_errors: raise ValueError('; '.join(raw_errors[:4]))\n   parsed, publication_repairs = publish_verified_response(parsed,packet)")
# Insert import near existing imports.
import_line = 'from llm_foundation.structured_facts import publish_verified_response\n'
if import_line not in s:
    s = import_line + s
# Preserve existing validation and any installed factual checks; metadata additions
# do not modify the response schema.
return_line = "   return parsed,{'attempts':i+1,'input_estimated_tokens':estimate,'status':'validated'}"
if s.count(return_line) == 1:
    s = s.replace(return_line, "   return parsed,{'attempts':i+1,'input_estimated_tokens':estimate,'status':'validated','publication_repairs':publication_repairs}")
backup = p.with_suffix('.py.pre_structured_fix.bak')
if not backup.exists():
    shutil.copy2(p, backup)
p.write_text(s, encoding='utf-8')
print('Patched', p, '| backup:', backup)
