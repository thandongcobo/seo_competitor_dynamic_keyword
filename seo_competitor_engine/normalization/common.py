from __future__ import annotations

from urllib.parse import urlparse


def canonical_domain(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip().lower()
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    host = urlparse(raw).netloc
    return host[4:] if host.startswith("www.") else host


def first_result(api_json: dict) -> dict:
    tasks = api_json.get("tasks") or []
    if not tasks:
        return {}
    results = tasks[0].get("result") or []
    return results[0] if results else {}
