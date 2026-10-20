from __future__ import annotations

from normalization.common import first_result


def normalize_backlink_summary(api_json: dict, target: str) -> dict:
    result = first_result(api_json)
    return {
        "target": target,
        "rank": result.get("rank"),
        "backlinks": result.get("backlinks"),
        "referring_domains": result.get("referring_domains"),
        "referring_main_domains": result.get("referring_main_domains"),
        "referring_pages": result.get("referring_pages"),
        "dofollow": result.get("dofollow"),
        "broken_backlinks": result.get("broken_backlinks"),
        "backlinks_spam_score": result.get("backlinks_spam_score"),
    }


def normalize_backlinks(api_json: dict, target: str) -> dict:
    result = first_result(api_json)
    items = result.get("items") or []
    rows = []
    for item in items:
        rows.append({
            "url_from": item.get("url_from"),
            "domain_from": item.get("domain_from"),
            "url_to": item.get("url_to"),
            "anchor": item.get("anchor"),
            "dofollow": item.get("dofollow"),
            "domain_from_rank": item.get("domain_from_rank"),
            "page_from_rank": item.get("page_from_rank"),
            "rank": item.get("rank"),
            "first_seen": item.get("first_seen"),
            "last_seen": item.get("last_seen"),
        })
    return {"target": target, "total_count": result.get("total_count"), "items": rows}
