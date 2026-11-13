SEO Competitor Engine - Frontend Patch

Copy these items into the ROOT of your existing seo_competitor_engine project:
  frontend\
  scripts\serve_dashboard.py
  run_dashboard.bat

Do not replace your data, .env, collectors, analysis, normalization, or existing scripts.

Run from the project root:
  .\.venv\Scripts\Activate.ps1
  python -m scripts.serve_dashboard

Open:
  http://127.0.0.1:8000/

The dashboard is read-only. It reads existing JSON files and does not call DataForSEO.
