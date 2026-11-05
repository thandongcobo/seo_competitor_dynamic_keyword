"""Inspect the structure of an SEO comparison JSON without exporting its values.

Run from project root:
    python -m scripts.inspect_comparison_schema --keyword aviator
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

MAX_DEPTH = 9
MAX_KEYS_PER_OBJECT = 100
MAX_LIST_SAMPLES = 12
MAX_LINES = 2200


def kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def key_label(key: Any) -> str:
    """Key names are schema, but prevent unexpected newlines/control chars."""
    return json.dumps(str(key), ensure_ascii=True)


def describe(value: Any) -> str:
    t = kind(value)
    if isinstance(value, (list, dict)):
        return f"{t} (entries={len(value)})"
    return t


def collect_shape(value: Any, path: str, depth: int, lines: list[str]) -> None:
    if len(lines) >= MAX_LINES:
        return
    prefix = "  " * depth
    if depth > MAX_DEPTH:
        lines.append(f"{prefix}{path}: [maximum nesting depth reached]")
        return
    if isinstance(value, dict):
        lines.append(f"{prefix}{path}: object (fields={len(value)})")
        for idx, (k, v) in enumerate(value.items()):
            if len(lines) >= MAX_LINES:
                return
            if idx >= MAX_KEYS_PER_OBJECT:
                lines.append(f"{prefix}  ... {len(value) - MAX_KEYS_PER_OBJECT} fields omitted")
                break
            child = f"{path}.{key_label(k)}"
            if isinstance(v, (dict, list)):
                collect_shape(v, child, depth + 1, lines)
            else:
                lines.append(f"{prefix}  {child}: {describe(v)}")
    elif isinstance(value, list):
        types = Counter(kind(item) for item in value)
        type_text = ", ".join(f"{k}:{v}" for k, v in sorted(types.items())) or "empty"
        lines.append(f"{prefix}{path}: array (items={len(value)}; types={type_text})")
        if not value:
            return
        # Multiple object shapes may appear in findings/recommendations; inspect distinct shapes.
        seen: set[tuple] = set()
        inspected = 0
        for item in value[:MAX_LIST_SAMPLES]:
            if not isinstance(item, (dict, list)):
                continue
            signature = (kind(item), tuple(sorted(str(k) for k in item)) if isinstance(item, dict) else len(item))
            if signature in seen:
                continue
            seen.add(signature)
            inspected += 1
            collect_shape(item, f"{path}[*shape{inspected}*]", depth + 1, lines)
            if inspected >= 3:
                break
    else:
        lines.append(f"{prefix}{path}: {describe(value)}")


def get_path(data: dict, *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def generate_report(data: dict, keyword: str, source: Path) -> str:
    lines = [
        "=== SEO COMPARISON JSON SCHEMA INSPECTION ===",
        f"Keyword requested: {keyword}",
        f"Source filename: {source.name}",
        "Mode: STRUCTURE ONLY — scalar values, URLs, raw content and credentials are NOT included.",
        "",
        "=== TOP-LEVEL FIELDS ===",
    ]
    for key, value in data.items():
        lines.append(f"{key_label(key)}: {describe(value)}")
    lines += ["", "=== REPORTING COMPONENT CHECKLIST ==="]
    checks = [
        ("Keyword", ("keyword",)),
        ("Primary ranking URLs", ("primary_ranking_urls",)),
        ("Ranking summary", ("ranking_summary",)),
        ("Evidence quality", ("evidence_quality",)),
        ("Page-level evidence", ("page_level_evidence",)),
        ("Domain-level evidence", ("domain_level_evidence",)),
        ("Technical comparison", ("technical_comparison",)),
        ("On-page comparison", ("onpage_comparison",)),
        ("Backlink comparison", ("backlink_comparison",)),
        ("Keyword comparison", ("keyword_comparison",)),
        ("Intent alignment", ("intent_alignment",)),
        ("Advanced evidence", ("advanced_evidence",)),
        ("Findings", ("findings",)),
        ("Recommendations", ("recommendations",)),
        ("Analysis policy", ("analysis_policy",)),
        ("LLM-ready metadata", ("llm_ready",)),
    ]
    for label, path in checks:
        val = get_path(data, *path)
        present = path[0] in data
        lines.append(f"{'PRESENT' if present else 'MISSING'} | {label}: {describe(val) if present else '-'}")
    lines += ["", "=== NESTED FIELD STRUCTURE ==="]
    for key, value in data.items():
        if len(lines) >= MAX_LINES:
            break
        collect_shape(value, f"root.{key_label(key)}", 0, lines)
    if len(lines) >= MAX_LINES:
        lines.append("[Report truncated at safe line limit]")
    lines += [
        "", "=== NOTES ===",
        "Only field names, types, collection counts and example object SHAPES are shown.",
        "A missing field can indicate an optional feature, not a pipeline failure.",
        "Do not use this schema report as evidence of SEO ranking performance.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a safe schema report for the SEO comparison JSON")
    parser.add_argument("--keyword", required=True, help="Keyword used by the analysis pipeline, e.g. aviator")
    parser.add_argument("--input", type=Path, help="Optional path to an existing comparison JSON")
    parser.add_argument("--output", type=Path, help="Optional path for the text report")
    args = parser.parse_args(argv)

    slug = re.sub(r"[^a-z0-9]+", "_", args.keyword.lower()).strip("_")
    if not slug:
        parser.error("keyword must contain letters or digits")
    root = Path(__file__).resolve().parents[1]
    source = args.input or root / "output" / "results" / slug / f"{slug}_comparison.json"
    dest = args.output or root / "output" / "results" / slug / f"{slug}_schema_report.txt"
    if not source.is_file():
        print(f"ERROR: JSON file not found: {source}", file=sys.stderr)
        return 1
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        print(f"ERROR: Could not read valid JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(data, dict):
        print("ERROR: Expected a JSON object at the root", file=sys.stderr)
        return 1
    report = generate_report(data, args.keyword, source)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(report, encoding="utf-8")
    print(f"Schema report saved: {dest}")
    print(f"Top-level fields: {len(data)}")
    print("No JSON values were exported. Share only the generated *_schema_report.txt file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
