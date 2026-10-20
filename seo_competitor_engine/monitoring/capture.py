from __future__ import annotations
import json, threading, uuid, hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit
from collectors.playwright_collector import crawl_page
from . import store
from .diff import compare,digest

_locks={}; _guard=threading.Lock()

def _tracking_quality(data, requested_url):
    """Return conservative quality metadata before comparing or aging offers."""
    text=data.get('rendered_page_text') or data.get('seo_content_text') or ''
    words=len(text.split())
    final_url=data.get('final_url') or requested_url
    try:
        same_host=urlsplit(final_url).hostname.lower().rstrip('.') == urlsplit(requested_url).hostname.lower().rstrip('.')
    except (AttributeError, TypeError):
        same_host=False
    reasons=[]; warnings=[]
    if data.get('extraction_status')!='complete': reasons.append('Page extraction was incomplete.')
    if data.get('status_code') is not None and int(data['status_code']) >= 400: reasons.append(f"Page returned HTTP {data['status_code']}.")
    if not same_host: reasons.append('Final URL is on a different host from the registered page.')
    if data.get('content_stable') is False: reasons.append('Rendered content did not stabilize.')
    if words < 40:
        if data.get('image_inventory'):
            warnings.append('Low visible-text volume; text-based promotion absence will not be used to age existing offers.')
        else:
            reasons.append('Very little public text or image content was captured.')
    return {'eligible':not reasons,'reasons':reasons,'warnings':warnings,'word_count':words,'same_host':same_host,
            'final_url':final_url,'checked_at':store.now()}

def capture(page_id):
    store.init_db(); page=store.page(page_id)
    if not page: raise ValueError('Unknown monitored webpage')
    with _guard:
        lock=_locks.setdefault(page_id,threading.Lock())
    if not lock.acquire(blocking=False): raise RuntimeError('A capture is already running for this webpage')
    capture_id='cap_'+uuid.uuid4().hex; started=store.now()
    try:
        with store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            cutoff=(datetime.now(timezone.utc)-timedelta(minutes=30)).isoformat()
            c.execute("UPDATE captures SET status='failed',finished_at=?,error='Capture did not finish within its lease.' WHERE webpage_id=? AND status='running' AND started_at<?",(started,page_id,cutoff))
            if c.execute("SELECT 1 FROM captures WHERE webpage_id=? AND status='running'",(page_id,)).fetchone():
                raise RuntimeError('A capture is already running for this webpage')
            c.execute('INSERT INTO captures VALUES (?,?,?,?,?,?,?)',(capture_id,page_id,'running',started,None,None,None))
        store.validate_public_host(page['url'])
        snap_id='snap_'+uuid.uuid4().hex
        store.ARTIFACT_DIR.mkdir(parents=True,exist_ok=True)
        artifact_dir=store.ARTIFACT_DIR/snap_id
        data=crawl_page(page['url'],artifact_dir=artifact_dir,public_only=True)
        if data.get('extraction_status')!='complete': raise RuntimeError(data.get('error') or 'Capture was incomplete')
        quality=_tracking_quality(data,page['url'])
        data['tracking_quality']=quality
        data['tracking_eligible']=quality['eligible']
        previous=store.snapshots(page_id); previous_payload=store.payload(previous[0]) if previous else None
        try:
            from .promotions import analyze_capture, investigate_candidates
            analysis=analyze_capture(data)
            for candidate in analysis.get('candidates',[]):
                if not candidate.get('image_path'): continue
                try:
                    from PIL import Image
                    with Image.open(candidate['image_path']) as artwork:
                        pixels=artwork.convert('RGB')
                        candidate.setdefault('details',{})['creative_sha256']=hashlib.sha256(str(pixels.size).encode()+pixels.tobytes()).hexdigest()
                except (OSError,ValueError): pass
            data['promotion_analysis']=investigate_candidates(
                analysis, source_url=data.get('final_url') or page['url'],
                previous_candidates=(previous_payload or {}).get('promotion_analysis',{}).get('candidates',[])) if quality['eligible'] else analysis
        except Exception as exc:
            # A promotion-classification failure must not invalidate a successful page capture.
            data['promotion_analysis']={'status':'error','message':'Promotion analysis could not complete; page capture was saved.','error_type':type(exc).__name__,'candidates':[]}
        old_mode=(previous_payload or {}).get('screenshot_mode')
        new_mode=data.get('screenshot_mode')
        if previous_payload and previous_payload.get('screenshot_path') and data.get('screenshot_path') and new_mode and old_mode!=new_mode:
            data['visual_comparison']={'status':'baseline','reason':'Screenshot capture layout changed; the next capture will be compared using the same layout.'}
        elif previous_payload and previous_payload.get('screenshot_path') and data.get('screenshot_path'):
            try:
                from PIL import Image, ImageChops, ImageEnhance
                old=Image.open(previous_payload['screenshot_path']).convert('RGB')
                new=Image.open(data['screenshot_path']).convert('RGB')
                width=max(old.width,new.width); height=max(old.height,new.height)
                old_canvas=Image.new('RGB',(width,height),'white'); new_canvas=Image.new('RGB',(width,height),'white')
                old_canvas.paste(old,(0,0)); new_canvas.paste(new,(0,0))
                diff=ImageChops.difference(old_canvas,new_canvas)
                changed=sum(1 for pixel in diff.convert('L').getdata() if pixel>24)
                total=width*height
                diff_path=artifact_dir/'visual_diff.png'
                ImageEnhance.Contrast(diff).enhance(3).save(diff_path)
                data['visual_comparison']={'status':'compared','changed_pixel_percent':round(changed*100/total,2) if total else 0,
                    'previous_dimensions':[old.width,old.height],'current_dimensions':[new.width,new.height],
                    'diff_image_path':str(diff_path)}
            except Exception as exc:
                data['visual_comparison']={'status':'unavailable','reason':f'{type(exc).__name__}: {exc}'}
        elif data.get('screenshot_path'):
            data['visual_comparison']={'status':'baseline','reason':'A second successful screenshot is needed for visual comparison.'}
        captured_at=store.now()
        data['captured_at']=captured_at
        path=store.ARTIFACT_DIR/(snap_id+'.json')
        path.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
        events=compare(previous_payload,data,previous[0]['id'],snap_id,page_id) if previous_payload and quality['eligible'] else []
        with store.connect() as c:
            for e in events:
                e['first_detected_at']=store.now(); c.execute('INSERT INTO changes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(e['id'],e['webpage_id'],e['previous_snapshot_id'],e['current_snapshot_id'],e['category'],e['element_type'],e['previous_value'],e['current_value'],e['first_detected_at'],e['section_id'],e['evidence'],1))
            c.execute('INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?)',(snap_id,page_id,capture_id,captured_at,data.get('final_url'), 'playwright-rendered-page-v2',digest(data),str(path)))
            c.execute('UPDATE captures SET status=?,finished_at=? WHERE id=?',('success',captured_at,capture_id))
            c.execute('UPDATE captures SET diagnostics=? WHERE id=?',(json.dumps({'tracking_quality':quality},ensure_ascii=False),capture_id))
            if quality['eligible']:
                c.execute('UPDATE webpages SET last_success_at=? WHERE id=?',(captured_at,page_id))
        if quality['eligible']:
            promotion_analysis=dict(data.get('promotion_analysis') or {})
            if quality['word_count'] < 40:
                promotion_analysis['text_scan_complete']=False
            store.record_promotions(page_id,snap_id,captured_at,promotion_analysis)
        return {'capture_id':capture_id,'snapshot_id':snap_id,'changes':events,'status':'success',
                'tracking_eligible':quality['eligible'],'tracking_quality':quality}
    except Exception as exc:
        with store.connect() as c:c.execute('UPDATE captures SET status=?,finished_at=?,error=? WHERE id=?',('failed',store.now(),str(exc),capture_id))
        raise
    finally: lock.release()
