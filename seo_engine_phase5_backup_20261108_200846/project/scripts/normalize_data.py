from __future__ import annotations

from collectors.dataforseo_client import load_json, save_json
from config.settings import RAW_DIR, PROCESSED_DIR, settings, KEYWORD_SLUG
from normalization.serp import normalize_serp
from normalization.labs import (
    normalize_keyword_overview,
    normalize_search_intent,
    normalize_ranked_keywords,
    normalize_domain_intersection,
    normalize_competitors_domain,
)
from normalization.backlinks import normalize_backlink_summary, normalize_backlinks
from normalization.pages import normalize_page
from normalization.lighthouse import normalize_lighthouse
from scripts.resolve_pages import require_target
from normalization.common import canonical_domain
from scripts.resolve_pages import require_target, normalized_url


def maybe(src, dest, fn, *args):
    if not src.exists():
        print(f"SKIP missing: {src}")
        return
    result = fn(load_json(src), *args)
    save_json(result, dest)
    print(f"Normalized: {dest}")


def expected_target(side: str, engine: str = "google") -> dict | None:
    try:
        return require_target(side, engine)
    except ValueError:
        return None


def normalize_priority_page(side: str) -> None:
    # A Google comparison must not silently use a Bing crawl of another page.
    expected = expected_target(side, "google")
    if not expected:
        print(f"SKIP {side} page: no Google SERP ranking URL")
        return
    src = RAW_DIR / "pages" / f"{KEYWORD_SLUG}_google_{side}.json"
    if not src.exists():
        print(f"SKIP missing: {src}")
        return
    raw = load_json(src)
    observed = raw.get("ranking_url") or raw.get("requested_url")
    if normalized_url(observed) != normalized_url(expected["ranking_url"]):
        print(f"SKIP {side} page: captured URL differs from current Google ranking URL")
        return
    normalized = normalize_page(raw)
    normalized.update({
        "keyword": settings.keyword, "serp_engine": "google", "target_side": side,
        "ranking_url": expected["ranking_url"], "ranking_position": expected["rank"],
        "url_alignment": raw.get("url_alignment") or (
            "redirected_from_ranking_url" if raw.get("final_url") and normalized_url(raw["final_url"]) != normalized_url(expected["ranking_url"])
            else "matched" if raw.get("final_url") else "unverified"
        ),
    })
    save_json(normalized, PROCESSED_DIR / f"page_{side}.json")
    print(f"Normalized: {PROCESSED_DIR / f'page_{side}.json'}")


def normalize_backlink_evidence(side: str, level: str, target: str, engine: str | None = None) -> None:
    src = RAW_DIR / "backlinks" / f"{KEYWORD_SLUG}_{side}_{level}_summary.json"
    if not src.exists():
        print(f"SKIP missing: {src}")
        return
    raw = load_json(src)
    meta_path = src.with_suffix(".meta.json")
    metadata = load_json(meta_path) if meta_path.exists() else {}
    task_targets = [task.get("data", {}).get("target") for task in (raw.get("tasks") or []) if isinstance(task.get("data"), dict)]
    actual = metadata.get("target") or next((v for v in task_targets if v), None)
    if not actual:
        print(f"SKIP {src}: API target cannot be verified; rerun the request if needed")
        return
    mismatched = (normalized_url(actual) != normalized_url(target)) if level == "page" else (canonical_domain(actual) != canonical_domain(target))
    if mismatched:
        print(f"SKIP {src}: API target {actual!r} does not match current {level} target {target!r}")
        return
    normalized = normalize_backlink_summary(raw, target)
    normalized.update({"keyword": settings.keyword, "scope": level,
                       "side": side, "serp_engine": engine, "ranking_url": target if level == "page" else None,
                       "target_verified": True})
    dest = PROCESSED_DIR / f"backlinks_{side}_{level}_summary.json"
    save_json(normalized, dest)
    print(f"Normalized: {dest}")


def normalize_serp_source(engine: str) -> None:
    # Active source: Playwright local SERP snapshot. Legacy DataForSEO SERP is
    # retained only as a fallback for historical files.
    playwright_path = RAW_DIR / "serp" / f"{KEYWORD_SLUG}_{engine}_playwright.json"
    legacy_path = RAW_DIR / "serp" / f"{KEYWORD_SLUG}_{engine}_result.json"
    source = playwright_path if playwright_path.exists() else legacy_path
    if not source.exists():
        print(f"SKIP missing SERP: {source}")
        return
    maybe(
        source,
        PROCESSED_DIR / f"serp_{engine}.json",
        normalize_serp,
        settings.keyword,
        engine,
    )


def main() -> None:
    for engine in ["google", "bing"]:
        normalize_serp_source(engine)

    labs_map = [
        ("keyword_overview", "keyword_overview.json", normalize_keyword_overview),
        ("search_intent", "search_intent.json", normalize_search_intent),
        ("domain_intersection", "domain_intersection.json", normalize_domain_intersection, settings.keyword),
        ("ranked_ours", "ranked_ours.json", normalize_ranked_keywords, settings.our_domain),
        ("ranked_benchmark", "ranked_benchmark.json", normalize_ranked_keywords, settings.benchmark_competitor_domain),
        ("competitors_domain", "competitors_domain.json", normalize_competitors_domain),
    ]
    for item in labs_map:
        action, dest_name, fn, *extras = item
        maybe(RAW_DIR / "labs" / f"{KEYWORD_SLUG}_{action}.json", PROCESSED_DIR / dest_name, fn, *extras)

    for side, domain in [("ours", settings.our_domain), ("benchmark", settings.benchmark_competitor_domain)]:
        normalize_backlink_evidence(side, "domain", domain)
        page_target = expected_target(side)
        if page_target:
            normalize_backlink_evidence(side, "page", page_target["ranking_url"], "google")

    for side in ("ours", "benchmark"):
        normalize_priority_page(side)

    # Lighthouse is a local, optional collector. Never fabricate missing audit scores.
    for side in ("ours", "benchmark"):
        for device in ("mobile", "desktop"):
            src = RAW_DIR / "lighthouse" / f"{KEYWORD_SLUG}_google_{side}_{device}.json"
            if not src.exists():
                continue
            target = require_target(side, "google")
            maybe(src, PROCESSED_DIR / f"lighthouse_{side}_{device}.json",
                  lambda raw, k, s, d, u: normalize_lighthouse(raw, keyword=k, side=s, device=d, ranking_url=u),
                  settings.keyword, side, device, target["ranking_url"])

    page_dir = RAW_DIR / "pages"
    if page_dir.exists():
        for src in page_dir.glob(f"{KEYWORD_SLUG}_*_*.json"):
            name = src.stem
            if name.endswith("_ours") or name.endswith("_benchmark"):
                continue
            maybe(src, PROCESSED_DIR / "candidate_pages" / f"{name}.json", normalize_page)


if __name__ == "__main__":
    main()
