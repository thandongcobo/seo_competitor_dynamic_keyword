from __future__ import annotations
import ipaddress, json, socket, sqlite3, uuid
from difflib import SequenceMatcher
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / 'data' / 'monitoring.sqlite3'
ARTIFACT_DIR = ROOT / 'data' / 'monitoring_artifacts'

def now(): return datetime.now(timezone.utc).isoformat()
@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
def init_db():
    with connect() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS webpages(id TEXT PRIMARY KEY,url TEXT NOT NULL UNIQUE,domain TEXT NOT NULL,keywords TEXT NOT NULL,source_evidence TEXT,active INTEGER NOT NULL DEFAULT 0,frequency_hours INTEGER NOT NULL DEFAULT 24,created_at TEXT NOT NULL,last_success_at TEXT,next_capture_at TEXT);
        CREATE TABLE IF NOT EXISTS captures(id TEXT PRIMARY KEY,webpage_id TEXT NOT NULL,status TEXT NOT NULL,started_at TEXT NOT NULL,finished_at TEXT,error TEXT,diagnostics TEXT,FOREIGN KEY(webpage_id) REFERENCES webpages(id));
        CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY,webpage_id TEXT NOT NULL,capture_id TEXT NOT NULL,captured_at TEXT NOT NULL,final_url TEXT,extraction_method TEXT,content_hash TEXT,payload_path TEXT NOT NULL,FOREIGN KEY(webpage_id) REFERENCES webpages(id));
        CREATE TABLE IF NOT EXISTS changes(id TEXT PRIMARY KEY,webpage_id TEXT NOT NULL,previous_snapshot_id TEXT,current_snapshot_id TEXT,category TEXT NOT NULL,element_type TEXT NOT NULL,previous_value TEXT,current_value TEXT,first_detected_at TEXT NOT NULL,section_id TEXT,evidence TEXT,active INTEGER NOT NULL DEFAULT 1,FOREIGN KEY(webpage_id) REFERENCES webpages(id));
        CREATE TABLE IF NOT EXISTS promotions(id TEXT PRIMARY KEY,page_id TEXT NOT NULL,fingerprint TEXT NOT NULL,title TEXT NOT NULL,extracted_text TEXT NOT NULL,source_url TEXT,target_url TEXT,image_path TEXT,image_index INTEGER,first_seen_at TEXT NOT NULL,last_seen_at TEXT NOT NULL,last_snapshot_id TEXT NOT NULL,status TEXT NOT NULL,confidence TEXT NOT NULL,review_status TEXT NOT NULL,missed_captures INTEGER NOT NULL DEFAULT 0,history_json TEXT NOT NULL DEFAULT '[]',UNIQUE(page_id,fingerprint),FOREIGN KEY(page_id) REFERENCES webpages(id));
        CREATE INDEX IF NOT EXISTS idx_snapshots_page_time ON snapshots(webpage_id,captured_at);
        CREATE INDEX IF NOT EXISTS idx_changes_page_time ON changes(webpage_id,first_detected_at);
        CREATE INDEX IF NOT EXISTS idx_promotions_page_status ON promotions(page_id,status,last_seen_at);
        CREATE TABLE IF NOT EXISTS promotion_aliases(page_id TEXT NOT NULL,fingerprint TEXT NOT NULL,promotion_id TEXT NOT NULL,PRIMARY KEY(page_id,fingerprint));
        ''')

        columns={row['name'] for row in c.execute('PRAGMA table_info(promotions)')}
        for name, declaration in (
            ('source_type', "TEXT NOT NULL DEFAULT 'image'"),
            ('details_json', "TEXT NOT NULL DEFAULT '{}'"),
            ('investigation_json', "TEXT NOT NULL DEFAULT '{}'"),
            ('first_snapshot_id', 'TEXT'),
            ('category_override_json', 'TEXT'),
        ):
            if name not in columns:
                c.execute(f'ALTER TABLE promotions ADD COLUMN {name} {declaration}')
        c.execute('''UPDATE promotions SET first_snapshot_id=(SELECT id FROM snapshots s
            WHERE s.webpage_id=promotions.page_id AND s.captured_at=promotions.first_seen_at LIMIT 1)
            WHERE first_snapshot_id IS NULL''')


def validate_public_url(url):
    """Reject malformed, credential-bearing, local, and literal private URLs."""
    if not isinstance(url,str) or not url.strip() or len(url)>2048:
        raise ValueError('Enter a valid public webpage URL (up to 2048 characters)')
    try:
        parsed=urlsplit(url.strip())
        host=(parsed.hostname or '').rstrip('.').lower()
        port=parsed.port
    except ValueError as exc:
        raise ValueError('Enter a valid public webpage URL') from exc
    if parsed.scheme.lower() not in ('http','https') or not host or parsed.username or parsed.password:
        raise ValueError('Only public HTTP(S) webpage URLs without embedded credentials are allowed')
    if port not in (None,80,443):
        raise ValueError('Only standard public HTTP(S) ports are allowed')
    if host in ('localhost','localhost.localdomain') or host.endswith(('.localhost','.local','.internal')) or '.' not in host:
        raise ValueError('Local or intranet URLs cannot be monitored')
    try:
        address=ipaddress.ip_address(host)
    except ValueError:
        address=None
    if address is not None and not address.is_global:
        raise ValueError('Private or non-public IP addresses cannot be monitored')
    return url.strip()


def validate_public_host(url):
    """At capture time, reject hostnames resolving to any non-public address."""
    safe_url=validate_public_url(url)
    parsed=urlsplit(safe_url)
    try:
        addresses={item[4][0] for item in socket.getaddrinfo(parsed.hostname,parsed.port or (443 if parsed.scheme=='https' else 80),type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise ValueError('The public webpage host could not be resolved') from exc
    if not addresses:
        raise ValueError('The public webpage host did not resolve to an address')
    for value in addresses:
        try: address=ipaddress.ip_address(value)
        except ValueError as exc: raise ValueError('The webpage host returned an invalid network address') from exc
        if not address.is_global:
            raise ValueError('The webpage host resolves to a private or non-public network address')
    return safe_url


def register(url, keyword='aviator', source_evidence='evidence.serp.primary_ranking_urls.benchmark', active=True):
    url=validate_public_url(url)
    p=urlsplit(url)
    init_db(); page_id='page_'+uuid.uuid4().hex
    with connect() as c:
        row=c.execute('SELECT id FROM webpages WHERE url=?',(url,)).fetchone()
        if row: c.execute('UPDATE webpages SET keywords=?,source_evidence=?,active=? WHERE id=?',(json.dumps([keyword]),source_evidence,int(active),row['id'])); return row['id']
        c.execute('INSERT INTO webpages VALUES (?,?,?,?,?,?,?,?,?,?)',(page_id,url,p.hostname,json.dumps([keyword]),source_evidence,int(active),24,now(),None,None)); return page_id
def pages():
    init_db();
    with connect() as c:return [dict(x) for x in c.execute('SELECT * FROM webpages ORDER BY created_at DESC').fetchall()]
def page(page_id):
    with connect() as c:
        r=c.execute('SELECT * FROM webpages WHERE id=?',(page_id,)).fetchone(); return dict(r) if r else None
def snapshots(page_id):
    with connect() as c: rows=[dict(x) for x in c.execute('SELECT s.* FROM snapshots s JOIN captures c ON c.id=s.capture_id WHERE s.webpage_id=? AND c.status=\'success\' ORDER BY s.captured_at DESC',(page_id,)).fetchall()]
    result=[]
    for row in rows:
        try:
            data=json.loads(Path(row['payload_path']).read_text(encoding='utf-8'))
            if data.get('tracking_eligible',True): result.append(row)
        except (OSError,ValueError,json.JSONDecodeError):
            # Preserve historical capture metadata if an older local artifact
            # has been moved or cleaned; its original eligibility is unknown.
            result.append(row)
    return result
def captures(page_id):
    with connect() as c:return [dict(x) for x in c.execute('SELECT * FROM captures WHERE webpage_id=? ORDER BY started_at DESC',(page_id,)).fetchall()]
def changes(page_id):
    with connect() as c:return [dict(x) for x in c.execute('SELECT * FROM changes WHERE webpage_id=? ORDER BY first_detected_at DESC',(page_id,)).fetchall()]
def payload(snapshot): return json.loads(Path(snapshot['payload_path']).read_text(encoding='utf-8'))
def snapshot(snapshot_id):
    with connect() as c:
        row=c.execute('SELECT * FROM snapshots WHERE id=?',(snapshot_id,)).fetchone()
        return dict(row) if row else None

def record_promotions(page_id, snapshot_id, captured_at, analysis):
    """Persist image/text candidates and age only sources scanned successfully."""
    init_db()
    candidates=analysis.get('candidates') or []
    ocr_complete=analysis.get('image_scan_complete',analysis.get('status') in ('available','partial'))
    text_complete=bool(analysis.get('text_scan_complete'))
    with connect() as c:
        page_row=c.execute('SELECT url FROM webpages WHERE id=?',(page_id,)).fetchone()
        monitored_url=page_row['url'] if page_row else ''
        observed_ids=set()
        for item in candidates:
            row=c.execute('SELECT * FROM promotions WHERE page_id=? AND fingerprint=?',
                          (page_id,item['fingerprint'])).fetchone()
            if not row:
                row=c.execute('''SELECT p.* FROM promotions p JOIN promotion_aliases a ON a.promotion_id=p.id
                    WHERE a.page_id=? AND a.fingerprint=?''',(page_id,item['fingerprint'])).fetchone()
            # A stable public destination is a better identity signal than a
            # rotating CDN URL or wording variant. Never merge candidates that
            # lack a destination because that would risk joining unrelated offers.
            if not row and item.get('target_url'):
                target=urlsplit(item['target_url'])
                source=urlsplit(monitored_url)
                if target.path not in ('','/') and target.netloc.lower()==source.netloc.lower() and target.path!=source.path:
                    possible=c.execute('''SELECT * FROM promotions WHERE page_id=? AND target_url=?
                        AND status IN ('current','possibly_rotated','not_detected','not_seen')
                        ORDER BY last_seen_at DESC''',(page_id,item['target_url'])).fetchall()
                    new_text=' '.join(((item.get('title') or '')+' '+(item.get('extracted_text') or '')).lower().split())
                    matches=[]
                    for candidate_row in possible:
                        if candidate_row['id'] in observed_ids: continue
                        old_text=' '.join(((candidate_row['title'] or '')+' '+(candidate_row['extracted_text'] or '')).lower().split())
                        score=SequenceMatcher(None,old_text,new_text).ratio()
                        if score>=0.8: matches.append((score,candidate_row))
                    matches.sort(key=lambda value:value[0],reverse=True)
                    if matches and (len(matches)==1 or matches[0][0]-matches[1][0]>=0.15): row=matches[0][1]
            source_type=item.get('source_type','image')
            details_json=json.dumps(item.get('details') or {},ensure_ascii=False)
            investigation_json=json.dumps(item.get('investigation') or {},ensure_ascii=False)
            if row:
                previous=dict(row)
                promotion_id=previous['id']
                history=json.loads(previous.get('history_json') or '[]')
                old_details=previous.get('details_json') or '{}'
                old_detail_data=json.loads(old_details)
                new_detail_data=item.get('details') or {}
                creative_changed=bool(old_detail_data.get('creative_sha256') and new_detail_data.get('creative_sha256') and old_detail_data['creative_sha256']!=new_detail_data['creative_sha256'])
                text_changed=(item.get('extracted_text') or '')!=previous.get('extracted_text','')
                offer_fields=('amounts','percentages','promo_codes','dates','time_windows','eligibility_or_terms','terms_url')
                details_changed=any(old_detail_data.get(k,[])!=new_detail_data.get(k,[]) for k in offer_fields if k!='time_windows' or k in old_detail_data)
                content_changed=text_changed or details_changed or creative_changed
                if content_changed:
                    history.append({'event':'creative_changed' if creative_changed and not text_changed and not details_changed else 'version_changed','observed_at':captured_at,'snapshot_id':snapshot_id,
                                    'text':item.get('extracted_text') or '', 'image_path':item.get('image_path'),
                                    'details':item.get('details') or {}, 'source_url':item.get('source_url'),
                                    'target_url':item.get('target_url'), 'previous_snapshot_id':previous['last_snapshot_id'],
                                    'previous_text':previous['extracted_text'], 'previous_details':json.loads(old_details),
                                    'image_index':item.get('image_index'),'creative_changed':creative_changed})
                if previous['status'] in ('possibly_rotated','not_detected','not_seen'):
                    history.append({'event':'seen_again','observed_at':captured_at,'snapshot_id':snapshot_id,
                                    'note':'This candidate was observed again after a gap in detection.'})
                review_status=(item.get('review_status','needs_review') if content_changed or previous.get('review_status') not in ('confirmed','dismissed')
                               else previous['review_status'])
                c.execute('''UPDATE promotions SET title=?,extracted_text=?,source_url=?,target_url=?,image_path=?,image_index=?,
                    last_seen_at=?,last_snapshot_id=?,status='current',confidence=?,review_status=?,missed_captures=0,history_json=?,
                    source_type=?,details_json=?,investigation_json=?
                    WHERE id=?''',
                    (item.get('title') or 'Promotion candidate',item.get('extracted_text') or '',item.get('source_url'),
                     item.get('target_url'),item.get('image_path'),item.get('image_index'),captured_at,snapshot_id,item.get('confidence','low'),
                     review_status,json.dumps(history,ensure_ascii=False),source_type,details_json,investigation_json,previous['id']))
            else:
                promotion_id='promo_'+uuid.uuid4().hex
                c.execute('''INSERT INTO promotions(id,page_id,fingerprint,title,extracted_text,source_url,target_url,image_path,image_index,
                    first_seen_at,last_seen_at,last_snapshot_id,status,confidence,review_status,missed_captures,history_json,
                    source_type,details_json,investigation_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,'[]',?,?,?)''',
                    (promotion_id,page_id,item['fingerprint'],item.get('title') or 'Promotion candidate',
                     item.get('extracted_text') or '',item.get('source_url'),item.get('target_url'),item.get('image_path'),
                     item.get('image_index'),
                     captured_at,captured_at,snapshot_id,'current',item.get('confidence','low'),
                     item.get('review_status','needs_review'),source_type,details_json,investigation_json))
                c.execute('UPDATE promotions SET first_snapshot_id=? WHERE id=?',(snapshot_id,promotion_id))
            observed_ids.add(promotion_id)
            c.execute('INSERT OR IGNORE INTO promotion_aliases VALUES (?,?,?)',(page_id,item['fingerprint'],promotion_id))
        rows=c.execute("SELECT id,fingerprint,missed_captures,source_type,history_json,title FROM promotions WHERE page_id=? AND status IN ('current','possibly_rotated')",(page_id,)).fetchall()
        for row in rows:
            if row['id'] in observed_ids:
                continue
            source_type=row['source_type'] or 'image'
            if source_type=='text': can_age=text_complete
            elif source_type=='image': can_age=ocr_complete
            else: can_age=text_complete  # A text-backed offer can be checked without OCR.
            if not can_age:
                continue
            misses=row['missed_captures']+1
            status='not_detected' if misses>=2 else 'possibly_rotated'
            if status=='not_detected':
                history=json.loads(row['history_json'] or '[]')
                history.append({'event':'not_detected','observed_at':captured_at,'snapshot_id':snapshot_id,
                                'note':'Candidate not detected in two eligible captures; this does not prove the offer ended.'})
                c.execute("UPDATE promotions SET missed_captures=?,status=?,history_json=? WHERE id=?",
                          (misses,status,json.dumps(history,ensure_ascii=False),row['id']))
                continue
            c.execute("UPDATE promotions SET missed_captures=?,status=? WHERE id=?",
                      (misses,status,row['id']))

def promotions_for_domain(domain):
    init_db()
    with connect() as c:
        rows=c.execute('''SELECT p.*,w.domain,w.url AS page_url FROM promotions p
            JOIN webpages w ON w.id=p.page_id WHERE lower(w.domain)=lower(?)
            ORDER BY CASE p.status WHEN 'current' THEN 0 WHEN 'possibly_rotated' THEN 1 ELSE 2 END,
            p.last_seen_at DESC''',(domain,)).fetchall()
        result=[]
        for row in rows:
            item=dict(row)
            try:item['history']=json.loads(item.pop('history_json', '[]'))
            except (TypeError,json.JSONDecodeError):item['history']=[]
            for source, target in (('details_json','details'),('investigation_json','investigation')):
                try:item[target]=json.loads(item.pop(source,'{}'))
                except (TypeError,json.JSONDecodeError):item[target]={}
            result.append(item)
        return result

def promotions_for_page(page_id):
    init_db()
    with connect() as c:
        rows=c.execute('''SELECT p.*,w.domain,w.url AS page_url FROM promotions p
            JOIN webpages w ON w.id=p.page_id WHERE p.page_id=?
            ORDER BY CASE p.status WHEN 'current' THEN 0 WHEN 'possibly_rotated' THEN 1 ELSE 2 END,
            p.last_seen_at DESC''',(page_id,)).fetchall()
        result=[]
        for row in rows:
            item=dict(row)
            for source,target in (('history_json','history'),('details_json','details'),('investigation_json','investigation')):
                try:item[target]=json.loads(item.pop(source,'[]' if target=='history' else '{}'))
                except (TypeError,json.JSONDecodeError):item[target]=[] if target=='history' else {}
            result.append(item)
        return result

def update_promotion_review(promotion_id, decision):
    if decision not in ('confirmed','dismissed','needs_review'):
        raise ValueError('Review decision must be confirmed, dismissed, or needs_review')
    init_db()
    with connect() as c:
        cur=c.execute('UPDATE promotions SET review_status=? WHERE id=?',(decision,promotion_id))
        if cur.rowcount!=1:
            raise ValueError('Promotion candidate was not found')
    return {'promotion_id':promotion_id,'review_status':decision}
