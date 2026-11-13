"""Persistent orchestration around the existing SEO investigation components.

This adapter never implements SEO analysis itself. External collection and model
requests remain explicit calls to their existing tools; opening or navigating a
workflow only reads saved state and artifacts.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time
from datetime import datetime, timezone

from config.settings import ROOT
from scripts import serp_investigations

STAGES = (
    'keyword_search', 'webpage_selection', 'evidence_collection',
    'evidence_processing', 'recommendation_generation',
    'validation_classification', 'results_reporting',
)
LABELS = {
    'keyword_search': 'Keyword search', 'webpage_selection': 'Webpage selection',
    'evidence_collection': 'Evidence collection',
    'evidence_processing': 'Evidence processing and comparison',
    'recommendation_generation': 'Recommendation generation',
    'validation_classification': 'Validation and classification',
    'results_reporting': 'Results and reporting',
}
SCHEMA_VERSION = '1.0'
ADAPTER_VERSION = 'phase1.1'


def _now():
    return datetime.now(timezone.utc).isoformat()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def _base(investigation_id: str) -> Path:
    serp_investigations.read_investigation(investigation_id)
    return serp_investigations.INVESTIGATIONS / investigation_id


def _workflow_dir(investigation_id: str) -> Path:
    return _base(investigation_id) / 'workflow'


def _search_jobs_dir() -> Path:
    return ROOT / 'data' / 'investigation_workflows' / 'search_jobs'


def _state_path(investigation_id: str) -> Path:
    return _workflow_dir(investigation_id) / 'checkpoint.json'


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    data = json.dumps(payload, ensure_ascii=False, indent=2) + '\n'
    with temp.open('w', encoding='utf-8', newline='\n') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


class _InvestigationLock:
    """Cross-process create-exclusive lock with bounded stale-lock recovery."""
    def __init__(self, path: Path, timeout: float = 15):
        self.path, self.timeout = path, timeout
        self.fd = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(self.fd, json.dumps({'pid': os.getpid(), 'created_at': _now()}).encode())
                return self
            except FileExistsError:
                try:
                    info = json.loads(self.path.read_text(encoding='utf-8'))
                    pid = int(info.get('pid', -1))
                    try:
                        os.kill(pid, 0)
                        alive = True
                    except (OSError, ValueError):
                        alive = False
                    if not alive:
                        self.path.unlink(missing_ok=True)
                        continue
                except (OSError, ValueError, TypeError):
                    # Never steal a malformed lock immediately; allow the writer
                    # time to finish its tiny lock metadata write.
                    try:
                        if time.time() - self.path.stat().st_mtime > 60:
                            self.path.unlink(missing_ok=True)
                            continue
                    except OSError:
                        continue
                if time.monotonic() >= deadline:
                    raise RuntimeError('Another worker is updating this investigation. Try again shortly.')
                time.sleep(.05)

    def __exit__(self, *_):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        self.path.unlink(missing_ok=True)


def _new_state(investigation_id: str, selection: dict) -> dict:
    now = _now()
    stages = {key: {'label': LABELS[key], 'status': 'not_started', 'attempts': [],
                    'input_fingerprint': None, 'outputs': []} for key in STAGES}
    branch_path = _base(investigation_id) / 'workflow_branch.json'
    branch = json.loads(branch_path.read_text(encoding='utf-8')) if branch_path.is_file() else None
    search_stage = stages['keyword_search']
    search_stage.update(status='completed', started_at=selection.get('created_at'),
                        completed_at=selection.get('created_at'),
                        component='original saved SERP snapshot or manual selection')
    if selection.get('serp_sha256'):
        try:
            from scripts.dashboard_serp_search import _snapshot_path
            snapshot = _snapshot_path(selection['keyword'])
            if snapshot.is_file() and _sha(snapshot) == selection['serp_sha256']:
                search_stage['outputs'] = [{'path': str(snapshot.relative_to(ROOT)).replace('\\', '/'),
                                            'scope': 'workspace',
                                            'sha256': selection['serp_sha256'],
                                            'size_bytes': snapshot.stat().st_size}]
            else:
                search_stage['status'] = 'failed'
                search_stage['error'] = {'kind': 'snapshot_unavailable',
                    'message': 'Original search snapshot is missing or has changed.'}
        except (OSError, ValueError):
            search_stage['status'] = 'failed'
            search_stage['error'] = {'kind': 'snapshot_unavailable',
                'message': 'Original search snapshot could not be verified.'}
    else:
        search_stage['outputs'] = [{'reference': 'manual webpage selection; no SERP search requested'}]
    current = 'webpage_selection' if search_stage['status'] == 'completed' else 'keyword_search'
    return {'schema_version': SCHEMA_VERSION, 'investigation_id': investigation_id,
            'keyword': selection['keyword'],
            'webpages': {'ours': selection.get('ours'), 'benchmark': selection.get('benchmark')},
            'serp_snapshot': {'sha256': selection.get('serp_sha256'),
                              'collected_at': selection.get('serp_collected_at')},
            'created_at': now, 'updated_at': now, 'current_stage': current,
            'completed_stages': ['keyword_search'] if search_stage['status'] == 'completed' else [],
            'stages': stages, 'request_cache_records': [],
            'gemma_cache_records': [], 'recovery_attempts': [], 'branch': branch}


def _recover_and_reconcile(state: dict, investigation_id: str) -> dict:
    changed = False
    for key, stage in state['stages'].items():
        if stage.get('status') == 'running':
            stage['status'] = 'failed'
            stage['error'] = {'kind': 'server_restart', 'message': 'Stage was interrupted by a server restart.'}
            stage.setdefault('attempts', []).append({'status': 'failed', 'finished_at': _now(),
                                                     'reason': 'interrupted_during_restart'})
            changed = True
    base = _base(investigation_id)
    collection_pointer = base / 'workflow' / 'collection_active.json'
    evidence_stage = state['stages'].get('evidence_collection', {})
    if (evidence_stage.get('status') == 'completed' and not collection_pointer.is_file() and
            evidence_stage.get('component', '').startswith('scripts.investigation_offline.evidence_inventory')):
        evidence_stage.update(status='awaiting_review', completed_at=None,
            error={'kind': 'phase1_1_collection_preparation',
                   'message': 'Saved evidence needs an isolated, versioned collection record before processing.'})
        state.setdefault('recovery_attempts', []).append({'stage': 'evidence_collection',
            'attempted_at': _now(), 'action': 'phase1_1_checkpoint_migration',
            'status': 'awaiting_review', 'message': 'Prepare saved evidence without external requests.'})
        changed = True
    execution = base / 'offline_execution.json'
    if execution.is_file():
        try:
            report = json.loads(execution.read_text(encoding='utf-8'))
            if report.get('status') == 'completed':
                for key in STAGES[3:]:
                    stage = state['stages'][key]
                    if stage.get('status') != 'completed':
                        stage.update(status='completed', started_at=stage.get('started_at') or report.get('completed_at'),
                                     completed_at=report.get('completed_at') or _now(),
                                     component='scripts.run_investigation_offline.run',
                                     outputs=_verified_report_outputs(base, report))
                        changed = True
        except (OSError, ValueError, TypeError):
            pass
    for stage_id, stage in state['stages'].items():
        if stage.get('status') != 'completed':
            continue
        invalid = _invalid_outputs(stage.get('outputs') or [], base)
        if invalid:
            stage.update(status='failed', completed_at=_now(),
                         error={'kind': 'checkpoint_integrity_failure',
                                'message': 'A completed-stage artifact is missing or has a different checksum.'},
                         invalid_outputs=invalid)
            stage.setdefault('attempts', []).append({'status': 'failed', 'finished_at': _now(),
                'reason': 'checkpoint_artifact_integrity_failure', 'outputs': invalid})
            state.setdefault('recovery_attempts', []).append({'stage': stage_id, 'attempted_at': _now(),
                'action': 'checkpoint_integrity_check', 'status': 'failed', 'outputs': invalid})
            changed = True
    state['completed_stages'] = [key for key in STAGES if state['stages'][key]['status'] == 'completed']
    if changed:
        state['updated_at'] = _now()
    return state


def _verified_report_outputs(base: Path, report: dict) -> list[dict]:
    outputs = []
    candidates = []
    for key in ('comparison_path', 'pdf_path', 'appendix_path'):
        value = report.get(key)
        if value:
            candidates.append(value)
    # The comparison may be nested under the run result or generated by its
    # deterministic filename; only paths contained within this investigation.
    for value in candidates:
        path = Path(value)
        if not path.is_absolute():
            path = base / path
        try:
            resolved = path.resolve()
            resolved.relative_to(base.resolve())
            if resolved.is_file():
                outputs.append({'path': str(resolved.relative_to(base.resolve())).replace('\\', '/'),
                                'sha256': _sha(resolved), 'size_bytes': resolved.stat().st_size})
        except (OSError, ValueError):
            continue
    # Recovered downstream stages must pin the execution record as well as
    # the comparison. comparison_history verifies both hashes before it will
    # expose recommendations, so omitting this output made otherwise valid
    # completed runs fail after restart/reconciliation.
    execution = base / 'offline_execution.json'
    if execution.is_file():
        try:
            outputs.append({'path': 'offline_execution.json', 'sha256': _sha(execution),
                            'size_bytes': execution.stat().st_size})
        except OSError:
            pass
    for path in (base / 'results').glob('*.pdf') if (base / 'results').is_dir() else ():
        try:
            outputs.append({'path': str(path.relative_to(base)).replace('\\', '/'),
                            'sha256': _sha(path), 'size_bytes': path.stat().st_size})
        except OSError:
            pass
    for path in (base / 'results').glob('*appendix*.md') if (base / 'results').is_dir() else ():
        try:
            outputs.append({'path': str(path.relative_to(base)).replace('\\', '/'),
                            'sha256': _sha(path), 'size_bytes': path.stat().st_size})
        except OSError:
            pass
    return outputs


def get_state(investigation_id: str) -> dict:
    selection = serp_investigations.read_investigation(investigation_id)
    path = _state_path(investigation_id)
    if not path.is_file():
        state = _new_state(investigation_id, selection)
        state = _recover_and_reconcile(state, investigation_id)
        _atomic_json(path, state)
        return state
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
        if state.get('investigation_id') != investigation_id or state.get('schema_version') != SCHEMA_VERSION:
            raise ValueError('Workflow checkpoint identity or schema mismatch.')
        state = _recover_and_reconcile(state, investigation_id)
        _atomic_json(path, state)
        return state
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError('Workflow checkpoint is incomplete or invalid; existing evidence was preserved.') from exc


def _write_state(investigation_id: str, state: dict) -> dict:
    state['updated_at'] = _now()
    state['completed_stages'] = [key for key in STAGES if state['stages'][key]['status'] == 'completed']
    _atomic_json(_state_path(investigation_id), state)
    return state


def _invalid_outputs(outputs: list, base: Path) -> list:
    invalid = []
    for output in outputs:
        if not isinstance(output, dict) or output.get('reference'):
            continue
        value = output.get('path')
        if not value:
            invalid.append(output)
            continue
        path = Path(value)
        if output.get('scope') == 'workspace':
            path = ROOT / path
        elif not path.is_absolute():
            path = base / path
        try:
            if not path.is_file() or (output.get('sha256') and _sha(path) != output['sha256']):
                archived = _verified_archived_serp_output(output, base)
                if archived:
                    # Keep the checkpoint tied to the immutable archived
                    # snapshot whose bytes match the original recorded hash.
                    # Never copy the archive over the current SERP snapshot.
                    output['recovered_from'] = output.get('path')
                    output['path'] = str(archived.relative_to(ROOT)).replace('\\', '/')
                    output['size_bytes'] = archived.stat().st_size
                else:
                    invalid.append(output)
        except OSError:
            invalid.append(output)
    return invalid


def _verified_archived_serp_output(output: dict, base: Path) -> Path | None:
    value = output.get('path')
    expected_sha = output.get('sha256')
    if (output.get('scope') != 'workspace' or not isinstance(value, str) or
            not value.replace('\\', '/').startswith('data/raw/serp/') or
            not isinstance(expected_sha, str) or len(expected_sha) != 64):
        return None
    selection_path = base / 'selection.json'
    try:
        selection = json.loads(selection_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    if selection.get('serp_sha256') != expected_sha:
        return None
    keyword = str(selection.get('keyword') or '').casefold()
    collected_at = selection.get('serp_collected_at')
    archive_dir = ROOT / 'data' / 'raw' / 'serp' / 'archive'
    if not keyword or not collected_at or not archive_dir.is_dir():
        return None
    for candidate in archive_dir.glob('*.json'):
        try:
            if _sha(candidate) != expected_sha:
                continue
            snapshot = json.loads(candidate.read_text(encoding='utf-8'))
            if (str(snapshot.get('keyword') or '').casefold() == keyword and
                    snapshot.get('datetime') == collected_at):
                return candidate
        except (OSError, json.JSONDecodeError):
            continue
    return None


def navigate(investigation_id: str, direction: str) -> dict:
    if direction not in ('previous', 'next'):
        raise ValueError('Direction must be previous or next.')
    with _InvestigationLock(_workflow_dir(investigation_id) / '.lock'):
        state = get_state(investigation_id)
        index = STAGES.index(state['current_stage'])
        target = index - 1 if direction == 'previous' else index + 1
        if target < 0 or target >= len(STAGES):
            return state
        if direction == 'next' and state['stages'][state['current_stage']]['status'] != 'completed':
            raise ValueError('Complete the current stage before moving to the next stage.')
        state['current_stage'] = STAGES[target]
        return _write_state(investigation_id, state)


def _input_digest(stage: str, selection: dict, inventory: dict | None = None) -> str:
    from config.settings import settings
    payload = {'stage': stage, 'selection': selection, 'adapter_version': ADAPTER_VERSION,
               'configuration': {'language_code': settings.language_code,
                                 'location_coordinate': settings.location_coordinate,
                                 'labs_location_name': settings.labs_location_name,
                                 'serp_depth': settings.serp_depth}}
    if inventory is not None:
        payload['evidence'] = [(row.get('kind'), row.get('side'), row.get('path'), row.get('sha256'), row.get('status'))
                               for row in inventory.get('entries', [])]
    return _canonical_sha(payload)


def _cache_file(investigation_id: str, stage: str, fingerprint: str) -> Path:
    return _workflow_dir(investigation_id) / 'cache' / f'{stage}_{fingerprint}.json'


def _record_output(path: Path, base: Path) -> dict:
    resolved = path.resolve()
    resolved.relative_to(base.resolve())
    if not resolved.is_file():
        raise ValueError(f'Required stage output is missing: {path.name}')
    return {'path': str(resolved.relative_to(base.resolve())).replace('\\', '/'),
            'sha256': _sha(resolved), 'size_bytes': resolved.stat().st_size}


def _execute(investigation_id: str, stage_id: str, force: bool = False) -> dict:
    if stage_id not in STAGES:
        raise ValueError('Unknown workflow stage.')
    state = get_state(investigation_id)
    stage_index = STAGES.index(stage_id)
    missing = [key for key in STAGES[:stage_index] if state['stages'][key]['status'] != 'completed']
    if missing:
        raise ValueError('Stage prerequisites are incomplete: ' + ', '.join(missing))
    stage = state['stages'][stage_id]
    if stage['status'] == 'completed' and not force:
        state['current_stage'] = stage_id
        stage['cache'] = 'hit'
        state['request_cache_records'].append({'stage': stage_id,
            'fingerprint': stage.get('input_fingerprint'), 'status': 'verified_checkpoint_reuse',
            'requests_made': 0, 'recorded_at': _now()})
        return _write_state(investigation_id, state)
    if stage['status'] == 'completed' and force and stage_id in ('evidence_processing', 'recommendation_generation',
                                                                 'validation_classification', 'results_reporting'):
        raise ValueError('Completed offline outputs are immutable. Create a new investigation version to rerun.')
    selection = serp_investigations.read_investigation(investigation_id)
    base = _base(investigation_id)
    inventory = None
    fingerprint = _input_digest(stage_id, selection, inventory)
    cache_path = _cache_file(investigation_id, stage_id, fingerprint)
    if stage_id != 'evidence_collection' and cache_path.is_file() and not force:
        try:
            entry = json.loads(cache_path.read_text(encoding='utf-8'))
            if entry.get('status') == 'completed' and all(
                    (base / output['path']).is_file() and _sha(base / output['path']) == output['sha256']
                    for output in entry.get('outputs', [])):
                stage.update(status='completed', input_fingerprint=fingerprint,
                             outputs=entry['outputs'], started_at=entry.get('started_at'), completed_at=_now(),
                             cache='hit', component=entry.get('component'))
                state['current_stage'] = stage_id
                _write_state(investigation_id, state)
                return state
        except (OSError, ValueError, KeyError, TypeError):
            pass

    now = _now()
    stage.update(status='running', started_at=now, completed_at=None, error=None,
                 input_fingerprint=fingerprint, cache='miss', component=None)
    state['current_stage'] = stage_id
    _write_state(investigation_id, state)
    try:
        outputs = []
        component = None
        if stage_id == 'keyword_search':
            component = 'saved SERP snapshot reader (no collection)'
            if selection.get('serp_sha256'):
                from scripts.dashboard_serp_search import _snapshot_path
                path = _snapshot_path(selection['keyword'])
                if not path.is_file() or _sha(path) != selection['serp_sha256']:
                    raise ValueError('The original SERP snapshot is missing or changed; the saved investigation remains intact.')
                outputs.append(_record_output(path, ROOT))
            else:
                outputs.append({'reference': 'no SERP snapshot was attached to this manual-page investigation'})
        elif stage_id == 'webpage_selection':
            component = 'scripts.serp_investigations.read_investigation'
            path = base / 'selection.json'
            output = _record_output(path, base)
            if not selection.get('keyword') or not selection.get('ours', {}).get('url') or not selection.get('benchmark', {}).get('url'):
                raise ValueError('Selection identity is incomplete.')
            outputs.append(output)
        elif stage_id == 'evidence_collection':
            from scripts.investigation_collection import execute_collection
            # Generic Run Stage is inventory/reuse only. Live collectors require
            # the separate /workflow/collection/execute authorization action.
            execute_collection(investigation_id, collectors=[], refresh=False)
            return get_state(investigation_id)
        elif stage_id == 'evidence_processing':
            source = selection.get('source')
            if source == 'observed_google_playwright_serp':
                from scripts.serp_processing_adapter import validate_serp_origin_investigation
                selection = validate_serp_origin_investigation(investigation_id)
            elif source != 'manual_exact_webpage_urls':
                raise ValueError('The current offline processing adapter supports manual exact-page investigations only.')
            component = 'scripts.run_investigation_offline.run (bundled processing, recommendations, validation and reporting)'
            from scripts.run_investigation_offline import run as run_offline
            from scripts.investigation_collection import active_evidence_root
            evidence_root = active_evidence_root(investigation_id) or ROOT
            result = run_offline(investigation_id, root=evidence_root, investigation_dir=base, generate_pdf=True)
            if result.get('status') != 'completed':
                raise ValueError('The offline comparison did not complete successfully.')
            execution_path = base / 'offline_execution.json'
            outputs.append(_record_output(execution_path, base))
            comparison = base / 'results' / f"{__import__('config.settings', fromlist=['keyword_slug']).keyword_slug(selection['keyword'])}_comparison.json"
            if comparison.is_file():
                outputs.append(_record_output(comparison, base))
            else:
                result_path = result.get('comparison_path')
                if result_path:
                    candidate = Path(result_path)
                    outputs.append(_record_output(candidate if candidate.is_absolute() else base / candidate, base))
            for file in sorted((base / 'results').glob('*.pdf')) + sorted((base / 'results').glob('*appendix*.md')):
                outputs.append(_record_output(file, base))
            if len(outputs) < 2:
                raise ValueError('Required comparison artifacts were not persisted.')
            # The existing runner is intentionally monolithic. These later
            # stages are completed only after verifying their produced records.
            generated_at = _now()
            for later, required in ((STAGES[4], 'recommendation'), (STAGES[5], 'classification'), (STAGES[6], 'report')):
                later_stage = state['stages'][later]
                later_stage.update(status='completed', started_at=now, completed_at=generated_at,
                                   component=component, outputs=outputs,
                                   input_fingerprint=_input_digest(later, selection, inventory))
                later_stage.setdefault('attempts', []).append({'status': 'completed', 'started_at': now,
                    'finished_at': generated_at, 'outputs': outputs,
                    'note': 'Produced and verified by the existing bundled offline runner.'})
            stage['outputs'] = outputs
        elif stage_id in STAGES[4:]:
            raise ValueError('This stage is emitted by the existing bundled offline processing step and cannot run independently.')
        else:
            raise ValueError('This stage is supplied from saved evidence only; no live request was started.')

        stage.update(status='completed', completed_at=_now(), outputs=outputs, component=component, error=None)
        stage.setdefault('attempts', []).append({'status': 'completed', 'started_at': now,
            'finished_at': stage['completed_at'], 'inputs': fingerprint, 'outputs': outputs})
        _atomic_json(cache_path, {'schema_version': SCHEMA_VERSION, 'stage': stage_id,
            'fingerprint': fingerprint, 'status': 'completed', 'started_at': now,
            'completed_at': stage['completed_at'], 'component': component, 'outputs': outputs,
            'request_metadata': {'requests_made_by_orchestrator': 0},
            'checksum': _canonical_sha(outputs)})
        if stage_id not in ('evidence_processing',):
            state['request_cache_records'].append({'stage': stage_id, 'fingerprint': fingerprint,
                'status': 'saved_evidence_or_inventory', 'requests_made': 0, 'recorded_at': _now()})
        return _write_state(investigation_id, state)
    except Exception as exc:
        stage.update(status='failed', completed_at=_now(),
                     error={'kind': type(exc).__name__, 'message': str(exc)[:1200]})
        stage.setdefault('attempts', []).append({'status': 'failed', 'started_at': now,
            'finished_at': stage['completed_at'], 'inputs': fingerprint,
            'error': stage['error']})
        state.setdefault('recovery_attempts', []).append({'stage': stage_id, 'attempted_at': _now(),
            'action': 'selective_stage_retry', 'status': 'failed', 'message': str(exc)[:1200]})
        _atomic_json(_cache_file(investigation_id, stage_id, fingerprint), {
            'schema_version': SCHEMA_VERSION, 'stage': stage_id, 'fingerprint': fingerprint,
            'status': 'failed', 'failed_at': _now(), 'error': stage['error'],
            'checksum': _canonical_sha(stage['error'])})
        _write_state(investigation_id, state)
        raise


def execute_stage(investigation_id: str, stage_id: str, *, refresh: bool = False) -> dict:
    if type(refresh) is not bool:
        raise ValueError('refresh must be a boolean.')
    with _InvestigationLock(_workflow_dir(investigation_id) / '.lock'):
        return _execute(investigation_id, stage_id, force=refresh)


def collection_plan(investigation_id: str, *, collectors=None, refresh=False) -> dict:
    from scripts.investigation_collection import public_plan
    return public_plan(investigation_id, collectors=collectors, refresh=refresh)


def collect_evidence(investigation_id: str, *, collectors, authorize_paid_dataforseo=False,
                     authorize_external_page_requests=False, refresh=False) -> dict:
    from scripts.investigation_collection import execute_collection
    with _InvestigationLock(_workflow_dir(investigation_id) / '.lock'):
        result = execute_collection(investigation_id, collectors=collectors,
            authorize_paid_dataforseo=authorize_paid_dataforseo,
            authorize_external_page_requests=authorize_external_page_requests,
            refresh=refresh)
        return {'collection': result, 'workflow': get_state(investigation_id)}


def start_keyword_search(keyword, depth=20) -> dict:
    """Persist an explicitly requested search job around the existing adapter."""
    from scripts import dashboard_serp_search
    from config.settings import settings
    safe_config = {'language_code': settings.language_code,
                   'location_coordinate': settings.location_coordinate,
                   'our_domain': settings.our_domain, 'depth': depth}
    fingerprint = _canonical_sha({'keyword': ' '.join(str(keyword).split()), 'config': safe_config})
    job = dashboard_serp_search.start_search(keyword, depth)
    if len(job.get('job_id', '')) != 32 or any(c not in '0123456789abcdef' for c in job.get('job_id', '')):
        # Test doubles and nonstandard adapters must not create production job
        # records under a noncanonical identifier.
        return job
    record = {'schema_version': SCHEMA_VERSION, **job, 'fingerprint': fingerprint,
              'request': {'keyword': job['keyword'], 'depth': job['depth'], 'configuration': safe_config},
              'status': job['status'], 'created_at': _now(), 'credentials_stored': False}
    _atomic_json(_search_jobs_dir() / f"{job['job_id']}.json", record)
    return job


def keyword_search_status(job_id: str) -> dict | None:
    if len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
        return None
    path = _search_jobs_dir() / f'{job_id}.json'
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
        from scripts import dashboard_serp_search
        live = dashboard_serp_search.job_status(job_id)
        if live:
            record.update(live)
            if live.get('status') == 'completed' and live.get('result'):
                snapshot = dashboard_serp_search._snapshot_path(record['keyword'])
                if snapshot.is_file():
                    record['snapshot'] = {'sha256': _sha(snapshot),
                        'path': str(snapshot.relative_to(ROOT)).replace('\\', '/'),
                        'size_bytes': snapshot.stat().st_size}
            _atomic_json(path, record)
            return live
        if record.get('status') == 'running':
            # Do not restart a browser after a server restart. Reconcile only
            # with a snapshot demonstrably written after this request began.
            snapshot = dashboard_serp_search._snapshot_path(record['keyword'])
            try:
                saved = dashboard_serp_search.read_snapshot(record['keyword'])
                fresh = (snapshot.is_file() and saved.get('collected_at') and
                         saved['collected_at'] >= record.get('started_at', ''))
            except (ValueError, FileNotFoundError, OSError):
                fresh = False
            if fresh:
                record.update(status='completed', finished_at=_now(),
                              result=saved,
                              snapshot={'sha256': _sha(snapshot),
                                        'path': str(snapshot.relative_to(ROOT)).replace('\\', '/'),
                                        'size_bytes': snapshot.stat().st_size})
            else:
                record.update(status='failed', finished_at=_now(),
                              error='Server restarted before the requested SERP snapshot was confirmed.')
            _atomic_json(path, record)
        return {key: value for key, value in record.items() if key not in ('request', 'credentials_stored')}
    except (OSError, ValueError, TypeError):
        return None


def branch_competitor(investigation_id: str, benchmark_url: str) -> dict:
    """Create a fresh immutable exact-page investigation; never rewrite the parent."""
    parent = serp_investigations.read_investigation(investigation_id)
    from scripts.resolve_pages import normalized_url
    from scripts.serp_investigations import validate_public_page_url
    new_url, _ = validate_public_page_url(benchmark_url)
    if normalized_url(new_url) == normalized_url(parent['benchmark']['url']):
        raise ValueError('Choose a different benchmark webpage to create a branch.')
    branch = serp_investigations.create_page_investigation(parent['keyword'], parent['ours']['url'],
                                                           new_url, parent.get('serp_sha256'))
    child_dir = serp_investigations.INVESTIGATIONS / branch['investigation_id']
    parent_selection = _base(investigation_id) / 'selection.json'
    meta = {'schema_version': SCHEMA_VERSION, 'parent_investigation_id': investigation_id,
            'parent_selection_sha256': _sha(parent_selection), 'created_at': _now(),
            'keyword': parent['keyword'], 'serp_sha256': parent.get('serp_sha256'),
            'changed_identity': 'benchmark', 'benchmark_url': new_url,
            'compatible_evidence_rechecked': True,
            'note': 'Evidence inventory was recomputed for the exact URLs; parent artifacts remain immutable.'}
    _atomic_json(child_dir / 'workflow_branch.json', meta)
    return {'investigation': branch, 'branch': meta}
