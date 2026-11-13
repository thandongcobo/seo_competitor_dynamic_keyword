"""Safely register an already completed replay in canonical Comparison History."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

from config.settings import ROOT
from scripts import comparison_history, serp_investigations
from scripts.dashboard_serp_search import _snapshot_path


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path.name}.")
    return value


def _safe_source(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute():
        raise ValueError("Historical source references must be relative to the engine root.")
    path = (root / candidate).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("Historical source reference escapes the engine root.") from exc
    if not path.is_file():
        raise FileNotFoundError(f"Historical source artifact is unavailable: {relative}")
    return path


def _copy(source: Path, staging: Path, relative: str, archive_files: list[dict]) -> Path:
    target = staging / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    digest = _sha(target)
    if digest != _sha(source):
        raise ValueError(f"Copied historical artifact failed hash verification: {relative}")
    archive_files.append({"path": relative.replace("\\", "/"), "sha256": digest})
    return target


def _copy_tree(source: Path, staging: Path, relative_root: str,
               archive_files: list[dict]) -> None:
    if not source.is_dir():
        raise FileNotFoundError(f"Historical output directory is unavailable: {source}")
    for item in sorted(source.rglob("*")):
        if not item.is_file():
            continue
        rel = (Path(relative_root) / item.relative_to(source)).as_posix()
        _copy(item, staging, rel, archive_files)


def _prior_version(source_base: Path, staging: Path, archive_files: list[dict]) -> dict | None:
    """Preserve the existing five-row legacy output without promoting it."""
    canonical = source_base / "results" / "aviator_comparison.json"
    if not canonical.is_file():
        return None
    prior = _read(canonical)
    path = "historical_versions/prior_canonical_comparison.json"
    _copy(canonical, staging, path, archive_files)
    rows = prior.get("recommendations") if isinstance(prior.get("recommendations"), list) else []
    status = {
        "path": path,
        "source_path": str(canonical.relative_to(ROOT)).replace("\\", "/"),
        "source_sha256": _sha(canonical),
        "version_status": "superseded_prior_canonical_record",
        "user_facing_status": "Not shown as the current validated recommendation set.",
        "recommendation_count": len(rows),
        "recommendations": [
            {"id": row.get("id"), "validation_status": row.get("validation_status") or "not_recorded_in_source",
             "evidence_tier": row.get("evidence_tier") or "not_recorded_in_source",
             "status": "superseded_prior_version"}
            for row in rows if isinstance(row, dict)
        ],
        "note": "Original bytes preserved. Missing validation and tier fields remain unasserted.",
    }
    status_path = "historical_versions/prior_canonical_version_status.json"
    status_file = staging / status_path
    status_file.parent.mkdir(parents=True, exist_ok=True)
    status_file.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    archive_files.append({"path": status_path, "sha256": _sha(status_file)})
    return status


def register_historical_comparison(source_investigation_id: str, replay_directory: str | Path,
                                  *, archive_id: str | None = None) -> dict:
    """Register a hash-verified offline replay as a separate canonical record.

    No collector, model, recommendation generator, or classifier is run. The
    saved recommendation validation/classification fields are checked using
    the same Comparison History adapter used by the normal dashboard.
    """
    source_base = serp_investigations.INVESTIGATIONS / source_investigation_id
    source_selection_path = source_base / "selection.json"
    source_execution_path = source_base / "offline_execution.json"
    if not source_selection_path.is_file() or not source_execution_path.is_file():
        raise FileNotFoundError("The canonical source investigation is incomplete.")
    source_selection = _read(source_selection_path)
    if source_selection.get("investigation_id") != source_investigation_id:
        raise ValueError("Canonical source selection identity mismatch.")

    replay = Path(replay_directory).resolve()
    permitted = (ROOT / "output" / "architecture_phase4_3A").resolve()
    try:
        replay.relative_to(permitted)
    except ValueError as exc:
        raise ValueError("Replay directory must be within output/architecture_phase4_3A.") from exc
    replay_execution_path = replay / "offline_execution.json"
    replay_execution = _read(replay_execution_path)
    if replay_execution.get("investigation_id") != source_investigation_id:
        raise ValueError("Replay execution does not match the source investigation ID.")
    if replay_execution.get("status") != "completed" or replay_execution.get("processing_status") != "completed":
        raise ValueError("Only a completed historical replay can be registered.")
    if replay_execution.get("requests_made") != 0 or replay_execution.get("llm_inference_requests") != 0:
        raise ValueError("The selected replay is not a zero-request offline execution.")

    keyword = source_selection.get("keyword")
    pages = {side: source_selection.get(side) or {} for side in ("ours", "benchmark")}
    selected_pages = replay_execution.get("selected_pages") or {}
    if (not isinstance(keyword, str) or replay_execution.get("keyword", "").casefold() != keyword.casefold() or
            any(not pages[side].get("url") or selected_pages.get(side, {}).get("url") != pages[side]["url"]
                for side in pages)):
        raise ValueError("Replay keyword or exact selected webpage identity differs from the canonical source.")

    comparison_rel = str(replay_execution.get("comparison_path") or "").replace("\\", "/")
    pdf_rel = str(replay_execution.get("pdf_path") or "").replace("\\", "/")
    appendix_rel = str(replay_execution.get("technical_appendix_path") or "").replace("\\", "/")
    if not comparison_rel.startswith("results/") or not pdf_rel.startswith("results/") or not appendix_rel.startswith("results/"):
        raise ValueError("Replay report references are missing or outside its results directory.")
    comparison_source = (replay / comparison_rel).resolve()
    pdf_source = (replay / pdf_rel).resolve()
    appendix_source = (replay / appendix_rel).resolve()
    for path in (comparison_source, pdf_source, appendix_source):
        try:
            path.relative_to(replay)
        except ValueError as exc:
            raise ValueError("Replay report reference escapes its replay directory.") from exc
        if not path.is_file():
            raise FileNotFoundError("A required replay report artifact is missing.")
    expected_reports = replay_execution.get("report_artifact_sha256") or {}
    if (_sha(pdf_source) != expected_reports.get("pdf") or _sha(appendix_source) != expected_reports.get("appendix") or
            pdf_source.read_bytes()[:5] != b"%PDF-"):
        raise ValueError("Replay management PDF or technical appendix failed its saved hash check.")

    comparison = _read(comparison_source)
    if (str(comparison.get("keyword") or "").casefold() != keyword.casefold() or
            (comparison.get("primary_ranking_urls") or {}).get("ours") != pages["ours"].get("url") or
            (comparison.get("primary_ranking_urls") or {}).get("benchmark") != pages["benchmark"].get("url")):
        raise ValueError("Replay recommendations do not match the saved keyword and exact pages.")
    accepted = comparison_history._validated_recommendations(comparison)
    if len(accepted) != 9:
        raise ValueError(f"Expected nine saved validated recommendations; found {len(accepted)}.")
    tier_counts = {tier: sum(row.get("evidence_tier") == tier for row in accepted)
                   for tier in ("tier_1_strong_evidence", "tier_2_moderate_evidence")}
    if tier_counts != {"tier_1_strong_evidence": 3, "tier_2_moderate_evidence": 6}:
        raise ValueError(f"Replay recommendation tier counts failed validation: {tier_counts}.")
    recommendation_ids = [row["id"] for row in accepted]
    for row in accepted:
        if not str(row.get("validation_status") or "").casefold().startswith("validated"):
            raise ValueError(f"Recommendation {row['id']} lacks a saved passed validation status.")

    provenance = replay_execution.get("source_provenance")
    if not isinstance(provenance, list) or len(provenance) < 12:
        raise ValueError("Replay source evidence provenance is incomplete.")
    evidence_inputs: list[tuple[str, str, str]] = []
    for index, row in enumerate(provenance):
        if not isinstance(row, dict) or not isinstance(row.get("raw_file"), str):
            raise ValueError("Replay source evidence reference is malformed.")
        source = _safe_source(ROOT, row["raw_file"])
        digest = row.get("sha256")
        if not isinstance(digest, str) or _sha(source) != digest:
            raise ValueError(f"Replay source evidence hash mismatch: {row['raw_file']}")
        evidence_inputs.append((row["raw_file"], str(row.get("normalized_file") or source.name), digest))

    serp_snapshot = _snapshot_path(keyword)
    serp_hash = source_selection.get("serp_sha256")
    if not serp_hash or not serp_snapshot.is_file() or _sha(serp_snapshot) != serp_hash:
        raise ValueError("The original SERP snapshot identity is missing or has changed.")
    snapshot = _read(serp_snapshot)
    if snapshot.get("keyword", "").casefold() != keyword.casefold():
        raise ValueError("The original SERP snapshot keyword does not match the source investigation.")
    for side in ("ours", "benchmark"):
        exact = next((row for row in snapshot.get("organic_results", [])
                      if row.get("url") == pages[side].get("url")), None)
        if not exact or exact.get("rank_group") != pages[side].get("rank"):
            raise ValueError(f"Original SERP snapshot does not support the saved {side} page/rank.")

    store = serp_investigations.INVESTIGATIONS.resolve()
    for existing in store.glob("*/historical_registration.json"):
        registered = _read(existing)
        if registered and registered.get("source_investigation_id") == source_investigation_id:
            raise FileExistsError("This source investigation already has a historical archive record.")
    ident = archive_id or uuid.uuid4().hex
    if len(ident) != 32 or any(char not in "0123456789abcdef" for char in ident):
        raise ValueError("Archive record ID must be a lowercase 32-character UUID hex value.")
    target = store / ident
    if target.exists():
        raise FileExistsError("Historical archive ID already exists; existing data was not changed.")
    staging = store / f".historical-import-{ident}.tmp"
    if staging.exists():
        raise FileExistsError("Historical import staging path already exists.")
    staging.mkdir(parents=True)
    archive_files: list[dict] = []
    evidence_refs: list[dict] = []
    try:
        # Preserve the exact source records and all replay outputs without
        # changing or replacing the canonical original investigation.
        _copy(source_selection_path, staging, "source_selection.json", archive_files)
        _copy(source_execution_path, staging, "source_execution.json", archive_files)
        replay_execution_archive_path = "source_replay_execution.json"
        _copy(replay_execution_path, staging, replay_execution_archive_path, archive_files)
        _copy_tree(replay / "processed", staging, "processed", archive_files)
        for source, rel in ((comparison_source, "results/aviator_comparison.json"),
                            (pdf_source, "results/aviator_executive_report.pdf"),
                            (appendix_source, "results/aviator_technical_appendix.md")):
            _copy(source, staging, rel, archive_files)
        txt_source = replay / "results" / "aviator_recommendations.txt"
        if txt_source.is_file():
            _copy(txt_source, staging, "results/aviator_recommendations.txt", archive_files)

        evidence_name_map: dict[str, str] = {}
        for index, (source_rel, label, digest) in enumerate(evidence_inputs, start=1):
            source = _safe_source(ROOT, source_rel)
            safe_name = f"evidence/source_{index:02d}_{Path(source_rel).name}"
            _copy(source, staging, safe_name, archive_files)
            evidence_name_map[source_rel] = safe_name
            evidence_refs.append({"source_path": source_rel.replace("\\", "/"),
                "archive_path": safe_name, "sha256": digest, "role": label})
        sidecar_index = len(evidence_refs)
        for source_rel, _label, _digest in evidence_inputs:
            if "backlinks/" not in source_rel.replace("\\", "/"):
                continue
            sidecar_rel = str(Path(source_rel).with_suffix(".meta.json")).replace("\\", "/")
            sidecar = _safe_source(ROOT, sidecar_rel)
            sidecar_index += 1
            archive_name = f"evidence/source_{sidecar_index:02d}_{sidecar.name}"
            _copy(sidecar, staging, archive_name, archive_files)
            evidence_refs.append({"source_path": sidecar_rel, "archive_path": archive_name,
                                  "sha256": _sha(sidecar), "role": "source_metadata_sidecar"})
        _copy(serp_snapshot, staging, "evidence/original_serp_snapshot.json", archive_files)
        evidence_refs.append({"source_path": str(serp_snapshot.relative_to(ROOT)).replace("\\", "/"),
            "archive_path": "evidence/original_serp_snapshot.json", "sha256": serp_hash,
            "role": "original_selection_serp_snapshot"})

        evaluation_refs = []
        for name in ("final_offline_integration_verification_report.md", "aviator_e2e_results.json",
                     "recommendation_quality_assessment.json", "acceptance_matrix.json"):
            source = ROOT / "output" / "architecture_phase4_3A" / name
            if source.is_file():
                rel = f"evaluation/{name}"
                _copy(source, staging, rel, archive_files)
                evaluation_refs.append({"source_path": str(source.relative_to(ROOT)).replace("\\", "/"),
                    "archive_path": rel, "sha256": _sha(source)})

        prior_status = _prior_version(source_base, staging, archive_files)
        validation = {
            "validation_source": "saved recommendation records, reviewed by the existing Comparison History validation adapter",
            "validated_recommendation_count": len(accepted),
            "validated_recommendation_ids": recommendation_ids,
            "tier_counts": tier_counts,
            "validation_status_by_id": {row["id"]: row.get("validation_status") for row in accepted},
            "evidence_audit_preserved": isinstance(comparison.get("recommendation_evidence_audit"), dict),
            "validated_at_registration": datetime.now(timezone.utc).isoformat(),
            "note": "Historical validation of saved outputs only; no evidence was refreshed and no recommendations were regenerated.",
        }
        validation_path = staging / "validation_audit.json"
        validation_path.write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        archive_files.append({"path": "validation_audit.json", "sha256": _sha(validation_path)})

        registered_at = datetime.now(timezone.utc).isoformat()
        selection = dict(source_selection)
        selection.update({"investigation_id": ident, "record_type": "historical_comparison_import",
            "source_investigation_id": source_investigation_id, "source": "historical_import",
            "serp_snapshot_reference": "evidence/original_serp_snapshot.json",
            "historical_record": True})
        selection_path = staging / "selection.json"
        selection_path.write_text(json.dumps(selection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        archive_files.append({"path": "selection.json", "sha256": _sha(selection_path)})

        archive_comparison_rel = "results/aviator_comparison.json"
        archive_pdf_rel = "results/aviator_executive_report.pdf"
        archive_appendix_rel = "results/aviator_technical_appendix.md"
        offline = dict(replay_execution)
        offline.update({"investigation_id": ident, "source_investigation_id": source_investigation_id,
            "record_type": "historical_comparison_import", "mode": "historical_saved_evidence_import",
            "status": "completed", "processing_status": "completed", "report_status": "completed",
            "keyword": keyword, "selected_pages": {side: pages[side] for side in pages},
            "comparison_path": archive_comparison_rel, "pdf_path": archive_pdf_rel,
            "technical_appendix_path": archive_appendix_rel,
            "report_artifact_sha256": {"pdf": _sha(staging / archive_pdf_rel),
                                       "appendix": _sha(staging / archive_appendix_rel)},
            "historical_registration": "historical_registration.json"})
        offline_path = staging / "offline_execution.json"
        offline_path.write_text(json.dumps(offline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        archive_files.append({"path": "offline_execution.json", "sha256": _sha(offline_path)})

        # Preserve duplicate replay and earlier legacy outputs as accurately
        # labelled versions; none are promoted over the selected final replay.
        version_refs = []
        older_replay = ROOT / "output" / "architecture_phase4_3A" / "aviator_replay" / source_investigation_id
        older_comparison = older_replay / "results" / "aviator_comparison.json"
        if older_comparison.is_file():
            older_data = _read(older_comparison)
            if [row.get("id") for row in older_data.get("recommendations", [])] == recommendation_ids:
                rel = "historical_versions/earlier_offline_replay_comparison.json"
                _copy(older_comparison, staging, rel, archive_files)
                version_refs.append({"path": rel, "source_path": str(older_comparison.relative_to(ROOT)).replace("\\", "/"),
                    "source_sha256": _sha(older_comparison), "status": "earlier_replay_same_validated_recommendation_version"})
        if prior_status:
            version_refs.append(prior_status)

        registration = {
            "schema_version": "1.0", "record_type": "historical_comparison_import",
            "investigation_id": ident, "source_investigation_id": source_investigation_id,
            "registered_at": registered_at, "source_completed_at": replay_execution.get("completed_at"),
            "source_replay_directory": str(replay.relative_to(ROOT)).replace("\\", "/"),
            "source_replay_execution_sha256": _sha(replay_execution_path),
            "source_replay_execution_archive_path": replay_execution_archive_path,
            "source_selection_sha256": _sha(source_selection_path),
            "source_comparison_sha256": _sha(comparison_source),
            "source_report_sha256": {"pdf": _sha(pdf_source), "appendix": _sha(appendix_source)},
            "serp_identity": {"sha256": serp_hash,
                "source_path": str(serp_snapshot.relative_to(ROOT)).replace("\\", "/"),
                "collected_at": source_selection.get("serp_collected_at"),
                "historical_serp_datetime": replay_execution.get("historical_serp_datetime"),
                "note": "Selection SERP snapshot and replay's normalized historical SERP are preserved as distinct provenance records."},
            "evidence_source_references": evidence_refs,
            "evaluation_references": evaluation_refs,
            "validation_summary": validation,
            "historical_versions": version_refs,
            "archive_files": sorted(archive_files, key=lambda row: row["path"]),
            "workflow_checkpoints": "not_created; imported historical record is not represented as a seven-stage workflow run",
        }
        registration_path = staging / "historical_registration.json"
        registration_path.write_text(json.dumps(registration, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(staging, target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    # Read through the same integrity gate used by dashboard history and API.
    detail = comparison_history.comparison_detail(ident)
    return {"investigation_id": ident, "source_investigation_id": source_investigation_id,
            "storage_path": str(target), "recommendation_count": detail["recommendation_count"],
            "tier_1_count": detail["tier_1_count"], "tier_2_count": detail["tier_2_count"],
            "has_pdf": detail["has_pdf"], "has_appendix": detail["has_appendix"],
            "has_serp_snapshot": detail["has_serp_snapshot"],
            "recommendation_ids": [row["id"] for row in detail["recommendations"]]}


if __name__ == "__main__":
    source_id = "27b58339290b4f5193204b5320556235"
    replay_path = ROOT / "output" / "architecture_phase4_3A" / "aviator_replay_1794155942453698500" / source_id
    print(json.dumps(register_historical_comparison(source_id, replay_path), indent=2))
