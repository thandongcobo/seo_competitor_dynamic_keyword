from __future__ import annotations

import argparse
import json
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
from scripts import dashboard_serp_search
from scripts import serp_investigations
from scripts import reporting_jobs
from scripts.search_investigation_history import search_history
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
    recommendation_audit = {}
    if comparison:
        from analysis.recommendation_classification import adapt_comparison
        comparison, recommendation_audit = adapt_comparison(comparison)
        recommendations = comparison.get("recommendations") or []
        from analysis.recommendations import reconcile_recommendations
        specialist_quality = read_json(result_dir / "llm_outputs/recommendation_quality_report.json") or {}
        recommendations, reconciliation_audit = reconcile_recommendations(
            recommendations, executive or {}, specialist_quality)
        recommendation_audit["reconciliation"] = reconciliation_audit
        comparison['recommendations'] = recommendations
        comparison['recommendation_classification_audit'] = recommendation_audit
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
        "recommendations": recommendations,
        "recommendation_reconciliation_audit": recommendation_audit,
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
        target = (FRONTEND / rel).resolve()
        try:
            target.relative_to(FRONTEND.resolve())
        except ValueError:
            return str(FRONTEND / '__invalid_path__')
        return str(target)

    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed_serp = urlparse(self.path)
        parts = parsed_serp.path.strip('/').split('/')
        if len(parts) == 4 and parts[:2] == ['api', 'investigations'] and parts[3] == 'workflow':
            try:
                from scripts.investigation_workflow import get_state
                self.send_json(200, get_state(parts[2]))
            except (ValueError, FileNotFoundError) as exc:
                self.send_json(404 if isinstance(exc, FileNotFoundError) else 400, {'error': str(exc)})
            return
        if len(parts) == 5 and parts[:2] == ['api', 'investigations'] and parts[3:] == ['workflow', 'collection-plan']:
            from urllib.parse import parse_qs
            query = parse_qs(parsed_serp.query)
            refresh = query.get('refresh', ['0'])[0].lower() in ('1', 'true', 'yes')
            try:
                self.send_json(200, __import__('scripts.investigation_workflow', fromlist=['collection_plan']).collection_plan(
                    parts[2], refresh=refresh))
            except (ValueError, FileNotFoundError) as exc:
                self.send_json(404 if isinstance(exc, FileNotFoundError) else 400, {'error': str(exc)})
            return
        if parsed_serp.path == '/api/investigations/history':
            from urllib.parse import parse_qs
            query = parse_qs(parsed_serp.query)
            value = lambda key: query.get(key, [''])[0]
            try:
                records = search_history(serp_investigations.INVESTIGATIONS,
                    keyword=value('keyword'), url_a=value('url_a'), url_b=value('url_b'), limit=50)
                # Never expose server-side filesystem paths or historical
                # artifacts that do not pass the current integrity checks.
                for record in records:
                    ident = record['investigation_id']
                    record['has_pdf'] = False
                    record['has_appendix'] = False
                    if record['reporting_status'] in ('draft_ready', 'approved'):
                        for kind, key in [('pdf', 'has_pdf'), ('appendix', 'has_appendix')]:
                            try:
                                reporting_jobs.artifact(ident, kind)
                                record[key] = True
                            except (ValueError, FileNotFoundError):
                                pass
                    record.pop('reports', None)
                self.send_json(200, {'investigations': records})
            except (ValueError, OSError) as exc:
                self.send_json(400, {'error': str(exc)})
            return
        if parsed_serp.path == '/api/comparisons/history':
            from urllib.parse import parse_qs
            from scripts.comparison_history import history
            query = parse_qs(parsed_serp.query)
            value = lambda key, default='': query.get(key, [default])[0]
            try:
                result = history(query=value('q'), keyword=value('keyword'),
                    competitor=value('competitor'), url=value('url'),
                    date_from=value('date_from'), date_to=value('date_to'),
                    sort=value('sort', 'recent'), page=value('page', '1'),
                    page_size=value('page_size', '20'))
                self.send_json(200, result)
            except (ValueError, OSError, TypeError) as exc:
                self.send_json(400, {'error': str(exc)})
            return
        if len(parts) >= 3 and parts[:2] == ['api', 'comparisons']:
            from scripts import comparison_history
            investigation_id = parts[2]
            try:
                if len(parts) == 3:
                    self.send_json(200, comparison_history.comparison_detail(investigation_id))
                    return
                if len(parts) == 5 and parts[3] == 'artifacts' and parts[4] in ('pdf', 'appendix'):
                    target = comparison_history.artifact(investigation_id, parts[4])
                    content = target.read_bytes()
                    content_type = 'application/pdf' if parts[4] == 'pdf' else 'text/markdown; charset=utf-8'
                    self.send_response(200)
                    self.send_header('Content-Type', content_type)
                    self.send_header('Content-Disposition', f'attachment; filename="comparison_{investigation_id}_{parts[4]}{target.suffix}"')
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Content-Length', str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                    return
                if len(parts) == 4 and parts[3] == 'serp':
                    target = comparison_history.saved_serp(investigation_id)
                    content = target.read_bytes()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Content-Disposition', f'inline; filename="comparison_{investigation_id}_serp.json"')
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Content-Length', str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                    return
            except (ValueError, FileNotFoundError, OSError, TypeError) as exc:
                self.send_json(404 if isinstance(exc, FileNotFoundError) else 400, {'error': str(exc)})
                return
            self.send_json(404, {'error': 'Unknown comparison history endpoint.'})
            return
        if len(parts) >= 4 and parts[:2] == ['api', 'investigations'] and parts[3] == 'reporting':
            investigation_id = parts[2]
            try:
                if len(parts) == 4:
                    self.send_json(200, reporting_jobs.status(investigation_id))
                    return
                if len(parts) == 6 and parts[4] == 'files' and parts[5] in ('pdf', 'appendix'):
                    target = reporting_jobs.artifact(investigation_id, parts[5])
                    content = target.read_bytes()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/pdf' if parts[5] == 'pdf' else 'text/markdown; charset=utf-8')
                    self.send_header('Content-Disposition', 'attachment; filename="' + target.name.replace('"', '') + '"')
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Content-Length', str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                    return
            except (ValueError, FileNotFoundError) as exc:
                self.send_json(404 if isinstance(exc, FileNotFoundError) else 400, {'error': str(exc)})
                return
            self.send_json(404, {'error': 'Unknown reporting endpoint.'})
            return
        if parsed_serp.path.startswith('/api/serp/jobs/'):
            job_id = parsed_serp.path.removeprefix('/api/serp/jobs/')
            from scripts.investigation_workflow import keyword_search_status
            job = keyword_search_status(job_id)
            if job is None:
                job = dashboard_serp_search.job_status(job_id)
            self.send_json(200 if job else 404, job or {'error': 'Search job not found or server restarted.'})
            return
        if parsed_serp.path == '/api/serp/snapshot':
            from urllib.parse import parse_qs
            keyword = parse_qs(parsed_serp.query).get('keyword', [''])[0]
            try:
                self.send_json(200, dashboard_serp_search.read_snapshot(keyword))
            except (ValueError, FileNotFoundError, OSError, json.JSONDecodeError) as exc:
                self.send_json(404 if isinstance(exc, FileNotFoundError) else 400, {'error': str(exc)})
            return
        if parsed_serp.path == '/api/serp/options':
            from urllib.parse import parse_qs
            keyword = parse_qs(parsed_serp.query).get('keyword', [''])[0]
            try:
                self.send_json(200, serp_investigations.selection_options(keyword))
            except (ValueError, FileNotFoundError, OSError, json.JSONDecodeError) as exc:
                self.send_json(404 if isinstance(exc, FileNotFoundError) else 400, {'error': str(exc)})
            return
        if parsed_serp.path == '/api/serp/hollywoodbets-options':
            from urllib.parse import parse_qs
            keyword = parse_qs(parsed_serp.query).get('keyword', [''])[0]
            try:
                from scripts.hollywoodbets_comparisons import selection_options
                self.send_json(200, selection_options(keyword))
            except (ValueError, FileNotFoundError, OSError, json.JSONDecodeError) as exc:
                self.send_json(404 if isinstance(exc, FileNotFoundError) else 400, {'error': str(exc)})
            return
        if parsed_serp.path.startswith('/api/investigations/') and parsed_serp.path.endswith('/offline-result'):
            try:
                investigation_id = parsed_serp.path.split('/')[-2]
                serp_investigations.read_investigation(investigation_id)
                path = serp_investigations.INVESTIGATIONS / investigation_id / 'offline_execution.json'
                if not path.is_file():
                    raise FileNotFoundError('Offline comparison has not been executed.')
                result = read_json(path)
                if isinstance(result, dict):
                    from analysis.recommendation_classification import adapt_comparison
                    if isinstance(result.get('comparison'), dict):
                        result['comparison'], audit = adapt_comparison(result['comparison'])
                        result['recommendation_classification_audit'] = audit
                    elif isinstance(result.get('recommendations'), list):
                        result, audit = adapt_comparison(result)
                        result['recommendation_classification_audit'] = audit
                self.send_json(200, result)
            except (ValueError, FileNotFoundError) as exc:
                self.send_json(404 if isinstance(exc, FileNotFoundError) else 400, {'error': str(exc)})
            return
        if parsed_serp.path.startswith('/api/investigations/') and parsed_serp.path.endswith('/report.pdf'):
            try:
                investigation_id = parsed_serp.path.split('/')[-2]
                serp_investigations.read_investigation(investigation_id)
                record = read_json(serp_investigations.INVESTIGATIONS / investigation_id / 'offline_execution.json')
                if not record or record.get('status') != 'completed' or not record.get('pdf_path'):
                    raise FileNotFoundError('Offline PDF is not available.')
                pdf = (serp_investigations.INVESTIGATIONS / investigation_id / record['pdf_path']).resolve()
                if pdf.parent != (serp_investigations.INVESTIGATIONS / investigation_id / 'results').resolve() or not pdf.is_file():
                    raise FileNotFoundError('Offline PDF is not available.')
                body = pdf.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'application/pdf')
                self.send_header('Content-Disposition', 'attachment; filename="seo_offline_aviator_report.pdf"')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers(); self.wfile.write(body)
            except (ValueError, FileNotFoundError) as exc:
                self.send_json(404 if isinstance(exc, FileNotFoundError) else 400, {'error': str(exc)})
            return
        if parsed_serp.path.startswith('/api/investigations/') and parsed_serp.path.endswith('/offline-evidence'):
            try:
                investigation_id = parsed_serp.path.split('/')[-2]
                self.send_json(200, serp_investigations.read_offline_evidence(investigation_id))
            except (ValueError, FileNotFoundError) as exc:
                self.send_json(404 if isinstance(exc, FileNotFoundError) else 400, {'error': str(exc)})
            return
        if parsed_serp.path.startswith('/api/investigations/'):
            try:
                self.send_json(200, serp_investigations.read_investigation(parsed_serp.path.split('/')[-1]))
            except (ValueError, FileNotFoundError) as exc:
                self.send_json(404 if isinstance(exc, FileNotFoundError) else 400, {'error': str(exc)})
            return
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
        parts = path.strip('/').split('/')
        if len(parts) == 5 and parts[:2] == ['api', 'investigations'] and parts[3] == 'workflow' and parts[4] in ('navigate', 'execute', 'branch'):
            try:
                origin = self.headers.get('Origin')
                if self.headers.get('Sec-Fetch-Site') == 'cross-site' or (origin and urlparse(origin).netloc != self.headers.get('Host')):
                    raise ValueError('Cross-origin workflow actions are not allowed.')
                length = int(self.headers.get('Content-Length', '0'))
                if not 1 <= length <= 8192:
                    raise ValueError('Invalid request size.')
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError('Request must be a JSON object.')
                from scripts import investigation_workflow as workflow
                if parts[4] == 'navigate':
                    result = workflow.navigate(parts[2], payload.get('direction'))
                elif parts[4] == 'execute':
                    result = workflow.execute_stage(parts[2], payload.get('stage'), refresh=payload.get('refresh', False))
                else:
                    result = workflow.branch_competitor(parts[2], payload.get('benchmark_url'))
                self.send_json(200, result)
            except RuntimeError as exc:
                self.send_json(409, {'error': str(exc)})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self.send_json(400, {'error': str(exc)})
            except FileNotFoundError as exc:
                self.send_json(404, {'error': str(exc)})
            except Exception:
                import logging
                logging.exception('Investigation workflow action failed')
                self.send_json(500, {'error': 'Workflow action failed. Review server logs.'})
            return
        if len(parts) == 6 and parts[:2] == ['api', 'investigations'] and parts[3:] == ['workflow', 'collection', 'execute']:
            try:
                origin = self.headers.get('Origin')
                if self.headers.get('Sec-Fetch-Site') == 'cross-site' or (origin and urlparse(origin).netloc != self.headers.get('Host')):
                    raise ValueError('Cross-origin collection actions are not allowed.')
                length = int(self.headers.get('Content-Length', '0'))
                if not 1 <= length <= 8192:
                    raise ValueError('Invalid request size.')
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError('Request must be a JSON object.')
                from scripts import investigation_workflow as workflow
                result = workflow.collect_evidence(parts[2],
                    collectors=payload.get('collectors', []),
                    authorize_paid_dataforseo=payload.get('authorize_paid_dataforseo', False),
                    authorize_external_page_requests=payload.get('authorize_external_page_requests', False),
                    refresh=payload.get('refresh', False))
                self.send_json(200, result)
            except Exception as exc:
                from scripts.investigation_collection import CollectionAuthorizationRequired
                if isinstance(exc, CollectionAuthorizationRequired):
                    self.send_json(403, {'error': str(exc), 'plan': exc.plan})
                elif isinstance(exc, RuntimeError):
                    self.send_json(409, {'error': str(exc)})
                elif isinstance(exc, (ValueError, TypeError, json.JSONDecodeError)):
                    self.send_json(400, {'error': str(exc)})
                elif isinstance(exc, FileNotFoundError):
                    self.send_json(404, {'error': str(exc)})
                else:
                    import logging
                    logging.exception('Evidence collection action failed')
                    self.send_json(500, {'error': 'Evidence collection failed. Review server logs.'})
            return
        if len(parts) in (4, 5) and parts[:2] == ['api', 'investigations'] and parts[3] == 'reporting':
            try:
                origin = self.headers.get('Origin')
                if self.headers.get('Sec-Fetch-Site') == 'cross-site' or (origin and urlparse(origin).netloc != self.headers.get('Host')):
                    raise ValueError('Cross-origin reporting actions are not allowed.')
                length = int(self.headers.get('Content-Length', '0'))
                if length < 0 or length > 4096:
                    raise ValueError('Invalid request size.')
                if length:
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict):
                        raise ValueError('Request must be an object.')
                if len(parts) == 4:
                    result = reporting_jobs.start(parts[2])
                    self.send_json(202, result)
                elif parts[4] == 'approve':
                    self.send_json(200, reporting_jobs.approve(parts[2]))
                else:
                    self.send_json(404, {'error': 'Unknown reporting action.'})
            except RuntimeError as exc:
                self.send_json(409, {'error': str(exc)})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self.send_json(400, {'error': str(exc)})
            except FileNotFoundError as exc:
                self.send_json(404, {'error': str(exc)})
            except Exception:
                import logging
                logging.exception('Reporting job error')
                self.send_json(500, {'error': 'Reporting action failed. Review server logs.'})
            return
        if path == '/api/serp/search':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 1 <= length <= 4096:
                    raise ValueError('Invalid request size.')
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError('Request must be a JSON object.')
                from scripts.investigation_workflow import start_keyword_search
                result = start_keyword_search(payload.get('keyword'), payload.get('depth', 20))
                self.send_json(202, result)
            except RuntimeError as exc:
                self.send_json(409, {'error': str(exc)})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self.send_json(400, {'error': str(exc)})
            return
        if path == '/api/investigations/hollywoodbets-compare':
            try:
                origin = self.headers.get('Origin')
                if self.headers.get('Sec-Fetch-Site') == 'cross-site' or (origin and urlparse(origin).netloc != self.headers.get('Host')):
                    raise ValueError('Cross-origin comparison actions are not allowed.')
                length = int(self.headers.get('Content-Length', '0'))
                if not 1 <= length <= 8192:
                    raise ValueError('Invalid request size.')
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError('Request must be a JSON object.')
                from scripts.hollywoodbets_comparisons import create_comparison
                result = create_comparison(keyword=payload.get('keyword'),
                    snapshot_sha256=payload.get('snapshot_sha256'),
                    primary_url=payload.get('primary_url'),
                    competitor_url=payload.get('competitor_url'),
                    idempotency_key=payload.get('idempotency_key'),
                    parent_investigation_id=payload.get('parent_investigation_id'))
                self.send_json(200 if result.get('idempotent_replay') else 201, result)
            except RuntimeError as exc:
                self.send_json(409, {'error': str(exc)})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self.send_json(400, {'error': str(exc)})
            except FileNotFoundError as exc:
                self.send_json(404, {'error': str(exc)})
            except Exception:
                import logging
                logging.exception('Hollywoodbets comparison creation failed')
                self.send_json(500, {'error': 'Comparison could not be created. Review server logs.'})
            return
        if path.startswith('/api/investigations/') and path.endswith('/run-offline'):
            try:
                from scripts.run_investigation_offline import run
                investigation_id = path.split('/')[-2]
                result = run(investigation_id)
                self.send_json(200, result)
            except (ValueError, FileNotFoundError) as exc:
                self.send_json(400, {'error': str(exc)})
            except Exception as exc:
                # Do not disclose internal paths or credentials to the browser.
                import logging
                logging.exception('Offline investigation execution failed')
                self.send_json(500, {'error': 'Offline processing failed. Review server logs.'})
            return
        if path == '/api/investigations/manual':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 1 <= length <= 8192:
                    raise ValueError('Invalid request size.')
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError('Request must be a JSON object.')
                result = serp_investigations.create_page_investigation(
                    payload.get('keyword'), payload.get('ours_url'),
                    payload.get('benchmark_url'), payload.get('snapshot_fingerprint'))
                self.send_json(201, result)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self.send_json(400, {'error': str(exc)})
            except FileNotFoundError as exc:
                self.send_json(404, {'error': str(exc)})
            return
        if path == '/api/investigations':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 1 <= length <= 4096:
                    raise ValueError('Invalid request size.')
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError('Request must be an object.')
                result = serp_investigations.create_investigation(
                    payload.get('keyword'), payload.get('ours'),
                    payload.get('benchmark'), payload.get('snapshot_fingerprint'))
                self.send_json(201, result)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self.send_json(400, {'error': str(exc)})
            except FileNotFoundError as exc:
                self.send_json(404, {'error': str(exc)})
            return
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
