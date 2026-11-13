from __future__ import annotations

from typing import Any

from collectors.dataforseo_client import DataForSEOClient


def keyword_overview_payload(keyword: str, location_name: str, language_code: str) -> list[dict[str, Any]]:
    return [{
        "keywords": [keyword],
        "location_name": location_name,
        "language_code": language_code,
        "include_clickstream_data": False,
    }]


def search_intent_payload(keyword: str) -> list[dict[str, Any]]:
    return [{"keywords": [keyword]}]


def domain_intersection_payload(
    our_domain: str,
    competitor_domain: str,
    location_name: str,
    language_code: str,
    limit: int = 100,
    *,
    keyword: str | None = None,
) -> list[dict[str, Any]]:
    """Compare domains, filtering shared organic keywords before API pagination.

    `ilike` is supported by DataForSEO Labs Domain Intersection. This is a
    case-insensitive phrase/substring match, not semantic keyword expansion.
    """
    task: dict[str, Any] = {
        "target1": our_domain,
        "target2": competitor_domain,
        "location_name": location_name,
        "language_code": language_code,
        "item_types": ["organic"],
        "intersections": True,
        "limit": limit,
        "include_clickstream_data": False,
        "order_by": ["keyword_data.keyword_info.search_volume,desc"],
    }
    if keyword is not None:
        phrase = " ".join(keyword.strip().split())
        if not phrase:
            raise ValueError("Domain Intersection keyword cannot be blank")
        # Avoid interpreting user-supplied LIKE wildcards as broader queries.
        if "%" in phrase or "_" in phrase:
            raise ValueError("Keyword contains SQL LIKE wildcards (% or _); use a keyword without these characters")
        task["filters"] = [["keyword_data.keyword", "ilike", f"%{phrase}%"]]
    return [task]


def ranked_keywords_payload(target: str, location_name: str, language_code: str, limit: int = 100) -> list[dict[str, Any]]:
    return [{
        "target": target,
        "location_name": location_name,
        "language_code": language_code,
        "limit": limit,
        "historical_serp_mode": "live",
        "include_clickstream_data": False,
    }]


def competitors_domain_payload(target: str, location_name: str, language_code: str, limit: int = 50) -> list[dict[str, Any]]:
    return [{
        "target": target,
        "location_name": location_name,
        "language_code": language_code,
        "item_types": ["organic"],
        "exclude_top_domains": True,
        "limit": limit,
    }]


def collect(client: DataForSEOClient, action: str, payload: list[dict[str, Any]]) -> dict[str, Any]:
    endpoints = {
        "keyword_overview": "/v3/dataforseo_labs/google/keyword_overview/live",
        "search_intent": "/v3/dataforseo_labs/google/search_intent/live",
        "domain_intersection": "/v3/dataforseo_labs/google/domain_intersection/live",
        "ranked_keywords": "/v3/dataforseo_labs/google/ranked_keywords/live",
        "competitors_domain": "/v3/dataforseo_labs/google/competitors_domain/live",
    }
    return client.post(endpoints[action], payload)
