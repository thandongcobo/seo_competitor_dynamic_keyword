import json
from pathlib import Path

from analysis.recommendations import classify_evidence_tier, generate_recommendations
from analysis.recommendation_classification import TIER_1, TIER_2

ROOT = Path(__file__).resolve().parents[1]


def test_saved_aviator_comparison_uses_verified_dynamic_evidence():
    saved = json.loads((ROOT / "output/results/aviator/aviator_comparison.json").read_text(encoding="utf-8"))
    urls = saved["primary_ranking_urls"]
    detailed = saved["technical_comparison"]["mobile"]["detailed_analysis"]
    technical = {"mobile": {"status": detailed["status"], "scope": detailed["scope"], "detailed_analysis": detailed}}
    onpage = saved["onpage_comparison"]
    backlink = saved["backlink_comparison"]
    advanced = {
        "backlinks": {"page": {"rank": backlink["rank"],
                                  "referring_domains": backlink["referring_domains"]}},
        "technical": {"mobile": saved["technical_comparison"]["mobile"]},
    }
    recs = generate_recommendations(keyword="aviator", ranking_urls=urls,
                                    advanced_evidence=advanced, onpage=onpage,
                                    technical_comparison=technical)
    assert recs
    assert all(r["evidence_provenance"]["target_url"] == urls["ours"] for r in recs)
    assert any(r["evidence_tier"] == TIER_1 for r in recs)
    assert any(r["evidence_tier"] == TIER_2 for r in recs)


def test_unrelated_synthetic_keyword_and_urls_are_not_hardcoded():
    urls = {"ours": "https://example.org/guides/solar-inverters",
            "benchmark": "https://other.example/reviews/inverters"}
    recs = generate_recommendations(keyword="residential solar inverter", ranking_urls=urls,
        advanced_evidence={}, onpage={"title_keyword_match": {"ours": False, "competitor": True}})
    assert len(recs) == 1
    rec = recs[0]
    assert rec["target_url"] == urls["ours"]
    assert "residential solar inverter" in rec["evidence"]
    assert rec["evidence_tier"] == TIER_2
    assert "aviator" not in str(rec).lower()
    assert len(" ".join(rec["actions"]).split()) >= 60


def test_tier_one_uses_strong_evidence_without_a_historical_outcome_requirement():
    assert classify_evidence_tier(observation_verified=True, action_supported=True,
                                  established_principle=True, exact_scope_verified=True,
                                  action_specific=True) == TIER_1
    assert classify_evidence_tier(observation_verified=True, action_supported=True,
                                  established_principle=True, exact_scope_verified=True,
                                  action_specific=True, material_uncertainty=True) == TIER_2
    assert classify_evidence_tier(observation_verified=False, action_supported=True) is None
    assert classify_evidence_tier(observation_verified=True, action_supported=True,
                                  established_principle=False) is None
