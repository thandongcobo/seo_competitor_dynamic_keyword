"""Four small, resumable recommendation-development requests after specialist analysis.

No DataForSEO, Google, Playwright, or Lighthouse collection occurs in this script.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
import sys

from llm_foundation.executive_synthesis import TASKS, build_packet, parse_response, save_json
from llm_foundation.focused_recommendations import (
    task_packet, task_request, fingerprint, validate_task, merge_tasks)
from llm_foundation.information_preservation import save_preservation_report
from llm_foundation.recommendation_quality import audit_recommendations
from llm_foundation.grounded_retry import diagnose_errors, repair_unambiguous_citations
from llm_foundation.evidence_recovery import recover_invalid_task
from config.settings import keyword_slug


def now():
    return datetime.now(timezone.utc).isoformat()


def load_saved(root):
    canonical = json.loads((root / 'llm_foundation/canonical_evidence.json').read_text(encoding='utf-8'))
    specialists = {task: json.loads((root / 'llm_outputs' / f'{task}_validated.json').read_text(encoding='utf-8')) for task in TASKS}
    return build_packet(canonical, specialists), specialists


def _retry_guidance(errors, response, scoped=None):
    """Explain numeric and citation failures using the exact fields in the model output.

    Never edit the response or bypass the existing strict validator. The same
    feedback applies to all four tasks and to arbitrary keywords/webpages.
    """
    errors = [str(error) for error in errors]
    numeric = any('numeric claim' in error for error in errors)
    linkage = any(term in error.lower() for error in errors for term in (
        'fact not linked', 'invalid evidence_ids', 'not linked to any cited',
        'unsupported specialist citation', 'unknown evidence', 'out-of-scope factual',
        'cross-specialist', 'orphan plan', 'cited evidence',
    ))
    if not numeric and not linkage:
        return ''
    fields = []
    for error in errors:
        match = re.search(r'((?:implementation_plans|finding_dispositions)\[\d+\](?:\.[A-Za-z_]+(?:\[\d+\])?)?)', error)
        if match and match.group(1) not in fields:
            fields.append(match.group(1))
    details = []
    for path in fields[:16]:
        try:
            value = response
            for token in re.findall(r'[^.\[\]]+|\[\d+\]', path):
                value = value[int(token[1:-1])] if token.startswith('[') else value[token]
            details.append({'field': path, 'current_value': value})
        except (KeyError, IndexError, TypeError, ValueError):
            details.append({'field': path})
    advice = []
    if numeric:
        advice.append(
            'NUMERIC EVIDENCE CORRECTION: The flagged numbers are not justified by the cited facts. '
            'Remove unsupported quantities, numeric ranges, percentages, deadlines and thresholds from ALL flagged fields, including success_measure, rationale, implementation_steps '
            'and finding_dispositions. Do not simply relabel numbers as proposals or replace one invented target with another. '
            'Use conditional, measurable verification steps without arbitrary quotas. '
            'Keep observed values only when the exact cited FACT supports them. '
            'Do not infer ranking causation from a single observed SERP.')
    if linkage:
        advice.append(
            'EVIDENCE LINKAGE CORRECTION: For EACH plan, its evidence_ids must be a subset of '
            'the UNION of specialist_fact_links for its cited specialist_finding_ids. '
            'For EACH disposition, evidence_ids must be allowed by that individual finding. '
            'Use BL_PAGE for exact-page backlink counts, BL_DOMAIN for domain-wide backlink '
            'counts, and SERP for observed ranking positions, only when those facts are in scope. '
            'Do not cite page-level evidence under a domain-only specialist finding. '
            'If a plan needs facts from two specialist findings, cite BOTH findings in the plan '
            'and link both actionable dispositions to the plan; otherwise remove the unsupported '
            'claim or turn it into an investigation. Do not invent fact IDs or alter original facts.')
    guidance = (' '.join(advice) + ' Preserve all original specialist findings, correct plan indices, '
                'and valid nonnumeric details. Flagged response fields: ' +
                json.dumps(details, ensure_ascii=False) + '. ')
    if scoped and isinstance(response, dict):
        diagnoses = diagnose_errors(errors, response, scoped)
        guidance += (' EXACT EVIDENCE DIAGNOSIS (not proof of causation; citation-only repairs must match metric scope): ' +
                     json.dumps(diagnoses[:16], ensure_ascii=False) + '. ')
        guidance += (' For numbers absent from approved facts, remove/reword them. '
                     'For numbers present but wrongly cited, use only permitted fact IDs linked to the cited specialist findings. '
                     'If a fact is outside the finding mapping, do not cite it unless a genuinely related finding is explicitly linked and all affected dispositions remain consistent. '
                     'Do not invent a new metric or target to replace an invalid one. ')
    return guidance


def generate_task(client, model, task, scoped, attempts, timeout, max_tokens, raw_dir, *, allow_partial_recovery=False):
    system, body = task_request(scoped, task)
    messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': body}]
    last_errors = []
    for attempt in range(1, attempts + 1):
        parsed = None
        attempt_audit = []
        response = client.chat.completions.create(
            model=model, messages=messages, temperature=0.1,
            max_tokens=max_tokens, timeout=timeout)
        choice = response.choices[0]
        content = choice.message.content or ''
        save_json(raw_dir / f'{task}_attempt_{attempt}.json', {
            'task': task, 'attempt': attempt, 'received_at_utc': now(),
            'finish_reason': choice.finish_reason, 'raw_response': content})
        if choice.finish_reason == 'length':
            raise ValueError(f'{task}: output truncated; increase --max-output-tokens or reduce the number of plans')
        try:
            parsed = parse_response(content)
            last_errors = validate_task(parsed, scoped, task)
            if last_errors:
                # Only add an exact, unambiguous, lineage-permitted citation.
                # The original model response stays in attempt_N.json.
                candidate, changes = repair_unambiguous_citations(parsed, last_errors, scoped)
                if changes:
                    new_errors = validate_task(candidate, scoped, task)
                    attempt_audit.extend([{**item, 'attempt': attempt,
                        'fully_validated': not bool(new_errors)} for item in changes])
                    parsed, last_errors = candidate, new_errors
            if not last_errors:
                if attempt_audit:
                    save_json(raw_dir / f'{task}_citation_repair_audit.json', {
                        'schema_version': '1.0', 'validated': True, 'changes': attempt_audit})
                return parsed, attempt
            save_json(raw_dir / f'{task}_attempt_{attempt}_diagnostics.json', {
                'schema_version': '1.0', 'task': task, 'attempt': attempt,
                'validation_errors': last_errors,
                'provisional_citation_changes': attempt_audit,
                'grounded_diagnostics': diagnose_errors(last_errors, parsed, scoped)})
        except (ValueError, TypeError, KeyError) as exc:
            last_errors = [str(exc)]
        if attempt < attempts:
            # Retry ONLY this specialist task; successful task outputs are never regenerated.
            messages.append({'role': 'assistant', 'content': content})
            messages.append({'role': 'user', 'content':
                'Correct the same specialist task JSON. Keep all valid plans and findings. '
                'Do not omit findings. ' + _retry_guidance(last_errors, parsed if isinstance(parsed, dict) else {}, scoped) +
                'Errors: ' + json.dumps(last_errors[:10], ensure_ascii=False) +
                '. Return a complete corrected JSON for this task ONLY.'})
    # A failed model correction is not grounds to discard all other valid work.
    # Reanalyse only the saved, current-run evidence and quarantine invalid
    # connected plans/findings; preserve the full raw model responses for audit.
    if allow_partial_recovery and isinstance(parsed, dict) and last_errors:
        candidate, recovery = recover_invalid_task(parsed, last_errors, scoped, task)
        save_json(raw_dir / f'{task}_evidence_recovery_audit.json', recovery)
        if candidate is not None:
            save_json(raw_dir / f'{task}_recovered_review.json', candidate)
            print(f'{task}: recovered with review; preserved {len(candidate["implementation_plans"])} '
                  f'of {len(parsed["implementation_plans"])} plans; '
                  f'{len(recovery["review_finding_ids"])} finding(s) require review', flush=True)
            return candidate, attempts
    raise ValueError(f'{task}: failed validation after {attempts} attempt(s): ' + '; '.join(last_errors[:8]))


def run(args, client=None, model=None):
    project = Path(__file__).resolve().parents[1]
    slug = keyword_slug(args.keyword)
    root = Path(args.evidence_root).resolve() if getattr(args, 'evidence_root', None) else project / 'output/results' / slug
    packet, specialists = load_saved(root)
    out = Path(args.output_dir).resolve() if args.output_dir else project / 'output/gemma_tests' / slug / 'focused'
    llm_dir = out / 'llm_outputs'
    task_dir = llm_dir / 'focused_tasks'
    task_dir.mkdir(parents=True, exist_ok=True)
    selected = list(args.tasks) if args.tasks else list(TASKS)
    if getattr(args, 'quality_check_only', False):
        target = llm_dir / 'executive_validated.json'
        if not target.exists():
            raise FileNotFoundError('No existing merged executive JSON: ' + str(target))
        existing = json.loads(target.read_text(encoding='utf-8'))
        quality = audit_recommendations(existing, expected_findings=[f['id'] for f in packet['specialist_findings']])
        save_json(llm_dir / 'recommendation_quality_report.json', quality)
        print(f'Offline quality audit: {quality["blocking_count"]} blocking, {quality["review_count"]} review flags; no requests')
        print('Quality report:', llm_dir / 'recommendation_quality_report.json')
        if getattr(args, 'quality_mode', 'audit') == 'enforce' and quality['blocking_count']:
            raise ValueError('Quality audit has blocking issues; do not publish without review')
        return quality
    save_json(llm_dir / 'executive_evidence_packet.json', packet)
    if args.dry_run:
        for task in selected:
            scoped = task_packet(packet, task)
            system, body = task_request(scoped, task)
            save_json(task_dir / f'{task}_request_preview.json', {'system': system, 'user': body})
            print(f'{task}: request preview saved; {len(body)} characters; no LLM request')
        return None
    if client is None:
        from llm_foundation.inference import load_config
        from openai import OpenAI
        config = load_config()
        model = config['model']
        client = OpenAI(base_url=config['base_url'], api_key=config['api_key'],
                        max_retries=0, timeout=args.timeout)
    if not model:
        raise ValueError('Model name required')
    for task in selected:
        scoped = task_packet(packet, task)
        digest = fingerprint(scoped, task, model)
        saved = task_dir / f'{task}_validated.json'
        if saved.exists() and not args.force:
            previous = json.loads(saved.read_text(encoding='utf-8'))
            if previous.get('fingerprint') == digest and not validate_task(previous.get('result'), scoped, task):
                print(f'{task}: reused validated saved response (no request)')
                continue
        # Clear only prior provisional recovery markers when explicitly regenerating this task.
        for suffix in ('evidence_recovery_audit.json', 'recovered_review.json'):
            (task_dir / f'{task}_{suffix}').unlink(missing_ok=True)
        save_json(task_dir / f'{task}_status.json', {'status': 'running', 'started_at_utc': now()})
        print(f'{task}: requesting focused recommendation development...', flush=True)
        try:
            result, count = generate_task(client, model, task, scoped, args.attempts, args.timeout,
                                          args.max_output_tokens, task_dir,
                                          allow_partial_recovery=not getattr(args, "strict_fail", False))
        except Exception as exc:
            save_json(task_dir / f'{task}_status.json', {'status': 'failed', 'error': str(exc)[:800], 'finished_at_utc': now()})
            raise
        recovery_file = task_dir / f'{task}_evidence_recovery_audit.json'
        recovery = (json.loads(recovery_file.read_text(encoding='utf-8'))
                    if recovery_file.exists() else {})
        recovery_status = recovery.get('status', 'validated')
        save_json(saved, {'schema_version': '1.0', 'task': task, 'model': model, 'fingerprint': digest,
                          'recovery_status': recovery_status,
                          'review_finding_ids': recovery.get('review_finding_ids', []),
                          'attempts': count, 'result': result, 'validated_at_utc': now()})
        save_json(task_dir / f'{task}_status.json', {'status': 'validated', 'finished_at_utc': now(), 'attempts': count})
        print(f'{task}: validated; plans={len(result["implementation_plans"])}; findings={len(result["finding_dispositions"])}', flush=True)
    outputs = {}
    for task in TASKS:
        saved = task_dir / f'{task}_validated.json'
        if not saved.exists():
            print(f'Partial run complete; {task} not yet available. Run remaining tasks to merge.')
            return None
        item = json.loads(saved.read_text(encoding='utf-8'))
        scoped = task_packet(packet, task)
        if item.get('model') != model or item.get('fingerprint') != fingerprint(scoped, task, model):
            print(f'Partial run complete; {task} cache belongs to different evidence or model.')
            return None
        outputs[task] = item['result']
    recovery_summary = {}
    for task in TASKS:
        entry = json.loads((task_dir / f'{task}_validated.json').read_text(encoding='utf-8'))
        if entry.get('recovery_status') == 'recovered_with_review':
            recovery_summary[task] = entry.get('review_finding_ids', [])
    merged = merge_tasks(packet, outputs)
    if recovery_summary:
        merged['limitations'].append(
            'Some model recommendations failed evidence checks and were isolated as investigations. '
            'See the per-task evidence recovery audit before approving any actions.')
    quality = audit_recommendations(merged, expected_findings=[f['id'] for f in packet['specialist_findings']],
                                   require_actionable=True)
    save_json(llm_dir / 'recommendation_quality_report.json', quality)
    print(f'Recommendation quality: {quality["blocking_count"]} blocking, {quality["review_count"]} review flags')
    if getattr(args, 'quality_mode', 'audit') == 'enforce' and quality['blocking_count']:
        raise ValueError('Quality gate blocked publication; inspect recommendation_quality_report.json. Existing validated output was not overwritten.')
    save_json(llm_dir / 'executive_validated.json', merged)
    save_preservation_report(out, specialists, merged)
    save_json(llm_dir / 'focused_run_metadata.json', {'model': model, 'keyword': args.keyword,
              'recommendation_engine': 'four_specialist_focused_v4',
              'generated_at_utc': now(), 'mode': 'four-focused-requests-deterministic-merge',
              'specialist_tasks': list(TASKS), 'recommendation_quality_status': quality['status'],
              'recommendation_quality_blocking': quality['blocking_count'],
              'recommendation_quality_review': quality['review_count'],
              'total_plans': len(merged['implementation_plans']),
              'total_dispositions': len(merged['finding_dispositions']),
              'evidence_recovery': recovery_summary,
              'requires_human_review': True})
    print(f'Merged validated recommendations: {len(merged["implementation_plans"])} plans, '
          f'{len(merged["finding_dispositions"])} specialist dispositions')
    print('Executive output:', llm_dir / 'executive_validated.json')
    if args.pdf:
        from scripts.generate_executive_pdf import main as pdf_main
        pdf_main(['--keyword', args.keyword, '--input', str(root / f'{slug}_comparison.json'),
                  '--output-dir', str(out)])
    return merged


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--keyword', required=True)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--evidence-root', type=Path, help='Explicit run-specific canonical and specialist evidence directory')
    parser.add_argument('--tasks', nargs='+', choices=TASKS, help='Run selected tasks; resume remaining later')
    parser.add_argument('--dry-run', action='store_true', help='Save prompts only; zero LLM requests')
    parser.add_argument('--quality-check-only', action='store_true', help='Audit existing merged output; zero LLM requests')
    parser.add_argument('--quality-mode', choices=['audit', 'enforce'], default='audit',
                        help='audit: preserve output and flag issues; enforce: block publication on critical issues')
    parser.add_argument('--force', action='store_true', help='Regenerate selected task outputs')
    parser.add_argument('--strict-fail', action='store_true', help='Disable conservative partial recovery (legacy fail-closed mode)')
    parser.add_argument('--pdf', action='store_true', help='Generate PDF once all four tasks validate')
    parser.add_argument('--attempts', type=int, default=2)
    parser.add_argument('--timeout', type=int, default=120)
    parser.add_argument('--max-output-tokens', type=int, default=3072)
    args = parser.parse_args(argv)
    if args.attempts < 1 or args.attempts > 3:
        parser.error('--attempts must be between 1 and 3')
    if args.max_output_tokens < 256 or args.timeout < 10:
        parser.error('Output token limit or timeout too small')
    try:
        run(args)
    except Exception as exc:
        print(f'Focused recommendation run stopped: {type(exc).__name__}: {exc}', file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
