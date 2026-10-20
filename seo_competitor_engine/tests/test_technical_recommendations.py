from analysis.technical_diagnostics import compare_technical

URLS = {'ours':'https://example.com/aviator','benchmark':'https://rival.com/aviator'}

def audit(side, data):
    return {'status':'usable','target_verified':True,'final_url_verified':True,
            'scope':'page','device':'mobile','ranking_url':URLS[side],
            'technical_diagnostics':data}

def fixture():
    our = {'javascript_execution':{'bootup-time':{'status':'present','numeric_value':6041.436,'numeric_unit':'millisecond','display_value':'6.0 s','items':[{'url':'https://safe.example/wdp.js','total':1612,'scripting':1600}]}},
           'unused_javascript':{'unused-javascript':{'status':'present','numeric_value':4520,'numeric_unit':'millisecond','display_value':'Est savings of 1,108 KiB','items':[{'url':'https://safe.example/main.js','wastedBytes':335735,'totalBytes':629253}]}},
           'render_blocking':{'render-blocking-insight':{'status':'present','numeric_value':None,'display_value':'Est savings of 160 ms','items':[{'url':'https://safe.example/config.js','wastedMs':1734}]}},
           'image_delivery':{'image-delivery-insight':{'status':'present','display_value':'Est savings of 245 KiB','items':[{'url':'https://safe.example/image.jpg','wastedBytes':69890}]}}}
    comp = {'javascript_execution':{'bootup-time':{'status':'present','numeric_value':8566.8,'numeric_unit':'millisecond'}},
            'unused_javascript':{'unused-javascript':{'status':'present','numeric_value':5520,'numeric_unit':'millisecond'}}}
    return audit('ours',our),audit('benchmark',comp)

def test_priorities_and_specific_resources():
    result=compare_technical(*fixture(),expected_urls=URLS)
    assert result['status']=='usable'
    assert len(result['investigations'])==4
    assert len(result['observations'])==2
    assert [r['priority'] for r in result['investigations']]==['high','high','medium','low']
    js=next(r for r in result['investigations'] if r['area']=='javascript_execution')
    assert js['affected_resources'][0]['url']=='https://safe.example/wdp.js'
    assert js['measurement']['unit']=='millisecond'
    assert js['actions'] and js['validation']
    assert 'ranking causation' in js['note']

def test_no_false_savings_claims():
    result=compare_technical(*fixture(),expected_urls=URLS)
    blocking=next(r for r in result['investigations'] if r['area']=='render_blocking')
    assert blocking['measurement']['value'] is None
    assert blocking['measurement']['display']=='Est savings of 160 ms'
    assert blocking['affected_resources'][0]['wastedMs']==1734
    assert 'guaranteed' in blocking['note']

def test_missing_diagnostics_not_invented():
    ours,comp=fixture()
    ours['technical_diagnostics']={'lcp_breakdown':{'lcp-breakdown-insight':{'status':'not_applicable','items':[]}}}
    result=compare_technical(ours,comp,expected_urls=URLS)
    assert result['investigations']==[]

def test_url_mismatch_withheld():
    ours,comp=fixture()
    comp['ranking_url']='https://other.example/aviator'
    result=compare_technical(ours,comp,expected_urls=URLS)
    assert result['status']=='withheld'
    assert not result['investigations']

def test_original_summary_still_compatible():
    result=compare_technical(*fixture(),expected_urls=URLS)
    assert all('recommendation' in r and 'evidence' in r and 'confidence' in r for r in result['investigations'])
    assert result['observations'][0]['ours']==6041.436
