"""Deterministic evidence coverage for executive synthesis and auditability."""
from __future__ import annotations

from typing import Any


def _obj(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def build_coverage_manifest(source: dict) -> dict:
    """Describe usable, selected and omitted evidence without inferring quality."""
    quality = _obj(source.get("evidence_quality"))
    pages = _obj(source.get("page_level_evidence"))
    advanced = _obj(source.get("advanced_evidence"))
    ranking = _obj(_obj(source.get("ranking_summary")).get("google"))
    categories = {}

    def add(name: str, usable: bool, selected: list[str], omitted: list[str], note: str = ""):
        categories[name] = {
            "evidence_exists": bool(usable or selected or omitted),
            "verified_usable": bool(usable),
            "selected_paths": selected,
            "omitted_paths": omitted,
            "exclusion_reason": note if not usable else "",
            "additional_investigation_required": not bool(usable),
        }

    serp_ok = isinstance(ranking.get("our_position"), int) and isinstance(ranking.get("benchmark_position"), int)
    add("search_visibility", serp_ok, ["evidence.serp.ranking_summary"] if serp_ok else [],
        [] if serp_ok else ["evidence.serp.ranking_summary"], "Confirmed positions are missing from the saved SERP." if not serp_ok else "")
    page_ok = quality.get("page_ours") == "usable" and quality.get("page_benchmark") == "usable"
    add("onpage_content", page_ok, ["evidence.onpage.pages", "evidence.onpage.comparison"] if page_ok else [],
        [] if page_ok else ["evidence.onpage.pages", "evidence.onpage.comparison"], "One or both ranking pages are not verified." if not page_ok else "")
    backlinks = _obj(advanced.get("backlinks"))
    bl_ok = bool(backlinks.get("page") or backlinks.get("domain"))
    add("backlinks_authority", bl_ok, ["evidence.backlinks" ] if bl_ok else [],
        [] if bl_ok else ["evidence.backlinks"], "No usable backlink evidence." if not bl_ok else "")
    tech_ok = quality.get("lighthouse_ours_mobile") == "usable" and quality.get("lighthouse_benchmark_mobile") == "usable"
    add("technical_lighthouse", tech_ok, ["evidence.technical.mobile_audits"] if tech_ok else [],
        [] if tech_ok else ["evidence.technical.mobile_audits"], "One or both verified mobile audits are unavailable." if not tech_ok else "")
    kw = _obj(advanced.get("keyword_intersection"))
    kw_ok = kw.get("status") == "usable"
    add("related_keyword_competition", kw_ok, ["evidence.keywords.intersection"] if kw_ok else [],
        [] if kw_ok else ["evidence.keywords.intersection"], "Related keyword evidence is unavailable." if not kw_ok else "")
    recs = source.get("recommendations")
    rec_ok = isinstance(recs, list) and bool(recs)
    add("deterministic_findings_recommendations", rec_ok, ["deterministic_recommendations", "deterministic_findings"] if rec_ok else [],
        [] if rec_ok else ["deterministic_recommendations"], "No deterministic recommendations were generated." if not rec_ok else "")
    return {"schema_version": "1.0", "categories": categories,
            "covered_count": sum(1 for x in categories.values() if x["verified_usable"]),
            "category_count": len(categories)}
