"""Run local Lighthouse on exact Google SERP targets (no DataForSEO requests)."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

from config.settings import RAW_DIR, settings, KEYWORD_SLUG
from scripts.resolve_pages import require_target, normalized_url


def build_command(url: str, output_path: Path, *, device: str, npx: str = "npx") -> list[str]:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Invalid HTTP(S) ranking URL")
    command = [
        npx, "--yes", "lighthouse", url,
        "--output=json", f"--output-path={output_path}",
        "--only-categories=performance,accessibility,best-practices,seo",
        "--chrome-flags=--headless=new --disable-gpu",
        "--quiet", "--no-enable-error-reporting",
    ]
    if device == "desktop":
        command.append("--preset=desktop")
    return command


def run_audit(side: str, device: str, *, execute: bool, refresh: bool,
              timeout: int, engine: str = "google") -> Path:
    # Do not accept a configured fallback URL or an arbitrary user-supplied URL.
    target = require_target(side, engine)
    url = target["ranking_url"]
    output = RAW_DIR / "lighthouse" / f"{KEYWORD_SLUG}_{engine}_{side}_{device}.json"
    diagnostics = RAW_DIR / "lighthouse" / f"{KEYWORD_SLUG}_{engine}_{side}_{device}_error.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    npx = shutil.which("npx") or shutil.which("npx.cmd") or "npx"
    temp_output = output.with_name(output.stem + "_pending.json")
    command = build_command(url, temp_output, device=device, npx=npx)
    print(f"Keyword: {settings.keyword} | Engine: {engine} | Side: {side} | Device: {device}")
    print(f"Ranking URL: {url}")
    print(f"Output: {output}")
    print("Command:", subprocess.list2cmdline(command))
    if not execute:
        print("DRY RUN ONLY. Add --execute to run local Lighthouse (no paid API calls).")
        return output
    if output.exists() and not refresh:
        try:
            cached = json.loads(output.read_text(encoding="utf-8"))
            if normalized_url(cached.get("requestedUrl")) == normalized_url(url):
                print("Existing audit retained. Use --refresh to rerun.")
                return output
        except (OSError, ValueError):
            pass
        raise RuntimeError("Existing Lighthouse audit belongs to another URL or is invalid; use --refresh to replace it")
    env = dict(os.environ)
    if settings.playwright_browser_path:
        env["CHROME_PATH"] = settings.playwright_browser_path
    if temp_output.exists():
        temp_output.unlink()
    try:
        completed = subprocess.run(command, capture_output=True, text=True,
                                   timeout=timeout, env=env, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        diagnostics.write_text(f"Lighthouse execution failed: {exc}\n", encoding="utf-8")
        raise RuntimeError(f"Lighthouse failed; diagnostics: {diagnostics}") from exc
    if completed.returncode != 0:
        diagnostics.write_text(
            f"Exit code: {completed.returncode}\nSTDOUT:\n{completed.stdout[-4000:]}\n"
            f"STDERR:\n{completed.stderr[-8000:]}\n", encoding="utf-8")
        raise RuntimeError(f"Lighthouse exited with {completed.returncode}; see {diagnostics}")
    try:
        audit = json.loads(temp_output.read_text(encoding="utf-8"))
        if not isinstance(audit, dict) or not audit.get("lighthouseVersion"):
            raise ValueError("Missing lighthouseVersion in audit")
    except (OSError, ValueError) as exc:
        diagnostics.write_text(f"Invalid Lighthouse JSON: {exc}\n", encoding="utf-8")
        raise RuntimeError(f"Lighthouse output invalid; see {diagnostics}") from exc
    if normalized_url(audit.get("requestedUrl")) != normalized_url(url):
        diagnostics.write_text("Lighthouse requestedUrl does not match the SERP URL.\n", encoding="utf-8")
        raise RuntimeError(f"Audit URL mismatch; see {diagnostics}")
    temp_output.replace(output)
    if diagnostics.exists():
        diagnostics.unlink()
    print("Saved:", output)
    return output


def main() -> None:
    p = argparse.ArgumentParser(description="Lighthouse audits of exact Google ranking URLs")
    p.add_argument("--side", choices=["ours", "benchmark", "both"], default="both")
    p.add_argument("--device", choices=["mobile", "desktop"], default="mobile")
    p.add_argument("--engine", choices=["google"], default="google")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--timeout", type=int, default=240)
    args = p.parse_args()
    if args.timeout < 30:
        p.error("--timeout must be at least 30 seconds")
    for side in (["ours", "benchmark"] if args.side == "both" else [args.side]):
        try:
            run_audit(side, args.device, execute=args.execute,
                      refresh=args.refresh, timeout=args.timeout, engine=args.engine)
        except (ValueError, RuntimeError) as exc:
            print(f"ERROR: {side}: {exc}", file=sys.stderr)
            raise SystemExit(1)


if __name__ == "__main__":
    main()
