# START HERE - SEO Competitor Analysis Engine MVP

This project is the first end-to-end version of the SEO competitor analysis engine.

## Objective

Given a target keyword, compare our website with Betway and dynamically discovered search competitors using:

- Playwright - Google + Bing SERP collection from the local browser
- DataForSEO Labs API - Google domain/keyword intelligence
- DataForSEO Backlinks API
- Playwright - page-level crawling

The MVP saves raw data as JSON, normalizes it, runs Python comparisons, and produces a structured result ready for a future LLM recommendation layer.

## New project setup from scratch

From the extracted `seo_competitor_engine` root in a VS Code PowerShell terminal:

```powershell
.\setup.bat
.\.venv\Scripts\Activate.ps1
```

Open `.env` and enter the API credentials. Do not share them.

Required settings:

```text
DATAFORSEO_LOGIN=your_api_login
DATAFORSEO_PASSWORD=your_api_password
KEYWORD=aviator
LANGUAGE_CODE=en
LOCATION_COORDINATE=-29.7359502,31.0699179,200
LABS_LOCATION_NAME=South Africa
OUR_DOMAIN=hollywoodbets.net
BENCHMARK_COMPETITOR_DOMAIN=betway.co.za
SERP_DEPTH=50
COMPETITOR_WINDOW=5
CANDIDATE_CRAWL_LIMIT=12
```

The coordinate is the user-supplied location target, rounded to the maximum 7 decimal places supported by DataForSEO.

## Cost protection

Do not use `--force` during normal testing. Identical paid requests are cached locally by endpoint + payload.

A command without `--execute` is a dry run and does not call DataForSEO.

## Live data sequence

1. Test credentials once:

```powershell
python -m scripts.test_connection --execute
```

2. Google SERP:

```powershell
python -m scripts.collect_serp --engine google --execute
python -m scripts.fetch_serp --engine google --execute
```

3. Bing SERP:

```powershell
python -m scripts.collect_serp --engine bing --execute
python -m scripts.fetch_serp --engine bing --execute
```

4. Labs:

```powershell
python -m scripts.collect_labs --action search_intent --execute
python -m scripts.collect_labs --action keyword_overview --execute
python -m scripts.collect_labs --action ranked_ours --limit 100 --execute
python -m scripts.collect_labs --action ranked_benchmark --limit 100 --execute
python -m scripts.collect_labs --action competitors_domain --limit 100 --execute
python -m scripts.collect_labs --action domain_intersection --limit 100 --execute
```

5. Discover target and competitor pages:

```powershell
python -m scripts.resolve_pages --engine all
```

6. Backlinks for both domains and ranking pages:

```powershell
python -m scripts.collect_backlinks --side ours --level domain --type summary --execute
python -m scripts.collect_backlinks --side benchmark --level domain --type summary --execute
python -m scripts.collect_backlinks --side ours --level page --type summary --execute
python -m scripts.collect_backlinks --side benchmark --level page --type summary --execute
```

7. Crawl pages with local Chrome/Edge through Playwright:

```powershell
python -m scripts.crawl_pages
```

8. Normalize everything:

```powershell
python -m scripts.normalize_data
```

9. Generate the LLM-ready comparison:

```powershell
python -m scripts.run_analysis
```

Final output:

`output/results/aviator_comparison.json`

## What the SERP data means

The raw SERP preserves all returned SERP elements. The normalized SERP separates organic results from non-organic SERP features. Organic ranking calculations use `rank_group`.

Top 50 means the API is asked to retrieve 50 results/elements at the configured depth; the processor then identifies the organic group and retains the full SERP evidence. The project does not rewrite the keyword to add gambling context.

## Competitor policy

Betway is the permanent benchmark. All organic domains in the captured Top 50 are retained as candidate search competitors. Ranking neighbours around Hollywoodbets are prioritized. Labs competitor data is merged with SERP candidates. The project deliberately avoids hard-coded keyword-term filters.

## SSL / corporate proxy

The DataForSEO client injects the Windows/system certificate store through `truststore`, while keeping TLS verification enabled.

## Storage

PostgreSQL is intentionally not used yet. Raw DataForSEO responses and Playwright SERP/page snapshots remain in isolated JSON areas. DataForSEO Labs/Backlinks requests are cached locally so analysis logic can be changed repeatedly without re-paying for the same request.
