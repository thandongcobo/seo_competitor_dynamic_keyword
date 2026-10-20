from __future__ import annotations

import argparse
from urllib.parse import urlsplit, urlunsplit

from analysis.rankings import compare_rankings, extract_serp_candidates
from collectors.dataforseo_client import load_json, save_json
from config.settings import RAW_DIR, PROCESSED_DIR, settings, KEYWORD_SLUG
from normalization.serp import normalize_serp


def load_normalized(engine: str) -> dict:
    pw_path = RAW_DIR / "serp" / f"{KEYWORD_SLUG}_{engine}_playwright.json"
    if pw_path.exists():
        return normalize_serp(load_json(pw_path), settings.keyword, engine)

    raw_path = RAW_DIR / "serp" / f"{KEYWORD_SLUG}_{engine}_result.json"
    if raw_path.exists():
        return normalize_serp(load_json(raw_path), settings.keyword, engine)

    raise SystemExit(f"Missing SERP data for {engine}. Run python -m scripts.collect_playwright_serp --engine {engine} first.")



def normalized_url(url: str | None) -> str | None:
    """Normalize for identity checks only; never rewrite an API or crawl target."""
    if not isinstance(url, str) or not url.strip():
        return None
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        return None
    host = parts.hostname.lower()
    port = f":{parts.port}" if parts.port and parts.port not in (80, 443) else ""
    path = (parts.path or "/").rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), host + port, path, parts.query, ""))


def targets_from_resolved(data: dict, engine: str = "google") -> dict:
    """Extract the *exact* observed URLs. No configured-domain/page fallback."""
    comparison = (data.get("engines", {}).get(engine, {}).get("comparison") or {})
    targets = {}
    for side, prefix, domain_key in (("ours", "our", "our_domain"), ("benchmark", "benchmark", "benchmark_domain")):
        url = comparison.get(f"{prefix}_url")
        if url and not normalized_url(url):
            raise ValueError(f"Invalid SERP URL for {side}: {url!r}")
        targets[side] = {
            "side": side, "keyword": data.get("keyword"), "engine": engine,
            "ranking_url": url, "rank": comparison.get(f"{prefix}_position"),
            "domain": data.get(domain_key), "source": "captured_serp",
        }
    return targets


def primary_targets(engine: str = "google") -> dict:
    """Require a SERP-derived URL for each side, preventing silent domain fallback."""
    manifest_path = PROCESSED_DIR / "target_manifest.json"
    resolved_path = PROCESSED_DIR / "resolved_candidates.json"
    if manifest_path.exists():
        manifest = load_json(manifest_path)
        if manifest.get("keyword") != settings.keyword:
            raise ValueError("Target manifest keyword differs from current keyword")
        targets = (manifest.get("by_engine") or {}).get(engine)
        if targets is None:
            raise ValueError(f"No resolved targets for {engine}")
    elif resolved_path.exists():
        data = load_json(resolved_path)
        if data.get("keyword") != settings.keyword:
            raise ValueError("Resolved SERP keyword differs from current keyword")
        targets = targets_from_resolved(data, engine)
    else:
        raise ValueError("No resolved SERP targets. Run the resolve stage first.")
    return targets


def require_target(side: str, engine: str = "google") -> dict:
    if side not in {"ours", "benchmark"}:
        raise ValueError(f"Unknown side: {side}")
    target = primary_targets(engine).get(side) or {}
    if not normalized_url(target.get("ranking_url")):
        raise ValueError(f"No captured {engine} ranking URL for {side}; refusing a domain/page fallback")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve target pages and discover potential competitors from saved Playwright SERPs.")
    parser.add_argument("--engine", choices=["google", "bing", "all"], default="all")
    args = parser.parse_args()

    engines = ["google", "bing"] if args.engine == "all" else [args.engine]
    combined: dict[str, dict] = {}
    per_engine: dict[str, dict] = {}

    for engine in engines:
        norm = load_normalized(engine)
        comparison = compare_rankings(
            norm,
            settings.our_domain,
            settings.benchmark_competitor_domain,
            window=settings.competitor_window,
        )
        candidates = extract_serp_candidates(
            norm,
            settings.our_domain,
            settings.benchmark_competitor_domain,
            settings.competitor_window,
        )
        per_engine[engine] = {"comparison": comparison, "candidates": candidates}

        for candidate in candidates:
            domain = candidate.get("domain")
            if not domain:
                continue
            row = combined.setdefault(domain, {
                "domain": domain,
                "engines": [],
                "positions": {},
                "urls": {},
                "reasons": [],
                "is_permanent_benchmark": False,
                "is_serp_neighbour": False,
            })
            if engine not in row["engines"]:
                row["engines"].append(engine)
            row["positions"][engine] = candidate.get("rank_group")
            row["urls"][engine] = candidate.get("url")
            row["is_permanent_benchmark"] = row["is_permanent_benchmark"] or bool(candidate.get("is_permanent_benchmark"))
            row["is_serp_neighbour"] = row["is_serp_neighbour"] or bool(candidate.get("is_serp_neighbour"))
            for reason in candidate.get("candidate_reason", []):
                if reason not in row["reasons"]:
                    row["reasons"].append(reason)

    def combined_priority(row: dict) -> tuple:
        if row["is_permanent_benchmark"]:
            p = 0
        elif row["is_serp_neighbour"]:
            p = 1
        else:
            p = 2
        best_rank = min([r for r in row["positions"].values() if isinstance(r, int)], default=9999)
        return (p, best_rank, row["domain"])

    out = {
        "keyword": settings.keyword,
        "our_domain": settings.our_domain,
        "benchmark_domain": settings.benchmark_competitor_domain,
        "engines": per_engine,
        "potential_competitors_from_serp": sorted(combined.values(), key=combined_priority),
        "competitor_discovery_policy": {
            "permanent_benchmark": "Betway is always tracked when present.",
            "serp_candidates": "All captured organic domains are retained as candidates; ranking neighbours are prioritized.",
            "business_classification": "No keyword-specific hard-coded filter is used. Labs and page evidence are used later to strengthen classification.",
        },
    }
    out_path = PROCESSED_DIR / "resolved_candidates.json"
    save_json(out, out_path)
    manifest = {
        "schema_version": "1.0", "keyword": settings.keyword,
        "primary_engine": "google", "by_engine": {
            engine: targets_from_resolved(out, engine) for engine in per_engine
        },
        "policy": "Exact observed ranking URLs are primary; domains are supporting context only.",
    }
    save_json(manifest, PROCESSED_DIR / "target_manifest.json")

    google = per_engine.get("google", {}).get("comparison", {})
    compatibility = {
        "our_url": google.get("our_url"),
        "competitor_url": google.get("benchmark_url"),
        "our_position": google.get("our_position"),
        "competitor_position": google.get("benchmark_position"),
    }
    save_json(compatibility, PROCESSED_DIR / "resolved_pages_google.json")

    print(f"Saved: {out_path}")
    for engine, data in per_engine.items():
        cmp = data["comparison"]
        print(f"{engine.upper()}: our={cmp.get('our_position')} benchmark={cmp.get('benchmark_position')} gap={cmp.get('position_gap')}")
    print(f"Potential SERP candidates retained: {len(out['potential_competitors_from_serp'])}")


if __name__ == "__main__":
    main()
