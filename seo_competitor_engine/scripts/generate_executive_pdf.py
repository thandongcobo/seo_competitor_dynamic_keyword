"""Offline management PDF and full evidence appendix from an explicitly selected executive JSON.

This renderer never invokes collectors or an LLM. The executive JSON is not modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from copy import deepcopy
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

from analysis.final_report import generate_report
from llm_foundation.recommendation_quality import audit_recommendations
from config.settings import keyword_slug
from analysis.recommendation_classification import adapt_recommendations, TIER_LABELS, TIER_ORDER


def report_consistency_errors(ex):
    """Check preservation of specialist IDs and reciprocal plan links."""
    errors = []
    plans = ex.get('implementation_plans') or []
    rows = ex.get('finding_dispositions') or []
    originals = ex.get('specialist_findings') or []
    original_ids = [r.get('id') for r in originals if isinstance(r, dict)]
    disposition_ids = [r.get('specialist_finding_id') for r in rows if isinstance(r, dict)]
    if len(original_ids) != len(set(original_ids)):
        errors.append('Duplicate original specialist finding IDs')
    if len(disposition_ids) != len(set(disposition_ids)):
        errors.append('Duplicate specialist finding dispositions')
    if originals and set(original_ids) != set(disposition_ids):
        errors.append('Specialist finding coverage differs from original findings')
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f'Disposition {i} is not an object')
            continue
        fid = row.get('specialist_finding_id')
        for idx in row.get('plan_indices') or []:
            if type(idx) is not int or idx < 0 or idx >= len(plans):
                errors.append(f'Disposition {fid} references invalid plan index {idx}')
            elif not isinstance(plans[idx], dict) or fid not in (plans[idx].get('specialist_finding_ids') or []):
                errors.append(f'Disposition {fid} has no reciprocal link in plan {idx}')
    for idx, plan in enumerate(plans):
        if not isinstance(plan, dict):
            errors.append(f'Plan {idx} is not an object')
            continue
        for fid in plan.get('specialist_finding_ids') or []:
            if not any(isinstance(r, dict) and r.get('specialist_finding_id') == fid and
                       idx in (r.get('plan_indices') or []) for r in rows):
                errors.append(f'Plan {idx} has no reciprocal disposition for {fid}')
    return errors


def _md(value):
    """Escape untrusted content in Markdown headings/tables without rewriting evidence."""
    return str(value or '').replace('|', '\\|').replace('\n', ' ')


def _identity_metadata_lines(metadata):
    if not isinstance(metadata, dict):
        return []
    tracked = metadata.get('tracked_page') or {}
    competitor = metadata.get('competitor_page') or {}
    context = metadata.get('search_context') or {}
    lines = [
        '## Investigation identity and search context', '',
        f"**Investigation ID:** {metadata.get('investigation_id') or 'Not recorded'}", '',
        f"**Keyword / source:** {metadata.get('keyword') or 'Not recorded'} / {metadata.get('source') or 'Not recorded'}", '',
        f"**Search engine / market:** {metadata.get('search_engine') or 'Not available'} / {metadata.get('market') or 'Not available'}", '',
        f"**Search timestamp:** {metadata.get('search_timestamp') or 'Not available'}", '',
        '**Exact selected pages:**', '',
        f"- Tracked/primary page: {tracked.get('url') or 'Not recorded'} (observed position: {tracked.get('rank') if tracked.get('rank') is not None else 'Not available'})",
        f"- Competitor page: {competitor.get('url') or 'Not recorded'} (observed position: {competitor.get('rank') if competitor.get('rank') is not None else 'Not available'})", '',
    ]
    if tracked.get('redirect_url') or tracked.get('canonical_url'):
        lines.append('**Tracked-page redirect / canonical:** ' +
                     str(tracked.get('redirect_url') or 'Not recorded') + ' / ' +
                     str(tracked.get('canonical_url') or 'Not recorded'))
        lines.append('')
    if competitor.get('redirect_url') or competitor.get('canonical_url'):
        lines.append('**Competitor-page redirect / canonical:** ' +
                     str(competitor.get('redirect_url') or 'Not recorded') + ' / ' +
                     str(competitor.get('canonical_url') or 'Not recorded'))
        lines.append('')
    if metadata.get('serp_snapshot_reference'):
        lines.extend(['**Saved SERP snapshot reference:** ' + str(metadata['serp_snapshot_reference']), ''])
        lines.extend(['**Saved SERP snapshot SHA-256:** ' + str(metadata.get('serp_sha256') or 'Not recorded'), ''])
    if context:
        lines.extend(['**Saved search context:**', '', '```json',
                      json.dumps(context, ensure_ascii=False, indent=2), '```', ''])
    timestamps = metadata.get('evidence_collection_timestamps') or {}
    if timestamps:
        lines.extend(['**Evidence collection timestamps recorded in source artifacts:**', ''])
        lines.extend(f'- {key}: {value}' for key, value in sorted(timestamps.items()))
        lines.append('')
    references = metadata.get('evidence_references') or []
    if references:
        lines.extend(['**Selected investigation evidence references and SHA-256:**', ''])
        lines.extend(f"- {row.get('kind')} / {row.get('side') or 'shared'}: `{row.get('path')}` — `{row.get('sha256')}`"
                     for row in references)
        lines.append('')
    return lines


def build_appendix(data, ex, quality, source_name, canonical=None, run_records=None,
                   investigation_metadata=None):
    """Retain the entire deterministic source report and add *all* repaired evidence."""
    adapted_rows, classification_audit = adapt_recommendations(data.get('recommendations') or [])
    report_data = deepcopy(data)
    if data.get('recommendations'):
        report_data['recommendations'] = adapted_rows
    report_data['recommendation_classification_audit'] = classification_audit
    metadata = investigation_metadata if isinstance(investigation_metadata, dict) else None
    if metadata and not metadata.get('rankings_available'):
        ranking_summary = report_data.get('ranking_summary')
        if not isinstance(ranking_summary, dict):
            ranking_summary = {}
            report_data['ranking_summary'] = ranking_summary
        google = ranking_summary.get('google')
        if not isinstance(google, dict):
            google = {}
            ranking_summary['google'] = google
        google.update({'our_position': None, 'benchmark_position': None})
    deterministic = generate_report(report_data, source_name=source_name)
    if not ex:
        if not metadata:
            return deterministic
        synthetic_label = (['**SYNTHETIC REPORTING FIXTURE - no live or collected evidence.**', '']
                           if str(metadata.get('source') or '').startswith('synthetic_') else [])
        return '\n'.join([
            '# Technical evidence and recommendation appendix', '',
            *synthetic_label,
            'This report uses only the selected investigation’s saved comparison and validated recommendation records. '
            'No compatible investigation-bound executive payload was available; specialist plans were not invented or copied.', '',
            *_identity_metadata_lines(metadata),
            '## Classification compatibility audit', '', '```json',
            json.dumps(classification_audit, ensure_ascii=False, indent=2), '```', '',
            '## Full comparison evidence and recommended actions', '', deterministic.rstrip(), '',
        ])
    plans = ex.get('implementation_plans') or []
    dispositions = ex.get('finding_dispositions') or []
    originals = ex.get('specialist_findings') or []
    factual = ex.get('verified_factual_findings') or ex.get('key_findings') or []
    parts = [
        '# Technical evidence and implementation appendix', '',
        'The management list uses the single authoritative reconciled recommendation records in the selected comparison. '
        'Proposed copy is labeled as proposed and is kept distinct from captured source text. Original specialist plans, '
        'evidence references, historical evidence, validation and recovery records remain preserved below. These items remain drafts for review.', '',
        'The current presentation uses classification schema version 2: Tier 1 — Strong Evidence and Tier 2 — Moderate Evidence. '
        'Where a historical tier was present, its original value remains in the recommendation record/audit while this report uses the versioned evidence-based classification.', '',
        *_identity_metadata_lines(metadata),
        '## Classification compatibility audit', '', '```json',
        json.dumps(classification_audit, ensure_ascii=False, indent=2), '```', '',
        '## Part A — Authoritative recommendation evidence and implementation details', '',
        deterministic.rstrip(), '', '---', '',
        'These are proposals, not proof of ranking causation. Validate current URLs and dependencies before changes.', '',
    ]
    deterministic_recommendations = data.get('recommendations') or []
    if deterministic_recommendations:
        parts.extend(['## Deterministic recommendation implementation details and evidence', '',
                      'The user-facing summary uses a concise action statement. The full resource-level actions, exact URLs, evidence lineage and validation notes are retained here.', ''])
        for row in deterministic_recommendations:
            parts.extend([f"### {row.get('order', '')}. {_md(row.get('title'))}", '',
                          '**Exact target URL:** ' + str(row.get('target_url') or 'Not recorded'), '',
                          '**Difference observed:** ' + str(row.get('evidence') or ''), '',
                          '**Potential impact:** ' + str(row.get('interpretation') or ''), '',
                          '**User-facing action summary:** ' + str(row.get('display_action') or ''), '',
                          '**Full implementation actions:**', ''])
            for step in row.get('actions') or []:
                parts.append('- ' + str(step))
            if row.get('proposed_copy') or row.get('action_composition'):
                parts.extend(['', '**Evidence-grounded action composition:**', '', '```json',
                              json.dumps({'proposed_copy': row.get('proposed_copy'),
                                          'action_composition': row.get('action_composition'),
                                          'proposed_link_pairs': row.get('proposed_link_pairs'),
                                          'coalesced_recommendations': row.get('coalesced_recommendations')},
                                         ensure_ascii=False, indent=2), '```'])
            parts.extend(['', '**Evidence provenance:**', '', '```json',
                          json.dumps(row.get('evidence_provenance') or {}, ensure_ascii=False, indent=2), '```', '',
                          '**Validation status:** ' + str(row.get('validation_status') or 'not recorded'), '',
                          '**Recovery status:** ' + str(row.get('recovery_status') or 'not recorded'), ''])
    if ex:
        parts.extend(['## Part B — Current repaired implementation plans', '',
                      'These are proposals, not proof of ranking causation. Validate current URLs and dependencies before changes.', ''])
    if canonical:
        investigation = canonical.get('investigation') or {}
        tracked = canonical.get('tracked_website') or {}
        competitors = canonical.get('competitors') or []
        parts.extend([
            '## Investigation identity and evidence provenance', '',
            f"**Keyword / search context:** {investigation.get('keyword', 'Not recorded')} / "
            f"{investigation.get('search_engine', 'Not recorded')} / {investigation.get('market', 'Not recorded')}", '',
            '**Tracked exact URL:** ' + str(tracked.get('ranking_url') or 'Not recorded'), '',
            '**Benchmark exact URL:** ' + str((competitors[0] if competitors else {}).get('ranking_url') or 'Not recorded'), '',
            '**Canonical evidence source:** llm_foundation/canonical_evidence.json (identity checked against the selected comparison)', '',
            '**Canonical evidence SHA-256:** ' + str(canonical.get('_source_sha256') or 'Not recorded'), '',
            'Evidence IDs in the findings and plans refer to these verified canonical sections:', '',
        ])
        evidence_paths = {
            'SERP': 'evidence.serp.ranking_summary', 'ON_TITLE': 'evidence.onpage.pages + evidence.onpage.comparison',
            'ON_LINKS': 'evidence.onpage.pages + evidence.onpage.comparison',
            'BL_PAGE': 'evidence.backlinks.page', 'BL_DOMAIN': 'evidence.backlinks.domain',
            'TECH_LAB': 'evidence.technical.mobile_audits', 'TECH_INV': 'evidence.technical.detailed_analysis',
            'KW_SHARED': 'evidence.keywords.intersection', 'KW_QUERY_GAPS': 'evidence.keywords.intersection',
        }
        ids = sorted({eid for p in plans for eid in (p.get('evidence_ids') or [])} |
                     {eid for f in factual for eid in (f.get('evidence_ids') or [])})
        for eid in ids:
            parts.append(f'- **{eid}:** `{evidence_paths.get(eid, "evidence (mapping not declared)")}`')
        parts.append('')
    if run_records:
        parts.extend(['## Validation and recovery records', '',
                      'Saved run records are reproduced as status metadata; raw responses remain in their source files.', ''])
        for record in run_records:
            parts.append(f"- **{record.get('task', 'unknown')}:** status={record.get('status', 'unknown')}; "
                         f"attempts={record.get('attempts', 'unknown')}; recovery={record.get('recovery_status', 'not recorded')}; "
                         f"review_finding_ids={', '.join(record.get('review_finding_ids') or []) or 'none'}")
            if record.get('recovery_audit'):
                parts.extend(['', '**Saved recovery audit:**', '', '```json',
                              json.dumps(record['recovery_audit'], ensure_ascii=False, indent=2), '```'])
            if record.get('diagnostics'):
                parts.extend(['', '**Saved validation diagnostics:**', '', '```json',
                              json.dumps(record['diagnostics'], ensure_ascii=False, indent=2), '```'])
        parts.append('')
    else:
        parts.extend(['## Validation and recovery records', '',
                      'No matching focused-run metadata directory was supplied; validation and recovery details remain unavailable for this selected JSON.', ''])
    for idx, p in enumerate(plans, 1):
        parts.extend([
            f'### Plan {idx}: {_md(p.get("title"))}', '',
            f'**Priority:** {_md(p.get("priority"))} | **Owner:** {_md(p.get("owner"))}', '',
            f'**Plain-language explanation:** {p.get("simple_explanation", "")}', '',
            f'**Technical explanation:** {p.get("technical_explanation", "")}', '',
            f'**Rationale (model proposal):** {p.get("rationale", "")}', '',
            '**Implementation procedure (as validated in the selected JSON):**', '',
        ])
        for n, step in enumerate(p.get('implementation_steps') or [], 1):
            parts.append(f'{n}. {step}')
        parts.extend([
            '', '**Proposed success measure:** ' + str(p.get('success_measure') or 'Not provided'), '',
            '**Uncertainty:** ' + str(p.get('uncertainty') or 'Not provided'), '',
            '**Verified fact IDs:** ' + ', '.join(p.get('evidence_ids') or []), '',
            '**Original specialist finding IDs:** ' + ', '.join(p.get('specialist_finding_ids') or []), '',
            '**Implementation review:** Confirm prerequisites and repeatable baseline, obtain owner approval, '
            'and compare like-for-like results after any change. These checks are editorial guidance, not new observations.', '',
        ])
    parts.extend(['## Part C — Specialist finding dispositions (complete)', ''])
    for d in dispositions:
        parts.extend([
            f'### {d.get("specialist_finding_id", "Unknown")} — {d.get("outcome", "unspecified")}', '',
            '**Linked plan numbers:** ' + (', '.join(str(i + 1) for i in (d.get('plan_indices') or [])) or 'none'), '',
            '**Plain-language explanation:** ' + str(d.get('simple_explanation') or ''), '',
            '**Technical explanation:** ' + str(d.get('technical_explanation') or ''), '',
            '**Next step:** ' + str(d.get('next_step') or ''), '',
            '**Reason:** ' + str(d.get('reason') or ''), '',
            '**Evidence IDs:** ' + ', '.join(d.get('evidence_ids') or []), '',
        ])
    parts.extend([
        '## Part D — Original specialist findings (unabridged, not independently verified)', '',
        'The original specialist statements are retained verbatim for traceability. They may include hypotheses '
        'that were qualified or corrected in the repaired recommendations.', '',
    ])
    for r in originals:
        f = r.get('finding') or {}
        parts.extend([
            f'### {r.get("id", "Unknown")} — {r.get("task", "")}', '',
            '**Original source:** ' + str(r.get('source') or ''), '',
            '**Source SHA-256:** ' + str(r.get('source_sha256') or ''), '',
            '**Status:** ' + str(r.get('status') or ''), '',
        ])
        for field in ('observation', 'interpretation', 'counterevidence', 'recommended_action'):
            parts.extend([f'**{field.replace("_", " ").title()}:** {f.get(field, "")}', ''])
        parts.extend(['**Original evidence paths:** ' + ', '.join(f.get('evidence_paths') or []), ''])
    parts.extend(['## Part E — Verified factual findings', ''])
    for idx, f in enumerate(factual, 1):
        parts.extend([f'### Fact {idx}: {_md(f.get("statement"))}', ''])
        for key, title in [('interpretation', 'Interpretation'), ('why_it_matters', 'Why it matters'),
                           ('next_check', 'Next check'), ('limitation', 'Limitation')]:
            parts.extend([f'**{title}:** {f.get(key, "")}', ''])
        parts.extend(['**Evidence IDs:** ' + ', '.join(f.get('evidence_ids') or []), ''])
    parts.extend([
        '## Part F — Recommendation quality audit', '',
        f'**Status:** {quality["status"] if quality else "not run"}; '
        f'**Blocking flags:** {quality["blocking_count"] if quality else "unknown"}; '
        f'**Review flags:** {quality["review_count"] if quality else "unknown"}.', '',
        'These are heuristic checks, not proof of technical correctness or SEO ranking causation.', '',
    ])
    for issue in (quality or {}).get('issues', []):
        parts.append(f'- **{issue["severity"]}: {issue["code"]} ({issue["path"]})** — '
                     f'{issue["message"]} Next check: {issue["next_check"]}')
    return '\n'.join(parts).rstrip() + '\n'


def build_management_pdf(out_pdf, data, ex, quality, keyword, canonical=None, investigation_datetime=None,
                         investigation_metadata=None):
    """Concise management-facing PDF; full technical details remain in appendix."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, KeepTogether,
                                    Table, TableStyle, HRFlowable, PageBreak)

    styles = getSampleStyleSheet()
    purple = colors.HexColor('#4c1d95')
    ink = colors.HexColor('#202035')
    muted = colors.HexColor('#55556b')
    styles.add(ParagraphStyle(name='ReportTitleCustom', fontName='Helvetica-Bold', fontSize=18,
                              leading=23, textColor=ink, spaceAfter=10))
    styles.add(ParagraphStyle(name='ReportSectionCustom', fontName='Helvetica-Bold', fontSize=12.5,
                              leading=17, textColor=purple, spaceBefore=15, spaceAfter=7))
    styles.add(ParagraphStyle(name='ReportBodyCustom', fontName='Helvetica', fontSize=9.5,
                              leading=14, textColor=ink, spaceAfter=5))
    styles.add(ParagraphStyle(name='ReportSmallCustom', parent=styles['ReportBodyCustom'], fontSize=8.5,
                              leading=12, textColor=muted))
    styles.add(ParagraphStyle(name='ReportCardTitleCustom', fontName='Helvetica-Bold', fontSize=10.2,
                              leading=14, textColor=purple, spaceBefore=8, spaceAfter=5))
    styles.add(ParagraphStyle(name='ReportTableHeadCustom', parent=styles['ReportSmallCustom'],
                              textColor=colors.white, fontName='Helvetica-Bold'))
    styles.add(ParagraphStyle(name='ReportTableCellCustom', parent=styles['ReportSmallCustom'], textColor=ink))
    story = []

    def para(value, style='ReportBodyCustom'):
        return Paragraph(escape(str(value or '')), styles[style])

    def label(name, value, style='ReportBodyCustom'):
        return Paragraph(f'<b>{escape(name)}</b> {escape(str(value or "Not specified"))}', styles[style])

    def management_text(value):
        """Keep exact URLs in the appendix/header while shortening card copy."""
        text = str(value or '')
        def replace_url(match):
            url = match.group(0).rstrip('.,;:)')
            if url.rstrip('/') == str(exact_ours).rstrip('/'):
                return 'the tracked page'
            if url.rstrip('/') == str(exact_benchmark).rstrip('/'):
                return 'the benchmark page'
            parsed = urlsplit(url)
            path = parsed.path.rstrip('/')
            leaf = path.split('/')[-1]
            if leaf and not re.search(r'\.(?:js|css|jpe?g|png|webp|svg|woff2?|json)(?:$|\?)', leaf, re.I):
                name = re.sub(r'[-_]+', ' ', re.sub(r'\.[^.]+$', '', leaf)).strip()
                if len(name) > 70:
                    name = name[:67].rsplit(' ', 1)[0] + '...'
                return f'the “{name}” page' if name else 'the identified page'
            return 'the affected resource'
        text = re.sub(r'https?://[^\s<>]+', replace_url, text)
        text = re.sub(r'\s*\([^)]*(?:wasted|totalbytes|wastedbytes)[^)]*\)', '', text, flags=re.I)
        return re.sub(r'\s{2,}', ' ', text)

    def section(text):
        story.append(Paragraph(escape(text), styles['ReportSectionCustom']))

    rank = (data.get('ranking_summary') or {}).get('google') or {}
    ours = data.get('our_domain') or 'Tracked domain'
    competitor = data.get('benchmark_competitor_domain') or 'Benchmark domain'
    ranking = ((data.get('ranking_summary') or {}).get('google') or {})
    identity = (canonical or {}).get('investigation') or {}
    metadata = investigation_metadata if isinstance(investigation_metadata, dict) else {}
    tracked_metadata = metadata.get('tracked_page') or {}
    competitor_metadata = metadata.get('competitor_page') or {}
    exact_ours = (tracked_metadata.get('url') or
                  ((canonical or {}).get('tracked_website') or {}).get('ranking_url') or ranking.get('our_url') or 'Not recorded')
    competitors = (canonical or {}).get('competitors') or []
    exact_benchmark = (competitor_metadata.get('url') or
                       ((competitors[0] if competitors else {}).get('ranking_url')) or ranking.get('benchmark_url') or 'Not recorded')
    if metadata:
        market = metadata.get('market') or 'Not available'
        engine = metadata.get('search_engine') or 'Not available'
    else:
        market = identity.get('market') or data.get('labs_location') or 'Not recorded'
        engine = identity.get('search_engine') or ((rank.get('engine') if isinstance(rank, dict) else None)) or 'Google'
    if metadata:
        investigation_datetime = metadata.get('search_timestamp') or investigation_datetime or 'Not available in saved evidence'
    else:
        investigation_datetime = investigation_datetime or 'Not recorded in saved evidence'
    saved_recommendations = data.get('recommendations') or []
    adapted_saved, classification_audit = adapt_recommendations(saved_recommendations)
    if saved_recommendations:
        plans = adapted_saved
    else:
        plans, legacy_audit = adapt_recommendations(ex.get('implementation_plans') or [])
        classification_audit = legacy_audit
    tier_order = TIER_ORDER
    priority_order = {'high': 0, 'medium': 1, 'investigate': 2, 'low': 3}
    plans = sorted(enumerate(plans), key=lambda pair: (
        tier_order.get(pair[1].get('evidence_tier'), 4),
        -float(pair[1].get('priority_score')) if isinstance(pair[1].get('priority_score'), (int, float)) else 0,
        priority_order.get(pair[1].get('priority'), 4), pair[0]))
    plans = [plan for _, plan in plans]
    tier_labels = TIER_LABELS
    factual = ex.get('verified_factual_findings') or ex.get('key_findings') or []
    story.append(Paragraph(f'SEO Competitive Intelligence — {escape(keyword)}', styles['ReportTitleCustom']))
    story.append(para(f'Management decision brief | {ours} versus {competitor}', 'ReportSmallCustom'))
    if str(metadata.get('source') or '').startswith('synthetic_'):
        story.append(para('SYNTHETIC REPORTING FIXTURE - no live or collected evidence.', 'ReportSmallCustom'))
    if metadata.get('investigation_id'):
        story.append(label('Investigation ID:', metadata['investigation_id'], 'ReportSmallCustom'))
    story.append(label('Exact pages compared:', f'Tracked: {exact_ours} | Benchmark: {exact_benchmark}', 'ReportSmallCustom'))
    context = metadata.get('search_context') or {}
    context_text = ' | '.join(str(value) for value in (
        context.get('location_note'), context.get('search_url'),
        f"depth {context.get('depth_collected')}" if context.get('depth_collected') is not None else None,
    ) if value)
    location_coordinate = (metadata.get('location_coordinate') if metadata else
                           data.get('location_coordinate'))
    story.append(label('Search date / context:', f'{investigation_datetime} | {engine} | {market}'
                       + (f' | {context_text}' if context_text else '')
                       + (f' | location coordinate {location_coordinate}' if location_coordinate else ''), 'ReportSmallCustom'))
    if metadata.get('serp_snapshot_reference'):
        story.append(label('SERP snapshot:', metadata['serp_snapshot_reference'], 'ReportSmallCustom'))
    story.append(HRFlowable(width='100%', thickness=1.2, color=purple, spaceAfter=12))
    rankings_available = (metadata.get('rankings_available') if metadata else
                          type(rank.get('our_position')) is int and type(rank.get('benchmark_position')) is int)
    if rankings_available:
        our_position = tracked_metadata.get('rank') if metadata else rank.get('our_position')
        benchmark_position = competitor_metadata.get('rank') if metadata else rank.get('benchmark_position')
        story.append(label('Observed result:', f"In the saved Google organic result, {ours} ranked "
                           f"#{our_position} and {competitor} ranked "
                           f"#{benchmark_position}."))
        story.append(para('This is one historical search snapshot. The differences below are investigation '
                          'priorities, not demonstrated causes of Google ranking positions.'))
    else:
        story.append(label('Observed result:', 'Exact-page SERP rankings are not available for this investigation.'))
        story.append(para('The comparison uses saved evidence for the selected pages. SERP positions are unavailable, '
                          'and the observed differences do not establish ranking causes.'))
    if quality and (quality['blocking_count'] or quality['review_count']):
        story.append(label('Quality status:', f"{quality['blocking_count']} blocking and "
                           f"{quality['review_count']} review flags. Specialist review is required."))
    if factual:
        section('What the saved evidence establishes')
        for fact in factual[:4]:
            story.append(label('Observed:', fact.get('statement'), 'ReportSmallCustom'))
            story.append(label('Important limitation:', fact.get('limitation'), 'ReportSmallCustom'))
    section('Decisions requested from management')
    story.append(para('Assign the proposed owners to implement the preferred evidence-backed changes and '
                      'complete the stated verification. Ranking or traffic improvement is not guaranteed.'))
    head = [para(x, 'ReportTableHeadCustom') for x in ('Evidence tier', 'Preferred improvement', 'Priority')] 
    rows = [head]
    for p in plans:
        rows.append([para(tier_labels.get(p.get('evidence_tier'), 'Tier not recorded'), 'ReportTableCellCustom'),
                     para(p.get('title', ''), 'ReportTableCellCustom'),
                     para(str(p.get('priority_score', p.get('priority', 'not assigned'))), 'ReportTableCellCustom')])
    t = Table(rows, colWidths=[46*mm, 78*mm, 49*mm], repeatRows=1, hAlign='LEFT')
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), purple),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f7fb')]),
        ('LINEBELOW', (0, 0), (-1, -1), 0.3, colors.HexColor('#dddddf')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 7), ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))
    story.append(t)
    section('Before implementation')
    story.append(para('The technical appendix contains the full implementation steps, source evidence, original specialist findings, validation and recovery records. Measure changes using the stated checks; ranking outcomes are not guaranteed.'))
    section('Evidence-ranked recommendations')
    for i, p in enumerate(plans, 1):
        impact = (p.get('potential_impact_text') or p.get('expected_benefit') or p.get('benefit') or
                  p.get('interpretation') or p.get('rationale'))
        steps = p.get('actions') or p.get('implementation_steps') or p.get('implementation_details') or []
        action = str(p.get('display_action') or (' '.join(str(step) for step in steps if step) if isinstance(steps, list) else str(steps or '')))
        difference = p.get('evidence') or p.get('difference_observed') or p.get('simple_explanation') or p.get('observation')
        if str(p.get('id', '')).startswith('technical-mobile-'):
            area = (str(p.get('title') or 'technical issue').lower().removeprefix('improve ')
                    .removesuffix(' on the tracked page'))
            difference = (f"The saved mobile Lighthouse run flagged {area} on the tracked page. "
                          "This single lab observation does not establish field performance or ranking causation.")
        difference = management_text(difference)
        action = management_text(action)
        card = [Paragraph(f'{i}. {escape(str(p.get("title") or "Untitled"))}',
                          styles['ReportCardTitleCustom']),
                label('Evidence tier:', tier_labels.get(p.get('evidence_tier'), 'Tier not recorded'), 'ReportSmallCustom'),
                label('Difference Observed:', difference or
                      'The saved validated recommendation does not include a plain-language observation.'),
                label('Potential Impact:', (management_text(impact or 'Potential benefit is uncertain.') +
                      ' This is a potential outcome, not a ranking guarantee.' )),
                label('Recommended Action:', action or 'No implementation steps were recorded.'),
                Spacer(1, 7)]
        story.append(KeepTogether(card))
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor('#dedce7'))
        canvas.line(18*mm, 15*mm, 192*mm, 15*mm)
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(muted)
        canvas.drawString(18*mm, 11*mm, 'SEO Competitive Intelligence | Historical investigation')
        canvas.drawRightString(192*mm, 11*mm, str(doc.page))
        canvas.restoreState()

    SimpleDocTemplate(str(out_pdf), pagesize=A4, leftMargin=18*mm, rightMargin=18*mm,
                      topMargin=17*mm, bottomMargin=21*mm).build(
        story, onFirstPage=footer, onLaterPages=footer)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--keyword', required=True)
    parser.add_argument('--input', type=Path, help='Saved comparison JSON; no collectors run')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--executive-json', type=Path, help='Exact repaired executive JSON; do not use stale results')
    parser.add_argument('--investigation-metadata', type=Path,
                        help='Optional validated metadata for the selected saved investigation')
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    slug = keyword_slug(args.keyword)
    out = args.output_dir or root / 'output/results' / slug
    src = args.input or root / 'output/results' / slug / f'{slug}_comparison.json'
    executive_path = args.executive_json or out / 'llm_outputs/executive_validated.json'
    if args.executive_json and not executive_path.is_file():
        raise FileNotFoundError('Explicit repaired executive JSON not found: ' + str(executive_path))
    if not src.is_file():
        raise FileNotFoundError('Saved comparison JSON not found: ' + str(src))
    if not executive_path.is_file():
        message = ('Explicit repaired executive JSON not found: ' if args.executive_json else
                   'Executive JSON not found; provide --executive-json: ')
        raise FileNotFoundError(message + str(executive_path))
    data = json.loads(src.read_text(encoding='utf-8'))
    ex = json.loads(executive_path.read_text(encoding='utf-8'))
    investigation_metadata = (json.loads(args.investigation_metadata.read_text(encoding='utf-8'))
                              if args.investigation_metadata else None)
    canonical_path = out / 'llm_foundation/canonical_evidence.json'
    if not canonical_path.is_file():
        canonical_path = root / 'output/results' / slug / 'llm_foundation/canonical_evidence.json'
    canonical = json.loads(canonical_path.read_text(encoding='utf-8')) if canonical_path.is_file() else None
    if canonical:
        tracked = canonical.get('tracked_website') or {}
        competitors = canonical.get('competitors') or []
        expected = (data.get('ranking_summary') or {}).get('google') or {}
        canonical_matches = (canonical.get('investigation', {}).get('keyword', '').casefold() == args.keyword.casefold() and
            tracked.get('ranking_url') == expected.get('our_url') and competitors and
            competitors[0].get('ranking_url') == expected.get('benchmark_url'))
        if not canonical_matches:
            canonical = None
        else:
            canonical['_source_sha256'] = hashlib.sha256(canonical_path.read_bytes()).hexdigest()
    serp_path = root / 'data/processed' / slug / 'serp_google.json'
    investigation_datetime = None
    if serp_path.is_file():
        serp = json.loads(serp_path.read_text(encoding='utf-8'))
        if serp.get('keyword', '').casefold() == args.keyword.casefold():
            investigation_datetime = serp.get('datetime')
    task_dir = executive_path.parent / 'focused_tasks'
    run_records = []
    if task_dir.is_dir():
        for task in ('onpage', 'backlinks', 'technical', 'competition'):
            record_path = task_dir / f'{task}_validated.json'
            if record_path.is_file():
                record = json.loads(record_path.read_text(encoding='utf-8'))
                recovery_path = task_dir / f'{task}_evidence_recovery_audit.json'
                diagnostics = sorted(task_dir.glob(f'{task}_attempt_*_diagnostics.json'))
                run_records.append({'task': task, 'status': 'validated', 'attempts': record.get('attempts'),
                                    'recovery_status': record.get('recovery_status'),
                                    'review_finding_ids': record.get('review_finding_ids') or [],
                                    'recovery_audit': (json.loads(recovery_path.read_text(encoding='utf-8'))
                                                       if recovery_path.is_file() else None),
                                    'diagnostics': [json.loads(path.read_text(encoding='utf-8')) for path in diagnostics]})
    plans = ex.get('implementation_plans') or []
    dispositions = ex.get('finding_dispositions') or []
    factual = ex.get('verified_factual_findings') or ex.get('key_findings') or []
    if not plans or not dispositions or not factual:
        raise ValueError('Executive JSON must include plans, dispositions and verified factual findings')
    focused = ex.get('recommendation_engine') == 'four_specialist_focused_v4'
    quality_input = dict(ex, _enforce_user_loss_check=True)
    quality = audit_recommendations(quality_input, expected_findings=[r['id'] for r in ex.get('specialist_findings', [])],
        require_actionable=focused, enforce_causation=focused, enforce_unmeasured_loss=focused)
    if quality['blocking_count']:
        raise ValueError('Blocking quality flags remain; refusing to publish')
    errors = report_consistency_errors(ex)
    if errors:
        raise ValueError('Specialist lineage inconsistent: ' + '; '.join(errors[:5]))
    # Write only after all preflight checks pass; never modify the source files.
    out.mkdir(parents=True, exist_ok=True)
    appendix = out / f'{args.keyword}_technical_appendix.md'
    pdf = out / f'{args.keyword}_executive_report.pdf'
    appendix.write_text(build_appendix(data, ex, quality, src.name, canonical, run_records or None,
                                       investigation_metadata), encoding='utf-8')
    build_management_pdf(pdf, data, ex, quality, args.keyword, canonical, investigation_datetime,
                         investigation_metadata)
    (out / 'report_quality_audit.json').write_text(json.dumps(quality, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    manifest = {
        'source_executive_json': str(executive_path.resolve()),
        'source_executive_sha256': hashlib.sha256(executive_path.read_bytes()).hexdigest(),
        'source_comparison_json': str(src.resolve()),
        'source_comparison_sha256': hashlib.sha256(src.read_bytes()).hexdigest(),
        'implementation_plan_count': len(plans),
        'finding_disposition_count': len(dispositions),
        'original_specialist_finding_count': len(ex.get('specialist_findings') or []),
        'verified_factual_finding_count': len(factual),
        'blocking_quality_flags': quality['blocking_count'],
        'review_quality_flags': quality['review_count'],
        'report_type': 'concise_management_brief_plus_full_technical_appendix',
        'authoritative_recommendation_ids': [row.get('id') for row in plans if row.get('id')],
        'investigation_id': (investigation_metadata or {}).get('investigation_id'),
        'ignored_stale_summary_fields': ['proposed_decisions', 'recommended_improvements'],
        'outputs': [str(pdf), str(appendix)],
    }
    (out / 'report_generation_manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(pdf)
    print(appendix)
    print(out / 'report_generation_manifest.json')
    return manifest


if __name__ == '__main__':
    main()
