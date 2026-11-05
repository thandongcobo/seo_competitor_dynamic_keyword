"""Opt-in, investigation-scoped Gemma reporting jobs for already verified saved evidence.

This module NEVER runs SEO collectors or silently reuses a previous executive output.
Fresh arbitrary-URL collection is not implemented here. Reports are drafts until reviewed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone

from config.settings import ROOT, keyword_slug
from scripts import serp_investigations
from scripts.resolve_pages import normalized_url

_LOCK = threading.RLock()
_ACTIVE: set[str] = set()
_TASKS = ('onpage', 'backlinks', 'technical', 'competition')
_FILE_TYPES = {'pdf': 'executive_report.pdf', 'appendix': 'technical_appendix.md'}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def _base(investigation_id):
    serp_investigations.read_investigation(investigation_id)  # validates ID
    return serp_investigations.INVESTIGATIONS / investigation_id


def _state_path(investigation_id):
    return _base(investigation_id) / 'reporting' / 'status.json'


def _preflight(investigation_id, *, root=None):
    """Validate exact keyword and both URLs before touching an LLM or copying evidence."""
    root = ROOT if root is None else root
    selection = serp_investigations.read_investigation(investigation_id)
    if selection.get('source') != 'manual_exact_webpage_urls':
        raise ValueError('Only completed manual exact-page offline investigations are supported by this reporting bridge.')
    base = _base(investigation_id)
    execution_path = base / 'offline_execution.json'
    if not execution_path.is_file() or _load(execution_path).get('status') != 'completed':
        raise ValueError('Run the verified offline comparison first; no completed run-specific comparison exists.')
    keyword = selection['keyword']
    if any(c in keyword for c in '<>:"/\\|?*'):
        raise ValueError('Keyword contains characters unsupported by the current report filename convention.')
    slug = keyword_slug(keyword)
    comparison_path = base / 'results' / f'{slug}_comparison.json'
    if not comparison_path.is_file():
        raise FileNotFoundError('Investigation-specific comparison JSON is missing.')
    comparison = _load(comparison_path)
    urls = comparison.get('primary_ranking_urls') or {}
    for side in ('ours', 'benchmark'):
        if normalized_url(urls.get(side)) != normalized_url(selection[side]['url']):
            raise ValueError(f'Comparison does not match the selected {side} URL.')
    source = root / 'output' / 'results' / slug
    canonical_path = source / 'llm_foundation' / 'canonical_evidence.json'
    if not canonical_path.is_file():
        raise FileNotFoundError('Matching saved canonical specialist evidence is unavailable; run collection/specialists separately first.')
    canonical = _load(canonical_path)
    identity = canonical.get('investigation') or {}
    tracked = canonical.get('tracked_website') or {}
    competitors = canonical.get('competitors') or []
    if (identity.get('keyword', '').casefold() != keyword.casefold() or
            normalized_url(tracked.get('ranking_url')) != normalized_url(selection['ours']['url']) or
            not competitors or normalized_url(competitors[0].get('ranking_url')) != normalized_url(selection['benchmark']['url'])):
        raise ValueError('Saved specialist evidence belongs to a different keyword or webpage pair; refusing reuse.')
    specialists = {}
    for task in _TASKS:
        path = source / 'llm_outputs' / f'{task}_validated.json'
        if not path.is_file():
            raise FileNotFoundError(f'Missing saved {task} specialist result for this exact investigation.')
        specialists[task] = path
    # Recheck the source against the same packet validator used by the focused engine.
    from llm_foundation.executive_synthesis import build_packet
    packet = build_packet(canonical, {task: _load(path) for task, path in specialists.items()})
    if (packet.get('keyword', '').casefold() != keyword.casefold() or
            normalized_url((packet.get('tracked') or {}).get('url')) != normalized_url(selection['ours']['url']) or
            normalized_url((packet.get('benchmark') or {}).get('url')) != normalized_url(selection['benchmark']['url'])):
        raise ValueError('Reconstructed Gemma evidence packet does not match selected URLs.')
    return {'keyword': keyword, 'slug': slug, 'selection': selection,
            'comparison': comparison_path, 'canonical': canonical_path,
            'specialists': specialists, 'packet': packet}


def status(investigation_id):
    path = _state_path(investigation_id)
    if path.is_file():
        state = _load(path)
        if state.get('status') in ('running', 'preparing', 'validating', 'repairing', 'generating') and investigation_id not in _ACTIVE:
            # A restarted server must never advertise an orphaned job as running.
            state = {**state, 'status': 'interrupted', 'error': 'Server restarted; this job was interrupted. Start a new run.'}
            _write(path, state)
        return {**state, 'available': True}
    try:
        _preflight(investigation_id)
        return {'status': 'not_started', 'available': True, 'message': 'Saved specialist evidence matches both selected URLs. Gemma execution requires explicit approval.'}
    except (ValueError, FileNotFoundError, KeyError, TypeError) as exc:
        return {'status': 'not_ready', 'available': False, 'message': str(exc)}


def _update(investigation_id, **changes):
    path = _state_path(investigation_id)
    with _LOCK:
        state = _load(path)
        state.update(changes, updated_at=_now())
        _write(path, state)
    return state


def _run_command(command, *, cwd, log_path, limit=2400):
    """Log bounded command output without printing credentials or sending collector requests."""
    proc = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=limit, check=False, errors='replace')
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text((proc.stdout or '')[-20000:], encoding='utf-8')
    if proc.returncode:
        raise RuntimeError(f'Reporting stage failed (exit {proc.returncode}). Inspect server-side stage logs.')


def _execute(investigation_id, run_id, evidence):
    base = _base(investigation_id)
    work = base / 'reporting' / 'runs' / run_id
    log_dir = work / 'logs'
    try:
        # Sources are copied into this run only after matching exact page identities.
        evidence_root = work / 'evidence'
        (evidence_root / 'llm_foundation').mkdir(parents=True)
        (evidence_root / 'llm_outputs').mkdir(parents=True)
        pairs = [(evidence['canonical'], evidence_root / 'llm_foundation' / 'canonical_evidence.json'),
                 (evidence['comparison'], evidence_root / 'comparison.json')]
        pairs += [(src, evidence_root / 'llm_outputs' / f'{task}_validated.json')
                  for task, src in evidence['specialists'].items()]
        hashes = {}
        for src, dest in pairs:
            before = _sha(src)
            shutil.copy2(src, dest)
            if _sha(dest) != before or _sha(src) != before:
                raise ValueError('Saved evidence changed during preparation; refusing to continue.')
            hashes[str(dest.relative_to(work))] = before
        _write(work / 'source_hashes.json', hashes)
        keyword = evidence['keyword']
        focused = work / 'focused'
        _update(investigation_id, status='running', stage='focused_recommendations')
        _run_command([sys.executable, '-m', 'scripts.run_llm_focused_recommendations',
                      '--keyword', keyword, '--evidence-root', str(evidence_root),
                      '--output-dir', str(focused), '--quality-mode', 'audit',
                      '--attempts', '2', '--timeout', '120'], cwd=ROOT,
                     log_path=log_dir / 'focused.log')
        metadata_path = focused / 'llm_outputs' / 'focused_run_metadata.json'
        focused_metadata = _load(metadata_path) if metadata_path.is_file() else {}
        recovery_summary = focused_metadata.get('evidence_recovery') or {}
        if recovery_summary:
            _update(investigation_id, stage='evidence_reanalysis_completed',
                    evidence_recovery=recovery_summary,
                    message='Unsupported claims were isolated for review; continuing with validated evidence only.')
        merged = focused / 'llm_outputs' / 'executive_validated.json'
        packet = focused / 'llm_outputs' / 'executive_evidence_packet.json'
        if not merged.is_file() or not packet.is_file():
            raise RuntimeError('Focused Gemma stage did not produce a validated merge and evidence packet.')
        from llm_foundation.quality_repair import evidence_errors
        from llm_foundation.recommendation_quality import audit_recommendations
        from scripts.generate_executive_pdf import report_consistency_errors
        data = _load(merged)
        evidence_packet = _load(packet)
        if evidence_errors(data, evidence_packet):
            raise ValueError('Merged executive evidence validation failed.')
        expected = [f['id'] for f in evidence_packet.get('specialist_findings', [])]
        quality = audit_recommendations(data, expected_findings=expected)
        selected = merged
        if recovery_summary and not data.get('implementation_plans'):
            _update(investigation_id, status='needs_review', stage='evidence_review',
                    files={}, evidence_recovery=recovery_summary,
                    message='All proposed plans required review; no unsupported report was generated. '
                            'Original responses and recovery audits are saved in this investigation run.')
            return
        if quality['blocking_count'] or quality['review_count']:
            _update(investigation_id, status='repairing', stage='targeted_gemma_repair')
            repaired_dir = work / 'repair'
            try:
                _run_command([sys.executable, '-m', 'scripts.repair_recommendation_quality',
                              '--input', str(merged), '--packet', str(packet),
                              '--output-dir', str(repaired_dir), '--execute', '--include-review',
                              '--attempts', '2', '--timeout', '120'], cwd=ROOT,
                             log_path=log_dir / 'repair.log')
            except RuntimeError:
                if not recovery_summary:
                    raise
                _update(investigation_id, status='needs_review', stage='quality_review',
                        files={}, evidence_recovery=recovery_summary,
                        message='Evidence recovery succeeded but the quality-repair stage requires review. '
                                'Validated task outputs and audits remain saved; no report was published.')
                return
            selected = repaired_dir / 'executive_quality_repaired.json'
            if not selected.is_file():
                raise ValueError('Repair did not resolve all blocking quality issues.')
            data = _load(selected)
            quality = audit_recommendations(data, expected_findings=expected)
        if quality['blocking_count'] or evidence_errors(data, evidence_packet):
            if recovery_summary:
                _update(investigation_id, status='needs_review', stage='quality_review',
                        files={}, evidence_recovery=recovery_summary,
                        message='Unresolved quality or evidence checks require review. '
                                'No unsupported report was generated.')
                return
            raise ValueError('Quality or evidence validation failed after repair.')
        if report_consistency_errors(data):
            raise ValueError('Specialist finding/plan lineage is inconsistent.')
        # Use one recommendation contract for the dashboard and management PDF.
        # Unsafe or unmatched specialist plans remain in the appendix/audit only.
        from analysis.recommendations import reconcile_recommendations
        report_comparison = _load(evidence_root / 'comparison.json')
        deterministic = report_comparison.get('recommendations') or []
        authoritative, reconciliation_audit = reconcile_recommendations(deterministic, data, quality)
        report_comparison['recommendations'] = authoritative
        report_comparison['recommendation_reconciliation_audit'] = reconciliation_audit
        report_comparison_path = work / 'authoritative_comparison.json'
        _write(report_comparison_path, report_comparison)
        _write(work / 'recommendation_reconciliation_audit.json', reconciliation_audit)
        _update(investigation_id, status='generating', stage='draft_reports')
        reports = work / 'reports'
        _run_command([sys.executable, '-m', 'scripts.generate_executive_pdf',
                      '--keyword', keyword, '--input', str(report_comparison_path),
                      '--executive-json', str(selected), '--output-dir', str(reports)],
                     cwd=ROOT, log_path=log_dir / 'report.log')
        pdf = reports / f'{keyword}_executive_report.pdf'
        appendix = reports / f'{keyword}_technical_appendix.md'
        manifest = reports / 'report_generation_manifest.json'
        if not all(p.is_file() for p in (pdf, appendix, manifest)):
            raise RuntimeError('Report generation did not produce both reports and its manifest.')
        info = _load(manifest)
        if (info.get('source_executive_sha256') != _sha(selected) or
                info.get('source_comparison_sha256') != _sha(report_comparison_path) or
                info.get('authoritative_recommendation_ids') != [row.get('id') for row in authoritative if row.get('id')]):
            raise ValueError('Report manifest does not match selected repaired evidence.')
        _write(work / 'reporting_provenance.json', {
            'run_id': run_id, 'mode': 'saved_evidence_new_gemma_inference',
            'keyword': keyword, 'selected_pages': evidence['selection'],
            'selected_executive_sha256': _sha(selected), 'comparison_sha256': _sha(report_comparison_path),
            'authoritative_recommendation_ids': [row.get('id') for row in authoritative if row.get('id')],
            'recommendation_reconciliation_audit': reconciliation_audit,
            'source_hashes': hashes, 'quality_blocking': quality['blocking_count'],
            'quality_review': quality['review_count'], 'status': 'draft_pending_human_review',
        })
        _update(investigation_id, status='draft_ready', stage='awaiting_human_review',
                quality={'blocking': quality['blocking_count'], 'review': quality['review_count']},
                files={'pdf': {'path': str(pdf.relative_to(base)), 'sha256': _sha(pdf)},
                       'appendix': {'path': str(appendix.relative_to(base)), 'sha256': _sha(appendix)}},
                evidence_recovery=recovery_summary,
                message=('Partial draft: invalid recommendations were isolated; human review required.'
                         if recovery_summary else 'Draft reports generated from matching saved evidence. Human review required.'))
    except Exception as exc:
        # No fallback to a previous executive or report, and never expose credentials.
        _update(investigation_id, status='failed', stage='failed',
                error=f'{type(exc).__name__}: {str(exc)[:300]}', files={})
    finally:
        with _LOCK:
            _ACTIVE.discard(investigation_id)


def start(investigation_id):
    with _LOCK:
        if investigation_id in _ACTIVE:
            raise RuntimeError('A reporting job is already running for this investigation.')
        evidence = _preflight(investigation_id)
        run_id = uuid.uuid4().hex
        _write(_state_path(investigation_id), {
            'run_id': run_id, 'status': 'preparing', 'stage': 'preparing',
            'started_at': _now(), 'updated_at': _now(), 'files': {},
            'message': 'Explicit Gemma execution requested. No SEO collectors will run.',
        })
        _ACTIVE.add(investigation_id)
        try:
            thread = threading.Thread(target=_execute, args=(investigation_id, run_id, evidence), daemon=True)
            thread.start()
        except Exception:
            _ACTIVE.discard(investigation_id)
            _update(investigation_id, status='failed', error='Could not start reporting worker.')
            raise
    return status(investigation_id)


def artifact(investigation_id, kind):
    if kind not in _FILE_TYPES:
        raise FileNotFoundError('Unknown report type.')
    state = status(investigation_id)
    if state.get('status') not in ('draft_ready', 'approved'):
        raise FileNotFoundError('No current draft report is available.')
    file = (state.get('files') or {}).get(kind) or {}
    base = _base(investigation_id).resolve()
    path = (base / file.get('path', '')).resolve()
    run_id = state.get('run_id', '')
    expected_dir = (base / 'reporting' / 'runs' / run_id / 'reports').resolve()
    if path.parent != expected_dir or not path.is_file() or _sha(path) != file.get('sha256'):
        raise FileNotFoundError('Report artifact is missing or changed.')
    return path


def approve(investigation_id):
    with _LOCK:
        state = status(investigation_id)
        if state.get('status') != 'draft_ready':
            raise ValueError('Only a completed, unapproved draft may be approved.')
        artifact(investigation_id, 'pdf')
        artifact(investigation_id, 'appendix')
        approved_at = _now()
        run_id = state.get('run_id')
        provenance = _base(investigation_id) / 'reporting' / 'runs' / run_id / 'reporting_provenance.json'
        if provenance.is_file():
            record = _load(provenance)
            record.update(status='approved_by_user', approved_at=approved_at)
            _write(provenance, record)
        return _update(investigation_id, status='approved', stage='approved_by_user',
                       approved_at=approved_at, message='User explicitly approved the draft for internal use.')
