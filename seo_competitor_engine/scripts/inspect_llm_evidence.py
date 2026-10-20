"""Inspect comparison JSON structure without printing raw evidence values."""
import argparse
import json
from pathlib import Path

SECTIONS = (
    'ranking_summary', 'primary_ranking_urls', 'page_level_evidence',
    'domain_level_evidence', 'onpage_comparison', 'backlink_comparison',
    'technical_comparison', 'advanced_evidence', 'keyword_comparison',
    'intent_alignment', 'evidence_quality',
)


def describe(value):
    if isinstance(value, dict):
        return f'OBJECT ({len(value)} fields)'
    if isinstance(value, list):
        return f'ARRAY ({len(value)} items)'
    if isinstance(value, bool):
        return 'BOOLEAN'
    if isinstance(value, (int, float)):
        return 'NUMBER'
    if isinstance(value, str):
        return 'STRING'
    return 'NULL' if value is None else type(value).__name__


def inspect(value, depth=0, max_depth=2):
    if depth > max_depth:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            print(f"{'  ' * depth}{key}: {describe(item)}")
            if isinstance(item, dict):
                inspect(item, depth + 1, max_depth)
            elif isinstance(item, list) and item:
                print(f"{'  ' * (depth + 1)}[first item schema]")
                inspect(item[0], depth + 2, max_depth)


def main():
    parser = argparse.ArgumentParser(description='Offline SEO comparison JSON schema inspection')
    parser.add_argument('--file', default='output/results/aviator/aviator_comparison.json')
    args = parser.parse_args()
    path = Path(args.file)
    if not path.is_file():
        parser.error(f'File not found: {path.resolve()}')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        parser.error('JSON root must be an object')
    print('=== SEO LLM EVIDENCE SCHEMA INSPECTION ===')
    print('Source file:', path)
    print('Schema version:', data.get('schema_version'))
    print('\n--- TOP LEVEL ---')
    inspect(data, max_depth=0)
    for section in SECTIONS:
        print(f'\n--- {section} ---')
        inspect(data.get(section), max_depth=2)
    for name in ('findings', 'recommendations', 'potential_competitors'):
        value = data.get(name)
        print(f'\n{name} count:', len(value) if isinstance(value, list) else 'N/A')
        if isinstance(value, list) and value:
            print('First item schema:')
            inspect(value[0], max_depth=2)
    print('\nINSPECTION COMPLETE')


if __name__ == '__main__':
    main()
