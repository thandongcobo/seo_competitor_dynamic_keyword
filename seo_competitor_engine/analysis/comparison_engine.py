from __future__ import annotations


def _finding(category: str, evidence: str, confidence: str, evidence_type: str, direction: str = "context") -> dict:
    return {
        "category": category,
        "direction": direction,
        "confidence": confidence,
        "evidence_type": evidence_type,
        "evidence": evidence,
    }


def build_findings(ranking_summary: dict, cross_engine: dict | None = None, keyword_gap: dict | None = None, backlink_gap: dict | None = None, onpage: dict | None = None, intent: dict | None = None, competitors: list[dict] | None = None, evidence_quality: dict | None = None, advanced_evidence: dict | None = None) -> list[dict]:
    findings: list[dict] = []
    cross_engine = cross_engine or {}
    keyword_gap = keyword_gap or {}
    backlink_gap = backlink_gap or {}
    onpage = onpage or {}
    intent = intent or {}
    competitors = competitors or []
    evidence_quality = evidence_quality or {}
    for source, status in evidence_quality.items():
        if status != "usable":
            findings.append(_finding("evidence_limitation", f"{source}: {status}", "high", "data_quality", "context"))

    # Backward-compatible support for the earlier 5-argument call shape:
    # build_findings(ranking, keyword_gap, backlink_gap, onpage, intent)
    if "position_gap" in ranking_summary and "competitor_only_count" in cross_engine:
        legacy_ranking = ranking_summary
        legacy_keyword_gap = cross_engine
        legacy_backlink_gap = keyword_gap or {}
        legacy_onpage = backlink_gap or {}
        legacy_intent = onpage or {}
        ranking_summary = {"google": legacy_ranking}
        cross_engine = {}
        keyword_gap = legacy_keyword_gap
        backlink_gap = legacy_backlink_gap
        onpage = legacy_onpage
        intent = legacy_intent

    for engine, ranking in ranking_summary.items():
        gap = ranking.get("position_gap")
        if isinstance(gap, int) and gap != 0:
            direction = "competitor" if gap > 0 else "ours"
            findings.append(_finding(
                "ranking",
                f"On {engine}, benchmark position is {ranking.get('benchmark_position')} and our position is {ranking.get('our_position')}; gap = {gap} positions.",
                "high",
                "direct_observation",
                direction,
            ))
        elif gap == 0:
            findings.append(_finding("ranking", f"On {engine}, both domains have the same organic position.", "high", "direct_observation", "neutral"))
        elif gap is None:
            findings.append(_finding("ranking", f"On {engine}, one or both tracked domains were not found in the captured organic results.", "high", "direct_observation", "context"))

    if cross_engine.get("both_found"):
        findings.append(_finding(
            "cross_engine_consistency",
            f"Both tracked domains were found in Google and Bing, enabling a cross-engine ranking comparison.",
            "high",
            "direct_observation",
            "context",
        ))

    competitor_only = keyword_gap.get("competitor_only_count", 0)
    if competitor_only > 0 and not advanced_evidence:
        findings.append(_finding(
            "keyword_coverage",
            f"Benchmark has {competitor_only} keywords absent from our returned ranked-keyword sample.",
            "medium",
            "sampled_api_estimate",
            "competitor",
        ))

    shared = keyword_gap.get("shared_keyword_count", 0)
    benchmark_wins = keyword_gap.get("competitor_wins_shared", 0)
    our_wins = keyword_gap.get("our_wins_shared", 0)
    if shared:
        direction = "competitor" if benchmark_wins > our_wins else "ours" if our_wins > benchmark_wins else "neutral"
        findings.append(_finding(
            "shared_keyword_performance",
            f"Across {shared} shared returned keywords, benchmark wins {benchmark_wins}, ours wins {our_wins}.",
            "medium",
            "sampled_api_observation",
            direction,
        ))

    ref_domains = backlink_gap.get("referring_domains") or {}
    delta = ref_domains.get("competitor_minus_ours")
    if isinstance(delta, (int, float)) and delta != 0 and not advanced_evidence:
        findings.append(_finding(
            "backlinks",
            f"Benchmark has {abs(delta)} {'more' if delta > 0 else 'fewer'} referring domains for the compared ranking URLs (page-level backlink summaries).",
            "high",
            "direct_api_metric",
            "competitor" if delta > 0 else "ours",
        ))

    # Only the upstream validated, comparable standardized SEO-content counts
    # may contribute to this finding. Never fall back to full-page body words.
    seo = onpage.get("seo_content_comparison") or {}
    ours = seo.get("ours")
    benchmark = seo.get("benchmark")
    if (seo.get("comparable") is True
            and seo.get("method") == "rendered-main-innertext-v2"
            and type(ours) is int and ours >= 0
            and type(benchmark) is int and benchmark >= 0):
        findings.append(_finding(
            "content_length",
            f"Standardized cleaned SEO-content word counts are ours {ours} vs benchmark {benchmark} "
            f"(method: {seo['method']}; verified comparable SERP ranking pages). "
            "Content length is descriptive context, not content quality or a proven ranking factor.",
            "low",
            "verified_cleaned_content_metric",
            "context",
        ))

    jaccard = onpage.get("content_token_jaccard")
    if isinstance(jaccard, float):
        findings.append(_finding(
            "content_similarity",
            f"Our page and benchmark page have a token-set similarity of {jaccard:.3f}; this is a topical similarity signal, not a ranking score.",
            "low",
            "heuristic",
            "context",
        ))

    if intent.get("assessment"):
        findings.append(_finding(
            "search_intent",
            intent["assessment"],
            intent.get("confidence", "medium"),
            "heuristic",
            intent.get("direction", "context"),
        ))

    if competitors:
        top = competitors[:10]
        names = ", ".join(
            f"{row['domain']} ({row.get('nearest_serp_rank') or 'not local-rank'})"
            for row in top
        )
        findings.append(_finding(
            "competitor_discovery",
            f"The pipeline identified potential competitor domains from SERP/Labs evidence: {names}.",
            "medium",
            "combined_discovery",
            "context",
        ))

    if advanced_evidence:
        evidence = advanced_evidence
        kw = evidence.get("keyword_intersection") or {}
        if kw.get("status") == "usable" and kw.get("returned", 0):
            findings.append(_finding(
                "keyword_intersection",
                f"Among {kw['returned']} returned shared keyword comparisons, ours leads on {kw['ours_ahead']}, "
                f"benchmark leads on {kw['benchmark_ahead']}; generic (non-domain-branded) terms: "
                f"ours {kw['generic_ours_ahead']}, benchmark {kw['generic_benchmark_ahead']}. "
                "These are historical domain-level positions, not the live primary SERP or proof of absent rankings.",
                "medium", "filtered_domain_intersection", "context"))
        for warning in kw.get("warnings", []):
            if "withheld" in warning:
                findings.append(_finding("evidence_limitation", warning, "high", "data_quality"))

        links = evidence.get("backlinks") or {}
        page, domain = links.get("page") or {}, links.get("domain") or {}
        if page:
            ranks = page.get("rank") or {}
            refs = page.get("referring_domains") or {}
            if ranks.get("ours") is not None and ranks.get("competitor") is not None:
                domain_ranks = domain.get("rank") or {}
                suffix = (f" Domain-wide ranks: ours {domain_ranks['ours']} vs benchmark {domain_ranks['competitor']}."
                          if domain_ranks.get("ours") is not None and domain_ranks.get("competitor") is not None else "")
                findings.append(_finding(
                    "backlinks",
                    f"Ranking-page DataForSEO backlink rank: ours {ranks['ours']} vs benchmark {ranks['competitor']}; "
                    f"page referring domains: ours {refs.get('ours')} vs benchmark {refs.get('competitor')}." + suffix +
                    " Link-profile metrics are not Google ranking weights or proof of causation.",
                    "medium", "page_and_domain_api_metrics", "context"))
        for warning in links.get("warnings", []):
            findings.append(_finding("evidence_limitation", warning, "medium", "data_quality"))

        for device, tech in (evidence.get("technical") or {}).items():
            metrics = tech.get("lab_metrics") or {}
            scores = tech.get("scores") or {}
            performance = scores.get("performance") or {}
            lcp = metrics.get("largest_contentful_paint_ms") or {}
            tbt = metrics.get("total_blocking_time_ms") or {}
            if any(v is not None for v in (performance.get("ours"), performance.get("benchmark"),
                                            lcp.get("ours"), lcp.get("benchmark"))):
                findings.append(_finding(
                    "lighthouse",
                    f"{device.title()} Lighthouse lab performance: ours {performance.get('ours')}, "
                    f"benchmark {performance.get('benchmark')}; LCP ms: ours {lcp.get('ours')}, "
                    f"benchmark {lcp.get('benchmark')}; TBT ms: ours {tbt.get('ours')}, "
                    f"benchmark {tbt.get('benchmark')}. One lab run is not field CWV or ranking causation.",
                    "low", "lab_audit", "context"))

        for field, label in (("title_keyword_match", "HTML title"),
                             ("meta_keyword_match", "meta description"),
                             ("h1_keyword_match", "H1")):
            item = onpage.get(field) or {}
            if item.get("ours") is False and item.get("competitor") is True:
                findings.append(_finding("onpage_keyword_targeting",
                                         f"The selected keyword is absent from our {label} but present in the benchmark {label}.",
                                         "medium", "rendered_page_metadata", "competitor"))
    return findings
