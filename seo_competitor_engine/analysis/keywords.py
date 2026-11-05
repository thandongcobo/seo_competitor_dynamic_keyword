from __future__ import annotations


def _keyword_map(data: dict) -> dict[str, dict]:
    return {str(row.get("keyword")).casefold(): row for row in (data or {}).get("items", [])
            if isinstance(row, dict) and row.get("keyword")}


def compare_ranked_keywords(ours: dict, competitor: dict) -> dict:
    """Compare returned samples ONLY. No claim about absent rankings."""
    a, b = _keyword_map(ours), _keyword_map(competitor)
    shared = sorted(set(a) & set(b))
    competitor_only = sorted(set(b) - set(a))
    ours_only = sorted(set(a) - set(b))
    competitor_wins = our_wins = ties = 0
    for keyword in shared:
        ar = a[keyword].get("rank_group")
        br = b[keyword].get("rank_group")
        if isinstance(ar, int) and isinstance(br, int):
            if br < ar:
                competitor_wins += 1
            elif ar < br:
                our_wins += 1
            else:
                ties += 1

    def opportunity_score(row):
        volume = row.get("search_volume")
        rank = row.get("rank_group")
        volume = volume if isinstance(volume, (int, float)) else 0
        rank = rank if isinstance(rank, (int, float)) and rank > 0 else 100
        return float(volume) / float(rank)

    opportunities = sorted((b[k] for k in competitor_only), key=opportunity_score, reverse=True)
    return {
        "our_returned_keyword_count": len(a),
        "competitor_returned_keyword_count": len(b),
        "shared_keyword_count": len(shared),
        "competitor_only_count": len(competitor_only),
        "our_only_count": len(ours_only),
        "competitor_wins_shared": competitor_wins,
        "our_wins_shared": our_wins,
        "ties_shared": ties,
        "top_competitor_only_keywords": opportunities[:25],
        "scope": "returned_ranked_keywords_samples_only",
        "coverage_warning": "Keywords absent from a limited returned sample may still rank for that domain. Do not infer an organic keyword gap.",
        "estimate_policy": "Search volume and traffic estimates are supporting estimates, not actual traffic or ranking causation.",
    }
