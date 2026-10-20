import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llm_foundation.request_optimizer import prepare_request, optimize_packet


def sample():
    return {'schema_version':'1.0','task':'onpage',
            'investigation':{'keyword':'aviator','search_engine':'google'},
            'tracked_website':{'ranking_url':'https://example.com/aviator','position':2},
            'competitors':[{'ranking_url':'https://other.com/aviator','position':1}],
            'evidence_quality':{'page_ours':'usable','page_benchmark':'usable'},
            'evidence':{'serp':{'ranking_summary':{'our_position':2,'benchmark_position':1,
              'ranking_neighborhood':{'above':['a']*200}}},
              'onpage':{'pages':{'ours':{'title':'Aviator','internal_link_count':9},
                                 'benchmark':{'title':'Play Aviator','internal_link_count':28}},
              'comparison':{'title_keyword_match':{'ours':True,'competitor':True},
                            'content_token_jaccard':0.143,'word_count':{'ours':867,'competitor':2801}},
              'comparable':True}}}


def test_compact_preserves_evidence_paths():
    compact=optimize_packet('onpage',sample())
    assert compact['evidence']['onpage']['comparison']['content_token_jaccard']==0.143
    assert 'ranking_neighborhood' not in compact['evidence']['serp']['ranking_summary']
    assert 'word_count' not in compact['evidence']['onpage']['comparison']


def test_request_within_budget():
    compact, system, prompt, estimate=prepare_request('onpage',sample(),skills='Evidence only.',instructions='Analyse onpage.')
    assert estimate < 2050
    assert 'evidence.onpage' not in system
    assert 'Aviator' in prompt


def test_fail_closed_on_oversize():
    d=sample(); d['evidence']['onpage']['pages']['ours']['title']='x'*9000
    try:
        prepare_request('onpage',d,skills='Evidence only.',instructions='Analyse onpage.',max_input_tokens=2000)
    except ValueError as e:
        assert 'exceeds' in str(e)
    else:
        assert False, 'oversized prompt should fail'


def test_original_unchanged():
    d=sample(); before=repr(d)
    optimize_packet('onpage',d)
    assert repr(d)==before
