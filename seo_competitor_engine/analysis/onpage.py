from __future__ import annotations

import re
from collections import Counter
from analysis.seo_content_validation import compare as compare_seo_content

TRANSACTIONAL_TERMS = {"play", "bet", "join", "register", "sign up", "start", "deposit", "login", "play now"}
INFORMATIONAL_TERMS = {"what", "how", "guide", "rules", "learn", "explained", "tips"}
STOPWORDS = {"the", "and", "for", "with", "from", "this", "that", "you", "your", "are", "was", "our", "not", "but", "can", "has", "have", "www", "https", "com"}


def _text_tokens(text: str) -> Counter[str]:
    return Counter(w for w in re.findall(r"[a-z0-9]{3,}", text.casefold()) if w not in STOPWORDS)


def _verified_text(page: dict) -> str | None:
    text = page.get("seo_content_text")
    if not isinstance(text, str) or not text.strip():
        return None
    count = page.get("seo_content_word_count")
    if type(count) is not int or count < 0:
        return None
    if len(text.split()) != count:
        return None
    return text


def _jaccard(a: set[str], b: set[str]) -> float | None:
    if not a or not b:
        return None
    return len(a & b) / len(a | b)


def compare_pages(ours: dict, competitor: dict, keyword: str) -> dict:
    def contains_keyword(page, field):
        return keyword.casefold() in (page.get(field) or "").casefold()

    def h1_contains(page):
        return any(keyword.casefold() in (h or "").casefold()
                   for h in (page.get("headings") or {}).get("h1", []))

    def term_hits(text, terms):
        if text is None:
            return None
        return sum(bool(re.search(r"\b" + re.escape(term) + r"\b", text.casefold())) for term in terms)

    seo_content = compare_seo_content(ours, competitor)
    comparable_text = bool(seo_content["comparable"])
    our_text = _verified_text(ours) if comparable_text else None
    comp_text = _verified_text(competitor) if comparable_text else None
    text_available = our_text is not None and comp_text is not None
    ours_tokens = _text_tokens(our_text) if text_available else Counter()
    comp_tokens = _text_tokens(comp_text) if text_available else Counter()

    def pair(key):
        return {"ours": ours.get(key), "competitor": competitor.get(key)}

    return {
        "seo_content_comparison": seo_content,
        "title_keyword_match": {"ours": contains_keyword(ours, "title"), "competitor": contains_keyword(competitor, "title")},
        "meta_keyword_match": {"ours": contains_keyword(ours, "meta_description"), "competitor": contains_keyword(competitor, "meta_description")},
        "h1_keyword_match": {"ours": h1_contains(ours), "competitor": h1_contains(competitor)},
        "title": pair("title"),
        "meta_description": pair("meta_description"),
        "h1_headings": {"ours": (ours.get("headings") or {}).get("h1", []),
                        "competitor": (competitor.get("headings") or {}).get("h1", [])},
        "word_count": pair("word_count"),
        "main_word_count": {"ours": seo_content["ours"], "competitor": seo_content["benchmark"]},
        "legacy_main_word_count_diagnostic": {"ours": ours.get("main_word_count"), "competitor": competitor.get("main_word_count")},
        "internal_link_count": pair("internal_link_count"),
        "structured_data_count": pair("structured_data_count"),
        "transactional_term_hits": {"ours": term_hits(our_text, TRANSACTIONAL_TERMS) if text_available else None, "competitor": term_hits(comp_text, TRANSACTIONAL_TERMS) if text_available else None},
        "informational_term_hits": {"ours": term_hits(our_text, INFORMATIONAL_TERMS) if text_available else None, "competitor": term_hits(comp_text, INFORMATIONAL_TERMS) if text_available else None},
        "content_token_jaccard": _jaccard(set(ours_tokens), set(comp_tokens)) if text_available else None,
        "content_relevance_status": "comparable_cleaned_text" if text_available else "unavailable",
        "content_relevance_method": "verified_rendered_main_innertext_v2" if text_available else None,
        "top_shared_terms": [term for term, _ in (ours_tokens & comp_tokens).most_common(20)] if text_available else [],
        "content_quality_note": "Similarity and term signals use verified cleaned text only when both pages pass URL and method checks. These are descriptive signals, not quality or ranking scores.",
    }
