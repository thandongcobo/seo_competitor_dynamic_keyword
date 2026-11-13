import hashlib
import json
import threading
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

import pytest

from scripts import comparison_history, serve_dashboard, serp_investigations


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _recommendation(ident, tier, url):
    return {
        "id": ident, "title": f"Improve {ident}", "target_url": url,
        "evidence": f"Captured page evidence supports improve {ident}.",
        "interpretation": "The change may improve clarity and discoverability.",
        "action_justification": "The recorded action follows the captured evidence.",
        "display_action": "Update the identified page element and verify the rendered result.",
        "actions": [f"Update the identified element on {url}; recapture this exact URL to verify."],
        "success_check": "Confirm the revised element in a fresh exact-page capture.",
        "evidence_provenance": {"source": "archived exact-page evidence", "target_url": url,
                                "benchmark_url": "https://competitor.example/example",
                                "evidence_ids": [f"EV-{ident}"]},
        "limitations": "The destination section is not verified and needs review before editing."
            if tier == "tier_2_moderate_evidence" else "",
        "validation_status": "validated_rule_evidence", "recovery_status": "not_required",
        "evidence_tier": tier, "priority_score": 9,
        "action_composition": {"proposed_copy": {"candidate": "Grounded page improvement",
            "status": "proposed_not_observed", "validation": {"grounded": True},
            "source_evidence_ids": [f"EV-{ident}"]}},
    }


def _historical_record(root, ident="a" * 32):
    base = root / ident
    ours = {"domain": "hollywoodbets.net", "url": "https://www.hollywoodbets.net/example", "rank": 2}
    benchmark = {"domain": "competitor.example", "url": "https://competitor.example/example", "rank": 1}
    selection = {"investigation_id": ident, "record_type": "historical_comparison_import",
        "source_investigation_id": "b" * 32, "keyword": "example keyword", "created_at": "2026-01-01T00:00:00+00:00",
        "source": "historical_import", "historical_record": True, "serp_sha256": "c" * 64,
        "serp_snapshot_reference": "evidence/original_serp_snapshot.json",
        "ours": ours, "benchmark": benchmark}
    rows = [_recommendation("tier-one", "tier_1_strong_evidence", ours["url"]),
            _recommendation("tier-two", "tier_2_moderate_evidence", ours["url"])]
    comparison = {"keyword": selection["keyword"],
        "primary_ranking_urls": {"ours": ours["url"], "benchmark": benchmark["url"]},
        "recommendations": rows}
    comparison_rel = "results/example-comparison.json"
    pdf_rel, appendix_rel = "results/report.pdf", "results/appendix.md"
    snapshot_rel, evidence_rel = "evidence/original_serp_snapshot.json", "evidence/source.json"
    comparison_path = base / comparison_rel
    _write(comparison_path, comparison)
    pdf = base / pdf_rel; pdf.parent.mkdir(parents=True, exist_ok=True); pdf.write_bytes(b"%PDF-1.4\nfixture")
    appendix = base / appendix_rel; appendix.write_text("# Historical appendix\n", encoding="utf-8")
    snapshot = {"keyword": "example keyword", "organic_results": []}
    _write(base / snapshot_rel, snapshot)
    selection["serp_sha256"] = _sha(base / snapshot_rel)
    _write(base / evidence_rel, {"source": "saved"})
    _write(base / "selection.json", selection)
    source_selection = {**selection, "investigation_id": "b" * 32, "record_type": "canonical_source"}
    _write(base / "source_selection.json", source_selection)
    accepted = comparison_history._validated_recommendations(comparison)
    tier_counts = {"tier_1_strong_evidence": 1, "tier_2_moderate_evidence": 1}
    offline = {"investigation_id": ident, "source_investigation_id": "b" * 32,
        "record_type": "historical_comparison_import", "keyword": selection["keyword"],
        "status": "completed", "processing_status": "completed", "report_status": "completed",
        "selected_pages": {"ours": ours, "benchmark": benchmark}, "completed_at": "2026-01-02T00:00:00+00:00",
        "comparison_path": comparison_rel, "pdf_path": pdf_rel, "technical_appendix_path": appendix_rel,
        "report_artifact_sha256": {"pdf": _sha(pdf), "appendix": _sha(appendix)}}
    _write(base / "offline_execution.json", offline)
    replay_execution_rel = "source_replay_execution.json"
    _write(base / replay_execution_rel, {"investigation_id": "b" * 32, "status": "completed"})
    files = []
    for rel in (comparison_rel, pdf_rel, appendix_rel, snapshot_rel, evidence_rel,
                "selection.json", "source_selection.json", "offline_execution.json", replay_execution_rel):
        files.append({"path": rel, "sha256": _sha(base / rel)})
    registration = {"record_type": "historical_comparison_import", "investigation_id": ident,
        "source_investigation_id": "b" * 32, "registered_at": "2026-01-02T00:00:00+00:00",
        "source_replay_execution_archive_path": replay_execution_rel,
        "source_replay_execution_sha256": _sha(base / replay_execution_rel),
        "source_selection_sha256": _sha(base / "source_selection.json"),
        "source_comparison_sha256": _sha(base / comparison_rel),
        "source_report_sha256": {"pdf": _sha(pdf), "appendix": _sha(appendix)},
        "archive_files": files,
        "evidence_source_references": [{"source_path": "data/raw/example.json", "archive_path": evidence_rel,
                                        "sha256": _sha(base / evidence_rel)}],
        "validation_summary": {"validated_recommendation_count": len(accepted),
            "validated_recommendation_ids": [row["id"] for row in accepted], "tier_counts": tier_counts}}
    _write(base / "historical_registration.json", registration)
    return base


@contextmanager
def _server(monkeypatch, root):
    monkeypatch.setattr(serp_investigations, "INVESTIGATIONS", root)
    monkeypatch.setattr(comparison_history.serp_investigations, "INVESTIGATIONS", root)
    server = ThreadingHTTPServer(("127.0.0.1", 0), serve_dashboard.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown(); thread.join(timeout=2); server.server_close()


def test_historical_record_is_listed_and_loaded_without_normal_checkpoints(tmp_path):
    root = tmp_path / "investigations"; root.mkdir()
    base = _historical_record(root)
    detail = comparison_history.comparison_detail(base.name, root=root)
    assert detail["is_historical"] is True
    assert detail["source_investigation_id"] == "b" * 32
    assert detail["recommendation_count"] == 2
    assert detail["tier_1_count"] == detail["tier_2_count"] == 1
    assert [row["id"] for row in detail["recommendations"]] == ["tier-one", "tier-two"]
    assert comparison_history.history(root=root, keyword="example keyword")["total"] == 1


def test_historical_dashboard_api_serves_recommendations_and_reports(tmp_path, monkeypatch):
    root = tmp_path / "investigations"; root.mkdir()
    base = _historical_record(root)
    with _server(monkeypatch, root) as url:
        history = json.loads(urlopen(url + "/api/comparisons/history?keyword=example%20keyword").read())
        assert history["total"] == 1 and history["comparisons"][0]["is_historical"] is True
        detail = json.loads(urlopen(url + f"/api/comparisons/{base.name}").read())
        assert [row["id"] for row in detail["recommendations"]] == ["tier-one", "tier-two"]
        with urlopen(url + f"/api/comparisons/{base.name}/artifacts/pdf") as response:
            assert response.headers["Content-Type"] == "application/pdf"
            assert response.read().startswith(b"%PDF-")
        with urlopen(url + f"/api/comparisons/{base.name}/artifacts/appendix") as response:
            assert b"Historical appendix" in response.read()


def test_historical_evidence_tampering_removes_record_from_history(tmp_path):
    root = tmp_path / "investigations"; root.mkdir()
    base = _historical_record(root)
    evidence = base / "evidence/source.json"
    evidence.write_text('{"tampered": true}', encoding="utf-8")
    with pytest.raises(ValueError, match="integrity"):
        comparison_history.comparison_detail(base.name, root=root)
    assert comparison_history.history(root=root, keyword="example keyword")["total"] == 0
