"""Read-only activity feed over saved page and promotion evidence."""
from __future__ import annotations
from datetime import datetime, timezone
from . import store
import json
from .intelligence import classify, enrich, summarize_change, wording_summary


def _stamp(value):
    try: return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc).timestamp()
    except (ValueError, TypeError, AttributeError): return 0


def activity_feed(filters=None):
    filters = filters or {}
    pages = store.pages()
    events = []
    for page in pages:
        if filters.get('domain') and filters['domain'] != page['domain']: continue
        if filters.get('page_id') and filters['page_id'] != page['id']: continue
        snapshots = {s['id']: s for s in store.snapshots(page['id'])}
        def add(event):
            events.append({**event, 'domain': page['domain'], 'page_id': page['id'], 'page_url': page['url']})
        changes = [c for c in store.changes(page['id']) if c['previous_snapshot_id'] in snapshots and c['current_snapshot_id'] in snapshots]
        # The full visible text already includes main text; avoid a duplicate headline.
        full_text_pairs = {(c['previous_snapshot_id'], c['current_snapshot_id']) for c in changes if c['element_type'] == 'rendered_page_text'}
        for change in changes:
            if change['element_type'] == 'seo_content_text' and (change['previous_snapshot_id'], change['current_snapshot_id']) in full_text_pairs: continue
            item = summarize_change(change)
            add({'id': change['id'], 'kind': 'page_change', 'title': item['title'], 'summary': item['summary'],
                 'occurred_at': change['first_detected_at'], 'previous_snapshot_id': change['previous_snapshot_id'],
                 'snapshot_id': change['current_snapshot_id'], 'categories': [],
                 'previous_value': change['previous_value'], 'current_value': change['current_value']})
        saved = {}
        for promotion in store.promotions_for_page(page['id']):
            classification=enrich(promotion)
            override=classification['categories'] if classification['category_source']=='team' else None
            first = promotion.get('first_snapshot_id')
            original_text = ''
            original = {}
            if first in snapshots:
                if first not in saved:
                    try: saved[first] = store.payload(snapshots[first])
                    except (OSError, ValueError): saved[first] = {}
                candidates = saved[first].get('promotion_analysis', {}).get('candidates', [])
                original = next((c for c in candidates if c.get('fingerprint') == promotion['fingerprint']), {})
                original_text = original.get('extracted_text') or ''
            add({'id': promotion['id'] + ':first', 'kind': 'promotion_new', 'title': 'Promotion candidate first observed',
                 'summary': ('The page advertised: “' + original_text[:400] + '”.') if original_text else 'A banner candidate was recorded: ' + (original.get('title') or 'unnamed banner') + '. Readable offer wording was unavailable in that capture.',
                 'occurred_at': promotion['first_seen_at'], 'snapshot_id': first,
                 'categories': override or classify({'extracted_text': original_text})['categories'], 'promotion_id': promotion['id']})
            prior_text=original.get('extracted_text')
            prior_details=original.get('details')
            prior_snapshot=first
            for index, recorded in enumerate(promotion['history']):
                event=dict(recorded)
                if 'previous_text' not in event and prior_text is not None:
                    event.update(previous_text=prior_text,previous_details=prior_details,previous_snapshot_id=prior_snapshot)
                kind = event.get('event', 'version_changed')
                title = {'version_changed': 'Promotion wording or details changed', 'creative_changed':'Promotion artwork changed', 'not_detected': 'Promotion no longer detected', 'seen_again': 'Promotion observed again'}.get(kind, 'Promotion observation updated')
                if kind == 'version_changed':
                    summary = wording_summary(event.get('previous_text'), event.get('text')) if 'previous_text' in event else 'A new version was saved. The previous wording was not retained in this older history record.'
                    if 'previous_text' in event and not event['previous_text'] and event.get('text'):
                        title='Promotion wording became available'
                        summary='This previously unreadable candidate now has captured wording: “'+event['text'][:400]+'”. This may reflect improved extraction rather than a website change.'
                    if event.get('previous_text') == event.get('text'):
                        changed = [k.replace('_', ' ') for k in ('amounts', 'percentages', 'dates', 'time_windows', 'promo_codes', 'eligibility_or_terms') if (event.get('previous_details') or {}).get(k) != (event.get('details') or {}).get(k)]
                        summary = 'Extracted offer details changed' + (': ' + ', '.join(changed) if changed else '') + '. Open the evidence to check the conditions and source coverage.'
                        if not changed and not event.get('creative_changed'):
                            prior_text=event.get('text'); prior_details=event.get('details'); prior_snapshot=event.get('snapshot_id')
                            continue
                elif kind == 'creative_changed': summary = 'The captured promotion image changed while extracted wording and details stayed the same. Review the artwork; animation or crop movement can also cause a visual change.'
                else: summary = event.get('note') or title
                add({'id': f"{promotion['id']}:{index}", 'kind': 'promotion_change', 'title': title, 'summary': summary,
                     'occurred_at': event['observed_at'], 'snapshot_id': event.get('snapshot_id'),
                     'previous_snapshot_id': event.get('previous_snapshot_id'), 'promotion_id': promotion['id'],
                     'categories': override or classify({'extracted_text': event.get('text') or promotion['extracted_text']})['categories'],
                     'previous_value': event.get('previous_text'), 'current_value': event.get('text')})
                if 'text' in event:
                    prior_text=event['text']; prior_details=event.get('details'); prior_snapshot=event.get('snapshot_id')
        for capture in store.captures(page['id']):
            try: quality=json.loads(capture.get('diagnostics') or '{}').get('tracking_quality') or {}
            except (ValueError,AttributeError): quality={}
            if capture['status'] == 'failed':
                add({'id': capture['id'], 'kind': 'capture_failure', 'title': 'Page check failed',
                     'summary': 'The page could not be checked. Existing promotion status was preserved. ' + (capture.get('error') or ''),
                     'occurred_at': capture['finished_at'] or capture['started_at'], 'categories': []})
            elif quality.get('eligible') is False:
                add({'id':capture['id'],'kind':'capture_failure','title':'Page check was not suitable for tracking',
                     'summary':' '.join(quality.get('reasons') or [])+' Existing promotion status was preserved.',
                     'occurred_at':capture['finished_at'] or capture['started_at'],'categories':[]})
    if filters.get('kind'): events = [e for e in events if e['kind'] == filters['kind']]
    if filters.get('category'): events = [e for e in events if filters['category'] in e['categories']]
    if filters.get('since'): events = [e for e in events if _stamp(e['occurred_at']) >= _stamp(filters['since'] + 'T00:00:00+02:00')]
    if filters.get('until'): events = [e for e in events if _stamp(e['occurred_at']) <= _stamp(filters['until'] + 'T23:59:59.999999+02:00')]
    if filters.get('q'):
        query = filters['q'].lower()
        events = [e for e in events if query in (e['title'] + ' ' + e['summary'] + ' ' + e['domain']).lower()]
    events.sort(key=lambda e: (_stamp(e['occurred_at']), e['id']), reverse=True)
    offset = max(0, int(filters.get('offset') or 0))
    limit = min(100, max(1, int(filters.get('limit') or 40)))
    return {'events': events[offset:offset+limit], 'total': len(events), 'offset': offset,
            'has_more': offset+limit < len(events), 'pages': pages, 'scope': 'Registered public pages only'}
