"""Auditable SEO recommendations, with conservative triage rather than rank forecasts."""
from __future__ import annotations

from analysis.advanced_evidence import classify_opportunity_relevance


def _num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _recommend(code, title, impact, confidence, effort, relevance, evidence,
               rationale, actions, verify, caveat, target_url, action_type="investigate"):
    # Simple transparent triage rubric. It is not a predictive SEO score.
    weight = {"high": 3, "medium": 2, "low": 1}
    effort_weight = {"low": 3, "medium": 2, "high": 1}
    score = (2 * weight[relevance] + weight[impact] + weight[confidence]
             + effort_weight[effort])
    priority = "high" if score >= 13 else "medium" if score >= 10 else "low"
    return {
        "id": code, "title": title, "priority": priority,
        "priority_score": score,
        "priority_basis": "Triage rubric: 2*relevance + potential_impact + evidence_confidence + inverse_effort; ordinal only.",
        "potential_impact": impact,
        "evidence_confidence": confidence,
        "implementation_effort": effort,
        "keyword_relevance": relevance,
        "action_type": action_type,
        "target_url": target_url,
        "impact_estimate": {
            "potential": f"{impact}_qualitative_unquantified",
            "unit": "qualitative_opportunity_not_rank_lift",
            "quantified_rank_or_traffic_lift": None,
            "basis": "Rule-based opportunity assessment, not a validated causal forecast.",
        },
        "evidence": evidence, "interpretation": rationale, "actions": actions,
        "success_check": verify, "limitations": caveat,
        "status": "proposed_for_review",
    }


def generate_recommendations(*, keyword, ranking_urls, advanced_evidence, onpage, technical_comparison=None):
    """Generate only evidence-supported opportunities; keyword and domains stay dynamic."""
    results = []
    urls = ranking_urls or {}
    ours_url, benchmark_url = urls.get("ours"), urls.get("benchmark")
    if not ours_url or not benchmark_url:
        return []

    backlinks = (advanced_evidence or {}).get("backlinks") or {}
    page = backlinks.get("page") or {}
    page_rank = page.get("rank") or {}
    page_refs = page.get("referring_domains") or {}
    if (_num(page_rank.get("ours")) and _num(page_rank.get("competitor"))
            and page_rank["ours"] < page_rank["competitor"]):
        domain_rank = (backlinks.get("domain") or {}).get("rank") or {}
        extra = (f" Domain backlink rank: ours {domain_rank['ours']}, competitor {domain_rank['competitor']}."
                 if _num(domain_rank.get("ours")) and _num(domain_rank.get("competitor")) else "")
        results.append(_recommend(
            "page-link-profile", "Investigate page-specific backlink quality and relevant link-earning opportunities",
            "high", "medium", "high", "high",
            f"Page backlink rank: ours {page_rank['ours']}, competitor {page_rank['competitor']}; "
            f"referring domains: ours {page_refs.get('ours')}, competitor {page_refs.get('competitor')}." + extra,
            "The competitor page has stronger measured link signals, but aggregate counts cannot establish link quality or ranking causation.",
            ["Review referring-domain-level data for topical relevance, placement and editorial quality before acting.",
             "Identify legitimate opportunities to earn references to this exact ranking page.",
             "Improve useful resources and relevant internal links; avoid manipulative link schemes."],
            "Recheck the same page-level link metrics and independent SERP observations over time.",
            "Referring-domain exports are needed to establish link quality; effort is an estimate.",
            ours_url))

    intersection = (advanced_evidence or {}).get("keyword_intersection") or {}
    opportunities = intersection.get("top_generic_benchmark_leads") or []
    # Defense in depth: do not trust older/unfiltered advanced evidence.
    domains = (ours_url, benchmark_url)
    safe = []
    for row in opportunities:
        if not isinstance(row, dict):
            continue
        term = row.get("keyword")
        category, _ = classify_opportunity_relevance(term, keyword, domains)
        if category == "relevant_generic" and _num(row.get("our_rank")) and _num(row.get("benchmark_rank")):
            safe.append(row)
    if intersection.get("status") == "usable" and safe:
        top = safe[:5]
        terms = ", ".join(f"{r['keyword']} (ours #{r['our_rank']}, benchmark #{r['benchmark_rank']})" for r in top)
        results.append(_recommend(
            "generic-query-coverage", "Review intent coverage for relevant generic searches",
            "medium", "medium", "medium", "high",
            f"Shared keyword intersection, filtered generic competitor leads: {terms}.",
            "The competitor leads for these related queries in the saved DataForSEO dataset; these may rank different landing pages.",
            ["Verify the exact ranking URLs for each selected related query.",
             "Compare the relevant page sections, user intent and internal linking for those URLs.",
             "Only improve this page when the verified query intent matches its purpose."],
            "Monitor those same query positions and verify content changes against their intent.",
            "Lexical relevance screening is conservative, not semantic intent analysis; third-party or unfamiliar terms require review.",
            ours_url))

    metadata = (
        (
            "title_keyword_match", "HTML title", "medium", "high",
            "HTML title can help communicate page topic to search engines.",
            "Google may rewrite the displayed search-result title; exact keyword presence alone is not a ranking-quality metric.",
        ),
        (
            "meta_keyword_match", "meta description", "low", "medium",
            "Meta descriptions can affect search-result snippets and clicks; keyword presence is not a direct ranking boost.",
            "Google may generate its own search-result snippet instead of using the meta description. Editing it does not guarantee higher rankings or clicks.",
        ),
        (
            "h1_keyword_match", "main H1", "medium", "high",
            "A descriptive H1 helps users understand the page topic.",
            "An exact-match keyword in an H1 is not required; the heading should accurately describe the visible page content.",
        ),
    )
    for field, label, impact, relevance, role, caveat in metadata:
        row = (onpage or {}).get(field) or {}
        if row.get("ours") is False and row.get("competitor") is True:
            results.append(_recommend(
                "onpage-" + field, f"Verify {label} targeting for the selected keyword",
                impact, "medium", "low", relevance,
                f"Keyword '{keyword}' was not detected in our captured {label}, but was detected in the competitor's.",
                f"This is a captured-page difference, not a verified defect. {role}",
                ["First verify the current rendered HTML and canonical response at the exact ranking URL.",
                 f"If the {label} is genuinely generic or misleading, propose an accurate, natural topic-specific revision.",
                 "Review the proposed text with the SEO/content owner before publishing."],
                "Recrawl the exact URL after approval and compare search appearance over time.",
                caveat,
                ours_url, action_type="verify_before_edit"))

    # Detailed investigations are accepted only after the analysis pipeline has
    # validated both exact SERP URLs and the mobile Lighthouse audits.
    detailed = ((technical_comparison or {}).get("mobile") or {}).get("detailed_analysis") or {}
    verified_investigations = (
        [row for row in detailed.get("investigations", []) if isinstance(row, dict)
         and row.get("confidence") == "investigation_only" and row.get("title")
         and row.get("supporting_observation") and row.get("actions")]
        if detailed.get("status") == "usable" and detailed.get("scope") == "exact_serp_pages_mobile_lab"
        else []
    )
    technical = (advanced_evidence or {}).get("technical") or {}
    for device, data in technical.items():
        metrics = data.get("lab_metrics") or {}
        lcp = (metrics.get("largest_contentful_paint_ms") or {}).get("ours")
        tbt = (metrics.get("total_blocking_time_ms") or {}).get("ours")
        cls = (metrics.get("cumulative_layout_shift") or {}).get("ours")
        issues = []
        if _num(lcp) and lcp > 4000:
            issues.append(f"LCP {lcp / 1000:.2f}s")
        if _num(tbt) and tbt > 600:
            issues.append(f"TBT {tbt:.0f}ms")
        if _num(cls) and cls > 0.25:
            issues.append(f"CLS {cls:.3f}")
        if issues:
            has_detail = device == "mobile" and bool(verified_investigations)
            if has_detail:
                areas = {row.get("area") for row in verified_investigations}
                labels = (("javascript_execution", "JavaScript execution"),
                          ("unused_javascript", "unused JavaScript"),
                          ("image_delivery", "image delivery"),
                          ("render_blocking", "render-blocking resources"))
                observed = [label for key, label in labels if key in areas]
                detail_text = ", ".join(observed)
                actions = [
                    "Review the verified resource-level Lighthouse investigations in the technical section of the report.",
                    "Profile identified scripts and assets before modifying their loading behavior; preserve essential security and business functionality.",
                    "Repeat controlled mobile Lighthouse audits and test core user flows after changes.",
                ]
                caveat = ("Detailed Lighthouse diagnostics identify investigation targets (" + detail_text +
                          "), but the precise cause of slow LCP and any ranking impact remain unverified.")
            else:
                actions = ["Inspect the raw Lighthouse report for LCP element, render-blocking resources and long tasks.",
                           "Only identify a concrete cause after reviewing the raw diagnostic details.",
                           "Profile JavaScript and asset loading, then repeat comparable audits after any change."]
                caveat = "Only summary lab metrics are currently available; root causes and ranking impact are not established."
            results.append(_recommend(
                f"technical-{device}", f"Investigate {device} page-loading bottlenecks",
                "high", "high", "high", "high",
                f"Our {device} Lighthouse lab audit: " + ", ".join(issues) + ".",
                "Lab measurements indicate potential user-experience issues; they do not establish a ranking cause.",
                actions,
                "Repeat controlled lab audits and check field Core Web Vitals separately where available.",
                caveat,
                ours_url))

    # Deterministic tie-break: lower effort first; if effort ties, stable ID.
    # The score is an ordinal triage rubric, never a predicted ranking uplift.
    effort_rank = {"low": 0, "medium": 1, "high": 2}
    results.sort(key=lambda r: (-r["priority_score"], effort_rank[r["implementation_effort"]], r["id"]))
    for index, row in enumerate(results, 1):
        row["order"] = index
        row["tie_break_explanation"] = None

    # Explain every equal-score group, including the last item in the group.
    from itertools import groupby
    for score, grouped in groupby(results, key=lambda r: r["priority_score"]):
        peers = list(grouped)
        if len(peers) < 2:
            continue
        for position, row in enumerate(peers):
            if position == 0:
                next_row = peers[1]
                if effort_rank[row["implementation_effort"]] < effort_rank[next_row["implementation_effort"]]:
                    reason = (f"Placed before '{next_row['title']}' because estimated effort is "
                              f"{row['implementation_effort']} versus {next_row['implementation_effort']}.")
                else:
                    reason = "Equal effort; stable recommendation ID determines order."
            else:
                prev_row = peers[position - 1]
                if effort_rank[row["implementation_effort"]] > effort_rank[prev_row["implementation_effort"]]:
                    reason = (f"Placed after '{prev_row['title']}' because estimated effort is "
                              f"{row['implementation_effort']} versus {prev_row['implementation_effort']}.")
                else:
                    reason = "Equal effort; stable recommendation ID determines order."
            row["tie_break_explanation"] = (f"Equal triage score ({score}); {reason} "
                                             "This is a workflow tie-break, not a ranking-impact prediction.")
    return results


def format_recommendations_report(keyword, urls, findings, recommendations, quality):
    lines = ["=== SEO PHASE 2 RECOMMENDATION REPORT ===", f"Keyword: {keyword}",
             f"Our ranking URL: {urls.get('ours')}", f"Benchmark ranking URL: {urls.get('benchmark')}",
             f"Findings: {len(findings)}", f"Recommendations: {len(recommendations)}", ""]
    lines += ["=== EVIDENCE QUALITY ==="]
    lines += [f"{k}: {v}" for k, v in quality.items()]
    lines += ["", "=== PRIORITIZED RECOMMENDATIONS ==="]
    if not recommendations:
        lines.append("No supported recommendations generated from currently verified evidence.")
    for item in recommendations:
        lines += [
            f"{item['order']}. {item['title']}",
            f"   Priority: {item['priority']} (triage score {item['priority_score']}; not a ranking forecast)",
            f"   Potential impact: {item['potential_impact']} (not a rank-lift forecast)",
            f"   Evidence confidence: {item['evidence_confidence']}",
            f"   Implementation effort: {item['implementation_effort']}",
            f"   Keyword relevance: {item['keyword_relevance']}",
            f"   Action type: {item['action_type']}",
            f"   Target URL: {item['target_url']}",
            f"   Evidence: {item['evidence']}",
            f"   Interpretation: {item['interpretation']}",
        ]
        if item.get("tie_break_explanation"):
            lines.append(f"   Priority tie-break: {item['tie_break_explanation']}")
        lines += [f"   Action: {action}" for action in item["actions"]]
        lines += [f"   Validate: {item['success_check']}", f"   Caveat: {item['limitations']}", ""]
    lines += ["Important: Differences are observational, not proof of search-ranking causation or guaranteed uplift."]
    return "\n".join(lines) + "\n"
