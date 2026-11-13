from __future__ import annotations

from typing import Any

from collectors.dataforseo_client import DataForSEOClient


def summary_payload(target: str, include_subdomains: bool = False) -> list[dict[str, Any]]:
    return [{
        "target": target,
        "include_subdomains": include_subdomains,
        "exclude_internal_backlinks": True,
        "backlinks_status_type": "live",
        "rank_scale": "one_hundred",
    }]


def backlinks_payload(target: str, limit: int = 100) -> list[dict[str, Any]]:
    return [{
        "target": target,
        "limit": limit,
        "include_subdomains": False,
        "exclude_internal_backlinks": True,
        "backlinks_status_type": "live",
        "rank_scale": "one_hundred",
    }]


def collect_summary(client: DataForSEOClient, payload: list[dict[str, Any]]) -> dict[str, Any]:
    return client.post("/v3/backlinks/summary/live", payload)


def collect_backlinks(client: DataForSEOClient, payload: list[dict[str, Any]]) -> dict[str, Any]:
    return client.post("/v3/backlinks/backlinks/live", payload)
