# SERP production and diagnostic modes

The normal SEO keyword search uses the existing Playwright Chrome collector and
retains the corrected organic extraction, AI Overview exclusion, Google redirect
handling, Hollywoodbets discovery, pagination, saved organic results, per-page
organic JSON snapshots, and lightweight DOM validation. It does **not** capture
screenshots, raw HTML, per-page diagnostic metadata or historical comparisons.

## Configuration

In `.env` (create it from `.env.example` if needed):

```env
SERP_DIAGNOSTICS_ENABLED=false
```

To investigate a future Google UI change, set `SERP_DIAGNOSTICS_ENABLED=true`
and restart the dashboard. New searches will then save per-page screenshots,
HTML, metadata and a run report under `data/diagnostics/google/<keyword>/<run_id>/`.
The dashboard will also show the detailed diagnostic information. Switch the
setting back to `false` and restart after troubleshooting.

Neither mode retries until a preferred ranking is returned, changes Google's
observed result order, or requires the local LLM. Validation warnings can still
occur in production when the DOM evidence is incomplete or ambiguous.

Existing diagnostic folders are **not deleted** when production mode is enabled.
For portability, this distribution excludes `.venv`, local Chrome profiles,
`.env` credentials, and Python cache files. Recreate `.venv` with `setup.bat`.

## Windows commands

From the extracted `seo_competitor_engine` folder:

```cmd
.\setup.bat
.\.venv\Scripts\python.exe -m pytest tests\test_serp_production_debug_modes.py -v
.\.venv\Scripts\python.exe -m scripts.serve_dashboard --port 8000
```

Open http://127.0.0.1:8000/ and use **Keyword search**. The `setup.bat` script
installs dependencies without attempting to upgrade pip in place.
