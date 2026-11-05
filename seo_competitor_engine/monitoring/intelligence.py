"""Offline, evidence-bound promotion labels and readable change explanations."""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from urllib.parse import urlsplit

RULE_VERSION = '2026-10-19.1'
CATEGORIES = {
    'welcome': 'Welcome offers', 'rewards': 'Free bets & rewards',
    'cashback': 'Cashback', 'deposit': 'Deposit matches & bonuses',
    'prizes': 'Prize draws & jackpots', 'games': 'Game-specific offers',
    'partners': 'Partner & voucher deals', 'boosts': 'Boosts & multipliers',
    'unclassified': 'Unclassified / needs review',
}
PATTERNS = {
    'welcome': r'\b(welcome|new customers?|first deposit|sign.up bonus)\b',
    'rewards': r'\b(free bets?|free spins?|bonus spins?|rewards?|missions?|free flights?)\b',
    'cashback': r'\bcash\s?back\b',
    'deposit': r'\b(deposit match|match offer|deposit bonus|bonus deposit)\b',
    'prizes': r'\b(prizes?|jackpots?|prize pools?|leaderboards?|competitions?|stand to win|share of|cash prizes|best dressed fan)\b|\bwin\b.*\bR\s?\d',
    'games': r'\b(slots?|crash games?|aviator|aviatrix|roulette|blackjack|crazy time)\b',
    'partners': r'\b(vouchers?|partnered|partnership|dis.chem)\b',
    'boosts': r'\b(boosts?|boosted|multipliers?)\b',
}


def classify(item):
    # Asset filenames are not evidence of an offer's mechanics.
    text = item.get('extracted_text') or ''
    matches = {key: match.group(0) for key, pattern in PATTERNS.items()
               if (match := re.search(pattern, text, re.I))}
    return {'categories': list(matches) or ['unclassified'], 'category_evidence': matches,
            'category_rule_version': RULE_VERSION}


def _norm(value):
    return ' '.join(re.findall(r'\w+', str(value).lower()))


def verify(item):
    """Corroborate only independently retained card, offer, and terms evidence."""
    from .promotions import extract_offer_details
    investigation = item.get('investigation') or {}
    terms = investigation.get('terms_page') or {}
    base = {'status': 'needs_review', 'matched_fields': [], 'rule_version': RULE_VERSION,
            'reason': investigation.get('reason') or 'No linked public offer evidence is available.'}
    if investigation.get('status') != 'captured':
        return base
    base.update(status='details_available', reason='Public offer details captured; corroboration is incomplete.')
    if investigation.get('refresh_pending'):
        base['reason']='Saved public details are available; their refresh is waiting for a later capture.'
        return base
    # Older merged details cannot be used as independent proof.
    offer = investigation.get('offer_details')
    if not offer or terms.get('status') != 'captured':
        return base
    card = extract_offer_details(item.get('extracted_text') or '')
    sources = [item.get('page_url') or card.get('source_url') or item.get('source_url'),
               investigation.get('source_url'), terms.get('source_url')]
    if any(not u or urlsplit(u).scheme not in ('http', 'https') for u in sources):
        return base
    if len(set(sources)) != 3 or len({urlsplit(u).hostname for u in sources}) != 1:
        return base
    fields = ('amounts', 'percentages', 'promo_codes', 'dates', 'time_windows')
    matched, differences = [], []
    for field in fields:
        values = [{_norm(v) for v in d.get(field, [])} for d in (card, offer, terms.get('details') or {})]
        populated = [v for v in values if v]
        if len(populated) > 1 and any(v != populated[0] for v in populated[1:]):
            differences.append(field)
        if all(values) and values[0] == values[1] == values[2]:
            matched.append(field)
    # Require the offer promise itself on both detail pages, not merely a
    # coincidental currency value shared by unrelated offers.
    promise = re.split(r'[.!?]', item.get('extracted_text') or '')[0]
    promise = _norm(promise)
    linked_texts = [_norm(investigation.get('text_excerpt') or ''), _norm(terms.get('text_excerpt') or '')]
    same_promise = len(promise.split()) >= 5 and all(promise in t for t in linked_texts)
    base.update(matched_fields=matched, sources=sources, fields_needing_review=differences)
    if differences:
        base['reason'] = 'Amounts, rates, codes, or dates differ across sources; check their context and conditions.'
    elif matched and same_promise:
        base.update(status='automatically_corroborated',
                    reason='The offer wording and listed key fields agree on the card, public offer page, and public terms page. Other conditions may remain unextracted.')
    return base


def enrich(item):
    from .promotions import extract_offer_details
    result={**item, **classify(item), 'verification': verify(item), 'category_source':'automatic'}
    result['details']={**(item.get('details') or {})}
    if 'time_windows' not in result['details']:
        result['details']['time_windows']=extract_offer_details(item.get('extracted_text') or '')['time_windows']
    try: override=json.loads(item.get('category_override_json') or 'null')
    except (ValueError,TypeError): override=None
    if isinstance(override,list) and override and all(k in CATEGORIES for k in override):
        result.update(categories=override,category_source='team')
    return result


def _parse(value):
    try: return json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError): return value


def wording_summary(before, after):
    a, b = str(before or '').split(), str(after or '').split()
    if a == b: return 'The recorded details changed; inspect the source evidence for context.'
    if max(len(a),len(b))>150 and re.search(r'\*{3,}\d+',str(before)+str(after)):
        return 'Visible page text changed, including live-looking values and masked account labels. Automatically updating widgets can contribute to these differences. Identified promotion changes are listed separately; the full comparison is available in the evidence.'
    if max(len(a), len(b)) > 5000:
        return 'The page text changed across a large section. Open the saved comparison to inspect its full context.'
    excerpts = []
    for tag, i, j, x, y in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == 'equal': continue
        old, new = ' '.join(a[i:j])[:220], ' '.join(b[x:y])[:220]
        if tag == 'replace': excerpts.append(f'Wording changed from “{old}” to “{new}”.')
        elif tag == 'insert': excerpts.append(f'Text added: “{new}”.')
        else: excerpts.append(f'Text no longer detected: “{old}”.')
        if len(excerpts) == 3: break
    return ' '.join(excerpts)


def summarize_change(change):
    field = change['element_type']
    before, after = _parse(change.get('previous_value')), _parse(change.get('current_value'))
    labels = {'title': 'Page title', 'meta_description': 'Search description', 'canonical': 'Preferred page address',
              'headings': 'Page headings', 'internal_links': 'Links within the website', 'external_links': 'Links to other websites',
              'structured_data_blocks': 'Search-engine metadata', 'seo_content_text': 'Main page wording',
              'rendered_page_text': 'Visible page wording', 'main_word_count': 'Main content length',
              'image_inventory': 'Page images', 'background_image_inventory': 'Background images'}
    title = labels.get(field, field.replace('_', ' ')) + ' changed'
    if field in ('rendered_page_text', 'seo_content_text'):
        summary = wording_summary(before, after)
    elif field in ('title', 'meta_description', 'canonical'):
        summary = f'{labels[field]} changed from “{str(before or "not captured")[:250]}” to “{str(after or "not captured")[:250]}”.'
    elif field == 'image_inventory' and isinstance(after, dict):
        summary = f"Images observed: {after.get('added_count', 0)} added, {after.get('removed_count', 0)} no longer detected, and {after.get('modified_count', 0)} with changed properties. This alone does not establish an offer change."
    elif field == 'main_word_count':
        summary = f'The captured main content changed from {before} to {after} words.'
    elif isinstance(before, list) and isinstance(after, list):
        old, new = {json.dumps(x, sort_keys=True) for x in before}, {json.dumps(x, sort_keys=True) for x in after}
        summary = f'{labels.get(field, title)}: {len(new-old)} entries added and {len(old-new)} no longer detected.'
    elif field == 'headings':
        summary = wording_summary(json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False))
    else:
        summary = f'{labels.get(field, title)} were updated between the two saved captures.'
    return {**change, 'title': title, 'summary': summary, 'summary_rule_version': RULE_VERSION}
