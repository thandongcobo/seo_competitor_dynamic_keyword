"""Read-only, integrity-checked view of completed investigation recommendations."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from analysis.recommendation_classification import (
    TIER_1, TIER_2, TIER_LABELS, adapt_recommendations,
)
from scripts import serp_investigations

_ID = re.compile(r"^[0-9a-f]{32}$")
_TIERS = {TIER_1, TIER_2}
_DEFAULT_PAGE_SIZE = 20
_MAX_PAGE_SIZE = 50
_INDEX_VERSION = 1
_INDEX_TABLE = "comparison_history_entries"


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _base(root, investigation_id: str) -> tuple[Path, Path]:
    if not isinstance(investigation_id, str) or not _ID.fullmatch(investigation_id):
        raise ValueError("Invalid investigation ID.")
    data_root = Path(root or serp_investigations.INVESTIGATIONS).resolve()
    folder = (data_root / investigation_id).resolve()
    try:
        folder.relative_to(data_root)
    except ValueError as exc:
        raise ValueError("Investigation path is outside saved investigation storage.") from exc
    if not folder.is_dir():
        raise FileNotFoundError("Investigation not found.")
    return data_root, folder


def _contained(base: Path, value: str, *, parent: str | None = None,
               suffix: str | None = None) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Saved artifact reference is missing.")
    candidate = Path(value)
    if candidate.is_absolute():
        raise ValueError("Absolute artifact paths are not allowed.")
    resolved = (base / candidate).resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError("Saved artifact path escapes its investigation.") from exc
    if parent and resolved.parent != (base / parent).resolve():
        raise ValueError("Saved artifact is outside its expected investigation directory.")
    if suffix and resolved.suffix.lower() != suffix:
        raise ValueError("Saved artifact type does not match the requested artifact.")
    if not resolved.is_file():
        raise FileNotFoundError("Saved artifact is unavailable.")
    return resolved


def _index_path(data_root: Path) -> Path:
    """Keep the rebuildable metadata index beside, never inside, source folders."""
    return data_root.parent / ".comparison_history_index.sqlite3"


def _safe_candidate(base: Path, value, *, parent: str | None = None,
                    suffix: str | None = None) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        return None
    base_resolved = Path(os.path.abspath(base))
    resolved = Path(os.path.abspath(base_resolved / candidate))
    try:
        if os.path.commonpath((str(resolved), str(base_resolved))) != str(base_resolved):
            return None
    except (ValueError, OSError):
        return None
    if parent and os.path.normcase(str(resolved.parent)) != os.path.normcase(
            os.path.abspath(base_resolved / parent)):
        return None
    if suffix and resolved.suffix.lower() != suffix:
        return None
    return resolved


def _fingerprint_paths(data_root: Path, investigation_id: str) -> list[str]:
    """Find the small set of authoritative files that can change a summary.

    This discovery is used only when an index entry is new or stale. On warm
    reads, the persisted paths are checked with stat signatures and no JSON,
    recommendation, PDF, or appendix contents are loaded.
    """
    base = data_root / investigation_id
    paths: set[Path] = {base, base / "selection.json", base / "offline_execution.json",
                        base / "workflow" / "checkpoint.json"}
    try:
        resolved_base = base.resolve()
        resolved_base.relative_to(data_root.resolve())
    except (OSError, ValueError):
        return sorted(str(path) for path in paths)

    selection = _read(base / "selection.json")
    offline = _read(base / "offline_execution.json")
    if isinstance(offline, dict):
        comparison = _safe_candidate(base, offline.get("comparison_path"), parent="results", suffix=".json")
        if comparison:
            paths.add(comparison)
        for field, suffix in (("pdf_path", ".pdf"), ("technical_appendix_path", ".md")):
            candidate = _safe_candidate(base, offline.get(field), parent="results", suffix=suffix)
            if candidate:
                paths.add(candidate)
    if isinstance(selection, dict):
        reference = selection.get("serp_snapshot_reference")
        if isinstance(reference, str) and reference.strip() and not Path(reference).is_absolute():
            roots = [data_root.parent.parent]
            try:
                from config.settings import ROOT as engine_root
                roots.append(Path(engine_root))
            except ImportError:
                pass
            for root in roots:
                root = Path(os.path.abspath(root))
                candidate = Path(os.path.abspath(root / reference))
                try:
                    if os.path.commonpath((str(candidate), str(root))) != str(root):
                        continue
                except (ValueError, OSError):
                    continue
                paths.add(candidate)
    return sorted(str(path) for path in paths)


def _stat_key(path: str) -> str:
    path = os.fspath(path)
    if os.name == "nt":
        # Fingerprint paths are created from resolved store roots and safe
        # relative references, so normalize separators/case without the
        # filesystem lookup performed by ntpath.abspath on every cache row.
        return os.path.normcase(os.path.normpath(path))
    return os.path.abspath(path)


def _signature_from_stat(stat) -> list[int]:
    return [int(stat.st_dev), int(stat.st_ino), int(stat.st_size), int(stat.st_mtime_ns)]


def _stat_fingerprints(paths: list[str], *, cache: dict | None = None,
                       scanned_dirs: set[str] | None = None) -> dict[str, list[int] | None]:
    """Use directory enumeration metadata in batches instead of N file stats."""
    cache = cache if cache is not None else {}
    scanned_dirs = scanned_dirs if scanned_dirs is not None else set()
    requested = {_stat_key(path): path for path in paths}
    by_parent: dict[str, list[tuple[str, str]]] = {}
    for key, path in requested.items():
        if key in cache:
            continue
        parent = _stat_key(os.path.dirname(path))
        by_parent.setdefault(parent, []).append((key, os.path.basename(path)))
    for parent, needed in by_parent.items():
        if parent not in scanned_dirs:
            scanned_dirs.add(parent)
            wanted = {name.casefold(): key for key, name in needed}
            try:
                with os.scandir(parent) as entries:
                    for entry in entries:
                        key = wanted.get(entry.name.casefold())
                        if key is None:
                            continue
                        try:
                            cache[key] = _signature_from_stat(entry.stat(follow_symlinks=True))
                        except OSError:
                            cache[key] = None
            except OSError:
                pass
        for key, _name in needed:
            cache.setdefault(key, None)
    return {path: cache[_stat_key(path)] for path in sorted(set(paths))}


def _index_checksum(investigation_id: str, version: int, eligible: int,
                    summary_json: str, fingerprints_json: str) -> str:
    value = "\0".join((investigation_id, str(version), str(eligible), summary_json, fingerprints_json))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _enable_wal(connection: sqlite3.Connection) -> None:
    mode = connection.execute("PRAGMA journal_mode").fetchone()
    if mode and str(mode[0]).casefold() == "wal":
        return
    deadline = time.monotonic() + 15
    while True:
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as exc:
            if not any(word in str(exc).casefold() for word in ("locked", "busy")):
                raise
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


def _open_index(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = None
    try:
        connection = sqlite3.connect(path, timeout=15)
        connection.execute("PRAGMA busy_timeout=15000")
        _enable_wal(connection)
        connection.execute("PRAGMA synchronous=FULL")
        check = connection.execute("PRAGMA quick_check").fetchone()
        if not check or check[0] != "ok":
            raise sqlite3.DatabaseError("Comparison History index failed quick_check")
        connection.execute(f"""CREATE TABLE IF NOT EXISTS {_INDEX_TABLE} (
            investigation_id TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            eligible INTEGER NOT NULL,
            summary_json TEXT NOT NULL,
            fingerprints_json TEXT NOT NULL,
            checksum TEXT NOT NULL
        )""")
        connection.commit()
        return connection
    except sqlite3.DatabaseError as exc:
        try:
            if connection is not None:
                connection.close()
        except sqlite3.Error:
            pass
        message = str(exc).casefold()
        if not any(marker in message for marker in ("not a database", "malformed", "quick_check")):
            raise
        # Index data is disposable. Preserve a corrupt copy for diagnosis and
        # reconstruct from investigation folders on the next connection.
        if path.exists():
            corrupt = path.with_name(path.name + f".corrupt-{time.time_ns()}")
            os.replace(path, corrupt)
        for suffix in ("-wal", "-shm"):
            Path(str(path) + suffix).unlink(missing_ok=True)
        connection = sqlite3.connect(path, timeout=15)
        connection.execute("PRAGMA busy_timeout=15000")
        _enable_wal(connection)
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute(f"""CREATE TABLE IF NOT EXISTS {_INDEX_TABLE} (
            investigation_id TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            eligible INTEGER NOT NULL,
            summary_json TEXT NOT NULL,
            fingerprints_json TEXT NOT NULL,
            checksum TEXT NOT NULL
        )""")
        connection.commit()
        return connection


def _cache_entry(investigation_id: str, eligible: bool, summary: dict | None,
                 fingerprints: dict[str, list[int] | None]) -> tuple:
    summary_json = json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fingerprints_json = json.dumps(fingerprints, sort_keys=True, separators=(",", ":"))
    flag = int(eligible)
    return (investigation_id, _INDEX_VERSION, flag, summary_json, fingerprints_json,
            _index_checksum(investigation_id, _INDEX_VERSION, flag, summary_json, fingerprints_json))


def _cache_entry_is_fresh(row: tuple, data_root: Path, *, stat_cache: dict,
                          scanned_dirs: set[str]) -> tuple[bool, dict | None]:
    ident, version, eligible, summary_json, fingerprints_json, checksum = row
    if version != _INDEX_VERSION or type(eligible) is not int or eligible not in (0, 1):
        return False, None
    if _index_checksum(ident, version, eligible, summary_json, fingerprints_json) != checksum:
        return False, None
    try:
        summary = json.loads(summary_json)
        fingerprints = json.loads(fingerprints_json)
    except (TypeError, ValueError):
        return False, None
    if not isinstance(fingerprints, dict) or not fingerprints:
        return False, None
    base = _stat_key(str(data_root / ident))
    store_parent = _stat_key(str(data_root.parent.parent))
    try:
        from config.settings import ROOT as engine_root
        permitted_roots = (base, store_parent, _stat_key(str(engine_root)))
    except ImportError:
        permitted_roots = (base, store_parent)
    for path, expected in fingerprints.items():
        if not isinstance(path, str) or (expected is not None and
                (not isinstance(expected, list) or len(expected) != 4 or
                 any(type(part) is not int for part in expected))):
            return False, None
        absolute = _stat_key(path)
        if not any(absolute == root or absolute.startswith(root + os.sep) for root in permitted_roots):
            return False, None
    if fingerprints != _stat_fingerprints(list(fingerprints), cache=stat_cache,
                                          scanned_dirs=scanned_dirs):
        return False, None
    if eligible:
        if not isinstance(summary, dict) or summary.get("investigation_id") != ident:
            return False, None
        return True, summary
    return True, None


def _summary(item: dict) -> dict:
    """Drop recommendation detail and internal file paths from list metadata."""
    return {key: value for key, value in item.items()
            if not key.startswith("_") and key != "recommendations"}


def _sync_history_index(data_root: Path) -> list[dict]:
    """Reconcile the disposable summary index with authoritative source folders."""
    index_path = _index_path(data_root)
    connection = _open_index(index_path)
    try:
        cached_rows = {row[0]: row for row in connection.execute(
            f"SELECT investigation_id, version, eligible, summary_json, fingerprints_json, checksum FROM {_INDEX_TABLE}")}
        folders = {}
        stat_cache: dict[str, list[int] | None] = {}
        scanned_dirs: set[str] = set()
        root_key = _stat_key(str(data_root))
        scanned_dirs.add(root_key)
        with os.scandir(data_root) as entries:
            for entry in entries:
                if not _ID.fullmatch(entry.name):
                    continue
                try:
                    stat = entry.stat(follow_symlinks=True)
                    if not entry.is_dir(follow_symlinks=True):
                        continue
                    folder_path = Path(entry.path)
                    folders[entry.name] = folder_path
                    stat_cache[_stat_key(entry.path)] = _signature_from_stat(stat)
                except OSError:
                    continue

        summaries: list[dict] = []
        updates: dict[str, tuple] = {}
        for ident, folder in folders.items():
            row = cached_rows.get(ident)
            fresh, cached_summary = (_cache_entry_is_fresh(row, data_root, stat_cache=stat_cache,
                                                           scanned_dirs=scanned_dirs)
                                    if row else (False, None))
            if fresh:
                if cached_summary is not None:
                    summaries.append(cached_summary)
                continue

            eligible_item = None
            fingerprints = {}
            # Capture before and after loading. If an investigation is being
            # written concurrently, do not cache a mixed-generation summary.
            for _attempt in range(2):
                paths_before = _fingerprint_paths(data_root, ident)
                before = _stat_fingerprints(paths_before)
                try:
                    eligible_item = _load(data_root, ident)
                except (OSError, ValueError, TypeError, KeyError):
                    eligible_item = None
                fingerprints = _stat_fingerprints(paths_before)
                if before == fingerprints:
                    break
                eligible_item = None
            summary = _summary(eligible_item) if eligible_item else None
            updates[ident] = _cache_entry(ident, summary is not None, summary, fingerprints)
            if summary is not None:
                summaries.append(summary)

        deleted = set(cached_rows) - set(folders)
        if updates or deleted:
            connection.execute("BEGIN IMMEDIATE")
            if deleted:
                connection.executemany(f"DELETE FROM {_INDEX_TABLE} WHERE investigation_id = ?",
                                       ((ident,) for ident in deleted))
            if updates:
                connection.executemany(f"""INSERT INTO {_INDEX_TABLE}
                    (investigation_id, version, eligible, summary_json, fingerprints_json, checksum)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(investigation_id) DO UPDATE SET
                    version=excluded.version, eligible=excluded.eligible,
                    summary_json=excluded.summary_json, fingerprints_json=excluded.fingerprints_json,
                    checksum=excluded.checksum""", updates.values())
            connection.commit()
        return summaries
    finally:
        connection.close()


def _output_hash(stage: dict, relative_path: str) -> str | None:
    sources = [stage.get("outputs") or []]
    sources.extend((attempt.get("outputs") or []) for attempt in stage.get("attempts") or []
                   if isinstance(attempt, dict))
    for outputs in sources:
        for output in outputs:
            if isinstance(output, dict) and output.get("path") == relative_path:
                digest = output.get("sha256")
                return digest if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) else None
    return None


def _url_key(value) -> str:
    if not isinstance(value, str):
        return ""
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            return ""
        host = parts.hostname.lower().removeprefix("www.")
        path = (parts.path or "/").rstrip("/") or "/"
        return urlunsplit(("", host, path, parts.query, ""))
    except ValueError:
        return ""


def _validated_recommendations(comparison: dict) -> list[dict]:
    rows = comparison.get("recommendations")
    if not isinstance(rows, list) or not rows:
        raise ValueError("No saved recommendation set is available.")
    ids = [row.get("id") for row in rows if isinstance(row, dict)]
    if len(ids) != len(rows) or any(not isinstance(value, str) or not value for value in ids):
        raise ValueError("Saved recommendation records are incomplete.")
    if len(ids) != len(set(ids)):
        raise ValueError("Saved recommendation IDs are not unique.")
    # Task 7 remains the eligibility authority. Keep recommendations with an
    # explicit passed validation record; never promote a merely plausible row.
    accepted, _audit = adapt_recommendations(rows)
    accepted = [row for row in accepted
                if str(row.get("validation_status") or "").casefold().startswith("validated")
                and row.get("evidence_tier") in _TIERS]
    if not accepted:
        raise ValueError("No saved recommendations passed validation and Task 7 classification.")
    return accepted


def _load(root, investigation_id: str) -> dict:
    data_root, base = _base(root, investigation_id)
    selection = _read(base / "selection.json")
    offline = _read(base / "offline_execution.json")
    checkpoint = _read(base / "workflow" / "checkpoint.json")
    if not isinstance(selection, dict) or not isinstance(offline, dict):
        raise ValueError("Investigation selection or execution record is unavailable.")
    if checkpoint is not None and not isinstance(checkpoint, dict):
        raise ValueError("Investigation workflow checkpoint is invalid.")
    if selection.get("investigation_id") != investigation_id or offline.get("investigation_id") != investigation_id or (checkpoint and checkpoint.get("investigation_id") != investigation_id):
        raise ValueError("Saved investigation identity does not match its folder.")
    keyword = selection.get("keyword")
    ours, benchmark = selection.get("ours") or {}, selection.get("benchmark") or {}
    if not isinstance(keyword, str) or not keyword.strip() or not ours.get("url") or not benchmark.get("url"):
        raise ValueError("Saved comparison identity is incomplete.")
    if (str(offline.get("keyword") or "").casefold() != keyword.casefold() or
            (offline.get("selected_pages") or {}).get("ours", {}).get("url") != ours.get("url") or
            (offline.get("selected_pages") or {}).get("benchmark", {}).get("url") != benchmark.get("url")):
        raise ValueError("Saved execution context does not match the exact selected pages.")
    if offline.get("processing_status", "completed" if offline.get("status") in ("completed", "report_failed") else None) != "completed":
        raise ValueError("Recommendation processing did not complete.")
    stages = (checkpoint or {}).get("stages") or {}
    collection_stage = stages.get("evidence_collection")
    if isinstance(collection_stage, dict) and collection_stage.get("status") != "completed":
        raise ValueError("Evidence collection is incomplete or failed.")
    recommendation_stages_complete = all(
        (stages.get(key) or {}).get("status") == "completed"
        for key in ("recommendation_generation", "validation_classification"))
    report_failed_after_processing = (offline.get("status") == "report_failed" and
                                      offline.get("processing_status") == "completed")
    legacy_completed_record = (checkpoint is None and offline.get("status") == "completed")
    fallback_stage_states = [(stages.get(key) or {}).get("status") for key in
                             ("recommendation_generation", "validation_classification")]
    report_retry_completed = (offline.get("status") == "completed" and
        offline.get("processing_status") == "completed" and offline.get("report_status") == "completed" and
        (stages.get("evidence_processing") or {}).get("status") == "failed" and
        all(status in (None, "not_started") for status in fallback_stage_states))
    safe_fallback = (report_failed_after_processing or report_retry_completed) and all(
        status in (None, "not_started") for status in fallback_stage_states)
    safe_fallback = safe_fallback or legacy_completed_record
    if not recommendation_stages_complete and not safe_fallback:
        raise ValueError("Recommendation validation is incomplete.")
    slug_path = offline.get("comparison_path")
    comparison_path = _contained(base, slug_path, parent="results", suffix=".json")
    rel_comparison = comparison_path.relative_to(base).as_posix()
    if recommendation_stages_complete:
        generation_hash = _output_hash(stages["recommendation_generation"], rel_comparison)
        validation_hash = _output_hash(stages["validation_classification"], rel_comparison)
        if not generation_hash or not validation_hash:
            raise ValueError("Saved workflow checkpoint does not pin the required artifact.")
        # Both completed stages must pin the exact same source file. Hash it
        # once and reuse that digest rather than reopening it for each pin.
        comparison_hash = _sha(comparison_path)
        if comparison_hash != generation_hash or comparison_hash != validation_hash:
            raise ValueError("Saved investigation artifact failed its checkpoint integrity check.")
        execution_path = _contained(base, "offline_execution.json")
        execution_hash = _output_hash(stages["recommendation_generation"], "offline_execution.json")
        if not execution_hash:
            raise ValueError("Saved workflow checkpoint does not pin the required artifact.")
        if _sha(execution_path) != execution_hash:
            raise ValueError("Saved investigation artifact failed its checkpoint integrity check.")
        generation_path = comparison_path
    else:
        # The Phase 2.3 runner writes recommendations before rendering. A
        # report-only failure leaves the valid dataset available even when the
        # bundled workflow cannot checkpoint its later stage outputs.
        generation_path = comparison_path
    comparison = _read(generation_path)
    if not isinstance(comparison, dict):
        raise ValueError("Saved comparison JSON is invalid.")
    if (str(comparison.get("keyword") or "").casefold() != keyword.casefold() or
            (comparison.get("primary_ranking_urls") or {}).get("ours") != ours.get("url") or
            (comparison.get("primary_ranking_urls") or {}).get("benchmark") != benchmark.get("url")):
        raise ValueError("Saved comparison data belongs to a different keyword or selected webpage.")
    recommendations = _validated_recommendations(comparison)
    tier_counts = {tier: sum(row.get("evidence_tier") == tier for row in recommendations) for tier in _TIERS}
    metadata = offline.get("investigation_metadata") or {}
    report_paths = {}
    for kind, field, suffix in (("pdf", "pdf_path", ".pdf"),
                                ("appendix", "technical_appendix_path", ".md")):
        relative = offline.get(field)
        if not relative:
            continue
        try:
            artifact = _contained(base, relative, parent="results", suffix=suffix)
            expected = (offline.get("report_artifact_sha256") or {}).get("pdf" if kind == "pdf" else "appendix")
            if not expected:
                expected = _output_hash(stages.get("results_reporting") or {}, artifact.relative_to(base).as_posix())
            if expected and _sha(artifact) == expected and (kind != "pdf" or artifact.read_bytes()[:5] == b"%PDF-"):
                report_paths[kind] = artifact
        except (OSError, ValueError):
            continue
    serp_reference = selection.get("serp_snapshot_reference") or metadata.get("serp_snapshot_reference")
    serp_hash = selection.get("serp_sha256") or (metadata.get("serp_sha256"))
    serp_available = False
    if isinstance(serp_reference, str) and serp_hash:
        try:
            snapshot = _contained(data_root.parent.parent, serp_reference)
            serp_available = _sha(snapshot) == serp_hash
        except (OSError, ValueError):
            # Standard references are workspace-relative; permit this only if
            # the exact referenced path is under the engine root.
            try:
                from config.settings import ROOT as ENGINE_ROOT
                snapshot = _contained(Path(ENGINE_ROOT).resolve(), serp_reference)
                serp_available = _sha(snapshot) == serp_hash
            except (OSError, ValueError):
                serp_available = False
    completed_at = (stages.get("validation_classification") or {}).get("completed_at") or offline.get("completed_at") or selection.get("created_at")
    return {
        "investigation_id": investigation_id,
        "keyword": keyword,
        "created_at": selection.get("created_at"),
        "completed_at": completed_at,
        "source": selection.get("source"),
        "selection": {"ours": ours, "benchmark": benchmark,
                      "serp_sha256": selection.get("serp_sha256"),
                      "serp_snapshot_reference": serp_reference,
                      "serp_collected_at": selection.get("serp_collected_at"),
                      "search_context": selection.get("search_context") or {},
                      "investigation_date": completed_at},
        "workflow_status": "validated_recommendations_available",
        "report_status": "available" if "pdf" in report_paths else "unavailable",
        "has_pdf": "pdf" in report_paths,
        "has_appendix": "appendix" in report_paths,
        "has_serp_snapshot": serp_available,
        "recommendation_count": len(recommendations),
        "tier_1_count": tier_counts[TIER_1],
        "tier_2_count": tier_counts[TIER_2],
        "recommendation_sha256": _sha(comparison_path),
        "classification_version": sorted({row.get("classification_version") for row in recommendations
                                           if row.get("classification_version") is not None}, key=str),
        "comparison_path": rel_comparison,
        "report_references": {
            kind: f"/api/comparisons/{investigation_id}/artifacts/{kind}"
            for kind in report_paths
        },
        "serp_snapshot_url": f"/api/comparisons/{investigation_id}/serp" if serp_available else None,
        "recommendations": recommendations,
        "_artifacts": report_paths,
        "_serp_path": snapshot if serp_available else None,
    }


def comparison_detail(investigation_id: str, *, root=None) -> dict:
    """Return original validated recommendations and safe artifact availability."""
    record = _load(root, investigation_id)
    record.pop("_artifacts", None)
    record.pop("_serp_path", None)
    return record


def history(*, root=None, query="", keyword="", competitor="", url="",
            date_from="", date_to="", sort="recent", page=1,
            page_size=_DEFAULT_PAGE_SIZE) -> dict:
    """Search/paginate summaries; comparison JSON files are opened one at a time."""
    data_root = Path(root or serp_investigations.INVESTIGATIONS).resolve()
    if not data_root.is_dir():
        return {"comparisons": [], "page": 1, "page_size": _DEFAULT_PAGE_SIZE, "total": 0, "pages": 0}
    q = str(query or "").strip().casefold()
    kw = str(keyword or "").strip().casefold()
    comp = str(competitor or "").strip().casefold()
    url_match = _url_key(url)
    if url and not url_match:
        raise ValueError("Enter a valid HTTP(S) URL for the history filter.")
    try:
        start = date.fromisoformat(date_from) if date_from else None
        end = date.fromisoformat(date_to) if date_to else None
        page_num = max(1, int(page))
        size = min(_MAX_PAGE_SIZE, max(1, int(page_size)))
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid date or pagination filter.") from exc
    if start and end and start > end:
        raise ValueError("Start date must be on or before end date.")
    if sort not in {"recent", "oldest", "keyword", "competitor"}:
        raise ValueError("Unsupported history sort order.")
    records = []
    for item in _sync_history_index(data_root):
        ours, other = item["selection"]["ours"], item["selection"]["benchmark"]
        competitor_name = f"{other.get('domain') or ''} {other.get('title') or ''}".casefold()
        date_value = str(item.get("completed_at") or item.get("created_at") or "")[:10]
        try:
            record_date = date.fromisoformat(date_value)
        except ValueError:
            record_date = None
        text = " ".join((item["keyword"], competitor_name, str(ours.get("url") or ""),
                         str(other.get("url") or ""), item["investigation_id"])).casefold()
        if kw and kw not in item["keyword"].casefold():
            continue
        if comp and comp not in competitor_name:
            continue
        if url_match and url_match not in {_url_key(ours.get("url")), _url_key(other.get("url"))}:
            continue
        if start and (record_date is None or record_date < start):
            continue
        if end and (record_date is None or record_date > end):
            continue
        if q and q not in text:
            continue
        records.append({key: value for key, value in item.items() if not key.startswith("_") and key != "recommendations"})
    if sort == "oldest":
        records.sort(key=lambda row: (row.get("completed_at") or row.get("created_at") or "", row["investigation_id"]))
    elif sort == "keyword":
        records.sort(key=lambda row: (row["keyword"].casefold(), row.get("completed_at") or "",
                                      row["investigation_id"]))
    elif sort == "competitor":
        records.sort(key=lambda row: (((row["selection"].get("benchmark") or {}).get("domain") or "").casefold(),
                                      row.get("completed_at") or row.get("created_at") or "",
                                      row["investigation_id"]))
    else:
        records.sort(key=lambda row: (row.get("completed_at") or row.get("created_at") or "", row["investigation_id"]), reverse=True)
    total = len(records)
    pages = (total + size - 1) // size
    start_index = (page_num - 1) * size
    return {"comparisons": records[start_index:start_index + size], "page": page_num,
            "page_size": size, "total": total, "pages": pages}


def artifact(investigation_id: str, kind: str, *, root=None) -> Path:
    if kind not in ("pdf", "appendix"):
        raise ValueError("Unknown comparison artifact.")
    record = _load(root, investigation_id)
    path = (record.get("_artifacts") or {}).get(kind)
    if path is None:
        raise FileNotFoundError("Saved report is unavailable or failed its integrity check.")
    return path


def saved_serp(investigation_id: str, *, root=None) -> Path:
    record = _load(root, investigation_id)
    path = record.get("_serp_path")
    if path is None:
        raise FileNotFoundError("The original saved SERP snapshot is unavailable or has changed.")
    return path
