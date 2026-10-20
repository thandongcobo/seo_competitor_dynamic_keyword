"""Run one local Gemma specialist request against Stage 1 evidence packets."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from llm_foundation.inference import TASKS, load_config, run_specialist, write_json


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--keyword', required=True)
    p.add_argument('--task', choices=TASKS, default='onpage')
    p.add_argument('--attempts', type=int, default=2)
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    # Stage 1 already defines output location from keyword. No path traversal.
    import re
    slug = re.sub(r'[^a-z0-9]+', '_', args.keyword.lower()).strip('_')
    if not slug:
        p.error('Invalid keyword')
    results_dir = Path('output') / 'results' / slug
    folder = results_dir / 'llm_foundation'
    packet = folder / f'{args.task}_evidence.json'
    if not packet.exists():
        p.error(f'Missing {packet}; first run python -m scripts.build_llm_foundation --keyword "{args.keyword}"')
    evidence = json.loads(packet.read_text(encoding='utf-8'))
    actual = (evidence.get('investigation') or {}).get('keyword')
    if actual and actual.casefold() != args.keyword.casefold():
        p.error('Evidence keyword mismatch; rebuild the foundation for this keyword')
    root = Path(__file__).resolve().parents[1] / 'llm_foundation'
    skills = (root / 'skills.md').read_text(encoding='utf-8')
    instructions = (root / 'prompts' / f'{args.task}.md').read_text(encoding='utf-8')
    if args.dry_run:
        print(f'DRY RUN: task={args.task}; packet={packet}; no API request')
        return
    from openai import OpenAI
    config = load_config()
    client = OpenAI(base_url=config['base_url'], api_key=config['api_key'], max_retries=0)
    result, metadata = run_specialist(args.task, evidence, client=client,
                                      model=config['model'], skills=skills,
                                      instructions=instructions, attempts=args.attempts,
                                      diagnostic_dir=results_dir / 'llm_outputs' / 'diagnostics')
    out = results_dir / 'llm_outputs' / f'{args.task}_validated.json'
    write_json(out, result)
    write_json(out.with_name(f'{args.task}_run_metadata.json'), metadata)
    print(f'Validated {args.task} response saved: {out}')
    print(f'Findings: {len(result["findings"])}; attempts: {metadata["attempts"]}')

if __name__ == '__main__':
    main()
