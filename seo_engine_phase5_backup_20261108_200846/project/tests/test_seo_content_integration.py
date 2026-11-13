from analysis.seo_content_validation import compare
from analysis.onpage import compare_pages
from analysis.final_report import generate_report

U = {'ours':'https://www.hollywoodbets.net/aviator','benchmark':'https://www.betway.co.za/aviator'}

def page(side, words):
    u = U[side]
    return {'ranking_url':u,'requested_url':u,'final_url':u,'url_alignment':'matched',
            'seo_content_method':'rendered-main-innertext-v2','seo_content_status':'verified_candidate',
            'seo_content_word_count':words,'extraction_status':'complete','crawl_failed':False,
            'title':'Aviator','headings':{'h1':['Aviator']},'word_count':500,
            'main_word_count':3948,'rendered_main_word_count':625}

def test_valid_comparison():
    r=compare(page('ours',795),page('benchmark',446),U)
    assert r['comparable'] and r['ours']==795 and r['benchmark']==446
    on=compare_pages(page('ours',795),page('benchmark',446),'aviator')
    assert on['main_word_count']=={'ours':795,'competitor':446}
    assert on['legacy_main_word_count_diagnostic']['competitor']==3948

def test_wrong_method_or_url_withheld():
    a,b=page('ours',795),page('benchmark',446)
    b['seo_content_method']='rendered-main-clean-v1'
    assert not compare(a,b,U)['comparable']
    b['seo_content_method']='rendered-main-innertext-v2'
    b['final_url']='https://www.betway.co.za/'
    assert not compare(a,b,U)['comparable']
    assert compare_pages(a,b,'aviator')['main_word_count']=={'ours':None,'competitor':None}

def test_report_uses_standardized_count_only():
    a,b=page('ours',795),page('benchmark',446)
    data={'keyword':'aviator','primary_ranking_urls':U,
          'evidence_quality':{'page_ours':'usable','page_benchmark':'usable'},
          'page_level_evidence':{'ours':a,'benchmark':b}}
    text=generate_report(data)
    assert 'Standardized cleaned rendered SEO-content words (same method only) | 795 | 446' in text
    assert 'This is not a content-quality' in text
    b['seo_content_status']='unverified'
    text=generate_report(data)
    assert 'Standardized cleaned rendered SEO-content words (same method only) | Not available | Not available' in text
    assert 'Comparison withheld' in text
