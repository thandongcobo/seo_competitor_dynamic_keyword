"""Audit or selectively repair existing focused SEO recommendations using saved evidence.

Preview mode makes ZERO network requests. --execute contacts ONLY the configured LLM.
No existing executive, collector, dashboard, or specialist files are overwritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from llm_foundation.executive_synthesis import save_json
from llm_foundation.quality_repair import (evidence_errors, flagged_targets, quality_fingerprint,
                                           repair_with_client, _quality_audit)
from llm_foundation.recommendation_quality import audit_recommendations


def run(args, client=None, model=None):
    source = Path(args.input).resolve()
    evidence = Path(args.packet).resolve()
    out = Path(args.output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = json.loads(source.read_text(encoding='utf-8'))
    packet = json.loads(evidence.read_text(encoding='utf-8'))
    expected = [f['id'] for f in packet.get('specialist_findings', [])]
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    errors = evidence_errors(original, packet)
    if errors:
        raise ValueError('Existing evidence validation failed; repair cannot start: ' + '; '.join(errors[:5]))
    before = _quality_audit(original, expected)
    save_json(out / 'quality_repair_preview.json', {
        'original_file': str(source), 'original_sha256': original_hash,
        'blocking_count': before['blocking_count'], 'review_count': before['review_count'],
        'targets': flagged_targets(before, args.include_review),
        'note': 'Preview does not call an LLM or modify the original.'})
    print('Quality repair preview:', before['blocking_count'], 'blocking,', before['review_count'], 'review flags')
    if not args.execute:
        print('Preview saved; no model or external requests.')
        return before
    if client is None:
        from llm_foundation.inference import load_config
        from openai import OpenAI
        config = load_config()
        model = config['model']
        client = OpenAI(base_url=config['base_url'], api_key=config['api_key'],
                        timeout=args.timeout, max_retries=0)
    if not model:
        raise ValueError('Model name is required for --execute')
    digest = quality_fingerprint(original, packet, model, args.include_review)
    events = []

    def record(event):
        if event['kind'] == 'raw':
            idx = len([e for e in events if e['kind'] == 'raw']) + 1
            save_json(out / f'quality_repair_model_response_{idx:02d}.json', event)
        elif event['kind'] == 'accepted':
            save_json(out / 'quality_repair_checkpoint.json', {
                'fingerprint': digest, 'original_sha256': original_hash,
                'candidate': event['candidate']})
        events.append({k: v for k, v in event.items() if k not in ('candidate', 'raw_response')})
        save_json(out / 'quality_repair_events.json', events)

    candidate, report = repair_with_client(
        original, packet, client, model, attempts=args.attempts,
        include_review=args.include_review, max_output_tokens=args.max_output_tokens,
        timeout=args.timeout, on_event=record)
    report.update({'original_sha256': original_hash, 'fingerprint': digest})
    save_json(out / 'quality_repair_audit.json', report)
    save_json(out / 'quality_repair_candidate.json', candidate)
    if report['all_blocking_resolved']:
        save_json(out / 'executive_quality_repaired.json', candidate)
        print('Evidence validation passed; blocking quality issues resolved.')
        print('Repaired output (separate from original):', out / 'executive_quality_repaired.json')
    else:
        print('Some blocking quality issues remain. Candidate saved for review; no publish-ready output.')
    print('Quality after repair:', report['after']['blocking_count'], 'blocking,',
          report['after']['review_count'], 'review flags')
    print('Audit:', out / 'quality_repair_audit.json')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, help='Existing executive_validated.json')
    parser.add_argument('--packet', required=True, help='Saved executive_evidence_packet.json')
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--execute', action='store_true', help='Opt in to local LLM requests')
    parser.add_argument('--include-review', action='store_true', help='Repair review flags as well as blockers')
    parser.add_argument('--attempts', type=int, default=2)
    parser.add_argument('--timeout', type=int, default=120)
    parser.add_argument('--max-output-tokens', type=int, default=1800)
    args = parser.parse_args(argv)
    if not 1 <= args.attempts <= 3 or args.timeout < 10 or args.max_output_tokens < 256:
        parser.error('Invalid attempts, timeout, or output-token budget')
    try:
        run(args)
    except Exception as exc:
        print('Quality repair stopped:', type(exc).__name__, str(exc), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
