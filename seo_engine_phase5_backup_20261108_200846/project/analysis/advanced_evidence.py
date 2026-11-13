"""Keyword-independent, evidence-scoped comparisons for Phase 2.

All comparisons are descriptive. A link metric or Lighthouse score does not
establish causation for a Google ranking difference.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit
from analysis.backlinks import compare_backlink_summaries


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def hostname(value):
    if not isinstance(value, str) or not value.strip():
        return ""
    raw = value.strip()
    host = urlsplit(raw if "://" in raw else "https://" + raw).hostname or ""
    return host.lower().removeprefix("www.")


def domain_target_ok(data, expected_domain):
    """Do not silently use backlinks from an unrelated domain or page."""
    if not isinstance(data, dict) or not data:
        return False
    target = data.get("target")
    return (data.get("scope") == "domain" and hostname(target) == hostname(expected_domain))


def _brand_marker(domain):
    return hostname(domain).split(".")[0].replace("-", "").replace("_", "")


def classify_keyword(keyword, domains):
    collapsed = re.sub(r"[^a-z0-9]", "", (keyword or "").casefold())
    return "branded" if any(m and m in collapsed for m in map(_brand_marker, domains)) else "generic"


# Conservative, keyword-independent modifiers. Unrecognized terms are REVIEW,
# not automatically a generic opportunity. This deliberately favors precision.
_GENERIC_MODIFIERS = set("""
play playing online game games gaming casino casinos bet bets betting
how to what is are does work works rules guide guides tips explained
free demo practice mobile app apps download start now live real money
best where can i we you the a an on in at for with of from south africa
sites site website websites time when ways learn information about strategy
strategies beginner beginners official""".split())
_DOMAIN_MARKERS = {"www", "http", "https", "com", "net", "org", "co", "za", "io", "gov", "edu"}


def classify_opportunity_relevance(term, keyword, domains):
    """Return (class, reason) for one possible query opportunity.

    'relevant_generic' is a conservative lexical check, not semantic intent.
    Unknown tokens are kept for human review, not silently discarded as bad.
    """
    if not isinstance(term, str) or not term.strip() or not isinstance(keyword, str) or not keyword.strip():
        return "needs_review", "missing_query_or_keyword"
    text = term.casefold()
    if classify_keyword(term, domains) == "branded":
        return "tracked_brand", "tracked_domain_brand"
    if re.search(r"(?:https?://|www\.|\.[a-z]{2,}(?:/|$))", text):
        return "third_party_navigational", "url_like_query"
    term_tokens = re.findall(r"[a-z0-9]+", text)
    keyword_tokens = re.findall(r"[a-z0-9]+", keyword.casefold())
    if not keyword_tokens or not all(t in term_tokens for t in keyword_tokens):
        return "needs_review", "keyword_phrase_not_covered"
    remainder = [t for t in term_tokens if t not in set(keyword_tokens)]
    if any(t in _DOMAIN_MARKERS for t in remainder):
        return "third_party_navigational", "domain_marker"
    unknown = [t for t in remainder if t not in _GENERIC_MODIFIERS]
    if unknown:
        return "needs_review", "unrecognized_modifiers:" + ",".join(unknown[:4])
    return "relevant_generic", "known_generic_query_modifiers"


def _safe_result_observation(row, expected_domain):
    """Keep only same-domain organic landing-page identity for a query row."""
    if not isinstance(row, dict):
        return {}
    url = row.get("url")
    if not isinstance(url, str):
        return {}
    try:
        parsed = urlsplit(url)
    except ValueError:
        return {}
    host = (parsed.hostname or "").lower().removeprefix("www.")
    expected = hostname(expected_domain)
    if (parsed.scheme not in {"http", "https"} or not expected or
            not (host == expected or host.endswith("." + expected))):
        return {}
    return {
        "rank": number(row.get("rank_group") or row.get("rank_absolute")),
        "domain": host,
        "title": row.get("title")[:240] if isinstance(row.get("title"), str) else None,
        "url": urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", "", "")),
    }


def analyze_intersection(data, *, keyword, our_domain, benchmark_domain):
    result = {"status": "unavailable", "scope": "domain_keyword_intersection", "shared_only": True,
              "returned": 0, "total_count": None, "ours_ahead": 0, "benchmark_ahead": 0,
              "ties": 0, "generic_ours_ahead": 0, "generic_benchmark_ahead": 0,
              "branded_ours_ahead": 0, "branded_benchmark_ahead": 0,
              "top_generic_benchmark_leads": [], "related_generic_queries": [],
              "excluded_opportunities": [], "review_opportunities": [], "warnings": []}
    if not isinstance(data, dict) or not data:
        result["warnings"].append("No domain intersection data collected")
        return result
    if data.get("scope") != "domain_keyword_intersection":
        result["warnings"].append("Unexpected intersection scope; evidence withheld")
        return result
    if hostname(data.get("target1")) != hostname(our_domain) or hostname(data.get("target2")) != hostname(benchmark_domain):
        result["warnings"].append("Domain intersection targets do not match comparison domains; evidence withheld")
        return result
    if (data.get("analysis_keyword") or "").casefold() != (keyword or "").casefold():
        result["warnings"].append("Domain intersection keyword does not match current analysis; evidence withheld")
        return result
    result["status"] = "usable"
    result["total_count"] = data.get("total_count")
    candidates = []
    related_queries = []
    for row in data.get("items") or []:
        if not isinstance(row, dict):
            continue
        term = row.get("keyword") or ""
        if keyword.casefold() not in term.casefold():
            result["warnings"].append("Ignored keyword unrelated to selected phrase")
            continue
        ours = number(row.get("our_rank"))
        benchmark = number(row.get("benchmark_rank"))
        if ours is None or benchmark is None or ours <= 0 or benchmark <= 0:
            continue
        result["returned"] += 1
        brand_type = classify_keyword(term, (our_domain, benchmark_domain))
        relevance, reason = classify_opportunity_relevance(term, keyword, (our_domain, benchmark_domain))
        if brand_type == "generic" and relevance == "relevant_generic":
            first_result = _safe_result_observation(row.get("first_domain_serp_element"), our_domain)
            second_result = _safe_result_observation(row.get("second_domain_serp_element"), benchmark_domain)
            related_queries.append({
                "keyword": term, "our_rank": ours, "benchmark_rank": benchmark,
                "search_volume": number(row.get("search_volume")), "rank_gap": ours - benchmark,
                "relevance_class": relevance, "relevance_reason": reason,
                "ours_result": first_result, "benchmark_result": second_result,
            })
        if ours < benchmark:
            result["ours_ahead"] += 1
            result[f"{brand_type}_ours_ahead"] += 1
        elif benchmark < ours:
            result["benchmark_ahead"] += 1
            result[f"{brand_type}_benchmark_ahead"] += 1
            if brand_type == "generic":
                candidate = {"keyword": term, "our_rank": ours, "benchmark_rank": benchmark,
                             "search_volume": number(row.get("search_volume")), "rank_gap": ours - benchmark}
                candidate["relevance_class"] = relevance
                candidate["relevance_reason"] = reason
                candidate["ours_result"] = _safe_result_observation(row.get("first_domain_serp_element"), our_domain)
                candidate["benchmark_result"] = _safe_result_observation(row.get("second_domain_serp_element"), benchmark_domain)
                if relevance == "relevant_generic":
                    candidates.append(candidate)
                elif relevance == "third_party_navigational":
                    result["excluded_opportunities"].append(candidate)
                else:
                    result["review_opportunities"].append(candidate)
        else:
            result["ties"] += 1
    candidates.sort(key=lambda x: (x["search_volume"] is not None, x["search_volume"] or 0, x["rank_gap"]), reverse=True)
    result["top_generic_benchmark_leads"] = candidates[:10]
    related_queries.sort(key=lambda x: (x["search_volume"] is not None, x["search_volume"] or 0,
                                        abs(x["rank_gap"])), reverse=True)
    result["related_generic_queries"] = related_queries[:40]
    result["generic_relevance_policy"] = "Only recognized generic modifiers are recommended automatically; unfamiliar names require review."
    if number(result["total_count"]) is not None and result["total_count"] > len(data.get("items") or []):
        result["warnings"].append("API result is limited; counts reflect only returned shared keywords")
    result["warnings"].append("Intersection contains shared keywords only; it cannot establish missing rankings")
    return result


def analyze_backlinks(page_ours, page_benchmark, domain_ours, domain_benchmark, our_domain, benchmark_domain):
    out = {"page": {}, "domain": {}, "warnings": []}
    if page_ours and page_benchmark:
        out["page"] = compare_backlink_summaries(page_ours, page_benchmark)
    else:
        out["warnings"].append("One or both page-level backlink datasets unavailable or URL-unverified")
    if domain_target_ok(domain_ours, our_domain) and domain_target_ok(domain_benchmark, benchmark_domain):
        out["domain"] = compare_backlink_summaries(domain_ours, domain_benchmark)
    else:
        out["warnings"].append("One or both domain backlink targets missing or unverified; domain comparison withheld")
    out["scope_note"] = "Page backlinks refer to ranking URLs; domain backlinks are separate contextual metrics."
    return out


def analyze_technical(lighthouse):
    out = {}
    for device in ("mobile", "desktop"):
        a = (lighthouse.get("ours") or {}).get(device) or {}
        b = (lighthouse.get("benchmark") or {}).get(device) or {}
        if not a or not b:
            continue
        score_keys = ("performance", "accessibility", "best-practices", "seo")
        metric_keys = ("largest_contentful_paint_ms", "first_contentful_paint_ms", "total_blocking_time_ms", "cumulative_layout_shift", "speed_index_ms")
        scores = {key: {"ours": number((a.get("scores") or {}).get(key)),
                        "benchmark": number((b.get("scores") or {}).get(key))} for key in score_keys}
        metrics = {key: {"ours": number((a.get("lab_metrics") or {}).get(key)),
                         "benchmark": number((b.get("lab_metrics") or {}).get(key))} for key in metric_keys}
        out[device] = {"scores": scores, "lab_metrics": metrics,
                       "scope_note": "Single Lighthouse lab runs; not field Core Web Vitals or ranking causality."}
    return out


def build_advanced_evidence(*, keyword, our_domain, benchmark_domain, domain_intersection,
                            page_backlinks_ours, page_backlinks_benchmark,
                            domain_backlinks_ours, domain_backlinks_benchmark,
                            lighthouse):
    return {
        "keyword_intersection": analyze_intersection(domain_intersection, keyword=keyword,
                                                       our_domain=our_domain, benchmark_domain=benchmark_domain),
        "backlinks": analyze_backlinks(page_backlinks_ours, page_backlinks_benchmark,
                                      domain_backlinks_ours, domain_backlinks_benchmark,
                                      our_domain, benchmark_domain),
        "technical": analyze_technical(lighthouse),
    }
