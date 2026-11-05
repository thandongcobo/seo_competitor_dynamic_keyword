from __future__ import annotations
from datetime import datetime,timezone,timedelta
from . import store
from .capture import capture
def run_due():
    results=[]; now=datetime.now(timezone.utc)
    for p in store.pages():
        if not p['active']: continue
        attempts=store.captures(p['id'])
        last_attempt=attempts[0].get('started_at') if attempts else p['last_success_at']
        due=not last_attempt or datetime.fromisoformat(last_attempt.replace('Z','+00:00'))+timedelta(hours=p['frequency_hours'])<=now
        if due:
            try: results.append(capture(p['id']))
            except Exception as e: results.append({'webpage_id':p['id'],'status':'failed','error':str(e)})
    return results
