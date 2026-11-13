# Phase 1: Dashboard keyword search (20 October 2026)

## What was added

- **Keyword search** page in the existing monitoring dashboard.
- Enter any keyword and request 10, 20, or 50 Google organic results.
- `POST /api/serp/search` starts an asynchronous, **fresh** search using the original teammate Playwright/Chrome collector (`--refresh`).
- `GET /api/serp/jobs/<job_id>` reports the search status and returns collected results only on successful completion.
- `GET /api/serp/snapshot?keyword=<keyword>` reads an existing real Google snapshot on explicit request, clearly labelled as saved.
- Results show organic rank, domain, title, exact ranking URL, capture time, and collection completeness.
- Failed or blocked searches show errors; no fabricated results and no fallback to stale data presented as fresh.
- Search uses the original collector's Google `gl=za` context, **not** precise geolocation. Google may show challenges and may return partial results.
- Existing analysis, reports, and monitoring are untouched. **Domain selection and running a new comparison are Phase 2/3 and are not yet available in this release.**

## Windows installation (fresh extraction)

1. Extract ZIP and open `seo_competitor_engine` in VS Code.
2. Open **Terminal > New Terminal** (PowerShell):

```powershell
cd "C:\path\to\seo_competitor_engine"
.\setup.bat
.\.venv\Scripts\Activate.ps1
```

If PowerShell prevents script activation, use CMD and run `.venv\Scripts\activate.bat`, or run `.venv\Scripts\python.exe` directly instead of `python`.

3. For later paid DataForSEO / local Gemma analyses, copy `.env.example` to `.env` and fill in your **own** credentials. The Google keyword search itself does not require DataForSEO credentials.
4. Start the dashboard:

```powershell
python -m scripts.serve_dashboard --port 8000
```

5. Open `http://127.0.0.1:8000/` and select **Keyword search** in the sidebar. Enter a keyword and click **Search Google**. Chrome may open during collection. Do not close the Chrome window until collection finishes.
6. To stop the server, press `Ctrl+C` in the terminal.

**Updating an existing installation:** Keep a backup of your current `.env`, `.venv`, and user-generated data. This ZIP intentionally does not include credentials, virtual environments, Chrome profiles, browser caches, or sensitive diagnostic HTML. Existing source ZIP data/raw, data/processed, output/results, and monitoring history/artifacts have been retained in this release.

## Verification

```powershell
python -m pytest -q tests/test_dashboard_keyword_search.py
python -m pytest -q tests
```

Seven Phase 1 contract tests passed in the development environment. The full suite has 12 pre-existing failures (also present in the original uploaded version). A live Google collection could not be verified in the development container because the original collector launches a visible Chrome browser configured for the user's Windows machine. Test one live keyword search on that machine to verify the browser integration.

## Notes

- This search does **not** call paid DataForSEO endpoints.
- Only one live search runs at a time to avoid concurrent access to the collector's persistent Chrome profile.
- Search job state is in memory; restarting the dashboard resets job progress, but successfully collected snapshots remain saved.
- The initial dashboard's saved Aviator comparison is deliberately independent of new keyword searches until Phases 2 and 3.
