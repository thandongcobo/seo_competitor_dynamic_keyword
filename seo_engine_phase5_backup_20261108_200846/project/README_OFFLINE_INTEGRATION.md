# Existing SEO Engine: Offline Investigation Integration

This update **extends the existing investigation, normalization, comparison and reporting code**. It does not replace the collectors or run live requests.

## Run on Windows (CMD, from `seo_competitor_engine`)

```cmd
.\setup.bat
.\.venv\Scripts\python.exe -m pytest tests\test_investigation_offline_execution.py -v
.\.venv\Scripts\python.exe -m scripts.serve_dashboard --port 8000
```

Open http://127.0.0.1:8000/ -> **Keyword search** -> **Compare two exact webpages**.

For the available historical evidence, enter:

- Keyword: `aviator`
- Page A: `https://www.hollywoodbets.net/aviator`
- Page B: `https://www.betway.co.za/aviator`

Click **Save investigation & check saved evidence**, then **Run offline comparison**. The dashboard offers a download of the generated historical PDF.

Each run creates `data/investigations/<investigation_id>/processed/`, `results/`, and `offline_execution.json`. The original `data/raw/`, historical Gemma outputs and legacy reports are never overwritten. The execution record contains SHA-256 hashes for the source files.

## What is executed

- Verify all 12 raw saved evidence items against keyword, domain and exact-page source metadata, and recheck their hashes.
- Normalize the verified raw Labs, Backlinks, Playwright and Lighthouse evidence using the existing normalizers.
- Reuse the historical normalized Google SERP **only when both exact pages appear**. Its timestamp is preserved; it is not presented as a fresh ranking.
- Run the existing deterministic comparison and recommendation engine with investigation-isolated paths.
- Replay the **previously saved** validated executive Gemma response for the matching Aviator/Hollywoodbets/Betway comparison; do not invoke Gemma.
- Generate the existing executive PDF and technical appendix in the investigation's result folder.

No Google, DataForSEO, Playwright, Lighthouse or local LLM calls are made by this offline action. The separate **Search Google** button remains a live search and is **not part of offline replay**.

## Important boundaries

- Other keywords or page pairs can be entered and saved, but offline execution **refuses missing or mismatched evidence** rather than substituting Aviator data.
- The current PDF template contains Hollywoodbets/Betway-specific language. Offline PDF generation is therefore restricted to the supported orientation of this Aviator pair; the reverse comparison can be processed via the Python API with `generate_pdf=False`.
- Historic Gemma outputs validate downstream wiring, **not improved inference quality**. The next project phase is to prevent specialist findings being compressed, filtered or replaced by executive synthesis and report publication.
- This is an integration test with real saved evidence. It is not a new live ranking, a new audit or an API/LLM connectivity test.
- The original test suite has pre-existing failures; compare new failures against the baseline.
