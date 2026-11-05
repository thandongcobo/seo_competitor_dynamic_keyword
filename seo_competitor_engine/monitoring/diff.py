from __future__ import annotations
import hashlib, json, re, uuid

IGNORE_PATTERNS=(re.compile(r'(?i)(?<=Updated )\d{4}-\d{2}-\d{2}\b'),)
def clean(v):
    if isinstance(v,list): return [clean(x) for x in v if clean(x) not in ('',None)]
    if isinstance(v,dict): return {k:clean(vv) for k,vv in sorted(v.items()) if k not in ('text_sample','_observed_at','screenshot_path','rendered_html_path','diff_image_path','artifact_errors','visual_comparison','readiness_samples','readiness_wait_seconds','lazy_load_scroll_steps')}
    if isinstance(v,str):
        for p in IGNORE_PATTERNS:v=p.sub('<dynamic>',v)
        return ' '.join(v.split())
    return v
def digest(payload): return hashlib.sha256(json.dumps(clean(payload),ensure_ascii=False,sort_keys=True).encode()).hexdigest()
FIELDS=('title','meta_description','canonical','headings','internal_links','external_links','structured_data_blocks','seo_content_text','main_word_count','rendered_page_text','image_inventory','background_image_inventory')
def _image_summary(items):
    from urllib.parse import urlsplit, urlunsplit
    summary={}
    counts={}
    for item in items or []:
        if not isinstance(item,dict) or (item.get('natural_width',0)<=1 and item.get('natural_height',0)<=1): continue
        src=item.get('src') or ''
        if not src: continue
        parsed=urlsplit(src); stable_src=urlunsplit((parsed.scheme,parsed.netloc,parsed.path,'',''))
        counts[stable_src]=counts.get(stable_src,0)+1
        key=f"{stable_src}#{counts[stable_src]}"
        summary[key]={k:item.get(k) for k in ('alt','title','natural_width','natural_height','visible','loading')}
    return summary
def compare(previous,current,previous_id,current_id,page_id):
    out=[]
    for field in FIELDS:
        if field=='image_inventory':
            a=_image_summary(previous.get(field)); b=_image_summary(current.get(field))
            if a==b: continue
            added=[{'url':key.split('#')[0],**value} for key,value in b.items() if key not in a]
            removed=[{'url':key.split('#')[0],**value} for key,value in a.items() if key not in b]
            modified=[{'url':key.split('#')[0],'previous':a[key],'current':b[key]} for key in a.keys() & b.keys() if a[key]!=b[key]]
            category='added' if added and not removed and not modified else 'removed' if removed and not added and not modified else 'modified'
            old_value={'added':added,'removed':removed,'modified':modified}
            new_value={'added_count':len(added),'removed_count':len(removed),'modified_count':len(modified)}
            out.append({'id':'chg_'+uuid.uuid4().hex,'webpage_id':page_id,'previous_snapshot_id':previous_id,'current_snapshot_id':current_id,'category':category,'element_type':field,'previous_value':json.dumps(old_value,ensure_ascii=False)[:12000],'current_value':json.dumps(new_value,ensure_ascii=False),'first_detected_at':None,'section_id':field,'evidence':'snapshot:'+current_id})
            continue
        a=clean(previous.get(field)); b=clean(current.get(field))
        if a==b: continue
        if a in (None,'',[],{}): category='added'
        elif b in (None,'',[],{}): category='removed'
        else: category='modified'
        previous_value=json.dumps(a,ensure_ascii=False); current_value=json.dumps(b,ensure_ascii=False)
        if field in ('rendered_page_text','image_inventory','background_image_inventory'):
            previous_value=previous_value[:12000]; current_value=current_value[:12000]
        out.append({'id':'chg_'+uuid.uuid4().hex,'webpage_id':page_id,'previous_snapshot_id':previous_id,'current_snapshot_id':current_id,'category':category,'element_type':field,'previous_value':previous_value,'current_value':current_value,'first_detected_at':None,'section_id':field,'evidence':'snapshot:'+current_id})
    return out
