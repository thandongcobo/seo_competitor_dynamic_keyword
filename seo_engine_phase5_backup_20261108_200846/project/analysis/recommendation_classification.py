"""Versioned evidence classification and legacy presentation compatibility.

The classifier deliberately separates evidence strength from implementation
priority. It accepts saved recommendation records and never needs SERP access.
"""
from __future__ import annotations

from copy import deepcopy
from urllib.parse import urlsplit


CLASSIFICATION_VERSION = 2
TIER_1 = "tier_1_strong_evidence"
TIER_2 = "tier_2_moderate_evidence"
TIER_LABELS = {
    TIER_1: "Tier 1 — Strong Evidence",
    TIER_2: "Tier 2 — Moderate Evidence",
}
TIER_ORDER = {TIER_1: 1, TIER_2: 2}
LEGACY_TIERS = {
    "tier_1_historically_supported": TIER_1,
    "tier_2_evidence_supported": TIER_1,
    "tier_3_plausible_opportunity": TIER_2,
    "tier_1_strong_evidence": TIER_1,
    "tier_2_moderate_evidence": TIER_2,
}
VALIDATION_FAILURES = {"invalid", "failed", "rejected", "unsupported", "withheld", "recovery_failed",
                       "unvalidated", "not_validated", "not_verified", "blocked"}


def _text(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        return " ".join(_text(item) for item in value if item is not None).strip()
    return ""


def _absolute_http_url(value):
    try:
        parsed = urlsplit(str(value or ""))
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except ValueError:
        return False


def _assessment(record):
    evidence = _text(record.get("evidence") or record.get("difference_observed") or
                     record.get("observation") or record.get("finding") or
                     record.get("simple_explanation") or record.get("technical_explanation"))
    action = _text(record.get("display_action") or record.get("recommended_action") or
                   record.get("actions") or record.get("implementation_steps") or
                   record.get("implementation_details"))
    justification = _text(record.get("action_justification") or record.get("rationale") or
                          record.get("interpretation"))
    provenance = record.get("evidence_provenance") or {}
    target = record.get("target_url") or record.get("url") or provenance.get("tracked_url")
    source = _text(provenance.get("source") or record.get("evidence_source"))
    evidence_ids = (provenance.get("evidence_ids") or record.get("evidence_ids") or
                    record.get("source_evidence_ids") or [])
    validation = " ".join(str(value or "") for value in (
        record.get("validation_status"), record.get("validation"), record.get("status"),
    )).casefold()
    recovery = str(record.get("recovery_status") or "").casefold()
    failed = any(token in validation or token in recovery for token in VALIDATION_FAILURES)
    explicit_unsupported = record.get("unsupported_claims") is True or record.get("claims_supported") is False
    exact_target = _absolute_http_url(target)
    relevant_scope = bool(exact_target or provenance.get("measurement_scope") or
                          provenance.get("scope") or record.get("measurement_scope"))
    observation_verified = bool(evidence and relevant_scope and
                                (source or evidence_ids or validation.startswith("validated"))) and not failed
    intervention = (
        "replace", "add ", "update", "rewrite", "improve", "resize", "compress",
        "defer", "split", "relink", "optimize", "optimise", "reduce ",
        "implement", "revise", "expand", "earn ", "correct", "restore",
        "consolidate", "clarify", "enhance", "migrate", "modify", "repair",
        "configure", "convert", "serve ", "remove ", "create ", "link ",
    )
    action_supported = bool(action and justification and any(token in action.casefold() for token in intervention)
                            and not explicit_unsupported and not failed)
    provenance_target = provenance.get("target_url") or provenance.get("tracked_url")
    exact_scope = exact_target and (
        (provenance_target and str(provenance_target).rstrip("/").casefold() == str(target).rstrip("/").casefold())
        or bool(provenance.get("resource_candidates"))
        or bool((record.get("action_composition") or {}).get("proposed_copy", {}).get("source_evidence_ids"))
        or bool((record.get("action_composition") or {}).get("specific_page_url"))
        or bool((record.get("action_composition") or {}).get("status") == "specific_source_destination_pairs_but_source_pages_unverified")
    )
    composition = record.get("action_composition") or {}
    proposed = composition.get("proposed_copy") or {}
    copy_is_grounded = bool(proposed and proposed.get("validation", {}).get("grounded") is True
                            and proposed.get("status") == "proposed_not_observed")
    resources = provenance.get("resource_candidates") or []
    resource_specific = bool(resources and all(
        isinstance(item, dict) and _absolute_http_url(item.get("url")) for item in resources))
    link_pairs = record.get("proposed_link_pairs") or composition.get("proposed_link_pairs") or []
    page_pair_specific = bool(composition.get("specific_page_url") or link_pairs)
    action_specific = bool(copy_is_grounded or resource_specific or page_pair_specific)
    # Specific authored actions with direct citations may qualify when a saved
    # record predates structured composer metadata. No numeric score is used.
    if not action_specific and exact_scope and evidence_ids:
        action_specific = bool(target and str(target).casefold() in action.casefold())

    uncertainty_text = " ".join([
        _text(record.get("limitations")), _text(record.get("uncertainty")),
        _text(composition.get("limitation")),
    ]).casefold()
    moderate_markers = (
        "not captured", "not fully captured", "not verified", "does not establish",
        "not proof", "not prove", "not observed", "if the answer is incomplete",
        "only if", "after page and policy review", "review each listed page",
        "globally undiscoverable", "content is deficient", "incoming links",
        "reverse link", "source pages before editing",
    )
    material_uncertainty = (any(marker in uncertainty_text for marker in moderate_markers)
                            or composition.get("third_party_resources_require_owner_review") is True)
    # Certain potential benefits do not turn a verified opportunity into an
    # uncertain observation. Classification focuses on whether the proposed
    # edit itself is supported and implementable.
    strong = (observation_verified and action_supported and exact_scope and action_specific
              and not material_uncertainty)
    eligible = observation_verified and action_supported
    reason = (
        "Verified evidence is exact-scope and traceable; the action is specific, grounded, and follows a defensible principle."
        if strong else
        "A verified observation and reasonable actionable improvement exist, but page, relationship, implementation, or benefit uncertainty remains."
        if eligible else
        "Excluded: the saved record lacks a verified observation, a supported actionable improvement, or passed factual validation."
    )
    return {
        "observation_verified": bool(observation_verified),
        "action_supported": bool(action_supported),
        "exact_scope_verified": bool(exact_scope),
        "action_specific": bool(action_specific),
        "material_uncertainty": bool(material_uncertainty),
        "unsupported_claims_detected": bool(explicit_unsupported or failed),
        "eligible": bool(eligible),
        "tier": TIER_1 if strong else TIER_2 if eligible else None,
        "reason": reason,
    }


def classify_recommendation(record, *, preserve_legacy=True):
    """Return an adapted copy or ``None`` when evidence does not qualify for display."""
    if not isinstance(record, dict):
        return None, {"eligible": False, "reason": "malformed_recommendation_record"}
    row = deepcopy(record)
    old_tier = row.get("legacy_evidence_tier", row.get("evidence_tier"))
    assessment = _assessment(row)
    if not assessment["eligible"]:
        return None, {**assessment, "legacy_evidence_tier": old_tier,
                      "recommendation_id": row.get("id"), "title": row.get("title")}
    if preserve_legacy and old_tier and old_tier not in {TIER_1, TIER_2}:
        row["legacy_evidence_tier"] = old_tier
    row["classification_version"] = CLASSIFICATION_VERSION
    row["evidence_tier"] = assessment["tier"]
    row["tier_basis"] = assessment["reason"]
    row["classification_assessment"] = assessment
    audit = {**assessment, "legacy_evidence_tier": old_tier,
             "recommendation_id": row.get("id"), "title": row.get("title")}
    return row, audit


def adapt_recommendations(records):
    """Version-adapt saved rows without writing back to historical source files."""
    accepted, audit = [], []
    for record in records or []:
        row, disposition = classify_recommendation(record)
        audit.append(disposition)
        if row is not None:
            accepted.append(row)
    accepted.sort(key=lambda row: (
        TIER_ORDER.get(row.get("evidence_tier"), 99),
        -float(row.get("priority_score") or 0),
        str(row.get("id") or ""),
    ))
    for index, row in enumerate(accepted, 1):
        row["order"] = index
    return accepted, {
        "classification_version": CLASSIFICATION_VERSION,
        "input_count": len(records or []),
        "display_count": len(accepted),
        "excluded_count": len(records or []) - len(accepted),
        "recommendations": audit,
    }


def adapt_comparison(comparison):
    """Adapt a saved comparison in memory; never rewrite its source artifact."""
    if not isinstance(comparison, dict):
        return comparison, {"classification_version": CLASSIFICATION_VERSION,
                            "input_count": 0, "display_count": 0, "excluded_count": 0,
                            "recommendations": []}
    adapted = deepcopy(comparison)
    rows, audit = adapt_recommendations(adapted.get("recommendations") or [])
    adapted["recommendations"] = rows
    adapted["recommendation_classification_version"] = CLASSIFICATION_VERSION
    adapted["recommendation_classification_audit"] = audit
    return adapted, audit
