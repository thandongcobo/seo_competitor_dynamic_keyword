# Manual keyword + exact webpage investigations (offline first)

This update extends the existing SERP investigation workflow; it does not replace the original domain selectors, SERP collector, monitoring dashboard, or SEO analysis scripts.

## How to use

1. From the project root on Windows, run `setup.bat` (if this is a fresh extraction).
2. Start the dashboard with `.venv\Scripts\python.exe -m scripts.serve_dashboard --port 8000`.
3. Open `http://127.0.0.1:8000/`, then **Keyword search**.
4. In **Compare two exact webpages**, enter the keyword and two complete public `https://...` page URLs.
5. Select **Save investigation & check saved evidence**.

The backend saves:

- `data/investigations/<id>/selection.json`: keyword, exact entered URLs, observed exact-page Google positions (or null), saved SERP fingerprint, and investigation status.
- `data/investigations/<id>/offline_evidence.json`: evidence availability, verified source file paths and SHA-256 hashes. All items are read from disk; none are fabricated.

You can inspect the inventory at `GET /api/investigations/<id>/offline-evidence` and the selection at `GET /api/investigations/<id>`.

## Offline Aviator verification

Enter `aviator`, `https://www.hollywoodbets.net/aviator` and `https://www.betway.co.za/aviator`. With the bundled saved evidence, the inventory should find the previously collected domain/page DataForSEO, Playwright and mobile Lighthouse files. It matches each source by its recorded target; it never assumes a filename's `ours`/`benchmark` side still means the same domain after reversing the selected pair.

An inventory status of `available` means saved source metadata matched. It does **not** mean the evidence is fresh, its SEO content is complete, or that the full analysis was run. Saved rankings are observed positions for exact URLs only; a different URL on the same domain does not inherit a rank.

For another keyword or URL with no matching saved evidence, the investigation is still saved, but ranks are null and the missing evidence is clearly reported. The engine does not silently reuse Aviator data.

## Scope and safety

- No Google, DataForSEO, Playwright, Lighthouse, or Gemma requests are triggered by manual investigation creation or offline inventory.
- The existing live **Search Google** button remains a separate, explicit action.
- Existing domain-based investigation selection remains available for backward compatibility.
- The complete selected-pair execution workflow is **not yet connected**. The next integration step is to make existing collectors, normalization, four specialists, synthesis and PDF consume the selected investigation context with isolated output paths. No API calls should be made until that path is tested and explicitly enabled.
- The later project phase remains preserving detailed Gemma specialist findings through executive synthesis and actionable recommendation reporting.

## Tests

Run `.venv\Scripts\python.exe -m pytest tests\test_manual_page_investigations.py tests\test_serp_investigation_selection.py -v`.
