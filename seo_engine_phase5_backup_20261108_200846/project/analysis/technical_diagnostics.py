"""Offline, evidence-gated Lighthouse technical comparisons and investigation prompts."""
from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

AUDIT_GROUPS = {
    'javascript_execution': ('bootup-time', 'mainthread-work-breakdown', 'long-tasks'),
    'unused_javascript': ('unused-javascript',),
    'render_blocking': ('render-blocking-insight', 'render-blocking-resources'),
    'image_delivery': ('image-delivery-insight', 'modern-image-formats', 'uses-optimized-images'),
    'lcp_breakdown': ('lcp-breakdown-insight', 'lcp-discovery-insight', 'largest-contentful-paint-element'),
    'network_resources': ('total-byte-weight', 'network-requests', 'network-dependency-tree-insight'),
    'layout_stability': ('layout-shifts', 'cls-culprits-insight'),
    'third_parties': ('third-parties-insight', 'third-party-summary'),
}

# Allow only stable scalar evidence keys; never embed raw HTML, selector snippets, traces or screenshots.
ITEM_FIELDS = ('url', 'entity', 'group', 'totalBytes', 'wastedBytes', 'wastedMs',
               'total', 'scripting', 'scriptParseCompile', 'duration', 'transferSize',
               'resourceSize', 'mainThreadTime', 'startTime')


def sanitize_url(value):
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme not in ('http', 'https') or not parts.hostname:
            return None
        # Strip userinfo, query, fragment and unusual ports; keep host and path for triage.
        host = parts.hostname
        if ':' in host:
            host = f'[{host}]'
        return urlunsplit((parts.scheme, host, parts.path[:350], '', ''))
    except (ValueError, TypeError):
        return None


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _items(audit, limit=5):
    details = audit.get('details') or {}
    rows = details.get('items') or []
    if not isinstance(rows, list):
        return []
    output = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        item = {}
        for key in ITEM_FIELDS:
            value = row.get(key)
            if key == 'url':
                value = sanitize_url(value)
            if key in ('entity', 'group'):
                value = str(value)[:120] if isinstance(value, str) else None
            if key not in ('url', 'entity', 'group') and not number(value):
                continue
            if value is not None:
                item[key] = value
        if item:
            output.append(item)
    return output


def extract_technical_diagnostics(raw_audits):
    if not isinstance(raw_audits, dict):
        raw_audits = {}
    result = {}
    for group, ids in AUDIT_GROUPS.items():
        group_data = {}
        for audit_id in ids:
            audit = raw_audits.get(audit_id)
            if not isinstance(audit, dict):
                group_data[audit_id] = {'status': 'missing'}
                continue
            details = audit.get('details') or {}
            rows = details.get('items') if isinstance(details, dict) else None
            group_data[audit_id] = {
                'status': 'not_applicable' if audit.get('scoreDisplayMode') == 'notApplicable' else 'present',
                'score_display_mode': audit.get('scoreDisplayMode'),
                'numeric_value': audit.get('numericValue') if number(audit.get('numericValue')) else None,
                'numeric_unit': audit.get('numericUnit'),
                'display_value': str(audit.get('displayValue') or '')[:150],
                'item_count': len(rows) if isinstance(rows, list) else None,
                'items': _items(audit),
            }
        result[group] = group_data
    return result


# Priorities are engineering triage categories, not SEO ranking impact predictions.
INVESTIGATION_RULES = {
    'javascript_execution': {
        'priority': 'high', 'title': 'Profile JavaScript boot-up and main-thread execution',
        'actions': ['Profile the identified scripts in Chrome Performance before editing load order.',
                    'Identify initialization that is nonessential for first render; test deferral without disrupting security, fraud checks or core interactions.',
                    'Repeat comparable mobile Lighthouse audits and inspect boot-up time, TBT and application functionality.']},
    'unused_javascript': {
        'priority': 'high', 'title': 'Review JavaScript delivery and initial bundle utilization',
        'actions': ['Review code splitting and defer only features not needed for initial rendering.',
                    'Check script coverage during real user flows before removing code or third-party tags.',
                    'Repeat mobile audits and verify bundle sizes, feature behavior and conversion paths.']},
    'render_blocking': {
        'priority': 'low', 'title': 'Review render-blocking resource dependencies',
        'actions': ['Trace critical CSS and JS dependencies identified by Lighthouse.',
                    'Test safe changes to loading order; preserve configuration and required tracking functionality.',
                    'Repeat mobile audits and check FCP, LCP and regressions.']},
    'image_delivery': {
        'priority': 'medium', 'title': 'Review image sizing and delivery',
        'actions': ['Inspect flagged image assets for excessive dimensions and compression opportunities.',
                    'Test responsive image delivery and appropriate formats without harming visual quality.',
                    'Repeat mobile audits and check image transfer sizes and LCP separately.']},
    'lcp_breakdown': {
        'priority': 'medium', 'title': 'Investigate LCP phase breakdown',
        'actions': ['Inspect the original Lighthouse LCP phase breakdown and LCP element.',
                    'Do not infer an LCP root cause until the relevant element and timings are verified.',
                    'Repeat comparable mobile audits after changes.']},
}


def _resource_examples(audit: dict, *, limit: int = 4) -> list[dict]:
    """Select measured resources, preserving units and avoiding raw audit payloads."""
    rows = [x for x in audit.get('items', []) if isinstance(x, dict)]
    measure = next((k for k in ('total', 'wastedBytes', 'wastedMs', 'totalBytes')
                    if any(number(x.get(k)) for x in rows)), None)
    if measure:
        rows.sort(key=lambda x: x.get(measure) if number(x.get(measure)) else -1, reverse=True)
    return [{k: v for k, v in row.items() if k in ITEM_FIELDS} for row in rows[:limit]]


def _severity(area: str, audit: dict) -> str:
    """Conservative fixed triage for observed issues; never predict ranking lift."""
    base = INVESTIGATION_RULES[area]['priority']
    if area == 'javascript_execution' and number(audit.get('numeric_value')):
        return 'high' if audit['numeric_value'] >= 3000 else 'medium'
    if area == 'unused_javascript':
        wasted = sum(x.get('wastedBytes', 0) for x in audit.get('items', [])
                     if isinstance(x, dict) and number(x.get('wastedBytes')))
        return 'high' if wasted >= 300000 else 'medium'
    return base


def compare_technical(ours: dict, benchmark: dict, *, expected_urls: dict | None = None) -> dict:
    """Compare only verified audits of the selected SERP ranking pages."""
    def valid(a):
        return (isinstance(a, dict) and a.get('status') == 'usable'
                and a.get('target_verified') is True and a.get('final_url_verified') is True
                and a.get('scope') == 'page' and a.get('device') == 'mobile'
                and isinstance(a.get('ranking_url'), str) and bool(a['ranking_url'])
                and isinstance(a.get('technical_diagnostics'), dict) and bool(a['technical_diagnostics']))
    if expected_urls is not None:
        def normalized_url(url):
            if not isinstance(url, str):
                return None
            parsed = urlsplit(url)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname:
                return None
            return (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip('/') or '/', parsed.query)
        if not all(expected_urls.get(side) and normalized_url(audit.get('ranking_url')) == normalized_url(expected_urls[side])
                   for side, audit in (('ours', ours), ('benchmark', benchmark))):
            return {'status': 'withheld', 'reason': 'Lighthouse ranking URLs do not match the current Google SERP targets.',
                    'observations': [], 'investigations': []}
    if not valid(ours) or not valid(benchmark):
        return {'status': 'withheld', 'reason': 'Both exact SERP page mobile audits must be verified and usable.',
                'observations': [], 'investigations': []}
    od, bd = ours.get('technical_diagnostics') or {}, benchmark.get('technical_diagnostics') or {}
    observations, investigations = [], []
    for group, audit_ids in AUDIT_GROUPS.items():
        for aid in audit_ids:
            a, b = (od.get(group) or {}).get(aid) or {}, (bd.get(group) or {}).get(aid) or {}
            if a.get('status') != 'present' or b.get('status') != 'present':
                continue
            av, bv = a.get('numeric_value'), b.get('numeric_value')
            if number(av) and number(bv):
                observations.append({'group': group, 'audit_id': aid, 'ours': av,
                                     'benchmark': bv, 'unit': a.get('numeric_unit'),
                                     'note': 'Single-run Lighthouse lab observations, not a causal SEO ranking signal.'})
    targets = (
        ('javascript_execution', 'bootup-time', 'Investigate JS execution cost and top script resources.'),
        ('unused_javascript', 'unused-javascript', 'Review unused JS estimates; verify code splitting and script loading.'),
        ('render_blocking', 'render-blocking-insight', 'Inspect identified render-blocking CSS/JS before changing load order.'),
        ('image_delivery', 'image-delivery-insight', 'Inspect image sizing, formats and loading behavior.'),
        ('lcp_breakdown', 'lcp-breakdown-insight', 'Inspect raw LCP phase breakdown; root cause may be unavailable in summary.'),
    )
    for group, aid, guidance in targets:
        a = (od.get(group) or {}).get(aid) or {}
        if a.get('status') != 'present':
            continue
        if not a.get('items') and not number(a.get('numeric_value')) and not a.get('display_value'):
            continue
        rule = INVESTIGATION_RULES[group]
        resources = _resource_examples(a)
        priority = _severity(group, a)
        summary = {
            'javascript_execution': 'Lighthouse reports JavaScript boot-up work on the selected page.',
            'unused_javascript': 'Lighthouse flags potentially unused JavaScript in the measured load.',
            'render_blocking': 'Lighthouse identifies render-blocking resources in the measured load.',
            'image_delivery': 'Lighthouse identifies image-delivery opportunities in the measured load.',
            'lcp_breakdown': 'Lighthouse includes LCP diagnostic evidence for further investigation.',
        }[group]
        investigations.append({'area': group, 'audit_id': aid, 'evidence': a,
                               'recommendation': guidance,
                               'title': rule['title'], 'priority': priority,
                               'priority_basis': 'Conservative engineering triage based on audit category and measured severity; not a ranking forecast.',
                               'supporting_observation': summary,
                               'measurement': {'value': a.get('numeric_value'), 'unit': a.get('numeric_unit'),
                                               'display': a.get('display_value')},
                               'affected_resources': resources,
                               'actions': list(rule['actions']),
                               'validation': rule['actions'][-1],
                               'confidence': 'investigation_only',
                               'note': 'Single-run Lighthouse lab evidence. Estimated savings are not guaranteed and do not establish ranking causation.'})
    investigations.sort(key=lambda x: ({'high': 0, 'medium': 1, 'low': 2}.get(x['priority'], 3), x['area']))
    return {'status': 'usable', 'scope': 'exact_serp_pages_mobile_lab',
            'observations': observations, 'investigations': investigations}
