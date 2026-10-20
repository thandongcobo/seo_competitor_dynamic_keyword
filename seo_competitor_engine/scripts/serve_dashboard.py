from __future__ import annotations

import argparse
import json
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
from monitoring import store
from monitoring.intelligence import CATEGORIES, enrich, summarize_change

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except Exception:
        return None


def first_existing(paths):
    for p in paths:
        data = read_json(p)
        if data is not None:
            return data
    return None


def dashboard_state():
    env = {}
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()

    serp_files = sorted((ROOT / "data/raw/serp").glob("*_playwright.json")) if (ROOT / "data/raw/serp").exists() else []
    if not serp_files and (ROOT / "data/raw/serp").exists():
        serp_files = sorted((ROOT / "data/raw/serp").glob("*_result.json"))
    serp_raw = first_existing(list(reversed(serp_files)))

    resolved = first_existing([
        ROOT / "data/processed/resolved_candidates.json",
        ROOT / "data/processed/resolved_pages_google.json",
    ])
    result_dir = ROOT / "output/results" / env.get("KEYWORD", "aviator")
    comparison = read_json(result_dir / f"{env.get('KEYWORD', 'aviator')}_comparison.json")
    canonical = read_json(result_dir / "llm_foundation/canonical_evidence.json")
    coverage = read_json(result_dir / "llm_foundation/evidence_coverage.json")
    executive = read_json(result_dir / "llm_outputs/executive_validated.json")
    executive_meta = read_json(result_dir / "llm_outputs/executive_run_metadata.json") or {}
    executive_status = read_json(result_dir / "llm_outputs/executive_run_status.json") or {}
    analysis = comparison or (first_existing(sorted((ROOT / "output/results").glob("*.json"), reverse=True)) if (ROOT / "output/results").exists() else None)

    if isinstance(serp_raw, dict) and serp_raw.get("collection_method") == "playwright_local_browser":
        rankings = serp_raw.get("organic_results") or []
    else:
        try:
            rankings = [
                x for x in (serp_raw["tasks"][0]["result"][0].get("items") or [])
                if x.get("type") == "organic"
            ] if serp_raw else []
        except Exception:
            rankings = []

    our_domain = env.get("OUR_DOMAIN", "hollywoodbets.net")
    benchmark = env.get("BENCHMARK_COMPETITOR_DOMAIN", env.get("COMPETITOR_DOMAIN", "betway.co.za"))

    def hit(domain):
        wanted = domain.lower().replace("www.", "")
        return next((r for r in rankings if str(r.get("domain", "")).lower().replace("www.", "") == wanted), None)

    ours, bench = hit(our_domain), hit(benchmark)

    findings = []
    if isinstance(analysis, dict):
        findings = analysis.get("findings", []) or analysis.get("analysis", {}).get("findings", []) or []

    candidates = []
    if isinstance(resolved, dict):
        candidates = (
            resolved.get("potential_competitors_from_serp")
            or resolved.get("potential_competitors")
            or resolved.get("candidates")
            or []
        )

    file_list = []
    for base in [ROOT / "data/raw", ROOT / "data/processed", ROOT / "output/results"]:
        if base.exists():
            file_list += [str(p.relative_to(ROOT)) for p in base.rglob("*.json")]

    if comparison:
        ranking_summary = comparison.get("ranking_summary", {}).get("google", {})
        ranking_urls = comparison.get("primary_ranking_urls", {})
        ranking = {"our_position": ranking_summary.get("our_position"), "benchmark_position": ranking_summary.get("benchmark_position"),
                   "position_gap": (ranking_summary.get("our_position") - ranking_summary.get("benchmark_position")) if isinstance(ranking_summary.get("our_position"), int) and isinstance(ranking_summary.get("benchmark_position"), int) else None,
                   "our_url": ranking_urls.get("ours"), "benchmark_url": ranking_urls.get("benchmark")}
    report_base = f"/api/file?name={env.get('KEYWORD', 'aviator')}"
    recommendations = (comparison or {}).get("recommendations", []) if comparison else []
    if comparison and ranking.get("benchmark_url"):
        try:
            store.register(ranking["benchmark_url"], env.get("KEYWORD", "aviator"), "evidence.serp.ranking_summary", True)
        except ValueError:
            pass
    return {
        "meta": {
            "keyword": env.get("KEYWORD", "aviator"),
            "our_domain": our_domain,
            "benchmark_domain": benchmark,
            "location": env.get("LOCATION_COORDINATE") or env.get("LOCATION_NAME") or "Configured location",
        },
        "ranking": {
            "our_position": ours.get("rank_group") if ours else None,
            "benchmark_position": bench.get("rank_group") if bench else None,
            "position_gap": (ours.get("rank_group") - bench.get("rank_group")) if ours and bench else None,
        },
        "rankings": rankings,
        "competitors": candidates,
        "findings": findings,
        "comparison": comparison or {},
        "coverage": coverage or (canonical or {}).get("evidence_coverage", {}),
        "executive": executive or {},
        "executive_meta": executive_meta,
        "executive_status": executive_status,
        "recommendations": recommendations[:3],
        "report_links": {"pdf": report_base + "_executive_report.pdf", "markdown": report_base + "_full_seo_report.md", "appendix": report_base + "_technical_appendix.md", "json": report_base + "_comparison.json"},
        "files": {
            "serp": bool(serp_raw),
            "labs": any((ROOT / "data/raw/labs").glob("*.json")) if (ROOT / "data/raw/labs").exists() else False,
            "backlinks": any((ROOT / "data/raw/backlinks").glob("*.json")) if (ROOT / "data/raw/backlinks").exists() else False,
            "pages": any((ROOT / "data/raw/pages").glob("*.json")) if (ROOT / "data/raw/pages").exists() else False,
            "analysis": bool(analysis),
        },
        "file_list": sorted(file_list),
        "monitoring": {"pages": store.pages(), "initialized": True},
    }


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        rel = urlparse(path).path.lstrip("/") or "index.html"
        return str((FRONTEND / rel).resolve())

    def do_GET(self):
        if urlparse(self.path).path == "/api/dashboard":
            body = json.dumps(dashboard_state(), ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        path=urlparse(self.path).path
        if path == '/api/monitoring/activity':
            from urllib.parse import parse_qs
            from monitoring.activity import activity_feed
            try:
                filters={k:v[0] for k,v in parse_qs(urlparse(self.path).query).items()}
                data={**activity_feed(filters),'categories':CATEGORIES,'version':'2026-10-19.1'}
            except ValueError:
                self.send_error(400,'Invalid activity filter'); return
            body=json.dumps(data,ensure_ascii=False).encode()
            self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path.startswith('/api/monitoring/artifacts/'):
            parts=path.strip('/').split('/')
            if len(parts)==6 and parts[4]=='promotion-image':
                row=store.snapshot(parts[3])
                if not row:
                    self.send_error(404,'Snapshot not found'); return
                try:
                    saved=store.payload(row)
                    image_index=int(parts[5])
                    crop=next((item for item in saved.get('promotion_image_crops',[]) if item.get('image_index')==image_index),None)
                    target=Path(crop['path']).resolve() if crop and crop.get('path') else None
                    if not target: raise FileNotFoundError
                    target.relative_to(store.ARTIFACT_DIR.resolve())
                    body=target.read_bytes()
                except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError):
                    self.send_error(404,'Promotion image unavailable'); return
                self.send_response(200); self.send_header('Content-Type','image/png'); self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(body); return
            if len(parts)!=5 or parts[4] not in ('screenshot','html','visual-diff'):
                self.send_error(404); return
            row=store.snapshot(parts[3])
            if not row:
                self.send_error(404,'Snapshot not found'); return
            try: saved=store.payload(row)
            except (OSError,ValueError,json.JSONDecodeError):
                self.send_error(404,'Snapshot data unavailable'); return
            key={'screenshot':'screenshot_path','html':'rendered_html_path','visual-diff':'visual_comparison'}[parts[4]]
            target_value=saved.get(key)
            if parts[4]=='visual-diff': target_value=(target_value or {}).get('diff_image_path')
            if not target_value:
                self.send_error(404,'Artifact unavailable'); return
            target=Path(target_value).resolve()
            try: target.relative_to(store.ARTIFACT_DIR.resolve())
            except ValueError:
                self.send_error(403); return
            if not target.is_file():
                self.send_error(404,'Artifact not found'); return
            body=target.read_bytes(); content_type='image/png' if target.suffix.lower()=='.png' else 'text/html; charset=utf-8'
            self.send_response(200); self.send_header('Content-Type',content_type); self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(body); return
        if path == '/api/monitoring/pages' or path.startswith('/api/monitoring/pages/'):
            parts=path.strip('/').split('/'); page_id=parts[3] if len(parts)>3 else None
            if not page_id:
                data={'pages':store.pages()}
            else:
                page=store.page(page_id)
                if not page:
                    self.send_error(404,'Monitored page not found'); return
                snapshots=store.snapshots(page_id)
                latest=None
                if snapshots:
                    try: latest=store.payload(snapshots[0])
                    except (OSError,ValueError,json.JSONDecodeError): latest=None
                for snapshot in snapshots: snapshot.pop('payload_path',None)
                captures=store.captures(page_id)
                for capture in captures:
                    if capture.get('diagnostics'):
                        try: capture['diagnostics']=json.loads(capture['diagnostics'])
                        except (TypeError,json.JSONDecodeError): pass
                data={'page':page,'snapshots':snapshots,'changes':[summarize_change(c) for c in store.changes(page_id)],'captures':captures,'latest_snapshot':latest,
                      'promotions':[enrich(p) for p in store.promotions_for_page(page_id)], 'categories':CATEGORIES,
                      'promotion_analysis':(latest or {}).get('promotion_analysis',{})}
            body=json.dumps(data,ensure_ascii=False).encode(); self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
        parsed = urlparse(self.path)
        if parsed.path == "/api/file":
            from urllib.parse import parse_qs
            name = parse_qs(parsed.query).get("name", [""])[0]
            target = (ROOT / "output/results/aviator" / name).resolve()
            allowed = (ROOT / "output/results/aviator").resolve()
            if target.parent == allowed and target.is_file():
                body = target.read_bytes(); self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
            self.send_error(404); return
        super().do_GET()

    def do_POST(self):
        path=urlparse(self.path).path
        if path in ('/api/monitoring/register','/api/monitoring/capture','/api/monitoring/promotions/review','/api/monitoring/settings','/api/monitoring/promotions/categories'):
            try:
                length=int(self.headers.get('Content-Length','0'))
                if length<0 or length>65536: raise ValueError('Request is too large')
                data=json.loads(self.rfile.read(length) or b'{}')
                if path.endswith('register'):
                    result={'page_id':store.register(data['url'],data.get('keyword','aviator'),data.get('source_evidence','dashboard.user_added_public_url'),data.get('active',True))}
                elif path.endswith('categories'):
                    categories=data.get('categories')
                    if not isinstance(categories,list) or any(not isinstance(k,str) or k not in CATEGORIES for k in categories): raise ValueError('Select valid promotion categories.')
                    with store.connect() as connection:
                        changed=connection.execute('UPDATE promotions SET category_override_json=? WHERE id=?',(json.dumps(list(dict.fromkeys(categories))) if categories else None,data['promotion_id']))
                        if changed.rowcount!=1: raise ValueError('Unknown promotion')
                    result={'status':'saved'}
                elif path.endswith('settings'):
                    hours=int(data.get('frequency_hours',24))
                    if not 1 <= hours <= 720 or not isinstance(data.get('active'),bool): raise ValueError('Choose an interval from 1 to 720 hours and an enabled/paused state.')
                    with store.connect() as connection:
                        changed=connection.execute('UPDATE webpages SET active=?,frequency_hours=? WHERE id=?',(int(data['active']),hours,data['page_id']))
                        if changed.rowcount!=1: raise ValueError('Unknown monitored page')
                    result={'status':'saved'}
                elif path.endswith('review'):
                    result=store.update_promotion_review(data['promotion_id'],data['decision'])
                else:
                    from monitoring.capture import capture
                    result=capture(data['page_id'])
                body=json.dumps(result,ensure_ascii=False).encode(); self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
            except Exception as e:
                body=json.dumps({'error':str(e)}).encode(); self.send_response(400); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
            return
        self.send_error(404)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Serve the local SEO dashboard")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    print(f"SEO dashboard: http://127.0.0.1:{args.port}/")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
