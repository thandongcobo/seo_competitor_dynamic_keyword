from __future__ import annotations

import hashlib
import json

from scripts import investigation_workflow as workflow


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_completed_search_checkpoint_recovers_exact_archived_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, "ROOT", tmp_path)
    ident = "a" * 32
    base = tmp_path / "data" / "investigations" / ident
    archive = tmp_path / "data" / "raw" / "serp" / "archive" / "keyword_20261110.json"
    original = {"keyword": "lucky numbers", "datetime": "2026-11-09T12:49:17.941502+00:00",
                "organic_results": [{"rank_group": 1, "url": "https://example.test/"}]}
    raw = json.dumps(original).encode()
    archive.parent.mkdir(parents=True)
    archive.write_bytes(raw)
    expected = hashlib.sha256(raw).hexdigest()
    _write_json(base / "selection.json", {"keyword": "lucky numbers", "serp_sha256": expected,
                                           "serp_collected_at": original["datetime"]})
    current = tmp_path / "data" / "raw" / "serp" / "lucky_numbers.json"
    current.parent.mkdir(parents=True, exist_ok=True)
    current.write_text('{"keyword":"lucky numbers","organic_results":[]}', encoding="utf-8")
    output = {"path": "data/raw/serp/lucky_numbers.json", "scope": "workspace", "sha256": expected}

    assert workflow._invalid_outputs([output], base) == []
    assert output["path"] == "data/raw/serp/archive/keyword_20261110.json"
    assert output["recovered_from"] == "data/raw/serp/lucky_numbers.json"
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected
    assert current.read_text(encoding="utf-8") == '{"keyword":"lucky numbers","organic_results":[]}'


def test_archived_serp_with_wrong_identity_is_not_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, "ROOT", tmp_path)
    ident = "b" * 32
    base = tmp_path / "data" / "investigations" / ident
    archive = tmp_path / "data" / "raw" / "serp" / "archive" / "wrong_keyword.json"
    snapshot = {"keyword": "different keyword", "datetime": "2026-11-09T12:49:17.941502+00:00"}
    _write_json(archive, snapshot)
    raw = archive.read_bytes()
    expected = hashlib.sha256(raw).hexdigest()
    _write_json(base / "selection.json", {"keyword": "lucky numbers", "serp_sha256": expected,
                                           "serp_collected_at": snapshot["datetime"]})
    output = {"path": "data/raw/serp/lucky_numbers.json", "scope": "workspace", "sha256": expected}

    assert workflow._invalid_outputs([output], base) == [output]
    assert output["path"] == "data/raw/serp/lucky_numbers.json"
