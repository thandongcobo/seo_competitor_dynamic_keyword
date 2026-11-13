# Dynamic keyword mode (Windows CMD)

Your uploaded `.env` and `.venv` are deliberately NOT distributed. Keep your local credentials and virtual environment.

From project root:

```cmd
setup.bat
.venv\Scripts\activate
python -m scripts.keyword_pipeline --keyword "aviator" --stage serp
python -m scripts.keyword_pipeline --keyword "aviator" --stage resolve -- --engine google
python -m scripts.keyword_pipeline --keyword "aviator" --stage normalize
python -m scripts.keyword_pipeline --keyword "aviator" --stage analyze
```

For another keyword, use `--keyword "online slots"` in each command. No Python edits are required. The SERP stage reuses saved data unless `--refresh` is explicitly passed. The Labs and Backlinks stages require explicit `--execute` and may incur charges; always preview first:

```cmd
python -m scripts.keyword_pipeline --keyword "online slots" --stage labs -- --action search_intent
python -m scripts.keyword_pipeline --keyword "online slots" --stage labs -- --action search_intent --execute
```

The original teammate collector remains unchanged. Google `gl=za` is used; the stored coordinates are metadata, not applied to Google.

Raw files are keyword-prefixed. Normalized files live under `data/processed/<keyword_slug>/` and analysis under `output/results/<keyword_slug>/`. Browser profiles are never packaged. The existing dashboard may still need an explicit keyword selector to browse the new output directories; no UI keyword selector has been implemented here.

If you already have an old successful Aviator snapshot, it remains in `data/raw/serp/aviator_google_playwright.json` and will be reused. Do not pass `--refresh` unless you want a new Google request.
