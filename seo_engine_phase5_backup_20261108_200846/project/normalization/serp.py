from __future__ import annotations

from normalization.common import canonical_domain, first_result


def normalize_serp(api_json: dict, keyword: str, engine: str) -> dict:
    # Supports both DataForSEO-shaped responses and the local Playwright SERP format.
    if api_json.get("collection_method") == "playwright_local_browser":
        if api_json.get("status") != "ok":
            raise ValueError("Refusing to normalize blocked/incomplete browser SERP")
        organic = []
        features = []
        for item in api_json.get("organic_results") or []:
            row = dict(item)
            row["rank_group"] = int(row.get("rank_group", row.get("rank", len(organic) + 1)))
            row["engine"] = engine
            row["keyword"] = keyword
            row["domain"] = canonical_domain(row.get("domain") or row.get("url"))
            organic.append(row)
        features = list(api_json.get("serp_features") or [])
        return {
            "engine": engine,
            "keyword": keyword,
            "check_url": api_json.get("search_url"),
            "datetime": api_json.get("datetime"),
            "se_domain": engine,
            "se_results_count": None,
            "items_count": api_json.get("items_count"),
            "organic_results_count": len(organic),
            "organic_results": organic,
            "serp_features": features,
            "collection_method": "playwright_local_browser",
            "location_coordinate": api_json.get("location_coordinate"),
            "browser_profile": api_json.get("browser_profile"),
            "capture_scope": api_json.get("capture_scope", "unknown"),
            "requested_depth": api_json.get("requested_depth"),
            "status": api_json.get("status", "ok"),
        }

    result = first_result(api_json)
    items = result.get("items") or []
    organic: list[dict] = []
    features: list[dict] = []

    for item in items:
        normalized = {
            "engine": engine,
            "keyword": keyword,
            "type": item.get("type"),
            "rank_group": item.get("rank_group"),
            "rank_absolute": item.get("rank_absolute"),
            "domain": canonical_domain(item.get("domain") or item.get("url")),
            "url": item.get("url"),
            "title": item.get("title"),
            "description": item.get("description"),
            "position": item.get("position"),
            "is_image": item.get("is_image"),
            "is_video": item.get("is_video"),
            "is_featured_snippet": item.get("is_featured_snippet"),
        }
        if item.get("type") == "organic":
            organic.append(normalized)
        else:
            features.append(normalized)

    organic.sort(key=lambda row: (row.get("rank_group") is None, row.get("rank_group") or 10**9))

    return {
        "engine": engine,
        "keyword": keyword,
        "check_url": result.get("check_url"),
        "datetime": result.get("datetime"),
        "se_domain": result.get("se_domain"),
        "se_results_count": result.get("se_results_count"),
        "items_count": result.get("items_count"),
        "organic_results_count": len(organic),
        "organic_results": organic,
        "serp_features": features,
    }
