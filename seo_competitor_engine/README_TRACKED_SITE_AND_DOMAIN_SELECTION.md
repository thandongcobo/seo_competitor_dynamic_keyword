# Tracked-site discovery + two-domain selection (21 October 2026)

## What this update implements

1. Preserves the original Playwright/Chrome Google SERP collector and the observed order of results.
2. Collects a minimum of 10, 20 or 50 results, then continues through available Google pages until the configured tracked domain is observed with at least two subsequent organic results (if available), or a **hard cap of 100 observed organic results / 10 pages** is reached. No ranking is fabricated and no search is retried to obtain a desired rank.
3. Defaults the tracked domain to `OUR_DOMAIN=hollywoodbets.net` from `.env`. Matches subdomains but not lookalike domains.
4. Saves tracked-domain status, first observed organic position, exact URL, counts above/below, page-by-page diagnostics and stop reason in the Google SERP snapshot.
5. Displays tracked-domain discovery and search completeness in the dashboard's Keyword search page.
6. Provides two-domain selection from the *actual saved SERP*. Hollywoodbets is preselected when present, but users may choose any two distinct observed domains.
7. Creates an immutable investigation manifest under `data/investigations/<id>/selection.json` containing the keyword, timestamp, source SERP SHA-256, selected domains, first observed ranking URLs and positions. A changed snapshot invalidates an in-progress selection.
8. Retains all existing comparison scripts, reports, Gemma inference, monitoring dashboard, saved data and monitoring history.

## Important limitations

- Google results can differ from a normal signed-in Chrome search because the browser context, IP and session may differ. Finding Hollywoodbets does not fix that discrepancy or guarantee an absolute Google rank.
- If Google has no next page, blocks navigation or returns incomplete results, the collection stops and reports partial evidence.
- **Selecting two domains does not yet run the SEO comparison.** The next integration step is to execute the full DataForSEO, Playwright, Lighthouse, four-specialist Gemma and PDF pipeline using isolated investigation-specific evidence paths. This is intentionally gated to avoid overwriting older evidence or making unapproved paid requests.
- No live Google or paid API/LLM requests were made in the development environment. Offline integration tests and actual saved SERP compatibility were checked.

## Windows setup (new extraction)

Open the extracted `seo_competitor_engine` folder in VS Code or Command Prompt, then:

```cmd
.\setup.bat
.\.venv\Scripts\python.exe -m scripts.serve_dashboard --port 8000
```

`setup.bat` prefers the Windows `py` launcher when installed and falls back to `python`. The requirements include `tzdata` for `Africa/Johannesburg` timezone support.

Open `http://127.0.0.1:8000/`, choose **Keyword search**, enter your keyword, click **Search Google**, then select any two observed domains and click **Save comparison selection**. You can also choose **Load saved snapshot** for an existing real SERP.

The saved manifest is retrievable via `GET /api/investigations/<investigation_id>`.

Keep your existing `.env` credentials separately; the distribution does not contain credentials, virtual environments or Chrome profiles. If moving to a new installation, copy your existing `.env` and any locally created search/profile data you want to retain. No paid APIs or Gemma server are needed to test keyword search and domain selection.

## Tests

```cmd
.\.venv\Scripts\python.exe -m pytest -q tests/test_tracked_serp_discovery.py tests/test_serp_investigation_selection.py tests/test_dashboard_keyword_search.py
.\.venv\Scripts\python.exe -m pytest -q tests
```

The full suite retains 12 known pre-existing failures unrelated to this change. Live Windows Chrome integration must be verified locally.
