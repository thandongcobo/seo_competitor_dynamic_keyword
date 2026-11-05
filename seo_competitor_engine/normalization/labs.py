from __future__ import annotations

from normalization.common import first_result


def normalize_keyword_overview(api_json: dict) -> dict:
    result = first_result(api_json)
    items = result.get("items") or []
    if not items:
        return {}
    item = items[0]
    keyword_info = item.get("keyword_info") or {}
    intent = item.get("search_intent_info") or {}
    return {
        "keyword": item.get("keyword"),
        "search_volume": keyword_info.get("search_volume"),
        "monthly_searches": keyword_info.get("monthly_searches"),
        "main_intent": intent.get("main_intent"),
        "foreign_intent": intent.get("foreign_intent"),
    }


def normalize_search_intent(api_json: dict) -> dict:
    result = first_result(api_json)
    items = result.get("items") or []
    if not items:
        return {}
    item = items[0]
    primary = item.get("keyword_intent") or {}
    secondary = item.get("secondary_keyword_intents") or []
    return {
        "keyword": item.get("keyword"),
        "main_intent": primary.get("label"),
        "intent_probability": primary.get("probability"),
        "secondary_intents": secondary,
    }


def normalize_ranked_keywords(api_json: dict, target: str) -> dict:
    result = first_result(api_json)
    items = result.get("items") or []
    rows = []
    for item in items:
        kd = item.get("keyword_data") or {}
        ranked = item.get("ranked_serp_element") or {}
        serp = ranked.get("serp_item") or {}
        keyword_info = kd.get("keyword_info") or {}
        intent_info = kd.get("search_intent_info") or {}
        rows.append({
            "keyword": kd.get("keyword"),
            "search_volume": keyword_info.get("search_volume"),
            "main_intent": intent_info.get("main_intent"),
            "rank_group": serp.get("rank_group"),
            "rank_absolute": serp.get("rank_absolute"),
            "url": serp.get("url"),
            "etv": serp.get("etv") if serp.get("etv") is not None else item.get("etv"),
        })
    return {"target": target, "total_count": result.get("total_count"), "items": rows}


def normalize_domain_intersection(api_json: dict, keyword: str | None = None) -> dict:
    """Preserve keyword-specific shared-domain evidence and its limitations."""
    result = first_result(api_json)
    tasks = api_json.get("tasks") or []
    task = tasks[0] if tasks else {}
    request_data = task.get("data") or {}
    selected = " ".join((keyword or "").strip().split())
    rows = []
    excluded = 0
    for item in result.get("items") or []:
        keyword_data = item.get("keyword_data") or {}
        returned_keyword = keyword_data.get("keyword") or ""
        # A second local check protects against accidentally processing an
        # older, unfiltered response with a keyword-scoped output filename.
        if selected and selected.casefold() not in returned_keyword.casefold():
            excluded += 1
            continue
        keyword_info = keyword_data.get("keyword_info") or {}
        first = item.get("first_domain_serp_element") or {}
        second = item.get("second_domain_serp_element") or {}
        first_rank = first.get("rank_group")
        second_rank = second.get("rank_group")
        if isinstance(first_rank, int) and isinstance(second_rank, int):
            leader = "ours" if first_rank < second_rank else "benchmark" if second_rank < first_rank else "tie"
        else:
            leader = "unknown"
        rows.append({
            "keyword": returned_keyword,
            "search_volume": keyword_info.get("search_volume"),
            "first_domain_serp_element": first or None,
            "second_domain_serp_element": second or None,
            "intersection_result": item.get("intersection_result") or {},
            "our_rank": first_rank,
            "benchmark_rank": second_rank,
            "ranking_leader": leader,
        })
    return {
        "analysis_keyword": selected or None,
        "target1": result.get("target1") or request_data.get("target1"),
        "target2": result.get("target2") or request_data.get("target2"),
        "scope": "domain_keyword_intersection",
        "match_policy": "case_insensitive_phrase_substring" if selected else "unfiltered_domain_intersection",
        "intersection_mode": "shared_keywords_only",
        "total_count": result.get("total_count"),
        "items_count": len(rows),
        "excluded_nonmatching_items": excluded,
        "items": rows,
        "coverage_note": "API total_count is for the requested filter; returned items may be limited. No result does not prove either domain has no rankings for the input keyword.",
    }


def normalize_competitors_domain(api_json: dict) -> dict:
    result = first_result(api_json)
    return {
        "total_count": result.get("total_count"),
        "items": result.get("items") or [],
    }
