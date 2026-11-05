# SEO Competitor Intelligence Engine

An Aviator-focused MVP for comparing Hollywoodbets with Betway in Google search and monitoring changes on a selected public competitor page. It collects evidence, compares measurable differences, and presents findings in a local dashboard. The analysis is intended to guide investigation; it does not establish that a page difference caused a ranking change.

## What the project does

### Decisions & actions

- Shows the saved Google ranking positions and a comparison of captured evidence for Hollywoodbets and Betway.
- Builds a compact evidence packet from the comparison and specialist analyses, then asks the configured local LLM for an executive summary, findings, and proposed decisions.
- Validates the LLM response against the project schema and factual guardrails before the dashboard displays it. The raw response and run metadata are retained separately for review.
- Presents evidence, why it may matter, limitations, and suggested next checks. Findings remain hypotheses unless independently verified.

### Competitor change analysis

- Monitors the selected public ranking page (Betway by default); the dashboard can register, select, capture, and compare additional public HTTP(S) URLs.
- A capture uses Playwright to save rendered page text and fields, visible-page assets, captured HTML, and a full-page screenshot.
- Monitoring captures use a fresh browser context without saved cookies and block requests resolving to non-public network addresses; sign-in walls are not collected as promotion evidence.
- Successful captures are compared to previous successful captures for content/field changes. Pillow calculates screenshot pixel differences; this is visual evidence, not OCR or semantic image understanding.
- Promotion detection scans captured rendered text with local rules and also checks banner-sized image candidates with optional local Tesseract OCR. Candidates can be filtered by text/image source, searched, confirmed or dismissed by a reviewer, and tracked across captures.
- High-confidence candidates with a same-host public link can trigger bounded automatic investigation of the offer page and one linked terms page. Extraction records visible amounts, percentages, promo codes, dates, eligibility wording, source URLs, and evidence excerpts. No AI inference is used. Redirects, other hosts, sign-in pages, oversized pages, and non-text resources are not followed or treated as confirmed details.
- Automated matches remain promotion candidates, not guaranteed offers. A candidate missing from two eligible captures is labelled “not detected”; this is not proof that an offer ended. Monitoring covers registered pages only—not every URL on a domain.
- Captures are checked for basic tracking quality (successful extraction, same host, stable content where reported, and a minimum amount of text or imagery). Ineligible attempts remain in capture history but do not update the comparison baseline or promotion lifecycle.
- A stable same-host offer destination plus sufficiently similar wording can connect a changed creative/text version to an existing promotion record. This is a cautious heuristic; ambiguous cases remain separate candidates for team review.
- Recurring capture is opt-in. Start the scheduler explicitly with `python -m scripts.run_monitoring_scheduler`; it checks active pages at their configured interval (currently 24 hours by default). Stop with Ctrl+C. The dashboard alone does not start it.

## Data sources and interpretation

| Source | What it captures | How to interpret it |
| --- | --- | --- |
| Local-browser Google SERP (Playwright) | Search results for the configured keyword and market context | A point-in-time result; anti-automation challenges can prevent a valid capture. Browser geolocation is set, but network location may still affect results. |
| DataForSEO Labs | Keyword, intent, domain, and competitor context | Paid API data, separate from the live SERP capture. |
| DataForSEO Backlinks | Domain- and ranking-page backlink metrics | Counts and summaries do not establish link quality or ranking causation. |
| Playwright public-page crawl | Rendered content and technical/page fields from captured URLs | Only publicly accessible content rendered during capture is in scope. Sign-in-only content is not collected. |
| Screenshot + Pillow pixel comparison | Visual differences between two successful page captures | Pixel changes can result from ads, animation, layout, or timing; inspect the screenshots before interpreting. |
| Optional local Tesseract OCR | Text recognized from selected banner/image candidates | OCR can miss or misread text; results need human review. |
| Local LLM | Narrative synthesis of the saved evidence packet | Runs through the configured local OpenAI-compatible endpoint. It does not collect data or independently verify claims. |

DataForSEO SERP scripts are retained for legacy/reference use; the current main SERP collection path uses the local browser. Raw source data is kept separate from normalized and analyzed outputs so local processing can be repeated without recollecting data. Paid Labs and Backlinks requests still require explicit execution and may incur charges.

## Requirements and configuration

- Windows, Python, and an installed Chrome or Edge browser.
- A local LLM service compatible with the OpenAI client for executive synthesis.
- DataForSEO credentials only for Labs/Backlinks collection.
- Tesseract OCR installed separately if OCR-based promotion text extraction is wanted. Python image/OCR dependencies are listed in `requirements.txt`.

Create a local `.env` from `.env.example` and enter credentials locally. Never commit `.env` or paste API credentials into project documentation. Important settings include `KEYWORD` (currently `aviator`), `OUR_DOMAIN`, `BENCHMARK_COMPETITOR_DOMAIN`, location settings, Playwright capture timeouts, and local-LLM settings documented in `llm_foundation/inference.py` and the relevant configuration files. Keep local `.env` values private.

Install dependencies from the project root in PowerShell:

```powershell
.\setup.bat
.\.venv\Scripts\Activate.ps1
```

If Tesseract is not on PATH, set `TESSERACT_CMD` in the local environment to the installed `tesseract.exe` path.

## Run the dashboard

From the project root:

```powershell
.\.venv\Scripts\Activate.ps1
python -m scripts.test_dashboard
python -m scripts.serve_dashboard --port 8000
```

Open <http://127.0.0.1:8000/>. The dashboard opens on **Decisions & actions**; use the navigation for **Competitor change analysis**. If port 8000 is already occupied, choose another port (for example `--port 8001`) and open that port instead. The dashboard reads saved local files; starting it does not perform a new scrape or LLM run.

## Refresh the Aviator analysis

The collection and analysis stages are separate so saved evidence can be reused. Use the existing snapshot when possible; live SERP collection may be blocked by search-engine challenges. DataForSEO calls are paid and should be previewed before execution.

Example staged workflow from the project root (PowerShell):

```powershell
# Collect current local-browser SERP evidence
python -m scripts.keyword_pipeline --keyword "aviator" --stage serp

# Resolve ranking-page URLs and crawl public pages
python -m scripts.keyword_pipeline --keyword "aviator" --stage resolve -- --engine google
python -m scripts.keyword_pipeline --keyword "aviator" --stage crawl

# Optional paid sources: inspect the dry-run first, then add --execute to make the request
python -m scripts.keyword_pipeline --keyword "aviator" --stage labs -- --action search_intent
python -m scripts.keyword_pipeline --keyword "aviator" --stage backlinks -- --side ours --level domain --type summary

# Normalize and compare saved evidence
python -m scripts.keyword_pipeline --keyword "aviator" --stage normalize
python -m scripts.keyword_pipeline --keyword "aviator" --stage analyze

# Build structured evidence, run specialist local-LLM tasks, then executive synthesis
python -m scripts.build_llm_foundation --keyword "aviator"
python -m scripts.run_llm_specialist --keyword "aviator" --task onpage
python -m scripts.run_llm_specialist --keyword "aviator" --task backlinks
python -m scripts.run_llm_specialist --keyword "aviator" --task technical
python -m scripts.run_llm_specialist --keyword "aviator" --task competition
python -m scripts.run_llm_executive --keyword "aviator"
```

The local LLM endpoint and model must be running/configured before LLM tasks. See `llm_foundation/inference.py` for the expected connection settings. Other pipeline stages are available through `scripts.keyword_pipeline`; despite the dispatcher accepting a keyword, the dashboard and validated Aviator report should be treated as an Aviator MVP, not as a fully verified arbitrary-keyword product.

## Capture competitor changes

### Promotion intelligence and combined activity

The **Competitor activity** page combines observations from all registered pages. Filter by competitor, URL, event type, promotion category, date (South Africa time), or wording. Results are paginated. Plain-language summaries lead each event; raw comparisons and original screenshot links are expandable. First observed means first recorded by this engine, not the promotion's launch date. Older events are reconstructed from saved snapshots where possible; missing historical evidence is explicitly labelled.

On **Competitor change analysis**, clickable category panels filter the saved promotion cards. Labels may overlap (for example Cashback + Game-specific offers). Counts respect source/search/evidence filters. The rules use captured wording, not image filenames. Reviewers can correct categories or clear the overrides to restore automatic labels. Labels and summaries are generated locally without an LLM or OCR; collecting fresh pages and public terms still requires internet access.

Automatic investigation remains limited to three eligible public links per capture; candidates waiting for investigation are prioritized on later captures. A candidate is **automatically corroborated** only when retained card, offer-page, and terms-page evidence on three distinct same-host URLs repeats the offer promise, agrees on at least one key field, and contains no conflicting populated key-field sets. Otherwise it remains **public details available** or **needs more evidence**. Corroboration covers the observed wording and fields, not every legal condition or whether a customer qualifies. Existing merged historical data is not treated as independent corroboration. Team confirmation remains separate.

Promotion history now retains before/after wording and original snapshot IDs. Destination-based identity matches require similar wording and an unambiguous best match; aliases prevent a matched promotion from being aged out in the same capture. For future captures, image pixel hashes distinguish artwork changes from wording changes, starting after the first hash baseline. Text-backed promotions can be tracked without OCR. Promotion dates and hours are preserved in comparisons.

The page schedule form enables/pauses each URL and sets its check interval. It does not start the scheduler. The dashboard and scheduler share a capture lease so they cannot capture the same page concurrently. Captures that remain unfinished for over 30 minutes are marked failed when another attempt starts. Failed or limited checks appear in the combined activity feed.

Regression checks for this workflow: `python -m pytest tests/test_promotion_intelligence.py tests/test_promotions.py tests/test_monitoring.py tests/test_shadow_dom_capture.py -q`. These fixtures verify behavior; they are not a measured real-world promotion detection accuracy score.

Open **Competitor change analysis**. Select a saved URL or add another public URL, then use **Capture & compare**. The first eligible capture establishes a baseline; later eligible captures are compared. The page shows latest capture health, rendered text and screenshot evidence, field changes, a combined page/promotion activity timeline, and current/historical promotion candidates. Promotion text is filtered locally using rule-based phrases; high-confidence candidates may have their same-host public offer and terms pages investigated automatically. Use the text/image filter and search field to review candidates, then confirm or dismiss them. The capture stores artifacts locally under the monitoring data directories. Review screenshots, extracted text, changes, promotion details, and source excerpts together—pixel differences, OCR, and rule matches are signals for investigation, not conclusions.

To enable recurring checks, run the scheduler in a separate terminal:

```powershell
python -m scripts.run_monitoring_scheduler
```

The scheduler is not installed as a Windows service and is not started automatically; it stops when its terminal/process stops. Failed attempts are retried no sooner than the monitored page's configured interval.

## Where files are stored

- `data/raw/` — source-specific raw collection outputs.
- `data/processed/` — normalized and resolved data.
- `output/results/aviator/` — comparison reports, evidence packets, and LLM outputs.
- `monitoring/` and monitoring artifact storage — registered pages, capture history, detected changes, screenshots, and related artifacts.

The repository includes generated data and machine-local browser state in some working copies. Treat captures, diagnostic outputs, and model responses as project data; review them before sharing. Never include credentials or private browser profiles in a shared copy.

## Tests and useful references

```powershell
pytest -q
python -m scripts.test_dashboard
```

- `README_INSTALL.md` — installation notes.
- `README_KEYWORD_MODE.md` — notes on keyword-scoped CLI stages; some dashboard statements there may describe an earlier UI and should not override this README.
- `llm_foundation/prompts/` — local-LLM task instructions.
- `monitoring/` — public-page capture, comparison, promotion-candidate, and persistence logic.
