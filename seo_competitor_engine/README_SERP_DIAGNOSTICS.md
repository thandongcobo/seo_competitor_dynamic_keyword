# SERP Diagnostic Layer — 21 October 2026

## Purpose

The goal is **not** to obtain identical Google rankings on repeated searches or
keep retrying until Hollywoodbets receives a preferred position. Different
Google results are valid observations. The goal is to document the context of
each collection and investigate whether the parser accurately represented that
specific rendered Google SERP.

## New behavior

- The original Playwright Google search, organic extraction, Hollywoodbets
  tracking, pagination, and domain selection remain in place.
- Every collected Google page gets an **isolated** diagnostic directory:
  `data/diagnostics/google/<keyword>/<run_id>/`.
- For each page, `page_N_serp.png`, `page_N_serp.html`, and
  `page_N_metadata.json` are saved before extraction. Metadata is subsequently
  updated with the extracted-results audit. A `run_report.json` indexes all
  pages and their flags.
- The metadata contains configured keyword, `gl`, `hl`, `pws`, browser locale,
  timezone, headless setting, viewport and a privacy-safe identifier for the
  Chrome profile. Observed URL parameters, browser language, browser timezone,
  and user agent are recorded separately. The profile identifier **does not**
  prove that cookies, IP address, Google session or search intent were identical.
- HTML H3 heading candidates are saved alongside extraction counts and
  suspicious-result warnings. `AI Mode replied:` is flagged for review, **not**
  silently removed or reassigned a ranking.
- A fresh search compares its first 20 observed ranking URLs to the previous
  saved search. Differences are reported as observations, **never** a reason to
  accept/reject one search or to infer which Google intent was used.
- The Keyword search dashboard shows the run ID, diagnostics flags and a
  short previous-observation comparison. Raw HTML/screenshot evidence is not
  exposed by the dashboard's HTTP server.

## Windows installation and test

From the extracted `seo_competitor_engine` directory:

```cmd
.\setup.bat
.\.venv\Scripts\python.exe -m pytest -q tests\n.\.venv\Scripts\python.exe -m scripts.serve_dashboard --port 8000
```

Open `http://127.0.0.1:8000/` and choose **Keyword search**. Run `aviator`
twice, then compare the two separate run directories under
`data/diagnostics/google/aviator/`. Check the page screenshot against the
extracted rankings and inspect `page_1_metadata.json` for configured vs
observed browser/search context and parser warnings. No local Gemma inference or
paid DataForSEO request is triggered by keyword searching.

The setup script no longer upgrades pip in-place, avoiding the Windows pip
self-upgrade corruption encountered in the previous release. `tzdata` remains
in requirements.

## Interpretation limits

- A Google `gl=za` request is **not** precise GPS/coordinate emulation.
- The collector cannot guarantee a Google SERP identical to a signed-in
  personal Chrome session.
- HTML headings are not guaranteed to be organic listings. Diagnostic flags
  indicate candidates for human review, not proven parser errors.
- An automated audit cannot independently certify absolute Google ranks.
- If a search fails before loading a page, the existing failure diagnostic
  still records the error; no rendered SERP exists to capture.
- Saved HTML and screenshots may contain Google session details; keep them
  private. Do not publish the diagnostics directory.
- The complete two-domain SEO analysis execution remains a later phase.
