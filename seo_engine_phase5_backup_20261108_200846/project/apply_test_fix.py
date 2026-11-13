"""Patch the existing diagnostic test in place without overwriting newer fixtures."""
from pathlib import Path

path = Path('tests/test_inference_diagnostics.py')
if not path.is_file():
    raise SystemExit(f'Cannot find {path}. Run from the SEO project root.')
text = path.read_text(encoding='utf-8')
anchor = "validation.validate_output = lambda result, evidence: []"
addition = "validation.path_exists = lambda evidence, path: True"
if addition in text:
    print('Already patched:', path)
elif anchor not in text:
    raise SystemExit('Expected validator mock not found; no changes made.')
else:
    backup = path.with_suffix('.py.bak')
    backup.write_text(text, encoding='utf-8')
    path.write_text(text.replace(anchor, anchor + '\n' + addition, 1), encoding='utf-8')
    print('Updated:', path)
    print('Backup:', backup)
