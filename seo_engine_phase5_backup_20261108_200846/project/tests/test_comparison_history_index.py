"""Integrity and lifecycle tests for the rebuildable Comparison History index."""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen

import pytest

from scripts import comparison_history
from test_comparison_history import _create, _json, _server


def _store(tmp_path):
    root = tmp_path / "data" / "investigations"
    root.mkdir(parents=True)
    return root


def _checkpoint(base):
    path = base / "workflow" / "checkpoint.json"
    return path, json.loads(path.read_text(encoding="utf-8"))


def _save_comparison_and_pin(base, comparison):
    path = base / "results" / "garden-irrigation_comparison.json"
    _json(path, comparison)
    checkpoint_path, checkpoint = _checkpoint(base)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    for stage in ("recommendation_generation", "validation_classification"):
        for output in checkpoint["stages"][stage]["outputs"]:
            if output["path"] == "results/garden-irrigation_comparison.json":
                output["sha256"] = digest
    _json(checkpoint_path, checkpoint)


def test_warm_history_uses_metadata_only_and_keeps_search_sort_page_contract(tmp_path, monkeypatch):
    root = _store(tmp_path)
    _create(root, "1" * 32)
    _create(root, "2" * 32, keyword="mortgage calculator", competitor="finance.example")

    first = comparison_history.history(root=root, page_size=1, sort="keyword")
    assert first["total"] == 2 and first["comparisons"][0]["keyword"] == "garden irrigation"
    index_path = comparison_history._index_path(root)
    assert index_path.is_file()
    with sqlite3.connect(index_path) as db:
        payloads = [row[0] for row in db.execute("SELECT summary_json FROM comparison_history_entries")]
    assert all('"recommendations":' not in payload for payload in payloads)

    def should_not_load(*args, **kwargs):
        raise AssertionError("Warm listing reopened validated recommendation details")

    monkeypatch.setattr(comparison_history, "_load", should_not_load)
    warm = comparison_history.history(root=root, keyword="mortgage", page=1, page_size=1)
    assert warm["total"] == 1 and warm["comparisons"][0]["keyword"] == "mortgage calculator"
    assert comparison_history.history(root=root, url="https://hollywoodbets.net/garden-irrigation")["total"] == 1


def test_new_investigation_and_incomplete_to_valid_transition_are_discovered(tmp_path):
    root = _store(tmp_path)
    _create(root, "1" * 32)
    assert comparison_history.history(root=root)["total"] == 1

    _create(root, "2" * 32, keyword="mortgage calculator")
    assert comparison_history.history(root=root)["total"] == 2

    incomplete = _create(root, "3" * 32, keyword="newly validated topic")
    checkpoint_path, checkpoint = _checkpoint(incomplete)
    checkpoint["stages"]["validation_classification"]["status"] = "running"
    _json(checkpoint_path, checkpoint)
    assert comparison_history.history(root=root, keyword="newly validated topic")["total"] == 0

    checkpoint["stages"]["validation_classification"]["status"] = "completed"
    _json(checkpoint_path, checkpoint)
    result = comparison_history.history(root=root, keyword="newly validated topic")
    assert result["total"] == 1 and result["comparisons"][0]["investigation_id"] == "3" * 32


def test_stale_authoritative_hash_invalidates_then_rebuilds_index(tmp_path):
    root = _store(tmp_path)
    base = _create(root, "1" * 32)
    original = (base / "results" / "garden-irrigation_comparison.json").read_bytes()
    assert comparison_history.history(root=root)["total"] == 1

    (base / "results" / "garden-irrigation_comparison.json").write_text("{corrupted", encoding="utf-8")
    assert comparison_history.history(root=root)["total"] == 0

    (base / "results" / "garden-irrigation_comparison.json").write_bytes(original)
    assert comparison_history.history(root=root)["total"] == 1


def test_failed_evidence_collection_is_not_exposed_as_completed_history(tmp_path):
    root = _store(tmp_path)
    base = _create(root, "1" * 32)
    checkpoint_path, checkpoint = _checkpoint(base)
    checkpoint["stages"]["evidence_collection"] = {"status": "failed"}
    _json(checkpoint_path, checkpoint)
    assert comparison_history.history(root=root)["total"] == 0


@pytest.mark.parametrize("corruption", ["missing_recommendations", "duplicate_recommendation_ids"])
def test_missing_or_duplicate_recommendation_records_are_excluded(tmp_path, corruption):
    root = _store(tmp_path)
    base = _create(root, "1" * 32)
    path = base / "results" / "garden-irrigation_comparison.json"
    comparison = json.loads(path.read_text(encoding="utf-8"))
    if corruption == "missing_recommendations":
        comparison["recommendations"] = []
    else:
        comparison["recommendations"][1]["id"] = comparison["recommendations"][0]["id"]
    _save_comparison_and_pin(base, comparison)
    assert comparison_history.history(root=root)["total"] == 0


def test_malformed_investigation_identity_is_excluded_and_repaired_record_returns(tmp_path):
    root = _store(tmp_path)
    base = _create(root, "1" * 32)
    selection_path = base / "selection.json"
    original = selection_path.read_bytes()
    selection = json.loads(original)
    selection["keyword"] = {"unexpected": "object"}
    _json(selection_path, selection)
    assert comparison_history.history(root=root)["total"] == 0
    selection_path.write_bytes(original)
    assert comparison_history.history(root=root)["total"] == 1


def test_duplicate_folder_identity_is_rejected(tmp_path):
    root = _store(tmp_path)
    _create(root, "1" * 32)
    duplicate = _create(root, "2" * 32, keyword="duplicate identity")
    selection_path = duplicate / "selection.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    selection["investigation_id"] = "1" * 32
    _json(selection_path, selection)
    result = comparison_history.history(root=root)
    assert result["total"] == 1
    assert result["comparisons"][0]["investigation_id"] == "1" * 32


def test_equal_timestamp_sorting_has_stable_id_tiebreakers(tmp_path):
    root = _store(tmp_path)
    _create(root, "2" * 32, keyword="same keyword", competitor="same.example")
    _create(root, "1" * 32, keyword="same keyword", competitor="same.example")
    expected = {
        "recent": ["2" * 32, "1" * 32],
        "oldest": ["1" * 32, "2" * 32],
        "keyword": ["1" * 32, "2" * 32],
        "competitor": ["1" * 32, "2" * 32],
    }
    for sort, ids in expected.items():
        first = comparison_history.history(root=root, sort=sort, page_size=10)
        second = comparison_history.history(root=root, sort=sort, page_size=10)
        assert [row["investigation_id"] for row in first["comparisons"]] == ids
        assert [row["investigation_id"] for row in second["comparisons"]] == ids


def test_index_entry_tampering_is_revalidated_from_authoritative_store(tmp_path):
    root = _store(tmp_path)
    _create(root, "1" * 32)
    assert comparison_history.history(root=root)["total"] == 1
    index_path = comparison_history._index_path(root)
    with sqlite3.connect(index_path) as db:
        db.execute("UPDATE comparison_history_entries SET summary_json = '{}' WHERE investigation_id = ?",
                   ("1" * 32,))
    result = comparison_history.history(root=root)
    assert result["total"] == 1
    assert result["comparisons"][0]["keyword"] == "garden irrigation"


def test_corrupt_index_database_is_quarantined_and_rebuilt(tmp_path):
    root = _store(tmp_path)
    _create(root, "1" * 32)
    assert comparison_history.history(root=root)["total"] == 1
    index_path = comparison_history._index_path(root)
    index_path.write_bytes(b"not a sqlite database")
    result = comparison_history.history(root=root)
    assert result["total"] == 1
    assert list(index_path.parent.glob(index_path.name + ".corrupt-*"))


def test_deleted_investigation_is_removed_from_index(tmp_path):
    root = _store(tmp_path)
    base = _create(root, "1" * 32)
    assert comparison_history.history(root=root)["total"] == 1
    shutil.rmtree(base)
    assert comparison_history.history(root=root)["total"] == 0
    with sqlite3.connect(comparison_history._index_path(root)) as db:
        assert db.execute("SELECT COUNT(*) FROM comparison_history_entries").fetchone()[0] == 0


def test_parallel_history_requests_build_and_read_index_safely(tmp_path):
    root = _store(tmp_path)
    for i in range(1, 11):
        _create(root, f"{i:032x}", keyword=f"parallel topic {i}")
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _i: comparison_history.history(root=root, page_size=5), range(12)))
    assert all(result["total"] == 10 and len(result["comparisons"]) == 5 for result in results)


def test_invalid_report_hash_refreshes_availability_without_hiding_recommendations(tmp_path):
    root = _store(tmp_path)
    base = _create(root, "1" * 32)
    assert comparison_history.history(root=root)["comparisons"][0]["has_pdf"] is True
    pdf = base / "results" / "garden-irrigation_executive_report.pdf"
    pdf.write_bytes(b"%PDF-tampered")
    updated = comparison_history.history(root=root)
    assert updated["total"] == 1 and updated["comparisons"][0]["has_pdf"] is False
    with pytest.raises(FileNotFoundError):
        comparison_history.artifact("1" * 32, "pdf", root=root)


def test_dashboard_restart_reopens_persisted_index_and_detail(tmp_path, monkeypatch):
    root = _store(tmp_path)
    _create(root, "1" * 32)
    for _restart in range(2):
        with _server(monkeypatch, root) as base:
            with urlopen(base + "/api/comparisons/history", timeout=5) as response:
                history = json.loads(response.read().decode("utf-8"))
            assert history["total"] == 1
            with urlopen(base + f"/api/comparisons/{'1' * 32}", timeout=5) as response:
                detail = json.loads(response.read().decode("utf-8"))
            assert detail["recommendation_count"] == 3
            assert detail["tier_1_count"] == 2 and detail["tier_2_count"] == 1
