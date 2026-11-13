from __future__ import annotations


def _delta(our_value, competitor_value):
    if isinstance(our_value, (int, float)) and isinstance(competitor_value, (int, float)):
        return competitor_value - our_value
    return None


def _pct_more(our_value, competitor_value):
    if not isinstance(our_value, (int, float)) or not isinstance(competitor_value, (int, float)) or our_value == 0:
        return None
    return ((competitor_value - our_value) / our_value) * 100


def compare_backlink_summaries(ours: dict, competitor: dict) -> dict:
    metrics = ["rank", "backlinks", "referring_domains", "referring_main_domains", "referring_pages", "dofollow"]
    out = {}
    for metric in metrics:
        ov = ours.get(metric)
        cv = competitor.get(metric)
        out[metric] = {
            "ours": ov,
            "competitor": cv,
            "competitor_minus_ours": _delta(ov, cv),
            "competitor_pct_more": _pct_more(ov, cv),
        }
    return out
