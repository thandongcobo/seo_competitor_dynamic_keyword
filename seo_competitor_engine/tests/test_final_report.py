"""Offline regression tests; no DataForSEO, Playwright, Lighthouse or network required."""
from __future__ import annotations

import copy
import unittest

from analysis.final_report import generate_report


def fixture():
    urls = {"ours": "https://example.org/roulette", "benchmark": "https://rival.example/roulette"}
    def page(side):
        return {"ranking_url": urls[side], "requested_url": urls[side], "final_url": urls[side],
                "url_alignment": "matched", "title": "Roulette online",
                "meta_description": "Play roulette", "headings": {"h1": ["Roulette"]},
                "word_count": 500, "main_word_count": 320,
                "seo_content_method": "rendered-main-innertext-v2",
                "seo_content_status": "verified_candidate",
                "seo_content_word_count": 320, "extraction_status": "complete", "crawl_failed": False,
                "internal_link_count": 12, "structured_data_count": 1}
    def backlinks(side, scope, rank):
        return {"scope": scope, "target": urls[side] if scope == "page" else ("example.org" if side == "ours" else "rival.example"),
                "target_verified": True, "rank": rank, "backlinks": 100, "referring_domains": 40,
                "referring_main_domains": 25, "backlinks_spam_score": 10, "dofollow": None}
    def audit(side, performance, lcp):
        return {"status": "usable", "target_verified": True, "final_url_verified": True,
                "ranking_url": urls[side], "fetch_time": "2026-10-12T09:00:00Z",
                "scores": {"performance": performance, "seo": 90, "accessibility": 80, "best-practices": 85},
                "lab_metrics": {"largest_contentful_paint_ms": lcp, "first_contentful_paint_ms": 4000,
                                "total_blocking_time_ms": 1200, "cumulative_layout_shift": 0.01, "speed_index_ms": 6000}}
    return {"keyword": "roulette", "our_domain": "example.org", "benchmark_competitor_domain": "rival.example",
            "labs_location": "South Africa", "primary_ranking_urls": urls,
            "ranking_summary": {"google": {"our_position": 3, "benchmark_position": 1}},
            "evidence_quality": {"page_ours": "usable", "page_benchmark": "usable",
                                 "backlinks_ours_page": "usable", "backlinks_benchmark_page": "usable",
                                 "lighthouse_ours_mobile": "usable", "lighthouse_benchmark_mobile": "usable"},
            "page_level_evidence": {"ours": page("ours"), "benchmark": page("benchmark"),
                                    "backlinks_ours": backlinks("ours", "page", 18),
                                    "backlinks_benchmark": backlinks("benchmark", "page", 36),
                                    "lighthouse": {"ours": {"mobile": audit("ours", 28, 24000), "desktop": {}},
                                                   "benchmark": {"mobile": audit("benchmark", 16, 19000), "desktop": {}}}},
            "domain_level_evidence": {"backlinks_ours": backlinks("ours", "domain", 70),
                                      "backlinks_benchmark": backlinks("benchmark", "domain", 65),
                                      "ranked_ours": {"items": [{}]}, "ranked_benchmark": {"items": [{}]},
                                      "domain_intersection": {"items": [{"keyword": "roulette", "our_rank": 2, "benchmark_rank": 4}]}},
            "advanced_evidence": {"keyword_intersection": {"status": "usable", "returned": 1, "total_count": 1,
                                                           "ours_ahead": 1, "benchmark_ahead": 0, "ties": 0,
                                                           "generic_benchmark_ahead": 0, "top_generic_benchmark_leads": []}},
            "onpage_comparison": {"title_keyword_match": {"ours": True, "competitor": True}},
            "intent_alignment": {"main_intent": "informational", "intent_probability": 0.9},
            "recommendations": [{"order": 1, "title": "Improve landing page", "priority": "medium",
                                 "priority_basis": "High relevance", "potential_impact": "medium", "implementation_effort": "low",
                                 "evidence_confidence": "medium", "action_type": "investigate",
                                 "evidence": "Test evidence", "actions": ["Inspect HTML"],
                                 "success_check": "Recrawl", "limitations": "Not causal"}],
            "findings": [{"category": "ranking", "evidence": "Observed"}]}


class ReportTests(unittest.TestCase):
    def test_dynamic_keyword_and_domains(self):
        report = generate_report(fixture())
        self.assertIn("roulette", report)
        self.assertIn("example.org", report)
        self.assertIn("rival.example", report)
        self.assertNotIn("hollywoodbets", report.lower())
        self.assertIn("#3", report)
        self.assertIn("#1", report)
        self.assertIn("Improve landing page", report)

    def test_page_and_domain_backlinks_not_mixed(self):
        report = generate_report(fixture())
        self.assertIn("Page — DataForSEO backlink rank | 18 | 36", report)
        self.assertIn("Domain — DataForSEO backlink rank | 70 | 65", report)
        self.assertIn("Page-specific backlink advantage", report)

    def test_dataforseo_ranking_kept_separate(self):
        report = generate_report(fixture())
        self.assertIn("Separate DataForSEO observation", report)
        self.assertIn("#2", report)
        self.assertIn("#4", report)
        self.assertIn("must not overwrite", report)

    def test_withhold_unverified_page_and_audit(self):
        data = fixture()
        data["page_level_evidence"]["benchmark"]["ranking_url"] = "https://wrong.example/roulette"
        data["page_level_evidence"]["lighthouse"]["benchmark"]["mobile"]["final_url_verified"] = False
        data["evidence_quality"]["backlinks_benchmark_page"] = "unusable"
        report = generate_report(data)
        self.assertIn("No / unavailable", report)
        self.assertIn("Not available", report)
        self.assertIn("One or both page snapshots failed", report)
        self.assertNotIn("Title/topic signaling difference", report)

    def test_missing_data_not_zero(self):
        data = fixture()
        data["page_level_evidence"]["ours"].pop("seo_content_word_count")
        data["page_level_evidence"]["lighthouse"] = {}
        data["evidence_quality"].pop("lighthouse_ours_mobile")
        data["evidence_quality"].pop("lighthouse_benchmark_mobile")
        report = generate_report(data)
        self.assertIn("**Comparison withheld:** standardized content evidence is not mutually verified.", report)
        self.assertIn("Dofollow backlink counts are unavailable", report)
        self.assertIn("No verified mobile Lighthouse audits", report)

    def test_no_causal_or_rank_lift_forecast(self):
        report = generate_report(fixture())
        self.assertIn("not proof of causation", report)
        self.assertIn("No precise ranking lift", report)

    def test_no_instructions_from_source_executed(self):
        data = fixture()
        data["page_level_evidence"]["ours"]["title"] = "<script>alert(1)</script> | heading"
        report = generate_report(data)
        self.assertNotIn("<script>", report)
        self.assertIn("&lt;script&gt;", report)
        self.assertIn("\\|", report)

    def test_conflicting_main_word_counts_are_not_interchangeable(self):
        data = fixture()
        ours = data["page_level_evidence"]["ours"]
        benchmark = data["page_level_evidence"]["benchmark"]
        ours.pop("seo_content_word_count")
        benchmark["seo_content_word_count"] = 625
        benchmark["main_word_count"] = 3948
        benchmark["rendered_main_word_count"] = 625
        report = generate_report(data)
        self.assertIn("Standardized cleaned rendered SEO-content words (same method only)", report)
        self.assertIn("Not available | Not available", report)
        self.assertIn("Comparison withheld", report)
        self.assertIn("Do not substitute legacy counts", report)
        self.assertNotIn("3,948", report)
        self.assertNotIn("| 625 |", report)

    def test_rendered_main_counts_comparable_when_both_available(self):
        data = fixture()
        data["page_level_evidence"]["ours"]["seo_content_word_count"] = 300
        data["page_level_evidence"]["benchmark"]["seo_content_word_count"] = 625
        report = generate_report(data)
        self.assertIn("Standardized cleaned rendered SEO-content words (same method only) | 300 | 625", report)
        self.assertNotIn("**Comparison withheld:**", report)

    def test_confirmed_competitor_discovery_label_is_reconciled(self):
        data = fixture()
        data["potential_competitors"] = [
            {"domain": "rival.example", "nearest_serp_rank": None},
            {"domain": "another.example", "nearest_serp_rank": None},
        ]
        data["findings"].append({"category": "competitor_discovery", "confidence": "medium",
                                 "direction": "context", "evidence": "rival.example (not local-rank), another.example (not local-rank)"})
        report = generate_report(data)
        self.assertIn("Confirmed comparison competitor", report)
        self.assertIn("rival.example — #1 in the saved Google SERP", report)
        self.assertIn("Additional discovery candidates:** 1 records", report)
        self.assertIn("rival.example (confirmed Google #1; discovery rank unavailable)", report)
        self.assertIn("another.example (not local-rank)", report)
        self.assertNotIn("rival.example (not local-rank)", report)
        self.assertEqual(data["findings"][-1]["evidence"], "rival.example (not local-rank), another.example (not local-rank)")

    def test_hypothesis_scopes_and_intent_caveat(self):
        data = fixture()
        data["onpage_comparison"]["title_keyword_match"] = {"ours": False, "competitor": True}
        data["advanced_evidence"]["keyword_intersection"]["generic_benchmark_ahead"] = 5
        report = generate_report(data)
        self.assertIn("Direct page-level comparison (third-party link metric)", report)
        self.assertIn("Direct page-level HTML observation", report)
        self.assertIn("Direct page-level lab measurement (single run)", report)
        self.assertIn("Domain-level context (not evidence about the exact ranking page)", report)
        self.assertIn("broad keyword classification may not represent the specific intent", report)

    def test_bad_root_or_keyword(self):
        with self.assertRaises(ValueError):
            generate_report({})
        with self.assertRaises(ValueError):
            generate_report([])


if __name__ == "__main__":
    unittest.main()
