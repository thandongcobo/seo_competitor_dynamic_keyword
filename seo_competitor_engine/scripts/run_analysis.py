from __future__ import annotations

from collectors.dataforseo_client import load_json, save_json
from config.settings import PROCESSED_DIR, RESULTS_DIR, settings, KEYWORD_SLUG
from analysis.rankings import compare_rankings
from analysis.keywords import compare_ranked_keywords
from analysis.backlinks import compare_backlink_summaries
from analysis.onpage import compare_pages
from analysis.technical_diagnostics import compare_technical
from analysis.intent import assess_intent_alignment
from analysis.comparison_engine import build_findings
from analysis.advanced_evidence import build_advanced_evidence
from analysis.recommendations import generate_recommendations, format_recommendations_report
from analysis.competitors import extract_labs_competitor_domains, merge_candidate_sources
from scripts.resolve_pages import normalized_url


def maybe(name: str, default=None):
    path = PROCESSED_DIR / name
    return load_json(path) if path.exists() else default


def validate_page(page: dict, expected_url: str | None, side: str) -> tuple[dict, str]:
    if not expected_url:
        return {}, f"{side}: no Google SERP ranking URL"
    if not page:
        return {}, f"{side}: no normalized page data"
    if normalized_url(page.get("ranking_url") or page.get("requested_url")) != normalized_url(expected_url):
        return {}, f"{side}: page data belongs to a different ranking URL"
    if page.get("url_alignment") != "matched":
        return {}, f"{side}: page redirect or URL identity not verified"
    if page.get("crawl_failed") or page.get("extraction_status") != "complete":
        return {}, f"{side}: page crawl was incomplete or blocked"
    # A page with only navigation/footer content can pass the crawler's generic readiness test.
    if not isinstance(page.get("word_count"), int) or page["word_count"] < 200:
        return {}, f"{side}: limited extracted content coverage (under 200 words); review later"
    return page, "usable"


def validate_backlinks(data: dict, expected_url: str | None, side: str) -> tuple[dict, str]:
    if not data or not expected_url:
        return {}, f"{side}: no page-level backlink evidence"
    if data.get("scope") != "page" or not data.get("target_verified"):
        return {}, f"{side}: page backlink target not verified"
    if normalized_url(data.get("target")) != normalized_url(expected_url):
        return {}, f"{side}: backlinks refer to another page"
    return data, "usable"


def main() -> None:
    serp_google = maybe("serp_google.json", {})
    serp_bing = maybe("serp_bing.json", {})

    ranking_summary = {}
    for engine, data in [("google", serp_google), ("bing", serp_bing)]:
        if data:
            ranking_summary[engine] = compare_rankings(data, settings.our_domain, settings.benchmark_competitor_domain)

    google_rank = ranking_summary.get("google", {})

    cross_engine = {
        "google_ours": ranking_summary.get("google", {}).get("our_position"),
        "google_benchmark": ranking_summary.get("google", {}).get("benchmark_position"),
        "bing_ours": ranking_summary.get("bing", {}).get("our_position"),
        "bing_benchmark": ranking_summary.get("bing", {}).get("benchmark_position"),
        "both_found": all([
            ranking_summary.get("google", {}).get("our_position") is not None,
            ranking_summary.get("google", {}).get("benchmark_position") is not None,
            ranking_summary.get("bing", {}).get("our_position") is not None,
            ranking_summary.get("bing", {}).get("benchmark_position") is not None,
        ]) if ranking_summary else False,
    }

    ranked_ours = maybe("ranked_ours.json", {"items": []})
    ranked_benchmark = maybe("ranked_benchmark.json", {"items": []})
    domain_intersection = maybe("domain_intersection.json", {})
    backlink_ours = maybe("backlinks_ours_page_summary.json", {})
    backlink_benchmark = maybe("backlinks_benchmark_page_summary.json", {})
    page_ours = maybe("page_ours.json", {})
    page_benchmark = maybe("page_benchmark.json", {})
    targets = {"ours": google_rank.get("our_url"), "benchmark": google_rank.get("benchmark_url")}
    page_ours, page_ours_status = validate_page(page_ours, targets["ours"], "ours")
    page_benchmark, page_benchmark_status = validate_page(page_benchmark, targets["benchmark"], "benchmark")
    backlink_ours, backlink_ours_status = validate_backlinks(backlink_ours, targets["ours"], "ours")
    backlink_benchmark, backlink_benchmark_status = validate_backlinks(backlink_benchmark, targets["benchmark"], "benchmark")
    evidence_quality = {
        "page_ours": page_ours_status, "page_benchmark": page_benchmark_status,
        "backlinks_ours_page": backlink_ours_status, "backlinks_benchmark_page": backlink_benchmark_status,
    }
    search_intent = maybe("search_intent.json", {})
    labs_competitors = maybe("competitors_domain.json", {})
    resolved_candidates = maybe("resolved_candidates.json", {"potential_competitors_from_serp": []})

    keyword_gap = compare_ranked_keywords(ranked_ours, ranked_benchmark)
    backlink_gap = compare_backlink_summaries(backlink_ours, backlink_benchmark)
    onpage = compare_pages(page_ours, page_benchmark, settings.keyword) if page_ours and page_benchmark else {}
    intent = assess_intent_alignment(search_intent, onpage) if search_intent else {}

    serp_candidates = resolved_candidates.get("potential_competitors_from_serp", [])
    labs_candidates = extract_labs_competitor_domains(
        labs_competitors,
        exclude={settings.our_domain, settings.benchmark_competitor_domain},
    )
    candidates = merge_candidate_sources(
        serp_candidates,
        labs_candidates,
        settings.benchmark_competitor_domain,
        settings.our_domain,
    )

    # Optional local Lighthouse audits are page-level evidence, not field CWV.
    lighthouse = {side: {device: maybe(f"lighthouse_{side}_{device}.json", {})
                         for device in ("mobile", "desktop")}
                  for side in ("ours", "benchmark")}
    for side in ("ours", "benchmark"):
        for device, audit in lighthouse[side].items():
            if not audit:
                continue
            aligned = (audit.get("status") == "usable"
                       and normalized_url(audit.get("ranking_url")) == normalized_url(targets[side])
                       and audit.get("target_verified") and audit.get("final_url_verified"))
            if not aligned:
                evidence_quality[f"lighthouse_{side}_{device}"] = "unusable or URL mismatch; scores withheld"
                lighthouse[side][device] = {}
            else:
                evidence_quality[f"lighthouse_{side}_{device}"] = "usable"

    domain_backlinks_ours = maybe("backlinks_ours_domain_summary.json", {})
    domain_backlinks_benchmark = maybe("backlinks_benchmark_domain_summary.json", {})
    advanced = build_advanced_evidence(
        keyword=settings.keyword,
        our_domain=settings.our_domain,
        benchmark_domain=settings.benchmark_competitor_domain,
        domain_intersection=domain_intersection,
        page_backlinks_ours=backlink_ours,
        page_backlinks_benchmark=backlink_benchmark,
        domain_backlinks_ours=domain_backlinks_ours,
        domain_backlinks_benchmark=domain_backlinks_benchmark,
        lighthouse=lighthouse,
    )

    findings = build_findings(
        ranking_summary,
        cross_engine,
        keyword_gap,
        backlink_gap,
        onpage,
        intent,
        candidates,
        evidence_quality=evidence_quality,
        advanced_evidence=advanced,
    )

    # Technical comparisons are descriptive. A Lighthouse score does not establish causality.
    technical_comparison = {}
    for device in ("mobile", "desktop"):
        ours_audit = lighthouse["ours"][device]
        benchmark_audit = lighthouse["benchmark"][device]
        if not ours_audit or not benchmark_audit:
            continue
        technical_comparison[device] = {
            "scores": {key: {"ours": ours_audit["scores"].get(key),
                             "benchmark": benchmark_audit["scores"].get(key)}
                       for key in ("performance", "accessibility", "best-practices", "seo")},
            "lab_metrics": {key: {"ours": ours_audit["lab_metrics"].get(key),
                                  "benchmark": benchmark_audit["lab_metrics"].get(key)}
                            for key in ours_audit.get("lab_metrics", {})},
            "interpretation": "Lab observations only; no ranking causality or field CWV inferred.",
            "detailed_analysis": (compare_technical(ours_audit, benchmark_audit, expected_urls=targets)
                                  if device == "mobile" else
                                  {"status": "withheld", "reason": "Detailed comparison currently supports mobile only.",
                                   "observations": [], "investigations": []}),
        }
    result = {
        "schema_version": "0.5",
        "primary_ranking_urls": targets,
        "evidence_quality": evidence_quality,
        "page_level_evidence": {"ours": page_ours, "benchmark": page_benchmark, "backlinks_ours": backlink_ours, "backlinks_benchmark": backlink_benchmark, "lighthouse": lighthouse},
        "technical_comparison": technical_comparison,
        "advanced_evidence": advanced,
        "domain_level_evidence": {"ranked_ours": ranked_ours, "ranked_benchmark": ranked_benchmark, "domain_intersection": domain_intersection, "backlinks_ours": domain_backlinks_ours, "backlinks_benchmark": domain_backlinks_benchmark},
        "keyword": settings.keyword,
        "location_coordinate": settings.location_coordinate,
        "labs_location": settings.labs_location_name,
        "our_domain": settings.our_domain,
        "benchmark_competitor_domain": settings.benchmark_competitor_domain,
        "ranking_summary": ranking_summary,
        "cross_engine_summary": cross_engine,
        "keyword_comparison": keyword_gap,
        "backlink_comparison": backlink_gap,
        "onpage_comparison": onpage,
        "intent_alignment": intent,
        "potential_competitors": candidates,
        "analysis_policy": {
            "overall_score": "Not used.",
            "confidence": "Findings are labelled high/medium/low based on evidence strength.",
            "estimated_metrics": "Traffic/search-volume style estimates are comparative supporting signals, not exact measurements.",
            "causation": "Observed differences do not prove a search engine used that signal as the cause of the ranking difference.",
            "url_first": "Page-level evidence is only compared when it matches the exact Google SERP ranking URL.",
            "coverage": "Incomplete, redirected or thin crawls are withheld from comparative page findings.",
            "lighthouse": "Local lab metrics only. Missing, redirected or failed audits are not interpreted as zero or poor SEO. A usable Lighthouse audit does not independently verify full SEO-content rendering.",
            "competitor_definition": "Potential competitor = a domain with meaningful SERP/Labs evidence of competing with our search demand; classification is evidence-based and may remain provisional.",
        },
        "findings": findings,
        "llm_ready": {
            "task": "Explain why the benchmark competitor may outrank our website for the target keyword and identify evidence-backed improvement opportunities.",
            "instruction": "Use only the evidence supplied in this JSON. Separate observed facts from hypotheses. Do not claim access to Google/Bing ranking weights. Do not invent missing metrics.",
        },
    }
    recommendations = generate_recommendations(
        keyword=settings.keyword,
        ranking_urls=targets,
        advanced_evidence=advanced,
        onpage=onpage,
        technical_comparison=technical_comparison,
    )
    result["recommendations"] = recommendations
    result["recommendation_policy"] = {
        "impact": "Qualitative opportunity estimates only; no invented ranking, click, or revenue uplift.",
        "priority": "Implementation triage, separate from evidence confidence.",
        "method": "Deterministic evidence-based rules; not an LLM or a causal model.",
    }
    out = RESULTS_DIR / f"{KEYWORD_SLUG}_comparison.json"
    save_json(result, out)
    report_path = RESULTS_DIR / f"{KEYWORD_SLUG}_recommendations.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(format_recommendations_report(
        settings.keyword, targets, findings, recommendations, evidence_quality), encoding="utf-8")
    print(f"Analysis complete: {out}")
    print(f"Recommendation report: {report_path}")
    print(f"Recommendations produced: {len(recommendations)}")
    print(f"Findings produced: {len(findings)}")
    print(f"Potential competitors identified: {len(candidates)}")
    for finding in findings:
        print(f"- [{finding['confidence'].upper()}] {finding['category']}: {finding['evidence']}")


if __name__ == "__main__":
    main()
