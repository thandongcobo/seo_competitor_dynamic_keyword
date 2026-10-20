from __future__ import annotations


def assess_intent_alignment(search_intent: dict, onpage_comparison: dict) -> dict:
    intent = search_intent.get("main_intent")
    probability = search_intent.get("intent_probability")
    if intent == "transactional":
        ours = onpage_comparison.get("transactional_term_hits", {}).get("ours", 0) or 0
        competitor = onpage_comparison.get("transactional_term_hits", {}).get("competitor", 0) or 0
    elif intent == "informational":
        ours = onpage_comparison.get("informational_term_hits", {}).get("ours", 0) or 0
        competitor = onpage_comparison.get("informational_term_hits", {}).get("competitor", 0) or 0
    else:
        return {
            "main_intent": intent,
            "intent_probability": probability,
            "assessment": "MVP intent-alignment heuristic is not yet implemented for this intent class.",
            "ours": None,
            "competitor": None,
            "direction": "context",
            "confidence": "low",
        }

    difference = competitor - ours
    if difference > 1:
        assessment = f"Competitor shows stronger heuristic alignment with {intent} intent ({competitor} term signals vs {ours})."
        direction = "competitor"
        confidence = "medium"
    elif difference < -1:
        assessment = f"Our page shows stronger heuristic alignment with {intent} intent ({ours} term signals vs {competitor})."
        direction = "ours"
        confidence = "medium"
    else:
        assessment = f"No clear heuristic difference in {intent} intent alignment ({ours} vs {competitor} term signals)."
        direction = "neutral"
        confidence = "low"
    return {
        "main_intent": intent,
        "intent_probability": probability,
        "ours": ours,
        "competitor": competitor,
        "assessment": assessment,
        "direction": direction,
        "confidence": confidence,
    }
