from __future__ import annotations


def normalize_page(page_json: dict) -> dict:
    keys = [
        "requested_url", "final_url", "status_code", "title", "title_length",
        "meta_description", "meta_description_length", "canonical", "robots",
        "headings", "h1_count", "word_count", "internal_link_count",
        "external_link_count", "structured_data_count", "text_sample",
        "extraction_status", "crawl_failed", "blocked", "content_quality_reason",
        "content_readiness_checked", "error", "diagnostic_directory",
        "keyword", "serp_engine", "ranking_url", "ranking_position", "target_side",
        "url_alignment", "evidence_scope", "main_word_count", "rendered_main_word_count", "rendered_word_count",
        "seo_content_word_count", "seo_content_status", "seo_content_method",
        "seo_content_selector", "seo_content_tag", "seo_content_candidate_count",
        "seo_content_excluded_nodes", "seo_content_heading_count",
        "seo_content_body_words", "seo_content_reason", "seo_content_text",
        # Retain structured qualitative evidence for evidence enrichment. These
        # fields are local normalized data; the LLM foundation applies bounds.
        "internal_links", "external_links", "structured_data_blocks",
        "content_stable", "rendered_word_count", "rendered_main_word_count",
        "rendered_h1_count", "collected_at", "capture_timestamp",
    ]
    result = {key: page_json.get(key) for key in keys}
    result["evidence_scope"] = "page"
    return result
