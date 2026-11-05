from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.settings import CACHE_DIR
from collectors.dataforseo_client import DataForSEOClient, load_json, save_json


def request_fingerprint(method: str, path: str, payload: Any = None) -> str:
    canonical = json.dumps(
        {"method": method.upper(), "path": path, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def cache_path(method: str, path: str, payload: Any = None) -> Path:
    return CACHE_DIR / "requests" / f"{request_fingerprint(method, path, payload)}.json"


def get_cached_response(method: str, path: str, payload: Any = None) -> dict[str, Any] | None:
    path_obj = cache_path(method, path, payload)
    if not path_obj.exists():
        return None
    entry = load_json(path_obj)
    return entry.get("response")


def _write_cache(method: str, path: str, payload: Any, response: dict[str, Any]) -> Path:
    out = cache_path(method, path, payload)
    save_json(
        {
            "method": method.upper(),
            "path": path,
            "payload": payload,
            "cached_at_utc": datetime.now(timezone.utc).isoformat(),
            "reported_cost_usd": response.get("cost"),
            "response": response,
        },
        out,
    )
    return out


def cached_post(
    client: DataForSEOClient,
    path: str,
    payload: list[dict[str, Any]],
    *,
    force: bool = False,
) -> tuple[dict[str, Any], bool]:
    if not force:
        cached = get_cached_response("POST", path, payload)
        if cached is not None:
            return cached, True
    response = client.post(path, payload)
    _write_cache("POST", path, payload, response)
    return response, False


def cached_get(
    client: DataForSEOClient,
    path: str,
    *,
    force: bool = False,
) -> tuple[dict[str, Any], bool]:
    if not force:
        cached = get_cached_response("GET", path, None)
        if cached is not None:
            return cached, True
    response = client.get(path)
    _write_cache("GET", path, None, response)
    return response, False
