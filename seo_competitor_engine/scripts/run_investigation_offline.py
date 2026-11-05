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
from pathlib import Path
import shutil
import subprocess
import sys
import threading

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
    if selection.get('source') != 'manual_exact_webpage_urls':
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
    # The existing PDF explicitly describes Hollywoodbets versus Betway. Until
    # dynamic reporting is implemented, do not mislabel another pair.
    supported_pair = (selection['ours']['domain'] == 'hollywoodbets.net' and
                      selection['benchmark']['domain'] == 'betway.co.za' and keyword.casefold() == 'aviator')
    if generate_pdf and not supported_pair:
        raise ValueError('Existing executive PDF is Aviator/Hollywoodbets/Betway-specific; dynamic PDF requires a later adaptation.')
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
        if supported_pair and historical_llm.exists():
            target = output / 'llm_outputs' / 'executive_validated.json'
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(historical_llm, target)
            provenance.append({'historical_llm_output': str(historical_llm.relative_to(root)),
                               'sha256': _sha(historical_llm), 'mode': 'reused_saved_output_no_inference'})
        # Upgrade only the investigation copy of the historical executive output.
        # The saved original model response and specialist outputs are never overwritten.
        if supported_pair and historical_llm.exists():
            from llm_foundation.executive_synthesis import build_packet, parse_response, validate_executive
            from llm_foundation.structured_facts import publish_verified_response
            from llm_foundation.information_preservation import save_preservation_report
            llm_source = results_source / 'llm_outputs'
            canonical_source = results_source / 'llm_foundation' / 'canonical_evidence.json'
            raw_source = llm_source / 'executive_model_raw.json'
            tasks = ('onpage', 'backlinks', 'technical', 'competition')
            specialist_sources = {task: llm_source / f'{task}_validated.json' for task in tasks}
            if canonical_source.exists() and raw_source.exists() and all(x.exists() for x in specialist_sources.values()):
                canonical = _read(canonical_source)
                identity = canonical.get('tracked_website') or {}
                others = canonical.get('competitors') or []
                if (normalized_url(identity.get('ranking_url')) == normalized_url(selection['ours']['url']) and
                    others and normalized_url(others[0].get('ranking_url')) == normalized_url(selection['benchmark']['url']) and
                    (canonical.get('investigation') or {}).get('keyword', '').casefold() == keyword.casefold()):
                    specialists = {task: _read(path) for task, path in specialist_sources.items()}
                    packet = build_packet(canonical, specialists)
                    original_model = parse_response(_read(raw_source)['raw_response'])
                    problems = validate_executive(original_model, packet)
                    if problems:
                        raise ValueError('Historical model output no longer validates: ' + '; '.join(problems[:3]))
                    upgraded, _ = publish_verified_response(original_model, packet)
                    shutil.copy2(historical_llm, output / 'llm_outputs' / 'historical_executive_before_preservation.json')
                    _write(output / 'llm_outputs' / 'executive_validated.json', upgraded)
                    _write(output / 'llm_outputs' / 'executive_evidence_packet.json', packet)
                    shutil.copy2(raw_source, output / 'llm_outputs' / 'executive_model_raw.json')
                    for task, source in specialist_sources.items():
                        shutil.copy2(source, output / 'llm_outputs' / f'{task}_validated.json')
                    preservation = save_preservation_report(output, specialists, upgraded)
                    if not preservation['all_original_findings_preserved']:
                        raise ValueError('Specialist findings lost during publication.')
                    provenance.append({'historical_specialist_findings': preservation['original_specialist_findings'],
                                       'preserved': True, 'mode': 'saved_real_outputs_no_inference'})
                else:
                    raise ValueError('Historical LLM evidence does not match the exact selected ranking URLs.')
        pdf_generated = False
        pdf_warning = None
        if generate_pdf:
            historical_executive = output / 'llm_outputs' / 'executive_validated.json'
            if not historical_executive.is_file():
                raise ValueError('Saved historical executive output missing; cannot generate the existing report.')
            missing = historical_pdf_missing_sections(_read(historical_executive))
            if missing:
                # Keep successful historical investigations reportable using the
                # already-saved deterministic recommendations. Preserve the old
                # executive payload in the appendix; do not fabricate Gemma plans.
                from scripts.generate_executive_pdf import build_appendix, build_management_pdf
                legacy_executive = _read(historical_executive)
                canonical_path = results_source / 'llm_foundation' / 'canonical_evidence.json'
                canonical = _read(canonical_path) if canonical_path.is_file() else None
                serp_path = root / 'data/processed' / slug / 'serp_google.json'
                historical_date = _read(serp_path).get('datetime') if serp_path.is_file() else None
                pdf_path = output / f'{keyword}_executive_report.pdf'
                appendix_path = output / f'{keyword}_technical_appendix.md'
                build_management_pdf(pdf_path, comparison, legacy_executive, None,
                                     keyword, canonical, historical_date)
                appendix = build_appendix(comparison, legacy_executive, None,
                                          comparison_path.name, canonical)
                appendix_path.write_text(appendix, encoding='utf-8')
                pdf_generated = True
                pdf_warning = ('The saved executive payload lacks ' + ', '.join(missing) +
                               '; the draft uses the saved deterministic recommendation list. '
                               'No Gemma recommendations were fabricated or regenerated.')
            else:
                from scripts.generate_executive_pdf import main as pdf_main
                pdf_main(['--keyword', keyword, '--input', str(comparison_path),
                          '--output-dir', str(output)])
                pdf_generated = True
        report = {'schema_version': '1.0', 'investigation_id': investigation_id,
                  'mode': 'offline_saved_evidence_replay', 'requests_made': 0,
                  'llm_inference_requests': 0, 'status': 'completed',
                  'keyword': keyword, 'selected_pages': {side: selection[side] for side in ('ours','benchmark')},
                  'historical_serp_datetime': serp.get('datetime'),
                  'note': 'Historical SERP and separately captured SEO evidence; not a new live ranking measurement. Saved LLM outputs are historical, not newly generated.',
                  'source_provenance': provenance,
                  'comparison_path': str(comparison_path.relative_to(base)),
                  'pdf_path': str((output / f'{keyword}_executive_report.pdf').relative_to(base)) if pdf_generated else None,
                  'historical_pdf_status': ('generated' if pdf_generated else
                                            'skipped_incompatible_historical_executive' if pdf_warning else 'not_requested'),
                  'historical_pdf_warning': pdf_warning,
                  'completed_at': datetime.now(timezone.utc).isoformat()}
        _write(base / 'offline_execution.json', report)
        return report
    except Exception:
        # Preserve the original investigation and raw evidence; avoid leaving
        # a misleading partial report that looks like a successful execution.
        shutil.rmtree(processed, ignore_errors=True)
        shutil.rmtree(output, ignore_errors=True)
        raise


def main():
    p = argparse.ArgumentParser(description='Offline replay of an existing manual two-URL investigation (no external calls)')
    p.add_argument('investigation_id')
    p.add_argument('--no-pdf', action='store_true')
    a = p.parse_args()
    print(json.dumps(run(a.investigation_id, generate_pdf=not a.no_pdf), indent=2))


if __name__ == '__main__':
    main()
