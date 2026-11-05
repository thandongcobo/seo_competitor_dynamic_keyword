SEO COMPETITOR ENGINE - TEAMMATE COLLECTOR INTEGRATION PATCH

From this ZIP, COPY/ADD these files into your existing seo_competitor_engine root:

  scripts/team_serp/SEO_SERP_Monitor_aviator.py  (ADD; original teammate source, unchanged)
  collectors/team_serp_adapter.py              (ADD)
  scripts/collect_team_serp.py                 (ADD)

Do NOT replace existing scripts/collect_playwright_serp.py, normalization,
Labs, Backlinks, frontend, data, .env, or .venv. This is an additive patch.
Do NOT copy your teammate's Chrome profile or their cookies.

CMD commands from the existing project root:
  .venv\Scripts\activate
  python -m scripts.collect_team_serp
  python -m scripts.resolve_pages --engine google

The first command saves data/raw/serp/<KEYWORD>_google_playwright.json.
Existing successful data is reused by default. --refresh intentionally
makes a new search. Google CAPTCHA/challenge is recorded as a failure;
no CAPTCHA bypass or automatic retry is attempted.

IMPORTANT:
- The teammate's original Google search and extraction functions run
  unchanged, but the Excel/hourly runner is NOT executed.
- The teammate script is limited to 10 organic results, not 50.
- Google targeting uses hl=en, gl=za, and browser/network location; the
  coordinates in .env are NOT sent to Google by this collector.
- This adapter requires playwright and openpyxl from the existing project.
- If Chrome blocks the session, do not repeatedly retry.
