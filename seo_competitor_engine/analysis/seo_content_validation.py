"""Shared validation of standardized content counts for two SERP ranking pages."""
from urllib.parse import urlsplit

METHOD = 'rendered-main-innertext-v2'


def _url(url):
    if not isinstance(url, str):
        return ''
    p = urlsplit(url)
    return (p.scheme.lower(), (p.hostname or '').lower(), p.path.rstrip('/') or '/', p.query)


def validate(page, expected_url=None):
    if not isinstance(page, dict):
        return False, 'missing_page'
    if page.get('seo_content_method') != METHOD:
        return False, 'incompatible_extraction_method'
    if page.get('seo_content_status') != 'verified_candidate':
        return False, 'content_not_verified_candidate'
    if page.get('extraction_status') != 'complete' or page.get('crawl_failed') is True:
        return False, 'crawl_not_complete'
    count = page.get('seo_content_word_count')
    if type(count) is not int or count < 0:
        return False, 'invalid_word_count'
    ranking = page.get('ranking_url')
    if not ranking or not _url(ranking)[1]:
        return False, 'missing_ranking_url'
    if expected_url and _url(ranking) != _url(expected_url):
        return False, 'ranking_url_mismatch'
    if page.get('url_alignment') != 'matched':
        return False, 'url_alignment_not_matched'
    if page.get('requested_url') and _url(page['requested_url']) != _url(ranking):
        return False, 'requested_url_mismatch'
    if not page.get('final_url') or _url(page['final_url']) != _url(ranking):
        return False, 'final_url_mismatch'
    return True, 'verified_candidate'


def compare(ours, benchmark, urls=None):
    urls = urls or {}
    a, ar = validate(ours, urls.get('ours'))
    b, br = validate(benchmark, urls.get('benchmark'))
    comparable = a and b
    return {
        'comparable': comparable,
        'method': METHOD if comparable else None,
        'ours': ours.get('seo_content_word_count') if comparable else None,
        'benchmark': benchmark.get('seo_content_word_count') if comparable else None,
        'ours_validation': ar,
        'benchmark_validation': br,
        'scope': 'visible_cleaned_main_region_words_not_semantic_quality',
    }
