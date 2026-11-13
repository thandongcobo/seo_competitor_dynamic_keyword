"""Execute the existing comparison/reporting stack using only verified saved evidence.

No network clients, browser collectors, Lighthouse or LLM inference are invoked.
The historical Gemma response is replayed, never presented as a new inference.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import uuid

from config.settings import ROOT, keyword_slug
from scripts import serp_investigations
from scripts.investigation_offline import evidence_inventory
from scripts.resolve_pages import normalized_url
from normalization.labs import normalize_ranked_keywords, normalize_domain_intersection, normalize_search_intent
from normalization.backlinks import normalize_backlink_summary
from normalization.pages import normalize_page
from normalization.lighthouse import normalize_lighthouse
from analysis.rankings import compare_rankings as original_compare_rankings

_RUN_LOCK = threading.Lock()  # run_analysis has legacy module-level paths/settings


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def historical_pdf_missing_sections(executive: dict) -> list[str]:
    """Check the minimum fields required by the newer management report generator.

    Historical executive responses can predate focused recommendations. Such
    evidence may be replayed, but must not be passed off as a repaired report.
    """
    required = (
        ('implementation plans', executive.get('implementation_plans')),
        ('specialist finding dispositions', executive.get('finding_dispositions')),
        ('verified factual findings',
         executive.get('verified_factual_findings') or executive.get('key_findings')),
    )
    return [name for name, value in required if not isinstance(value, list) or not value]


def _exact_rank(serp: dict, url: str) -> dict | None:
    return next((row for row in serp.get('organic_results', [])
                 if normalized_url(row.get('url')) == normalized_url(url)), None)


def _comparison_for_investigation(selection: dict, comparison: dict,
                                  metadata: dict | None = None) -> dict:
    """Reject an analysis result that is not the selected investigation's output."""
    if not isinstance(comparison, dict):
        raise ValueError('The saved comparison is not a valid JSON object.')
    keyword = selection.get('keyword')
    from scripts.dashboard_serp_search import validate_keyword
    if (not isinstance(keyword, str) or not keyword.strip() or validate_keyword(keyword) != keyword or
            str(comparison.get('keyword') or '').casefold() != keyword.casefold()):
        raise ValueError('The saved comparison keyword does not match the investigation.')
    urls = comparison.get('primary_ranking_urls') or {}
    for side in ('ours', 'benchmark'):
        page = selection.get(side) or {}
        if (normalized_url(urls.get(side)) != normalized_url(page.get('url')) or
                str(page.get('domain') or '').casefold() !=
                str((comparison.get('our_domain') if side == 'ours' else
                     comparison.get('benchmark_competitor_domain')) or '').casefold()):
            raise ValueError(f'The saved comparison {side} page identity does not match the investigation.')
    if metadata and metadata.get('rankings_available'):
        ranking = (comparison.get('ranking_summary') or {}).get('google') or {}
        for side, position_key, url_key in (
                ('ours', 'our_position', 'our_url'),
                ('benchmark', 'benchmark_position', 'benchmark_url')):
            page = selection[side]
            report_page = metadata['tracked_page'] if side == 'ours' else metadata['competitor_page']
            if (type(ranking.get(position_key)) is not int or
                    ranking.get(position_key) != report_page.get('rank') or
                    normalized_url(ranking.get(url_key)) != normalized_url(page.get('url'))):
                raise ValueError(f'The saved comparison {side} SERP ranking does not match its verified snapshot.')
    recommendations = comparison.get('recommendations')
    if not isinstance(recommendations, list) or not recommendations:
        raise ValueError('The selected comparison has no authoritative recommendation records.')
    ids = [row.get('id') for row in recommendations if isinstance(row, dict)]
    if len(ids) != len(recommendations) or not all(isinstance(value, str) and value for value in ids):
        raise ValueError('The selected comparison contains malformed recommendation records.')
    if len(ids) != len(set(ids)):
        raise ValueError('The selected comparison contains duplicate recommendation IDs.')
    from analysis.recommendation_classification import adapt_recommendations
    adapted, audit = adapt_recommendations(recommendations)
    if not adapted:
        raise ValueError('The selected comparison has no recommendations that pass classification.')
    return {'comparison': comparison, 'recommendations': adapted, 'classification_audit': audit}


def _report_metadata(selection: dict, inventory: dict, *, root: Path) -> dict:
    """Build report identity from the saved selection and its verified SERP, if any."""
    keyword = selection['keyword']
    source = selection.get('source')
    slug = keyword_slug(keyword)
    snapshot_path = ROOT / 'data' / 'raw' / 'serp' / f'{slug}_google_playwright.json'
    snapshot = None
    snapshot_hash = None
    ranks = {'ours': None, 'benchmark': None}
    search_context = {}
    serp_reference = selection.get('serp_snapshot_reference')
    expected_hash = selection.get('serp_sha256')
    if expected_hash and snapshot_path.is_file():
        actual_hash = _sha(snapshot_path)
        candidate = _read(snapshot_path)
        if (actual_hash == expected_hash and
                str(candidate.get('keyword') or '').casefold() == keyword.casefold()):
            rows = candidate.get('organic_results') or []
            matches = {}
            for side in ('ours', 'benchmark'):
                page = selection[side]
                found = [row for row in rows if isinstance(row, dict) and
                         row.get('url') == page.get('url') and
                         type(row.get('rank_group')) is int and row['rank_group'] > 0 and
                         str(row.get('domain') or '').casefold() == str(page.get('domain') or '').casefold()]
                if len(found) != 1:
                    matches = {}
                    break
                matches[side] = found[0]
            if len(matches) == 2:
                snapshot, snapshot_hash = candidate, actual_hash
                ranks = {side: matches[side]['rank_group'] for side in ('ours', 'benchmark')}
                if not serp_reference:
                    serp_reference = str(snapshot_path.resolve().relative_to(ROOT.resolve())).replace('\\', '/')
                search_context = dict(selection.get('search_context') or {})
                if not search_context:
                    search_context = {key: candidate.get(key) for key in (
                        'status', 'datetime', 'search_url', 'location_note', 'depth_requested',
                        'depth_collected', 'pages_completed', 'stop_reason', 'maximum_search_depth')}
    if source == 'observed_google_playwright_serp' and snapshot is None:
        raise ValueError('The selected SERP snapshot cannot be verified for report metadata.')
    timestamps = {}
    for entry in inventory.get('entries', []):
        if entry.get('status') != 'available' or not entry.get('path'):
            continue
        path = root / entry['path']
        if not path.is_file() or _sha(path) != entry.get('sha256'):
            raise ValueError('Evidence changed while preparing report metadata: ' + str(entry.get('path')))
        evidence = _read(path)
        sidecar_path = path.with_suffix('.meta.json')
        try:
            sidecar = _read(sidecar_path) if sidecar_path.is_file() else {}
        except (OSError, ValueError, TypeError):
            sidecar = {}
        stamp = next((source.get(key) for source in (evidence, sidecar) for key in
                      ('collected_at', 'captured_at', 'fetch_time', 'fetchTime', 'timestamp', 'created_at', 'generated_at')
                      if source.get(key)), None)
        if stamp:
            timestamps[f"{entry.get('kind')}:{entry.get('side') or 'shared'}"] = stamp
    tracked = selection['ours']
    competitor = selection['benchmark']
    return {
        'schema_version': '1.0', 'investigation_id': selection['investigation_id'],
        'source': source, 'keyword': keyword,
        'search_engine': 'Google' if snapshot is not None else None,
        'market': ((search_context.get('location_note') if search_context else None) or None),
        'location_coordinate': ((snapshot or {}).get('location_coordinate')),
        'search_timestamp': ((snapshot or {}).get('datetime') or (search_context.get('collected_at') if search_context else None)),
        'search_context': search_context,
        'serp_snapshot_reference': serp_reference if snapshot is not None else None,
        'serp_sha256': snapshot_hash,
        'rankings_available': snapshot is not None,
        'tracked_page': {'domain': tracked.get('domain'), 'url': tracked.get('url'),
                         'rank': ranks['ours'], 'redirect_url': tracked.get('redirect_url'),
                         'canonical_url': tracked.get('canonical_url')},
        'competitor_page': {'domain': competitor.get('domain'), 'url': competitor.get('url'),
                            'rank': ranks['benchmark'], 'redirect_url': competitor.get('redirect_url'),
                            'canonical_url': competitor.get('canonical_url')},
        'evidence_collection_timestamps': timestamps,
        'evidence_references': [{'path': row.get('path'), 'sha256': row.get('sha256'),
                                 'kind': row.get('kind'), 'side': row.get('side')}
                                for row in inventory.get('entries', []) if row.get('status') == 'available'],
    }


def _compatible_executive_payload(results_source: Path, selection: dict, inventory: dict,
                                  metadata: dict) -> bool:
    """Require investigation-bound provenance; a filename alone is never sufficient."""
    llm = results_source / 'llm_outputs'
    executive = llm / 'executive_validated.json'
    provenance_path = llm / 'executive_provenance.json'
    canonical = results_source / 'llm_foundation' / 'canonical_evidence.json'
    raw = llm / 'executive_model_raw.json'
    run_metadata_path = llm / 'executive_run_metadata.json'
    run_status_path = llm / 'executive_run_status.json'
    required = (executive, provenance_path, canonical, raw, run_metadata_path, run_status_path)
    if not all(path.is_file() for path in required):
        return False
    try:
        provenance = _read(provenance_path)
        run_metadata, run_status = _read(run_metadata_path), _read(run_status_path)
        raw_data, canonical_data = _read(raw), _read(canonical)
        specialists = {task: llm / f'{task}_validated.json'
                       for task in ('onpage', 'backlinks', 'technical', 'competition')}
        if not all(path.is_file() for path in specialists.values()):
            return False
        specialist_hashes = {path.name: _sha(path) for path in specialists.values()}
        expected_evidence = {row['path']: row['sha256'] for row in inventory.get('entries', [])
                             if row.get('status') == 'available'}
        if (provenance.get('schema_version') != '1.0' or
                provenance.get('investigation_id') != selection.get('investigation_id') or
                str(provenance.get('keyword') or '').casefold() != selection['keyword'].casefold() or
                normalized_url(provenance.get('tracked_url')) != normalized_url(selection['ours']['url']) or
                normalized_url(provenance.get('competitor_url')) != normalized_url(selection['benchmark']['url']) or
                provenance.get('evidence_hashes') != expected_evidence or
                provenance.get('specialist_hashes') != specialist_hashes or
                provenance.get('search_context') != metadata.get('search_context') or
                provenance.get('serp_sha256') != metadata.get('serp_sha256') or
                provenance.get('executive_sha256') != _sha(executive) or
                provenance.get('canonical_sha256') != _sha(canonical) or
                provenance.get('raw_response_sha256') != _sha(raw) or
                run_metadata.get('status') != 'validated' or run_status.get('status') != 'validated' or
                str(run_metadata.get('keyword') or '').casefold() != selection['keyword'].casefold() or
                raw_data.get('keyword', '').casefold() != selection['keyword'].casefold() or
                not provenance.get('model') or raw_data.get('model') != provenance.get('model') or
                run_metadata.get('model') != provenance.get('model')):
            return False
        prompt_relative = provenance.get('prompt_path')
        prompt_hash = provenance.get('prompt_sha256')
        if not prompt_relative or not prompt_hash:
            return False
        prompt_path = (results_source / prompt_relative).resolve()
        if results_source.resolve() not in prompt_path.parents or not prompt_path.is_file() or _sha(prompt_path) != prompt_hash:
            return False
        identity = canonical_data.get('investigation') or {}
        tracked = canonical_data.get('tracked_website') or {}
        competitors = canonical_data.get('competitors') or []
        if not (str(identity.get('keyword') or '').casefold() == selection['keyword'].casefold() and
                normalized_url(tracked.get('ranking_url')) == normalized_url(selection['ours']['url']) and
                bool(competitors) and
                normalized_url(competitors[0].get('ranking_url')) == normalized_url(selection['benchmark']['url'])):
            return False
        canonical_serp = ((canonical_data.get('evidence') or {}).get('serp') or {}).get('ranking_summary') or {}
        if (str(canonical_serp.get('keyword') or '').casefold() != selection['keyword'].casefold() or
                normalized_url(canonical_serp.get('our_url')) != normalized_url(selection['ours']['url']) or
                normalized_url(canonical_serp.get('benchmark_url')) != normalized_url(selection['benchmark']['url']) or
                (metadata.get('rankings_available') and
                 (canonical_serp.get('our_position') != metadata['tracked_page'].get('rank') or
                  canonical_serp.get('benchmark_position') != metadata['competitor_page'].get('rank')))):
            return False
        from llm_foundation.executive_synthesis import build_packet, parse_response, validate_executive
        specialist_data = {task: _read(path) for task, path in specialists.items()}
        packet = build_packet(canonical_data, specialist_data)
        response = parse_response(raw_data.get('raw_response', ''))
        if validate_executive(response, packet):
            return False
        from llm_foundation.structured_facts import publish_verified_response
        expected_executive, _ = publish_verified_response(response, packet)
        executive_data = _read(executive)
        if executive_data != expected_executive:
            return False
        from scripts.generate_executive_pdf import report_consistency_errors
        if report_consistency_errors(executive_data) or historical_pdf_missing_sections(executive_data):
            return False
        from llm_foundation.recommendation_quality import audit_recommendations
        focused = executive_data.get('recommendation_engine') == 'four_specialist_focused_v4'
        quality = audit_recommendations(
            dict(executive_data, _enforce_user_loss_check=True),
            expected_findings=[row['id'] for row in executive_data.get('specialist_findings', [])],
            require_actionable=focused, enforce_causation=focused,
            enforce_unmeasured_loss=focused)
        if quality.get('blocking_count'):
            return False
        return True
    except (OSError, ValueError, TypeError, KeyError):
        return False


def _generate_reports(output: Path, comparison: dict, keyword: str, metadata: dict,
                      *, executive: dict | None = None, canonical: dict | None = None,
                      only: tuple[str, ...] = ('pdf', 'appendix')) -> dict:
    """Render reports atomically so incomplete artifacts never look complete."""
    from scripts.generate_executive_pdf import build_appendix, build_management_pdf
    slug = keyword_slug(keyword)
    paths = {'pdf': output / f'{slug}_executive_report.pdf',
             'appendix': output / f'{slug}_technical_appendix.md'}
    statuses = {'pdf': 'not_requested', 'appendix': 'not_requested'}
    errors = {}
    artifact_hashes = {}
    run_id = uuid.uuid4().hex
    if 'pdf' in only:
        temp = output / f'.{slug}_{run_id}.tmp.pdf'
        try:
            build_management_pdf(temp, comparison, executive or {}, None, keyword, canonical,
                                 metadata.get('search_timestamp'), metadata)
            if not temp.is_file() or not temp.read_bytes().startswith(b'%PDF'):
                raise ValueError('PDF renderer did not produce a valid PDF file.')
            os.replace(temp, paths['pdf'])
            statuses['pdf'] = 'generated'
            artifact_hashes['pdf'] = _sha(paths['pdf'])
        except Exception as exc:
            temp.unlink(missing_ok=True)
            paths['pdf'].unlink(missing_ok=True)
            statuses['pdf'] = 'failed'
            errors['pdf'] = f'{type(exc).__name__}: {exc}'
    if 'appendix' in only:
        temp = output / f'.{slug}_{run_id}.tmp.md'
        try:
            appendix = build_appendix(comparison, executive or {}, None,
                                      f'{slug}_comparison.json', canonical,
                                      investigation_metadata=metadata)
            temp.write_text(appendix, encoding='utf-8')
            os.replace(temp, paths['appendix'])
            statuses['appendix'] = 'generated'
            artifact_hashes['appendix'] = _sha(paths['appendix'])
        except Exception as exc:
            temp.unlink(missing_ok=True)
            paths['appendix'].unlink(missing_ok=True)
            statuses['appendix'] = 'failed'
            errors['appendix'] = f'{type(exc).__name__}: {exc}'
    generated = [key for key, value in statuses.items() if value == 'generated']
    failed = [key for key, value in statuses.items() if value == 'failed']
    status = 'completed' if not failed else ('partial' if generated else 'failed')
    return {'status': status, 'pdf_status': statuses['pdf'],
            'appendix_status': statuses['appendix'],
            'pdf_path': str(paths['pdf']) if statuses['pdf'] == 'generated' else None,
            'technical_appendix_path': str(paths['appendix']) if statuses['appendix'] == 'generated' else None,
            'errors': errors, 'artifact_sha256': artifact_hashes,
            'executive_mode': 'validated_investigation_bound' if executive else 'deterministic_comparison_recommendations'}


def run(investigation_id: str, *, root: Path = ROOT, investigation_dir: Path | None = None,
        generate_pdf: bool = True) -> dict:
    """Serialize offline runs because the existing analysis has module-level paths."""
    with _RUN_LOCK:
        return _run_impl(investigation_id, root=root, investigation_dir=investigation_dir,
                         generate_pdf=generate_pdf)


def _run_impl(investigation_id: str, *, root: Path, investigation_dir: Path | None,
              generate_pdf: bool) -> dict:
    """Replay verified real evidence, never call any collection or inference service."""
    selection = serp_investigations.read_investigation(investigation_id)
    source = selection.get('source')
    if source == 'observed_google_playwright_serp':
        from scripts.serp_processing_adapter import validate_serp_origin_investigation
        selection = validate_serp_origin_investigation(investigation_id)
    elif source != 'manual_exact_webpage_urls':
        raise ValueError('Offline execution requires a manual exact-page investigation.')
    inventory = evidence_inventory(selection, root=root)  # revalidate at execution time
    if not inventory['complete']:
        missing = [f"{e['kind']} ({e['side'] or 'shared'})" for e in inventory['entries'] if e['status'] != 'available']
        raise ValueError('Saved evidence incomplete or mismatched: ' + ', '.join(missing))
    keyword = selection['keyword']
    slug = keyword_slug(keyword)
    processed_source = root / 'data' / 'processed' / slug
    results_source = root / 'output' / 'results' / slug
    serp_path = processed_source / 'serp_google.json'
    if not serp_path.is_file():
        raise ValueError('No historical normalized Google SERP evidence available.')
    serp = _read(serp_path)
    if serp.get('keyword', '').casefold() != keyword.casefold():
        raise ValueError('Historical Google SERP keyword mismatch.')
    for side in ('ours', 'benchmark'):
        if _exact_rank(serp, selection[side]['url']) is None:
            raise ValueError(f"Exact {side} page absent from historical Google SERP; cannot claim a ranking.")
    base = investigation_dir or (serp_investigations.INVESTIGATIONS / investigation_id)
    processed = base / 'processed'
    output = base / 'results'
    if (base / 'offline_execution.json').exists():
        raise ValueError('This investigation already has an offline execution. Create a new investigation to replay again.')
    if processed.exists() or output.exists():
        raise ValueError('Investigation output already exists; refusing to overwrite.')
    processed.mkdir(parents=True)
    output.mkdir(parents=True)
    provenance = []
    try:
        # All raw files are independently matched to the requested exact pages
        # by the pre-existing evidence inventory, and their SHA is rechecked.
        for item in inventory['entries']:
            src = root / item['path']
            if _sha(src) != item['sha256']:
                raise ValueError('Evidence changed during offline replay: ' + item['path'])
            raw = _read(src)
            kind, side = item['kind'], item['side']
            if kind == 'labs_ranked_keywords':
                dest = f'ranked_{side}.json'
                normalized = normalize_ranked_keywords(raw, selection[side]['domain'])
            elif kind.startswith('backlinks_'):
                scope = 'domain' if kind == 'backlinks_domain_summary' else 'page'
                target = selection[side]['domain'] if scope == 'domain' else selection[side]['url']
                dest = f'backlinks_{side}_{scope}_summary.json'
                normalized = normalize_backlink_summary(raw, target)
                normalized.update({'keyword': keyword, 'scope': scope, 'side': side,
                                   'serp_engine': 'google' if scope == 'page' else None,
                                   'ranking_url': target if scope == 'page' else None,
                                   'target_verified': True})
            elif kind == 'playwright_page':
                dest = f'page_{side}.json'
                normalized = normalize_page(raw)
                normalized.update({'keyword': keyword, 'serp_engine': 'google', 'target_side': side,
                                   'ranking_url': selection[side]['url'],
                                   'ranking_position': _exact_rank(serp, selection[side]['url'])['rank_group']})
            elif kind == 'lighthouse_mobile':
                dest = f'lighthouse_{side}_mobile.json'
                normalized = normalize_lighthouse(raw, keyword=keyword, side=side,
                    device='mobile', ranking_url=selection[side]['url'])
            elif kind == 'labs_domain_intersection':
                dest = 'domain_intersection.json'
                normalized = normalize_domain_intersection(raw, keyword)
            elif kind == 'labs_search_intent':
                dest = 'search_intent.json'
                normalized = normalize_search_intent(raw)
            else:
                raise ValueError('Unrecognized evidence kind: ' + kind)
            _write(processed / dest, normalized)
            provenance.append({'normalized_file': dest, 'raw_file': item['path'], 'sha256': item['sha256']})
        shutil.copy2(serp_path, processed / 'serp_google.json')
        provenance.append({'normalized_file': 'serp_google.json',
                           'raw_file': str(serp_path.relative_to(root)).replace('\\', '/'),
                           'sha256': _sha(serp_path)})
        # Reuse the existing analysis module in an isolated process. Its global
        # defaults remain unchanged for legacy CLI users and dashboard pages.
        from scripts import run_analysis
        original = (run_analysis.PROCESSED_DIR, run_analysis.RESULTS_DIR,
                    run_analysis.settings, run_analysis.KEYWORD_SLUG,
                    run_analysis.compare_rankings)
        def compare_exact(data, ours, benchmark):
            # Preserve every observed rank; ignore alternate URLs belonging to
            # the selected domains only when choosing their exact-page ranks.
            rows = [r for r in data.get('organic_results', []) if
                    (r.get('domain') not in (ours, benchmark) or
                     normalized_url(r.get('url')) == normalized_url(
                         selection['ours']['url'] if r.get('domain') == ours else selection['benchmark']['url']))]
            return original_compare_rankings({**data, 'organic_results': rows}, ours, benchmark)
        try:
            run_analysis.PROCESSED_DIR = processed
            run_analysis.RESULTS_DIR = output
            run_analysis.KEYWORD_SLUG = slug
            run_analysis.settings = replace(original[2], keyword=keyword,
                our_domain=selection['ours']['domain'],
                benchmark_competitor_domain=selection['benchmark']['domain'])
            run_analysis.compare_rankings = compare_exact
            run_analysis.main()
        finally:
            (run_analysis.PROCESSED_DIR, run_analysis.RESULTS_DIR,
             run_analysis.settings, run_analysis.KEYWORD_SLUG,
             run_analysis.compare_rankings) = original
        comparison_path = output / f'{slug}_comparison.json'
        comparison = _read(comparison_path)
        observed = comparison['primary_ranking_urls']
        if any(normalized_url(observed.get(side)) != normalized_url(selection[side]['url']) for side in ('ours','benchmark')):
            raise ValueError('Analysis did not retain exact selected page URLs.')
        historical_llm = results_source / 'llm_outputs' / 'executive_validated.json'
        executive, canonical = None, None
        metadata = None
        eligibility_error = None
        compatible_executive = False
        try:
            metadata = _report_metadata(selection, inventory, root=root)
            _comparison_for_investigation(selection, comparison, metadata)
            compatible_executive = _compatible_executive_payload(results_source, selection, inventory, metadata)
            if compatible_executive:
                executive = _read(historical_llm)
                canonical_path = results_source / 'llm_foundation' / 'canonical_evidence.json'
                canonical = _read(canonical_path)
                canonical['_source_sha256'] = _sha(canonical_path)
                provenance.append({'historical_llm_output': str(historical_llm.relative_to(root)),
                                   'sha256': _sha(historical_llm),
                                   'mode': 'reused_investigation_bound_validated_output_no_inference'})
        except Exception as exc:
            eligibility_error = f'{type(exc).__name__}: {exc}'
        report_result = {'status': 'not_requested', 'pdf_status': 'not_requested',
                         'appendix_status': 'not_requested', 'pdf_path': None,
                         'technical_appendix_path': None, 'errors': {},
                         'executive_mode': 'not_requested'}
        if generate_pdf:
            if eligibility_error:
                report_result = {'status': 'failed', 'pdf_status': 'failed',
                                 'appendix_status': 'failed', 'pdf_path': None,
                                 'technical_appendix_path': None,
                                 'errors': {'eligibility': eligibility_error},
                                 'executive_mode': 'not_started'}
            else:
                report_result = _generate_reports(output, comparison, keyword, metadata or {},
                                                  executive=executive, canonical=canonical)
        pdf_path = Path(report_result['pdf_path']) if report_result.get('pdf_path') else None
        appendix_path = (Path(report_result['technical_appendix_path'])
                         if report_result.get('technical_appendix_path') else None)
        report = {'schema_version': '1.0', 'investigation_id': investigation_id,
                  'mode': 'offline_saved_evidence_replay', 'requests_made': 0,
                  'llm_inference_requests': 0,
                  'status': ('completed' if report_result['status'] in ('completed', 'not_requested') else 'report_failed'),
                  'processing_status': 'completed', 'report_status': report_result['status'],
                  'pdf_status': report_result['pdf_status'],
                  'technical_appendix_status': report_result['appendix_status'],
                  'report_errors': report_result.get('errors') or {},
                  'report_artifact_sha256': report_result.get('artifact_sha256') or {},
                  'executive_mode': report_result.get('executive_mode'),
                  'historical_pdf_warning': (
                      'Report generation failed: ' + '; '.join(report_result.get('errors', {}).values())
                      if report_result['status'] in ('failed', 'partial') else
                      'No compatible investigation-bound executive payload was reused; the selected comparison recommendations are shown.'
                      if generate_pdf and not executive else None),
                  'keyword': keyword, 'selected_pages': {side: selection[side] for side in ('ours','benchmark')},
                  'historical_serp_datetime': serp.get('datetime'),
                  'investigation_metadata': metadata,
                  'note': 'Historical SERP and separately captured SEO evidence; not a new live ranking measurement. Saved LLM outputs are historical, not newly generated.',
                  'source_provenance': provenance,
                  'evidence_root': str(root.resolve()),
                  'comparison_path': str(comparison_path.relative_to(base)),
                  'pdf_path': str(pdf_path.relative_to(base)) if pdf_path else None,
                  'technical_appendix_path': str(appendix_path.relative_to(base)) if appendix_path else None,
                  'historical_pdf_status': report_result['pdf_status'],
                  'completed_at': datetime.now(timezone.utc).isoformat()}
        _write(base / 'offline_execution.json', report)
        return report
    except Exception:
        # Preserve the original investigation and raw evidence; avoid leaving
        # a misleading partial report that looks like a successful execution.
        shutil.rmtree(processed, ignore_errors=True)
        shutil.rmtree(output, ignore_errors=True)
        raise


def retry_report(investigation_id: str, *, root: Path | None = None,
                 investigation_dir: Path | None = None) -> dict:
    """Retry failed report rendering from saved comparison output only."""
    with _RUN_LOCK:
        return _retry_report_impl(investigation_id, root=root, investigation_dir=investigation_dir)


def _retry_report_impl(investigation_id: str, *, root: Path | None,
                       investigation_dir: Path | None) -> dict:
    base = investigation_dir or (serp_investigations.INVESTIGATIONS / investigation_id)
    status_path = base / 'offline_execution.json'
    if not status_path.is_file():
        raise FileNotFoundError('No saved offline comparison exists for report retry.')
    report = _read(status_path)
    if report.get('investigation_id') != investigation_id or report.get('status') != 'report_failed':
        raise ValueError('Report-only retry requires this investigation to have a failed report status.')
    root = Path(root or report.get('evidence_root') or ROOT)
    selection = serp_investigations.read_investigation(investigation_id)
    if selection.get('source') == 'observed_google_playwright_serp':
        from scripts.serp_processing_adapter import validate_serp_origin_investigation
        selection = validate_serp_origin_investigation(investigation_id)
    elif selection.get('source') != 'manual_exact_webpage_urls':
        raise ValueError('Report retry requires a supported investigation source.')
    inventory = evidence_inventory(selection, root=root)
    if not inventory.get('complete'):
        raise ValueError('Saved evidence is incomplete; report retry is not permitted.')
    original_hashes = {row.get('raw_file'): row.get('sha256')
                       for row in report.get('source_provenance', []) if row.get('raw_file')}
    for entry in inventory.get('entries', []):
        if original_hashes.get(entry.get('path')) != entry.get('sha256'):
            raise ValueError('Saved evidence identity changed since comparison processing; report retry is not permitted.')
    comparison_path = (base / report.get('comparison_path', '')).resolve()
    results_dir = (base / 'results').resolve()
    if comparison_path.parent != results_dir or not comparison_path.is_file():
        raise ValueError('Investigation-scoped comparison output is missing or invalid.')
    comparison = _read(comparison_path)
    metadata = _report_metadata(selection, inventory, root=root)
    _comparison_for_investigation(selection, comparison, metadata)
    results_source = root / 'output' / 'results' / keyword_slug(selection['keyword'])
    executive, canonical = None, None
    if _compatible_executive_payload(results_source, selection, inventory, metadata):
        executive = _read(results_source / 'llm_outputs' / 'executive_validated.json')
        canonical_path = results_source / 'llm_foundation' / 'canonical_evidence.json'
        canonical = _read(canonical_path)
        canonical['_source_sha256'] = _sha(canonical_path)
    output = base / 'results'
    previous_statuses = {'pdf': report.get('pdf_status'),
                         'appendix': report.get('technical_appendix_status')}
    slug = keyword_slug(selection['keyword'])
    prior_paths = {'pdf': output / f'{slug}_executive_report.pdf',
                   'appendix': output / f'{slug}_technical_appendix.md'}
    prior_hashes = report.get('report_artifact_sha256') or {}
    prior_valid = {
        kind: (previous_statuses[kind] == 'generated' and prior_paths[kind].is_file() and
               prior_hashes.get(kind) == _sha(prior_paths[kind]) and
               (kind != 'pdf' or prior_paths[kind].read_bytes().startswith(b'%PDF')))
        for kind in ('pdf', 'appendix')
    }
    only = tuple(kind for kind in ('pdf', 'appendix')
                 if not prior_valid[kind])
    if not only:
        raise ValueError('Both investigation-scoped report artifacts already exist; there is nothing to retry.')
    regenerated = _generate_reports(output, comparison, selection['keyword'], metadata,
                                    executive=executive, canonical=canonical, only=only)
    merged = {
        'pdf_status': ('generated' if prior_valid['pdf']
                       else regenerated['pdf_status']),
        'technical_appendix_status': ('generated' if prior_valid['appendix']
                                      else regenerated['appendix_status']),
    }
    merged['report_status'] = ('completed' if all(value == 'generated' for value in merged.values())
                               else 'partial' if 'generated' in merged.values() else 'failed')
    report.update(merged)
    report['status'] = 'completed' if merged['report_status'] == 'completed' else 'report_failed'
    report['report_errors'] = regenerated.get('errors') or {}
    report['report_artifact_sha256'] = {
        kind: (prior_hashes[kind] if prior_valid[kind] else regenerated.get('artifact_sha256', {}).get(kind))
        for kind in ('pdf', 'appendix')
        if (prior_valid[kind] or regenerated.get('artifact_sha256', {}).get(kind))
    }
    report['executive_mode'] = regenerated.get('executive_mode')
    report['historical_pdf_warning'] = (
        'Report generation failed: ' + '; '.join(regenerated.get('errors', {}).values())
        if merged['report_status'] != 'completed' else
        'No compatible investigation-bound executive payload was reused; the selected comparison recommendations are shown.'
        if not executive else None)
    report['investigation_metadata'] = metadata
    report['pdf_path'] = str(prior_paths['pdf'].relative_to(base)) if merged['pdf_status'] == 'generated' else None
    report['technical_appendix_path'] = (str(prior_paths['appendix'].relative_to(base))
                                         if merged['technical_appendix_status'] == 'generated' else None)
    report['completed_at'] = datetime.now(timezone.utc).isoformat()
    _write(status_path, report)
    return report


def main():
    p = argparse.ArgumentParser(description='Offline replay of an existing manual two-URL investigation (no external calls)')
    p.add_argument('investigation_id')
    p.add_argument('--no-pdf', action='store_true')
    p.add_argument('--retry-report', action='store_true',
                   help='Retry failed PDF/appendix generation from the saved comparison without reprocessing evidence')
    a = p.parse_args()
    result = (retry_report(a.investigation_id) if a.retry_report else
              run(a.investigation_id, generate_pdf=not a.no_pdf))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
