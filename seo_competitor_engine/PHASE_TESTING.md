# Phase testing

All phase tests below are offline and do not call DataForSEO.

```powershell
python -m scripts.test_phase --phase 1
python -m scripts.test_phase --phase 2
python -m scripts.test_phase --phase 3
python -m scripts.test_phase --phase 4
python -m scripts.test_phase --phase 5
python -m scripts.test_phase --phase 6
pytest -q
```

Recommended live-data sequence:

1. DataForSEO credentials
2. Google SERP
3. Bing SERP
4. Labs
5. Backlinks
6. Resolve competitors/pages
7. Playwright crawl
8. Normalize
9. Run analysis

Use `--execute` only on the live DataForSEO collection commands. Do not use `--force` unless a deliberate paid re-request is required.
