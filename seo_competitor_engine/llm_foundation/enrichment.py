"""Bounded, provenance-bearing evidence enrichment for focused SEO specialists.

The layer consumes saved comparison data only. It never collects pages or
promotes specialist interpretations into evidence. Text is deliberately capped.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit


MAX_ITEMS_PER_TASK = 24
MAX_TEXT_CHARS = 520
MAX_PAGE_LINKS = 80
MAX_KEYWORD_ROWS = 10


def _sha(value) -> str:
    raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _host(url):
    try:
        return (urlsplit(url).hostname or '').lower().removeprefix('www.')
    except (TypeError, ValueError):
        return ''


def _item(keyword, side, url, kind, value, scope, source, collected_at=None, limitations=None):
    identity = {'keyword': keyword, 'side': side, 'url': url, 'kind': kind,
                'source': source, 'value_sha256': _sha(value)}
    return {
        'evidence_id': 'ENR_' + _sha(identity)[:16].upper(),
        'source': source,
        'collected_at': collected_at,
        'keyword': keyword,
        'page': {'side': side, 'url': url, 'domain': _host(url)},
        'metric_or_observation': kind,
        'scope': scope,
        'value': value,
        'limitations': limitations or [],
        'provenance': {'source_sha256': _sha(value), 'source_path': source},
    }


def _sentences(text):
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+|\n+', text or '') if len(s.strip()) >= 35]


def _content_observations(keyword, pages, source_name, collected_at):
    rows = []
    token = [x for x in re.findall(r'[\w-]+', keyword.casefold()) if len(x) > 2]
    term_counts = Counter()
    for side in ('ours', 'benchmark'):
        page = pages.get(side) or {}
        url = page.get('ranking_url') or page.get('requested_url')
        page_collected_at = page.get('collected_at') or page.get('capture_timestamp')
        if not url or page.get('seo_content_status') not in ('candidate', 'verified_candidate'):
            continue
        headings = page.get('headings') or {}
        heading_rows = [{'level': level, 'text': str(text)[:MAX_TEXT_CHARS]}
                        for level in ('h1', 'h2', 'h3', 'h4')
                        for text in (headings.get(level) or [])[:30] if isinstance(text, str) and text.strip()]
        if heading_rows:
            rows.append(_item(keyword, side, url, 'rendered_heading_inventory', heading_rows,
                'page', source_name + f'#/page_level_evidence/{side}/headings', page_collected_at,
                ['Headings describe captured structure, not topic quality or ranking cause.']))
        sentences = _sentences(page.get('seo_content_text'))
        selected = []
        for sentence in sentences:
            words = [w for w in re.findall(r'[\w-]+', sentence.casefold()) if len(w) > 3]
            if any(t in sentence.casefold() for t in token):
                selected.append(sentence)
            term_counts.update(set(words))
        # Keep a small, repeatable sample of keyword-relevant visible passages.
        selected = list(dict.fromkeys(selected))[:6]
        if selected:
            passages = [{'text': s[:MAX_TEXT_CHARS], 'text_sha256': _sha(s)} for s in selected]
            rows.append(_item(keyword, side, url, 'keyword_relevant_visible_passages', passages,
                'page', source_name + f'#/page_level_evidence/{side}/seo_content_text', page_collected_at,
                ['Bounded excerpt sample from cleaned rendered main content; not a complete page transcript.',
                 'Keyword matching is lexical and does not establish intent satisfaction.']))
        metadata = {k: page.get(k) for k in ('title', 'meta_description', 'canonical', 'robots',
                    'status_code', 'extraction_status', 'url_alignment', 'seo_content_method',
                    'seo_content_word_count') if page.get(k) is not None}
        if metadata:
            rows.append(_item(keyword, side, url, 'page_metadata_and_rendering', metadata,
                'page', source_name + f'#/page_level_evidence/{side}', page_collected_at,
                ['Captured metadata is a point-in-time observation; canonical and robots values require interpretation.']))
        links = page.get('internal_links') or []
        if links:
            link_rows = [{'source_url': url, 'destination_url': u,
                          'direction': 'outgoing_from_selected_page'} for u in links[:MAX_PAGE_LINKS]
                         if isinstance(u, str) and _host(u) == _host(url)]
            if link_rows:
                rows.append(_item(keyword, side, url, 'outgoing_internal_link_inventory', link_rows,
                    'page', source_name + f'#/page_level_evidence/{side}/internal_links', page_collected_at,
                    ['Source crawl stores destination URLs but not anchor text, placement, visibility, or incoming links.',
                     'Outgoing links do not establish incoming links to this page.']))
        schemas = page.get('structured_data_blocks') or []
        if schemas:
            # Preserve compact type/property summaries, not unbounded JSON-LD blobs.
            summaries = []
            for block in schemas[:8]:
                try:
                    obj = json.loads(block) if isinstance(block, str) else block
                    if isinstance(obj, list): obj = obj[:4]
                    summaries.append({'jsonld_sha256': _sha(block), 'shape': _jsonld_shape(obj)})
                except (ValueError, TypeError):
                    summaries.append({'jsonld_sha256': _sha(block), 'parse_status': 'unparsed'})
            rows.append(_item(keyword, side, url, 'structured_data_inventory', summaries,
                'page', source_name + f'#/page_level_evidence/{side}/structured_data_blocks', page_collected_at,
                ['Presence and declared types do not prove validity, eligibility, or display in search results.']))
    # A data-derived lexical landscape keeps topic discovery independent of a
    # vertical-specific taxonomy. It is a review aid, never an asserted gap.
    terms = [{'term': term, 'page_presence': {side: term in (pages.get(side, {}).get('seo_content_text') or '').casefold()
              for side in ('ours', 'benchmark')}} for term, _ in term_counts.most_common(30)]
    if terms:
        rows.append(_item(keyword, 'pair', None, 'observed_content_vocabulary', terms,
            'page_pair', source_name + '#/page_level_evidence/*/seo_content_text', collected_at,
            ['Frequency and presence are lexical signals; absence is not a proven content or intent gap.']))
    return rows


def _jsonld_shape(value):
    if isinstance(value, dict):
        return {'type': value.get('@type'), 'properties': sorted(k for k in value if not k.startswith('@'))[:20]}
    return {'type': type(value).__name__}


def enrich_comparison(source: dict, source_path: str | Path, *, raw_data_root: str | Path | None = None) -> dict:
    """Return bounded evidence grouped by specialist, with source lineage."""
    raw_data_root = Path(raw_data_root).resolve() if raw_data_root is not None else None
    keyword = str(source.get('keyword') or '')
    urls = source.get('primary_ranking_urls') or {}
    pages = source.get('page_level_evidence') or {}
    name = Path(source_path).name
    source_file = Path(source_path)
    project_root = Path(raw_data_root).resolve().parent.parent if raw_data_root else (
        source_file.resolve().parents[3] if len(source_file.resolve().parents) > 3 else source_file.parent)
    # Comparison schema v0.5 omitted link destinations and JSON-LD blocks.
    # Reattach a saved raw page only after exact keyword+URL identity checks.
    raw_dir = Path(raw_data_root) / 'pages' if raw_data_root else project_root / 'data' / 'raw' / 'pages'
    for side in ('ours', 'benchmark'):
        page = pages.get(side)
        if not isinstance(page, dict): continue
        expected = page.get('ranking_url') or page.get('requested_url')
        for raw_path in sorted(raw_dir.glob('*.json')) if raw_dir.is_dir() else []:
            try:
                raw = json.loads(raw_path.read_text(encoding='utf-8'))
            except (OSError, ValueError, UnicodeError):
                continue
            raw_url = raw.get('ranking_url') or raw.get('requested_url')
            if (str(raw.get('keyword') or '').casefold() == keyword.casefold()
                    and raw_url == expected and raw.get('final_url') == expected
                    and raw.get('extraction_status') == 'complete'):
                for key in ('internal_links', 'structured_data_blocks', 'canonical', 'robots', 'seo_content_text'):
                    if key not in page or page.get(key) in (None, [], ''):
                        page[key] = raw.get(key)
                page['_enrichment_raw_source'] = str(raw_path.relative_to(project_root)).replace('\\', '/')
                page['_enrichment_raw_sha256'] = hashlib.sha256(raw_path.read_bytes()).hexdigest()
                break
    serp = ((source.get('ranking_summary') or {}).get('google') or {})
    collected_at = serp.get('datetime') or serp.get('collected_at')
    grouped = {k: [] for k in ('onpage', 'backlinks', 'technical', 'competition')}
    for row in _content_observations(keyword, pages, name, collected_at):
        side = row['page']['side']
        page = pages.get(side) if side in ('ours', 'benchmark') else None
        if isinstance(page, dict) and page.get('_enrichment_raw_source'):
            row['source'] = page['_enrichment_raw_source']
            row['provenance']['source_path'] = page['_enrichment_raw_source']
            row['collected_at'] = page.get('collected_at') or page.get('capture_timestamp')
            row['provenance']['source_sha256'] = page['_enrichment_raw_sha256']
        grouped['onpage'].append(row)
    # Exact-page/domain backlink summaries remain separate; enrich only with
    # raw measures already present in the comparison.
    advanced = source.get('advanced_evidence') or {}
    for scope in ('page', 'domain'):
        data = ((advanced.get('backlinks') or {}).get(scope) or {})
        if data:
            grouped['backlinks'].append(_item(keyword, 'pair', None, f'{scope}_backlink_summary', data,
                scope, name + f'#/advanced_evidence/backlinks/{scope}', collected_at,
                ['Third-party link-index aggregates are not link quality or ranking-causation evidence.']))
    intersection = (advanced.get('keyword_intersection') or {})
    rows = intersection.get('items') or intersection.get('top_generic_benchmark_leads') or []
    # The normalized comparison retains only a selected subset. Read the saved
    # matching Labs response when present, then reuse the existing normalizer.
    labs_dir = Path(raw_data_root) / 'labs' if raw_data_root else project_root / 'data' / 'raw' / 'labs'
    if labs_dir.is_dir():
        from config.settings import keyword_slug
        raw_intersection = labs_dir / f'{keyword_slug(keyword)}_domain_intersection.json'
        if raw_intersection.is_file():
            try:
                raw_value = json.loads(raw_intersection.read_text(encoding='utf-8'))
                task = (raw_value.get('tasks') or [{}])[0]
                result = (task.get('result') or [{}])[0]
                if (str(task.get('status_code')) == '20000' and
                    _host(result.get('target1')) in {_host(x) for x in (source.get('our_domain'), urls.get('ours')) if x} and
                    _host(result.get('target2')) in {_host(x) for x in (source.get('benchmark_competitor_domain'), urls.get('benchmark')) if x}):
                    from normalization.labs import normalize_domain_intersection
                    normalized = normalize_domain_intersection(raw_value, keyword)
                    rows = normalized.get('items') or rows
                    raw_by_keyword = {((i.get('keyword_data') or {}).get('keyword')): i
                                      for i in (result.get('items') or []) if isinstance(i, dict)}
                    for raw_row in rows:
                        if isinstance(raw_row, dict):
                            raw_row['_source_path'] = str(raw_intersection.relative_to(project_root)).replace('\\', '/')
                            raw_row['_source_sha256'] = hashlib.sha256(raw_intersection.read_bytes()).hexdigest()
                            original = raw_by_keyword.get(raw_row.get('keyword')) or {}
                            raw_row['_collected_at'] = ((original.get('keyword_data') or {}).get('keyword_info') or {}).get('last_updated_time')
            except (OSError, ValueError, UnicodeError, IndexError, TypeError):
                pass
    safe = []
    for row in rows:
        if not isinstance(row, dict): continue
        term = row.get('keyword')
        if not isinstance(term, str) or keyword.casefold() not in term.casefold(): continue
        first, second = row.get('our_rank'), row.get('benchmark_rank')
        if type(first) is int and type(second) is int and first > 0 and second > 0:
            from analysis.advanced_evidence import classify_opportunity_relevance
            relevance, reason = classify_opportunity_relevance(term, keyword,
                (urls.get('ours'), urls.get('benchmark')))
            if relevance != 'relevant_generic': continue
            first_result = row.get('first_domain_serp_element') or {}
            second_result = row.get('second_domain_serp_element') or {}
            safe.append({k: row.get(k) for k in ('keyword', 'our_rank', 'benchmark_rank',
                        'search_volume') if row.get(k) is not None} | {
                'rank_gap': first - second, 'relevance_class': relevance, 'relevance_reason': reason,
                'ours_result': {k: first_result.get(k) for k in ('rank_group', 'domain', 'title', 'description', 'url') if first_result.get(k) is not None},
                'benchmark_result': {k: second_result.get(k) for k in ('rank_group', 'domain', 'title', 'description', 'url') if second_result.get(k) is not None},
            })
    if safe:
        safe.sort(key=lambda x: (x.get('search_volume') is not None, x.get('search_volume') or 0,
                                 x.get('rank_gap') or 0), reverse=True)
        grouped['competition'].append(_item(keyword, 'pair', None, 'related_query_domain_rankings', safe[:MAX_KEYWORD_ROWS],
            'domain_keyword_intersection', name + '#/advanced_evidence/keyword_intersection', collected_at,
            ['Different URLs may rank; these domain-level rows do not identify the selected page or show missing queries.']))
        source_meta = next((r for r in rows if isinstance(r, dict) and r.get('_source_path')), None)
        if source_meta:
            grouped['competition'][-1]['source'] = source_meta['_source_path']
            grouped['competition'][-1]['provenance'].update(
                source_path=source_meta['_source_path'], source_sha256=source_meta['_source_sha256'])
            grouped['competition'][-1]['collected_at'] = source_meta.get('_collected_at')
    detailed = (((source.get('technical_comparison') or {}).get('mobile') or {}).get('detailed_analysis') or {})
    investigations = detailed.get('investigations') or []
    if investigations:
        compact_investigations = []
        for row in investigations[:8]:
            if not isinstance(row, dict): continue
            compact_investigations.append({k: row.get(k) for k in (
                'title', 'area', 'priority', 'audit_id', 'measurement',
                'supporting_observation', 'actions', 'validation', 'confidence', 'note') if row.get(k) is not None})
        grouped['technical'].append(_item(keyword, 'pair', None, 'lighthouse_technical_investigations', compact_investigations,
            'exact_page_pair_mobile_lab', name + '#/technical_comparison/mobile/detailed_analysis/investigations', collected_at,
            ['Single-run lab diagnostics are investigation targets, not proven LCP causes or field performance.']))
    # SERP neighborhood retains exact listed results and the search context
    # captured in the deterministic comparison, without copying a whole dump.
    neighborhood = serp.get('ranking_neighborhood') or {}
    for group_name in ('above', 'target', 'below'):
        values = neighborhood.get(group_name)
        if not values: continue
        if isinstance(values, dict): values = [values]
        compact = [{k: x.get(k) for k in ('rank_group', 'domain', 'title', 'description', 'url') if x.get(k) is not None}
                   for x in values[:8] if isinstance(x, dict)]
        if compact:
            grouped['competition'].append(_item(keyword, 'pair', None, 'serp_' + group_name, compact,
                'google_serp_snapshot', name + f'#/ranking_summary/google/ranking_neighborhood/{group_name}', collected_at,
                ['Point-in-time results; search location/device/session details may be incomplete.']))
    serp_dir = Path(raw_data_root) / 'serp' if raw_data_root else project_root / 'data' / 'raw' / 'serp'
    if serp_dir.is_dir():
        from config.settings import keyword_slug
        serp_file = serp_dir / f'{keyword_slug(keyword)}_google_playwright.json'
        if serp_file.is_file():
            try:
                saved_serp = json.loads(serp_file.read_text(encoding='utf-8'))
                if saved_serp.get('keyword', '').casefold() == keyword.casefold() and saved_serp.get('status') in ('ok', 'partial'):
                    value = {k: saved_serp.get(k) for k in ('status', 'datetime', 'search_url',
                        'location_note', 'depth_requested', 'depth_collected', 'pages_completed', 'stop_reason')
                        if saved_serp.get(k) is not None}
                    features = [x for x in saved_serp.get('serp_features', []) if isinstance(x, dict)]
                    if features:
                        value['serp_features'] = [{k: x.get(k) for k in ('type', 'title', 'question', 'text') if x.get(k)}
                                                  for x in features[:12]]
                    item = _item(keyword, 'pair', None, 'serp_search_context', value,
                        'google_serp_snapshot', str(serp_file.relative_to(project_root)).replace('\\', '/'),
                        saved_serp.get('datetime'), ['Browser session/IP and device details may not represent every user.'])
                    item['page']['selected_pages'] = {side: {'url': urls.get(side), 'domain': _host(urls.get(side))}
                                                      for side in ('ours', 'benchmark')}
                    item['provenance']['source_sha256'] = hashlib.sha256(serp_file.read_bytes()).hexdigest()
                    grouped['competition'].append(item)
            except (OSError, ValueError, UnicodeError):
                pass
    for items in grouped.values():
        for row in items:
            if row['page']['side'] == 'pair':
                row['page']['selected_pages'] = {
                    side: {'url': urls.get(side), 'domain': _host(urls.get(side))}
                    for side in ('ours', 'benchmark')}
    return {task: items[:MAX_ITEMS_PER_TASK] for task, items in grouped.items()}
