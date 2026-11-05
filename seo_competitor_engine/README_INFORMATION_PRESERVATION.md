# SEO Competitor Intelligence Engine — Information Preservation Update

This update extends the existing project, preserving the dynamic manual keyword / exact-two-URL offline comparison, SERP collector, monitoring dashboard, saved Aviator DataForSEO evidence, and existing Gemma specialist architecture.

## What changed

- Full original findings from all four saved specialists are carried into the executive evidence packet with stable finding IDs and SHA-256 fingerprints. Specialist opinions remain **unverified interpretations**, not validated SEO measurements.
- The publisher no longer overwrites validated Gemma executive summaries, findings, or decisions with shorter deterministic text. It adds separate `verified_factual_summary` and `verified_factual_findings` for safe, source-grounded reference.
- The executive LLM can optionally produce `implementation_plans` with ordered practical steps, owner, priority, evidence IDs, original specialist IDs, success measurement and uncertainty. Validation rejects unknown references or incomplete plans.
- The report includes an unabridged specialist-finding section and all generated implementation plans, not only the first three management decisions.
- The fixed legacy request-token budget is removed. The full specialist evidence is used by default. Set `LLM_MAX_INPUT_TOKENS` only if your local model server has a known limit. Optional `LLM_MAX_OUTPUT_TOKENS` and `LLM_TIMEOUT_SECONDS` are available.
- Offline investigation replay can upgrade its **own output copy** using the saved original Gemma executive response and all specialist outputs; historical source files remain untouched.

## Test the existing Aviator evidence without making any requests

Open the `seo_competitor_engine` directory in CMD/VS Code and run:

```cmd
.\.venv\Scripts\python.exe -m pytest tests\test_information_preservation.py tests\test_investigation_offline_execution.py -v
.\.venv\Scripts\python.exe -m scripts.run_llm_executive --keyword aviator --republish-saved --output-dir output\preservation_test\aviator\llm_outputs
.\.venv\Scripts\python.exe -m scripts.generate_executive_pdf --keyword aviator --input output\results\aviator\aviator_comparison.json --output-dir output\preservation_test\aviator
```

Review:

- `output/preservation_test/aviator/llm_outputs/information_preservation_report.json`
- `output/preservation_test/aviator/llm_outputs/executive_validated.json`
- `output/preservation_test/aviator/aviator_executive_report.pdf`

The historical Aviator data contains **11 original specialist findings**. All 11 were preserved in the offline replay, with no missing or modified findings. The old executive response has **zero structured implementation plans**, because it was generated before the new schema existed. The report transparently labels this gap; it does not invent steps or claim that the old model produced them.

## Test fresh Gemma executive synthesis later (explicitly calls local LLM)

With your existing `.env` and local Gemma server configured, run:

```cmd
.\.venv\Scripts\python.exe -m scripts.run_llm_executive --keyword aviator --dry-run --output-dir output\gemma_tests\aviator\llm_outputs
.\.venv\Scripts\python.exe -m scripts.run_llm_executive --keyword aviator --output-dir output\gemma_tests\aviator\llm_outputs
.\.venv\Scripts\python.exe -m scripts.generate_executive_pdf --keyword aviator --input output\results\aviator\aviator_comparison.json --output-dir output\gemma_tests\aviator
```

Only the **second command** makes a local Gemma request. None of these commands make new Google, DataForSEO, Playwright or Lighthouse requests. The separate output directory protects the historical baseline. Verify the server's real context/output limits and configure the optional environment variables if needed. A new inference can fail validation; inspect the saved failure diagnostics and do not treat failed outputs as final reports.

## Validation boundaries

- Retention tests prove specialist content survives the processing pipeline; they do **not** prove the model's new implementation plans are good SEO advice.
- Generated implementation plans must be reviewed for practicality, compliance and factual accuracy before deployment.
- No live local Gemma inference was run in the build environment; it cannot access your private local model endpoint or `.env` credentials.
- The existing baseline test suite has 12 known failures unrelated to this update; no new failures were introduced.
- The earlier Decisions & Actions UI restoration remains postponed, as agreed.
