from __future__ import annotations

from normalization.common import canonical_domain


def _extract_domain_from_item(item: dict) -> str | None:
    for key in ("domain", "competitor_domain", "target", "url"):
        value = item.get(key)
        if value:
            domain = canonical_domain(value)
            if domain:
                return domain
    for nested_key in ("competitor", "domain_data", "target_domain"):
        nested = item.get(nested_key)
        if isinstance(nested, dict):
            found = _extract_domain_from_item(nested)
            if found:
                return found
    return None


def extract_labs_competitor_domains(api_json: dict, exclude: set[str] | None = None) -> list[dict]:
    exclude = {canonical_domain(x) for x in (exclude or set())}
    tasks = api_json.get("tasks") or []
    result = tasks[0].get("result") if tasks else None
    result = result or []
    first = result[0] if result else {}
    items = first.get("items") or []
    candidates: list[dict] = []
    for item in items:
        domain = _extract_domain_from_item(item)
        if not domain or domain in exclude:
            continue
        candidates.append({
            "domain": domain,
            "source": "labs_competitors_domain",
            "raw_item": item,
        })
    dedupe: dict[str, dict] = {row["domain"]: row for row in candidates}
    return list(dedupe.values())


def merge_candidate_sources(serp_candidates: list[dict], labs_candidates: list[dict], benchmark_domain: str, our_domain: str) -> list[dict]:
    benchmark = canonical_domain(benchmark_domain)
    ours = canonical_domain(our_domain)
    merged: dict[str, dict] = {}

    for row in serp_candidates:
        domain = canonical_domain(row.get("domain"))
        if not domain or domain == ours:
            continue
        merged.setdefault(domain, {
            "domain": domain,
            "serp_present": False,
            "labs_present": False,
            "benchmark": domain == benchmark,
            "serp_positions": [],
            "candidate_reasons": [],
        })
        merged[domain]["serp_present"] = True
        if row.get("rank_group") is not None:
            merged[domain]["serp_positions"].append(row["rank_group"])
        reason = row.get("candidate_reason")
        if reason and reason not in merged[domain]["candidate_reasons"]:
            merged[domain]["candidate_reasons"].append(reason)

    for row in labs_candidates:
        domain = canonical_domain(row.get("domain"))
        if not domain or domain == ours:
            continue
        merged.setdefault(domain, {
            "domain": domain,
            "serp_present": False,
            "labs_present": False,
            "benchmark": domain == benchmark,
            "serp_positions": [],
            "candidate_reasons": [],
        })
        merged[domain]["labs_present"] = True
        if "labs_competitor" not in merged[domain]["candidate_reasons"]:
            merged[domain]["candidate_reasons"].append("labs_competitor")

    rows = list(merged.values())
    for row in rows:
        if row["serp_positions"]:
            rank = min(row["serp_positions"])
            distance = min(row["serp_positions"])
            row["nearest_serp_rank"] = rank
            row["serp_proximity_score"] = 1.0 / max(distance, 1)
        else:
            row["nearest_serp_rank"] = None
            row["serp_proximity_score"] = 0.0
        row["discovery_score"] = (
            (5.0 if row["benchmark"] else 0.0)
            + (3.0 if row["serp_present"] else 0.0)
            + (2.0 if row["labs_present"] else 0.0)
            + row["serp_proximity_score"]
        )

    return sorted(rows, key=lambda r: (-r["discovery_score"], r["domain"]))
