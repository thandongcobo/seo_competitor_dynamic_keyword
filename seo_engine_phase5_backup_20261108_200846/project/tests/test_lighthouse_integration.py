import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from normalization.lighthouse import normalize_lighthouse
from scripts.collect_lighthouse import build_command, run_audit

URL = "https://www.hollywoodbets.net/aviator"


def audit(url=URL):
    return {
        "lighthouseVersion": "13.5.0", "requestedUrl": url, "finalDisplayedUrl": url,
        "fetchTime": "2026-10-12T08:00:00Z",
        "categories": {"performance": {"score": 0.8}, "seo": {"score": 0.95}},
        "audits": {"largest-contentful-paint": {"numericValue": 2250},
                   "cumulative-layout-shift": {"numericValue": 0.03}},
    }


def test_build_command_dynamic_url(tmp_path):
    cmd = build_command("https://example.com/roulette", tmp_path / "audit.json", device="desktop")
    assert "https://example.com/roulette" in cmd
    assert "--preset=desktop" in cmd
    assert "--output=json" in cmd
    assert "--only-categories=performance,accessibility,best-practices,seo" in cmd
    assert "--preset=desktop" not in build_command(URL, tmp_path / "m.json", device="mobile")


def test_normalize_lighthouse_valid():
    row = normalize_lighthouse(audit(), keyword="aviator", side="ours", device="mobile", ranking_url=URL)
    assert row["status"] == "usable"
    assert row["scores"]["performance"] == 80
    assert row["scores"]["seo"] == 95
    assert row["lab_metrics"]["largest_contentful_paint_ms"] == 2250
    assert row["target_verified"] is True


def test_reject_redirect_or_wrong_target():
    row = normalize_lighthouse(audit("https://example.com/roulette"), keyword="aviator", side="ours", device="mobile", ranking_url=URL)
    assert row["status"] == "unusable"
    assert not row["target_verified"]
    redirected = audit()
    redirected["finalDisplayedUrl"] = "https://www.hollywoodbets.net/"
    row = normalize_lighthouse(redirected, keyword="aviator", side="ours", device="mobile", ranking_url=URL)
    assert row["status"] == "unusable"
    assert not row["final_url_verified"]


def test_missing_scores_are_none_not_zero():
    data = audit()
    data["categories"] = {}
    row = normalize_lighthouse(data, keyword="aviator", side="ours", device="mobile", ranking_url=URL)
    assert row["status"] == "unusable"
    assert row["scores"]["performance"] is None


def test_dry_run_does_not_invoke_npx(tmp_path, monkeypatch):
    import scripts.collect_lighthouse as collector
    monkeypatch.setattr(collector, "RAW_DIR", tmp_path)
    monkeypatch.setattr(collector, "require_target", lambda side, engine: {"ranking_url": URL})
    def never(*args, **kwargs):
        raise AssertionError("dry run must not run Lighthouse")
    monkeypatch.setattr(collector.subprocess, "run", never)
    path = run_audit("ours", "mobile", execute=False, refresh=False, timeout=60)
    assert not path.exists()


def test_exec_uses_serp_url_and_caches(tmp_path, monkeypatch):
    import scripts.collect_lighthouse as collector
    monkeypatch.setattr(collector, "RAW_DIR", tmp_path)
    monkeypatch.setattr(collector, "require_target", lambda side, engine: {"ranking_url": URL})
    calls = []
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        output = next(a.split("=", 1)[1] for a in cmd if a.startswith("--output-path="))
        Path(output).write_text(json.dumps(audit()), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(collector.subprocess, "run", fake_run)
    output = run_audit("ours", "mobile", execute=True, refresh=False, timeout=60)
    assert output.exists()
    assert len(calls) == 1
    run_audit("ours", "mobile", execute=True, refresh=False, timeout=60)
    assert len(calls) == 1
    monkeypatch.setattr(collector, "require_target", lambda side, engine: {"ranking_url": "https://example.com/roulette"})
    with pytest.raises(RuntimeError, match="another URL"):
        run_audit("ours", "mobile", execute=True, refresh=False, timeout=60)
