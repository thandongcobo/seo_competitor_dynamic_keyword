"""Deterministic, evidence-traceable SEO report from the existing comparison JSON.

No API calls, no LLM, no invented rank or traffic uplift. All comparisons are
scoped to the exact ranking URLs and the data quality of the source evidence.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any
from analysis.seo_content_validation import compare as compare_seo_content


def obj(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def items(value: Any) -> list:
    return value if isinstance(value, list) else []


def numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def fmt(value: Any, suffix: str = "") -> str:
    if value is None or value == "":
        return "Not available"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, int):
        return f"{value:,}{suffix}"
    if isinstance(value, float):
        return f"{value:,.2f}{suffix}"
    return str(value)


def safe(value: Any, maxlen: int = 500) -> str:
    """Escape untrusted scalar content in Markdown table cells."""
    if isinstance(value, (list, dict)):
        value = str(value)
    result = fmt(value).replace("\r", " ").replace("\n", " ").replace("|", "\\|")
    result = result.replace("`", "'").replace("<", "&lt;").replace(">", "&gt;")
    return result[:maxlen] + ("…" if len(result) > maxlen else "")


def table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    lines = ["| " + " | ".join(safe(x) for x in headers) + " |",
             "| " + " | ".join("---" for _ in headers) + " |"]
    lines += ["| " + " | ".join(safe(v) for v in row) + " |" for row in rows]
    return lines


def side_name(domain: Any, fallback: str) -> str:
    return str(domain).strip() or fallback


def leader(ours: Any, benchmark: Any, our_label: str, benchmark_label: str,
           higher: bool = True) -> str:
    if not numeric(ours) or not numeric(benchmark):
        return "Not assessed"
    if ours == benchmark:
        return "Equal"
    better_ours = ours > benchmark if higher else ours < benchmark
    return our_label if better_ours else benchmark_label


def ms(value: Any) -> str:
    return f"{value / 1000:,.2f} s" if numeric(value) else "Not available"


def valid_page(data: dict, quality: dict, side: str, urls: dict) -> bool:
    if quality.get(f"page_{side}") != "usable":
        return False
    page = obj(data.get(side))
    if not page:
        return False
    expected = urls.get(side)
    actual = page.get("ranking_url") or page.get("requested_url")
    return bool(expected and actual and actual.rstrip("/").lower() == expected.rstrip("/").lower()
                and page.get("url_alignment") == "matched")


def valid_page_links(data: dict, quality: dict, side: str, urls: dict) -> bool:
    if quality.get(f"backlinks_{side}_page") != "usable":
        return False
    key = "backlinks_ours" if side == "ours" else "backlinks_benchmark"
    links = obj(data.get(key))
    return bool(links.get("scope") == "page" and links.get("target_verified")
                and links.get("target", "").rstrip("/").lower() == str(urls.get(side) or "").rstrip("/").lower())


def valid_mobile(data: dict, quality: dict, side: str, urls: dict) -> dict:
    if quality.get(f"lighthouse_{side}_mobile") != "usable":
        return {}
    audit = obj(obj(obj(data.get("lighthouse")).get(side)).get("mobile"))
    if audit.get("status") != "usable" or not audit.get("target_verified") or not audit.get("final_url_verified"):
        return {}
    if str(audit.get("ranking_url") or "").rstrip("/").lower() != str(urls.get(side) or "").rstrip("/").lower():
        return {}
    return audit


def domain_key(value: Any) -> str:
    """Compare hostnames, not display names or paths; no network calls."""
    value = str(value or "").strip().lower()
    if not value:
        return ""
    host = urlsplit(value if "://" in value else "https://" + value).hostname or ""
    return host.removeprefix("www.")


def stable_main_words(page: dict) -> tuple[Any, str]:
    """Use only explicitly rendered main-region measurements in the report.

    main_word_count is not necessarily the same extraction method; we retain
    it as diagnostic evidence rather than silently mixing the two definitions.
    """
    rendered = page.get("rendered_main_word_count")
    legacy = page.get("main_word_count")
    if numeric(rendered) and rendered >= 0:
        return rendered, "rendered_main_word_count"
    return None, "not measured by the rendered main-region method"


def main_count_discrepancy(page: dict) -> bool:
    rendered = page.get("rendered_main_word_count")
    legacy = page.get("main_word_count")
    return (numeric(rendered) and numeric(legacy) and
            abs(rendered - legacy) > max(100, 0.20 * max(rendered, legacy, 1)))


def displayed_discovery_finding(finding: dict, *, benchmark_domain: str,
                                benchmark_rank: Any, engine: str) -> str:
    """Do not propagate misleading discovery-only 'not local-rank' metadata."""
    raw = str(finding.get("evidence") or "")
    if finding.get("category") != "competitor_discovery" or not benchmark_domain:
        return raw
    if not numeric(benchmark_rank):
        return raw
    # Keep the original discovery observation while correcting the one confirmed
    # benchmark entry. Other discovery labels are left untouched.
    import re
    pattern = re.compile(r"(?<![\w.-])" + re.escape(benchmark_domain) +
                         r"\s*\(not local-rank\)", re.IGNORECASE)
    return pattern.sub(lambda _: f"{benchmark_domain} (confirmed {engine} #{benchmark_rank}; discovery rank unavailable)", raw)


def generate_report(data: dict, *, source_name: str = "comparison.json") -> str:
    if not isinstance(data, dict):
        raise ValueError("Comparison JSON root must be an object")
    keyword = str(data.get("keyword") or "").strip()
    if not keyword:
        raise ValueError("Comparison JSON has no keyword")
    urls = obj(data.get("primary_ranking_urls"))
    quality = obj(data.get("evidence_quality"))
    pages = obj(data.get("page_level_evidence"))
    domain = obj(data.get("domain_level_evidence"))
    advanced = obj(data.get("advanced_evidence"))
    ranking = obj(data.get("ranking_summary"))
    onpage = obj(data.get("onpage_comparison"))
    our_label = side_name(data.get("our_domain"), "Our site")
    comp_label = side_name(data.get("benchmark_competitor_domain"), "Competitor")
    google = obj(ranking.get("google"))
    engine_name = "Google" if google else "Available search engines"
    our_rank = google.get("our_position")
    comp_rank = google.get("benchmark_position")
    page_ok = {s: valid_page(pages, quality, s, urls) for s in ("ours", "benchmark")}
    links_ok = {s: valid_page_links(pages, quality, s, urls) for s in ("ours", "benchmark")}
    audit = {s: valid_mobile(pages, quality, s, urls) for s in ("ours", "benchmark")}
    bpage = obj(obj(advanced.get("backlinks")).get("page"))
    bdomain = obj(obj(advanced.get("backlinks")).get("domain"))
    intersection = obj(advanced.get("keyword_intersection"))
    recommendations = sorted((r for r in items(data.get("recommendations")) if isinstance(r, dict)),
                             key=lambda r: (r.get("order") if isinstance(r.get("order"), int) else 9999,
                                            -(r.get("priority_score") if numeric(r.get("priority_score")) else -1)))
    findings = [f for f in items(data.get("findings")) if isinstance(f, dict)]

    lines: list[str] = []
    def add(*parts: str) -> None:
        lines.extend(parts)
    add(f"# SEO Competitive Investigation — {safe(keyword, 120)}", "",
        f"**Search market:** {safe(data.get('labs_location') or 'Not specified')}  ",
        f"**Primary search engine:** {engine_name}  ",
        f"**Our domain:** {safe(our_label)}  ",
        f"**Comparison domain:** {safe(comp_label)}  ",
        f"**Source:** `{safe(source_name, 140)}` (existing local analysis; no new search performed)  ",
        f"**Report generated (UTC):** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}  ", "",
        "## 1. Executive summary", "")
    if numeric(our_rank) and numeric(comp_rank):
        if our_rank > comp_rank:
            add(f"In the saved Google organic SERP, **{safe(comp_label)} ranked #{comp_rank}** and "
                f"**{safe(our_label)} ranked #{our_rank}**, a gap of {our_rank - comp_rank} position(s).")
        elif our_rank < comp_rank:
            add(f"In the saved Google organic SERP, **{safe(our_label)} ranked #{our_rank}** and "
                f"**{safe(comp_label)} ranked #{comp_rank}**.")
        else:
            add(f"Both domains were recorded at position #{our_rank} in the saved Google ranking data.")
    else:
        add("The saved Google SERP does not contain both verified ranking positions; no rank-gap conclusion is made.")
    add("", "The report compares **observed evidence**, not Google's internal ranking weights. "
        "A stronger measured signal is a possible explanation to investigate, not proof of causation.", "")
    if recommendations:
        add("**Recommended investigation order:** " + "; ".join(
            f"{r.get('order', i)}. {safe(r.get('title'), 120)}" for i, r in enumerate(recommendations[:5], 1)) + ".", "")
    else:
        add("No supported recommendations were available in the saved comparison JSON.", "")

    add("## 2. Rankings and exact page identity", "")
    add(*table(["Source", our_label, comp_label], [
        ["Saved Google organic position", f"#{our_rank}" if numeric(our_rank) else None,
         f"#{comp_rank}" if numeric(comp_rank) else None],
        ["Exact ranking URL", urls.get("ours"), urls.get("benchmark")],
        ["Page evidence aligned", "Yes" if page_ok["ours"] else "No / unavailable",
         "Yes" if page_ok["benchmark"] else "No / unavailable"],
    ]), "")
    add("**Evidence paths:** `ranking_summary.google`, `primary_ranking_urls`, "
        "`evidence_quality`, `page_level_evidence`. Ranking positions reflect the saved SERP context, "
        "not a continuously updated Google result.", "")
    # The confirmed comparison domain is not an unranked potential candidate.
    candidates = [r for r in items(data.get("potential_competitors")) if isinstance(r, dict)]
    confirmed_key = domain_key(comp_label)
    additional = [r for r in candidates if domain_key(r.get("domain")) != confirmed_key]
    if numeric(comp_rank):
        add(f"**Confirmed comparison competitor:** {safe(comp_label)} — #{comp_rank} in the saved Google SERP. "
            "A discovery-specific label such as 'not local-rank' means that the discovery record lacks a "
            "local rank; it does not negate the confirmed SERP position.", "")
    if candidates:
        add(f"**Additional discovery candidates:** {len(additional)} records (excluding the confirmed benchmark). "
            "These are provisional candidates, not verified ranking competitors.", "")
    if intersection.get("status") == "usable":
        rows = items(obj(domain.get("domain_intersection")).get("items"))
        exact = next((r for r in rows if isinstance(r, dict) and str(r.get("keyword", "")).casefold() == keyword.casefold()), None)
        if exact:
            add("**Separate DataForSEO observation for the exact keyword:** "
                f"{safe(our_label)} #{fmt(exact.get('our_rank'))}; "
                f"{safe(comp_label)} #{fmt(exact.get('benchmark_rank'))}. "
                "This is a different ranking dataset and must not overwrite the saved Google SERP positions.", "")

    add("## 3. On-page SEO comparison", "")
    def field(side: str, key: str) -> Any:
        return obj(pages.get(side)).get(key) if page_ok[side] else None
    seo_comparison = compare_seo_content(obj(pages.get("ours")), obj(pages.get("benchmark")), urls)
    if not (page_ok["ours"] and page_ok["benchmark"]):
        seo_comparison = dict(seo_comparison, comparable=False, ours=None, benchmark=None)
    def main_words(side: str):
        return seo_comparison["ours" if side == "ours" else "benchmark"] if seo_comparison["comparable"] else None
    def h1(side: str) -> str:
        headings = obj(field(side, "headings"))
        return "; ".join(str(x) for x in items(headings.get("h1"))) or "Not available"
    rows = [
        ["HTML title", field("ours", "title"), field("benchmark", "title")],
        ["Meta description", field("ours", "meta_description"), field("benchmark", "meta_description")],
        ["H1 headings", h1("ours"), h1("benchmark")],
        ["Body word count (includes non-main content)", field("ours", "word_count"), field("benchmark", "word_count")],
        ["Standardized cleaned rendered SEO-content words (same method only)", main_words("ours"), main_words("benchmark")],
        ["Internal links", field("ours", "internal_link_count"), field("benchmark", "internal_link_count")],
        ["Structured data blocks", field("ours", "structured_data_count"), field("benchmark", "structured_data_count")],
    ]
    add(*table(["Page factor", our_label, comp_label], rows), "")
    for title, key in (("Title", "title_keyword_match"), ("Meta description", "meta_keyword_match"), ("H1", "h1_keyword_match")):
        r = obj(onpage.get(key))
        if page_ok["ours"] and page_ok["benchmark"] and r:
            add(f"- **{title} keyword presence:** ours {fmt(r.get('ours'))}; competitor {fmt(r.get('competitor'))}.")
    add("", "**Measurement policy:** Only `seo_content_word_count` from the matching "
        "`rendered-main-innertext-v2` method is comparable. Both pages must have `verified_candidate` "
        "status, complete crawls, and exact ranking/requested/final URL alignment. "
        "Old HTML, body, and rendered-main counts remain diagnostics, not substitutes.", "")
    if seo_comparison["comparable"]:
        add(f"**Standardized measurement:** {safe(our_label)} {fmt(main_words('ours'))} words; "
            f"{safe(comp_label)} {fmt(main_words('benchmark'))} words. "
            "This is not a content-quality or keyword-relevance ranking.", "")
    else:
        add("**Comparison withheld:** standardized content evidence is not mutually verified. "
            f"Our page: {safe(seo_comparison['ours_validation'])}; "
            f"benchmark: {safe(seo_comparison['benchmark_validation'])}. "
            "Do not substitute legacy counts.", "")
    add("**Interpretation:** Exact-match keyword presence, content length and token similarity are "
        "diagnostic context, not standalone ranking scores. Body text can include navigation or unrelated content. "
        "A missing main-content measurement is not zero content.", "",
        "**Evidence paths:** `page_level_evidence.ours`, `page_level_evidence.benchmark`, `onpage_comparison`.", "")

    add("## 4. Backlink comparison — page versus domain", "")
    def backlink_value(scope: str, metric: str, side: str) -> Any:
        if scope == "page" and not links_ok[side]:
            return None
        if scope == "domain":
            raw = obj(domain.get("backlinks_ours" if side == "ours" else "backlinks_benchmark"))
            if not raw or raw.get("scope") != "domain" or raw.get("target_verified") is False:
                return None
            return raw.get(metric)
        raw = obj(pages.get("backlinks_ours" if side == "ours" else "backlinks_benchmark"))
        return raw.get(metric)
    backlink_rows = []
    for scope in ("page", "domain"):
        for key, name in (("rank", "DataForSEO backlink rank"), ("backlinks", "Total backlinks"),
                          ("referring_domains", "Referring domains"),
                          ("referring_main_domains", "Referring main domains"),
                          ("backlinks_spam_score", "Backlink spam score")):
            a, b = backlink_value(scope, key, "ours"), backlink_value(scope, key, "benchmark")
            winner = leader(a, b, our_label, comp_label) if key not in ("backlinks_spam_score",) else "Not inferred from score alone"
            backlink_rows.append([scope.title() + " — " + name, a, b, winner])
    add(*table(["Metric", our_label, comp_label, "Measured advantage"], backlink_rows), "")
    add("**Interpretation:** Page-level and domain-level backlink profiles are different evidence scopes. "
        "Backlink rank is a third-party metric, not Google's ranking position. "
        "More backlinks or a higher backlink rank does not prove that links caused a SERP difference. "
        "Aggregate spam scores do not establish that individual links are harmful.", "",
        "**Evidence paths:** `page_level_evidence.backlinks_ours`, "
        "`page_level_evidence.backlinks_benchmark`, `domain_level_evidence.backlinks_*`, "
        "`advanced_evidence.backlinks`.", "")

    add("## 5. Technical SEO and Lighthouse mobile lab results", "")
    if audit["ours"] or audit["benchmark"]:
        metric_rows = []
        for key, label in (("performance", "Performance score /100"), ("seo", "Lighthouse SEO score /100"),
                           ("accessibility", "Accessibility score /100"), ("best-practices", "Best practices score /100")):
            a = obj(audit["ours"].get("scores")).get(key)
            b = obj(audit["benchmark"].get("scores")).get(key)
            metric_rows.append([label, a, b, leader(a, b, our_label, comp_label)])
        for key, label, as_seconds, higher in (
            ("largest_contentful_paint_ms", "Largest Contentful Paint (LCP)", True, False),
            ("first_contentful_paint_ms", "First Contentful Paint (FCP)", True, False),
            ("total_blocking_time_ms", "Total Blocking Time (TBT)", False, False),
            ("cumulative_layout_shift", "Cumulative Layout Shift (CLS)", False, False),
            ("speed_index_ms", "Speed Index", True, False),
        ):
            a = obj(audit["ours"].get("lab_metrics")).get(key)
            b = obj(audit["benchmark"].get("lab_metrics")).get(key)
            show = (lambda v: ms(v)) if as_seconds else (lambda v: fmt(v, " ms") if key == "total_blocking_time_ms" else fmt(v))
            metric_rows.append([label, show(a), show(b), leader(a, b, our_label, comp_label, higher)])
        add(*table(["Mobile Lighthouse measure", our_label, comp_label, "Better lab result"], metric_rows), "")
        add("**Audit timestamps (UTC):** " + f"ours {safe(audit['ours'].get('fetch_time'))}; "
            f"competitor {safe(audit['benchmark'].get('fetch_time'))}.", "")
    else:
        add("No verified mobile Lighthouse audits available for both ranking URLs.", "")
    add("**Desktop audits:** " + ("not collected in this comparison." if not any(obj(obj(obj(pages.get("lighthouse")).get(s)).get("desktop")) for s in ("ours", "benchmark"))
                                 else "some desktop evidence is present; evaluate separately before comparison."), "",
        "**Interpretation:** These are single-run Lighthouse lab observations, not real-user Core Web Vitals. "
        "A higher overall score does not imply that every individual metric is better. "
        "Raw Lighthouse diagnostic opportunities are required to identify root causes.", "",
        "**Evidence paths:** `page_level_evidence.lighthouse`, `technical_comparison`, "
        "`advanced_evidence.technical`.", "")

    # Detailed engineering investigations are deliberately separate from SEO actions.
    # Require the same verified page identities as the Lighthouse summary above.
    detailed = obj(obj(data.get("technical_comparison")).get("mobile")).get("detailed_analysis")
    detailed = obj(detailed)
    add("### Detailed engineering investigations (mobile Lighthouse)", "")
    if not (audit["ours"] and audit["benchmark"] and detailed.get("status") == "usable"
            and detailed.get("scope") == "exact_serp_pages_mobile_lab"):
        add("Detailed technical investigations withheld: verified mobile audits for both saved "
            "SERP ranking URLs and a usable exact-page comparison are required.", "")
    else:
        investigations = [x for x in items(detailed.get("investigations")) if isinstance(x, dict)]
        order = {"high": 0, "medium": 1, "low": 2}
        investigations.sort(key=lambda x: (order.get(x.get("priority"), 3), str(x.get("area") or "")))
        if not investigations:
            add("No resource-specific technical investigations were supported by the available audits.", "")
        for index, investigation in enumerate(investigations, 1):
            title = safe(investigation.get("title") or investigation.get("area") or "Investigation", 180)
            add(f"#### {index}. {title}", "",
                f"**Engineering priority:** {safe(investigation.get('priority'))}  ",
                f"**Audit:** `{safe(investigation.get('audit_id'), 100)}`  ",
                f"**Supporting observation:** {safe(investigation.get('supporting_observation'), 600)}  ",
                f"**Measurement:** {safe(obj(investigation.get('measurement')).get('display'), 180)}  ",
                f"**Priority basis:** {safe(investigation.get('priority_basis'), 500)}  ", "")
            resources = [r for r in items(investigation.get("affected_resources")) if isinstance(r, dict)]
            if resources:
                resource_rows = []
                for resource in resources[:5]:
                    description = ", ".join(
                        f"{key}: {fmt(resource[key])}"
                        for key in ("total", "scripting", "wastedBytes", "totalBytes", "wastedMs")
                        if numeric(resource.get(key)))
                    resource_rows.append([resource.get("url") or resource.get("entity") or "Unattributed resource",
                                          description or "See original audit"])
                add(*table(["Affected resource", "Observed measurement (original units)"], resource_rows), "")
            else:
                add("No individually attributable resources were included in the normalized evidence.", "")
            actions = [a for a in items(investigation.get("actions")) if isinstance(a, str)]
            if actions:
                add("**Engineering actions:**")
                for action in actions:
                    add(f"- {safe(action, 700)}")
                add("")
            add(f"**Validation:** {safe(investigation.get('validation'), 700)}  ",
                f"**Evidence confidence:** {safe(investigation.get('confidence'))}  ",
                f"**Limitation:** {safe(investigation.get('note'), 700)}", "")
        add("**Interpretation:** Engineering priorities are not SEO ranking priorities. "
            "Lighthouse measurements come from individual lab runs; resource-level timings and "
            "overall estimated savings must not be added together. Technical improvements do "
            "not establish search-ranking causation.", "",
            "**Evidence path:** `technical_comparison.mobile.detailed_analysis`.", "")

    add("## 6. Keyword competition and search intent", "")
    if intersection.get("status") == "usable":
        add(f"**Shared keyword records:** {fmt(intersection.get('returned'))} of "
            f"{fmt(intersection.get('total_count'))} reported. "
            f"Our domain ahead on {fmt(intersection.get('ours_ahead'))}; "
            f"competitor ahead on {fmt(intersection.get('benchmark_ahead'))}; "
            f"ties {fmt(intersection.get('ties'))}.", "")
        rows = []
        for row in items(intersection.get("top_generic_benchmark_leads"))[:10]:
            if not isinstance(row, dict):
                continue
            if row.get("relevance_class") in ("exclude", "excluded", "third_party_navigational"):
                continue
            rows.append([row.get("keyword"), f"#{row.get('our_rank')}" if numeric(row.get('our_rank')) else None,
                         f"#{row.get('benchmark_rank')}" if numeric(row.get('benchmark_rank')) else None,
                         row.get("search_volume"), row.get("relevance_class")])
        if rows:
            add(*table(["Related shared query", our_label, comp_label, "Estimated monthly searches", "Relevance class"], rows), "")
        add("These are **domain-level keyword observations**. Each query may rank a different landing page; "
            "do not attribute every query's rank to the two primary URLs.", "")
    else:
        add("Verified keyword-intersection evidence was not available.", "")
    intent = obj(data.get("intent_alignment"))
    add(f"**Keyword intent classification:** {safe(intent.get('main_intent'))}; "
        f"model probability {fmt(intent.get('intent_probability'))}. "
        "A classifier probability is not a measured percentage of searchers with that intent. "
        "For ambiguous terms, the broad keyword classification may not represent the specific intent "
        "of the captured SERP or the landing pages being compared; check the actual search results and page purpose.", "")
    our_sample = obj(domain.get("ranked_ours"))
    comp_sample = obj(domain.get("ranked_benchmark"))
    add(f"**Domain-wide ranked-keyword samples:** {len(items(our_sample.get('items')))} returned for {safe(our_label)}; "
        f"{len(items(comp_sample.get('items')))} for {safe(comp_label)}. "
        "Absence from a limited sample does not establish that a domain fails to rank for a keyword.", "",
        "**Evidence paths:** `advanced_evidence.keyword_intersection`, "
        "`domain_level_evidence.domain_intersection`, `domain_level_evidence.ranked_*`, `intent_alignment`.", "")

    add("## 7. Evidence-supported ranking hypotheses", "")
    hypotheses = []
    p_a = backlink_value("page", "rank", "ours")
    p_b = backlink_value("page", "rank", "benchmark")
    d_a = backlink_value("domain", "rank", "ours")
    d_b = backlink_value("domain", "rank", "benchmark")
    if numeric(p_a) and numeric(p_b) and p_b > p_a:
        counter = (f"However, domain-wide backlink rank favors {our_label} ({fmt(d_a)} vs {fmt(d_b)})."
                   if numeric(d_a) and numeric(d_b) and d_a > d_b else
                   "Domain-wide link signals and individual link quality may tell a different story.")
        hypotheses.append(("Page-specific backlink advantage", "Direct page-level comparison (third-party link metric)",
                           f"The competitor page has a higher third-party backlink rank ({fmt(p_b)} vs {fmt(p_a)}).",
                           counter, "Measured page difference; causal ranking contribution unverified; individual link quality not audited."))
    match = obj(onpage.get("title_keyword_match"))
    if page_ok["ours"] and page_ok["benchmark"] and match.get("ours") is False and match.get("competitor") is True:
        hypotheses.append(("Title/topic signaling difference", "Direct page-level HTML observation",
                           "The captured competitor HTML title includes the selected keyword while ours does not.",
                           "Exact-match keyword presence alone does not determine title quality or rankings.",
                           "Verified as a captured-page difference, not as a ranking cause; check the live title and intent fit."))
    l_a = obj(audit["ours"].get("lab_metrics")).get("largest_contentful_paint_ms")
    l_b = obj(audit["benchmark"].get("lab_metrics")).get("largest_contentful_paint_ms")
    if numeric(l_a) and numeric(l_b) and l_a > l_b:
        perf_a = obj(audit["ours"].get("scores")).get("performance")
        perf_b = obj(audit["benchmark"].get("scores")).get("performance")
        counter = (f"Overall Lighthouse performance favors {our_label} ({fmt(perf_a)} vs {fmt(perf_b)})."
                   if numeric(perf_a) and numeric(perf_b) and perf_a > perf_b else "Other lab metrics may favor our page.")
        hypotheses.append(("Slower observed LCP", "Direct page-level lab measurement (single run)",
                           f"Our mobile LCP was {ms(l_a)} versus {ms(l_b)} for the competitor.",
                           counter, "Observed in one Lighthouse lab run; no verified field performance or causal ranking effect."))
    if intersection.get("status") == "usable" and numeric(intersection.get("generic_benchmark_ahead")) and intersection["generic_benchmark_ahead"] > 0:
        hypotheses.append(("Related-query coverage", "Domain-level context (not evidence about the exact ranking page)",
                           f"The competitor leads on {fmt(intersection['generic_benchmark_ahead'])} classified generic shared queries.",
                           "These domain-level ranks may belong to different pages; branded and generic intent must be distinguished.",
                           "Context only for the primary query; inspect query-specific ranking URLs before applying content changes."))
    if hypotheses:
        for i, (name, evidence_scope, support, counter, limitation) in enumerate(hypotheses, 1):
            add(f"### {i}. {name}", "", f"**Evidence scope:** {evidence_scope}", "",
                f"**Supporting observation:** {support}", "",
                f"**Counterevidence or alternative:** {counter}", "",
                f"**Confidence/limitation:** {limitation}", "")
    else:
        add("No sufficiently supported ranking hypotheses were identified. Avoid inferring causes from missing evidence.", "")
    add("**Overall assessment:** The saved data supports competitive hypotheses, not a causal ranking attribution. "
        "Do not add these signals into an invented Google ranking score.", "")
    if findings:
        add("### Current analysis-engine findings", "")
        add(*table(["Category", "Evidence confidence", "Direction", "Recorded observation"], [
            [f.get("category"), f.get("confidence"), f.get("direction"),
             displayed_discovery_finding(f, benchmark_domain=comp_label, benchmark_rank=comp_rank, engine="Google")]
            for f in findings]), "")
        add("**Discovery reconciliation:** A confirmed benchmark's SERP position takes precedence "
            "over missing rank metadata in the discovery candidate list. The source finding remains "
            "unchanged in the comparison JSON; this report corrects its presentation only.", "")
        add("**Evidence path:** `findings`. These observations are reported separately from the causal hypotheses above.", "")

    add("## 8. Prioritized action plan", "")
    if recommendations:
        add(*table(["Order", "Recommendation", "Priority", "Potential impact", "Effort", "Evidence confidence", "Action type"], [
            [r.get("order", i), r.get("title"), r.get("priority"), r.get("potential_impact"),
             r.get("implementation_effort"), r.get("evidence_confidence"), r.get("action_type")]
            for i, r in enumerate(recommendations, 1)]), "")
        for i, r in enumerate(recommendations, 1):
            add(f"### {fmt(r.get('order', i))}. {safe(r.get('title'), 200)}", "",
                f"**Target URL:** {safe(r.get('target_url') or urls.get('ours'))}  ",
                f"**Priority rationale:** {safe(r.get('priority_basis'), 650)}  ",
                f"**Evidence:** {safe(r.get('evidence'), 850)}  ",
                f"**Interpretation:** {safe(r.get('interpretation'), 850)}  ",
                f"**Impact:** {safe(r.get('potential_impact'))} (qualitative, not a rank-lift forecast)  ",
                f"**Effort:** {safe(r.get('implementation_effort'))}  ",
                f"**Action type:** {safe(r.get('action_type'))}  ", "")
            for action in items(r.get("actions")):
                add(f"- {safe(action, 900)}")
            add("", f"**Success check:** {safe(r.get('success_check'), 1000)}  ",
                f"**Limitations:** {safe(r.get('limitations'), 1000)}", "")
    else:
        add("No recommendations were generated from the verified evidence.", "")
    add("**Impact methodology:** Potential impact and effort are qualitative assessments. "
        "No precise ranking lift, traffic lift or monetary return can be inferred from the current dataset.", "")

    add("## 9. Evidence quality, provenance and limitations", "")
    add(*table(["Evidence component", "Validation status"], [[k, v] for k, v in sorted(quality.items())]), "")
    limits = []
    if not page_ok["ours"] or not page_ok["benchmark"]:
        limits.append("One or both page snapshots failed exact URL/quality validation; page-level comparisons are withheld where unavailable.")
    if not links_ok["ours"] or not links_ok["benchmark"]:
        limits.append("One or both page-level backlink summaries were missing or not URL-verified.")
    if not audit["ours"] or not audit["benchmark"]:
        limits.append("One or both mobile Lighthouse audits were missing or not URL-verified.")
    if not seo_comparison["comparable"]:
        limits.append("Standardized content comparison withheld: one or both pages failed method, status, or URL verification.")
    if not any(obj(obj(obj(pages.get("lighthouse")).get(s)).get("desktop")) for s in ("ours", "benchmark")):
        limits.append("Desktop Lighthouse data was not collected.")
    if backlink_value("page", "dofollow", "ours") is None or backlink_value("page", "dofollow", "benchmark") is None:
        limits.append("Dofollow backlink counts are unavailable; missing values are not zero.")
    limits += ["Google SERP rankings and DataForSEO historical keyword rankings are separate sources and may disagree.",
               "Keyword-intersection ranks are domain-wide, not necessarily for the primary landing pages.",
               "Lighthouse is lab data; field Core Web Vitals and repeated controlled audits are not included.",
               "Search-volume and traffic estimates are modeled, not verified clicks or conversions.",
               "The comparison file does not establish which SEO signals Google actually weighted."]
    for limitation in dict.fromkeys(limits):
        add(f"- {limitation}")
    add("", "### Source and reproducibility", "",
        f"- Primary local source: `{safe(source_name, 140)}`.",
        "- Original data was collected and normalized by the existing SEO pipeline; this report performs no network requests.",
        "- Evidence-path labels above identify where each comparison is read from the local JSON.",
        "- Collection timestamps are shown where provided (e.g. Lighthouse); absent timestamps are not invented.",
        "- To evaluate another keyword, generate its comparison JSON and run this report generator with that keyword.", "",
        "---", "",
        "*Report generated from available evidence. Observed differences do not establish ranking causality or guaranteed improvements.*", "")
    return "\n".join(lines)
