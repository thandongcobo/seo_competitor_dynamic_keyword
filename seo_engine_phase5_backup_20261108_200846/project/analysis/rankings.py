from __future__ import annotations

from normalization.common import canonical_domain


def find_domain_result(normalized_serp: dict, domain: str) -> dict | None:
    wanted = canonical_domain(domain)
    for row in normalized_serp.get("organic_results", []):
        if canonical_domain(row.get("domain")) == wanted:
            return row
    return None


def _dedupe(rows: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    result: list[dict] = []
    for row in rows:
        key = (canonical_domain(row.get("domain")), row.get("rank_group"), row.get("url"))
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return sorted(result, key=lambda r: (r.get("rank_group") is None, r.get("rank_group") or 10**9))


def build_ranking_neighborhood(
    normalized_serp: dict,
    our_domain: str,
    benchmark_domain: str,
    window: int = 5,
) -> dict:
    organic = [
        row for row in normalized_serp.get("organic_results", [])
        if isinstance(row.get("rank_group"), int)
    ]
    organic.sort(key=lambda row: row["rank_group"])

    ours = find_domain_result(normalized_serp, our_domain)
    benchmark = find_domain_result(normalized_serp, benchmark_domain)
    our_position = ours.get("rank_group") if ours else None

    above: list[dict] = []
    below: list[dict] = []
    if isinstance(our_position, int):
        above = [r for r in organic if r["rank_group"] < our_position][-window:]
        below = [r for r in organic if r["rank_group"] > our_position][:window]

    return {
        "above": above,
        "target": ours,
        "below": below,
        "benchmark": benchmark,
        "benchmark_outside_window": benchmark if benchmark and benchmark not in above + below else None,
        "benchmark_tracked": True,
    }


def extract_serp_candidates(
    normalized_serp: dict,
    our_domain: str,
    benchmark_domain: str,
    window: int = 5,
) -> list[dict]:
    organic = [
        row for row in normalized_serp.get("organic_results", [])
        if row.get("domain") and isinstance(row.get("rank_group"), int)
    ]
    neighborhood = build_ranking_neighborhood(normalized_serp, our_domain, benchmark_domain, window)
    neighbor_domains = {
        canonical_domain(row.get("domain"))
        for row in neighborhood["above"] + neighborhood["below"]
    }
    benchmark_domain_canonical = canonical_domain(benchmark_domain)
    our_domain_canonical = canonical_domain(our_domain)

    candidates: list[dict] = []
    for row in organic:
        domain = canonical_domain(row.get("domain"))
        if not domain or domain == our_domain_canonical:
            continue

        reasons: list[str] = ["serp_result"]
        if domain == benchmark_domain_canonical:
            reasons.append("permanent_benchmark")
        if domain in neighbor_domains:
            reasons.append("serp_neighbour")

        candidates.append({
            **row,
            "candidate_reason": reasons,
            "is_permanent_benchmark": domain == benchmark_domain_canonical,
            "is_serp_neighbour": domain in neighbor_domains,
        })

    def priority(row: dict) -> tuple:
        # Benchmark first, then direct neighbours, then remaining SERP results by rank.
        if row.get("is_permanent_benchmark"):
            p = 0
        elif row.get("is_serp_neighbour"):
            p = 1
        else:
            p = 2
        return (p, row.get("rank_group") or 10**9, row.get("domain") or "")

    return sorted(candidates, key=priority)


def compare_rankings(
    normalized_serp: dict,
    our_domain: str,
    benchmark_domain: str,
    window: int = 5,
) -> dict:
    ours = find_domain_result(normalized_serp, our_domain)
    benchmark = find_domain_result(normalized_serp, benchmark_domain)
    our_rank = ours.get("rank_group") if ours else None
    benchmark_rank = benchmark.get("rank_group") if benchmark else None
    gap = (our_rank - benchmark_rank) if isinstance(our_rank, int) and isinstance(benchmark_rank, int) else None
    return {
        "engine": normalized_serp.get("engine"),
        "keyword": normalized_serp.get("keyword"),
        "our_position": our_rank,
        "benchmark_position": benchmark_rank,
        "position_gap": gap,
        "our_url": ours.get("url") if ours else None,
        "benchmark_url": benchmark.get("url") if benchmark else None,
        "benchmark_found": benchmark is not None,
        "organic_results_count": normalized_serp.get("organic_results_count"),
        "ranking_neighborhood": build_ranking_neighborhood(
            normalized_serp, our_domain, benchmark_domain, window=window
        ),
    }
