from __future__ import annotations

from typing import Any

from collectors.dataforseo_client import DataForSEOClient

SUPPORTED_ENGINES = {"google", "bing"}


def build_serp_task(
    keyword: str,
    location_coordinate: str,
    language_code: str,
    *,
    depth: int = 50,
    priority: int = 1,
    device: str = "desktop",
    os: str = "windows",
) -> list[dict[str, Any]]:
    return [{
        "keyword": keyword,
        "location_coordinate": location_coordinate,
        "language_code": language_code,
        "depth": depth,
        "priority": priority,
        "device": device,
        "os": os,
        "tag": f"mvp:{keyword}",
    }]


def post_serp_task(client: DataForSEOClient, engine: str, payload: list[dict[str, Any]]) -> dict[str, Any]:
    engine = engine.lower()
    if engine not in SUPPORTED_ENGINES:
        raise ValueError(f"Unsupported engine: {engine}")
    return client.post(f"/v3/serp/{engine}/organic/task_post", payload)


def get_serp_advanced(client: DataForSEOClient, engine: str, task_id: str) -> dict[str, Any]:
    engine = engine.lower()
    if engine not in SUPPORTED_ENGINES:
        raise ValueError(f"Unsupported engine: {engine}")
    return client.get(f"/v3/serp/{engine}/organic/task_get/advanced/{task_id}")


def extract_task_id(response: dict[str, Any]) -> str:
    tasks = response.get("tasks") or []
    if not tasks or not tasks[0].get("id"):
        raise ValueError("No task ID found in SERP response")
    return tasks[0]["id"]
