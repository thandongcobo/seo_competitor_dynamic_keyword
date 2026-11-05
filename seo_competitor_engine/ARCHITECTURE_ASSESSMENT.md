# SEO Competitor Intelligence Engine — Architecture Assessment

**Inspection date:** 3 November 2026  
**Scope:** Read-only source, documentation, saved artifact, and test inspection. No collection, API, model, or test execution was performed.  
**Repository state:** No project files were modified for this assessment; this document is the sole deliverable.

## Executive summary

This repository is more than the Aviator-only baseline described in the main README. It now contains (a) a keyword SERP search and selection UI, (b) a manual exact-two-URL investigation flow, (c) offline replay of evidence that is already saved and precisely matched to those URLs, (d) four Gemma specialists, (e) a focused recommendation-development stage with validation and partial recovery, (f) an explicit report-generation bridge, history retrieval, and (g) a separate page-change and promotion monitoring subsystem.

The core recommendation-quality issue has been addressed architecturally in several ways: canonical fact whitelists separate measurements from specialist interpretation; original specialist findings retain IDs and hashes; focused recommendations must cite approved facts linked to those findings; numeric and citation validators trigger scoped retry/repair; and unrepairable connected actions can be quarantined while unrelated work survives. These are meaningful safeguards, but they do not establish that a recommendation is correct, useful, compliant, or capable of improving rankings. The quality audit is heuristic and report drafts require human review.

The main business-objective gap is end-to-end arbitrary investigation execution. Users can search any keyword and save arbitrary exact URLs, and the analysis/LLM/reporting modules have dynamic arguments. But the manual investigation execution is an **offline replay from fixed global data folders**, and reporting requires a matching saved comparison plus four matching saved specialist outputs. There is no connected, investigation-scoped collector orchestration that collects fresh SERP, exact pages, page/domain backlinks, Labs and Lighthouse evidence for any selected pair. UI search exposes location/device controls only incompletely: SERP collection uses a Google browser context, while DataForSEO Labs location/language and Lighthouse device settings are separate configuration/collector choices. Historical data, one-time live search and a complete repeatable investigation are not the same capability.

## Evidence labels used here

- **Confirmed:** directly visible in code or a checked-in test/document.
- **Documentation claim:** stated in a README, phase note or project log, not independently established as a runtime result here.
- **Not confirmed:** the repository inspection does not establish the behavior or a test does not cover it.

The README files contain conflicting phase snapshots. Later code and tests demonstrate that some earlier “not yet implemented” notes are stale. Where appropriate, this assessment reports the code state and notes the documentation conflict.

## 1. Existing end-to-end architecture

### A. Live SERP search and exact-page selection

1. The dashboard at `frontend/index.html` / `frontend/js/app.js` calls `POST /api/serp/search` in `scripts/serve_dashboard.py`.
2. `scripts/dashboard_serp_search.py::start_search` validates the keyword and depth, runs `scripts.collect_team_serp --refresh` in a background thread, and verifies the saved snapshot timestamp is newer than the job start. Search job state is in memory. `read_snapshot` accepts only a successful/partial Google Playwright observation matching the requested keyword. It labels saved results separately from new results.
3. The collection path is the local browser collector (`collectors/team_serp_adapter.py`, `collectors/team_serp_pagination.py`, `collectors/tracked_serp.py`, and teammate script under `scripts/team_serp/`). Older DataForSEO SERP scripts remain, but the README and current search adapter identify the browser collector as the dashboard path. Google challenges and IP/session differences remain possible.
4. `scripts/serp_investigations.py::selection_options` and `create_investigation` allow two distinct observed SERP domains, binding the selection to a SERP SHA-256. Separately, `create_page_investigation` allows any two different public HTTP(S) URLs (including two URLs on one domain), saves exact URL identities, and records a rank only if that exact URL is in the saved SERP. It does not make a collection request. URL checks reject credentials, local hostnames, IP literal targets and nonstandard ports.
5. Selections are persisted under `data/investigations/<id>/selection.json`. `scripts/search_investigation_history.py::search_history`, exposed at `/api/investigations/history`, scopes results by keyword and/or URL pair and returns artifacts only from the corresponding investigation directory.

**Important scope:** Google search, exact URL selection, and analysis are distinct operations. SERP search does not run an SEO comparison; saving two manual URLs does not crawl them.

### B. Existing general-purpose collection and deterministic comparison path

The CLI dispatcher `scripts/keyword_pipeline.py` passes a keyword through `SEO_KEYWORD` and invokes independent stages:

| Stage | Entry point / primary responsibility | Evidence/output |
|---|---|---|
| SERP | `scripts.collect_team_serp` (browser); legacy `collect_serp.py`, `fetch_serp.py`, DataForSEO client | Raw Google observation; optionally Bing/legacy source |
| URL resolution | `scripts.resolve_pages` | Exact observed domain ranking URLs and ranks |
| Labs | `scripts.collect_labs` + `collectors/labs_collector.py` | Intent, ranked keywords, competitors, domain intersection; explicit `--execute` for paid calls |
| Backlinks | `scripts.collect_backlinks` + `collectors/backlinks_collector.py` | Page or domain summaries/sample; exact page URL resolved from SERP; explicit `--execute` |
| Page crawl | `scripts.crawl_pages` + `collectors.playwright_collector.crawl_page` | Public rendered page metadata, headings, links, structured data, cleaned main content, readiness and diagnostics |
| Lighthouse | `scripts.collect_lighthouse.py` | Page-level mobile/desktop lab audit; not field Core Web Vitals |
| Normalize | `scripts.normalize_data.py` and `normalization/*` | Keyword-namespaced processed files; target identity and quality metadata retained |
| Analyze | `scripts.run_analysis.py::main` | Comparison JSON and deterministic recommendations/report |

`analysis.rankings`, `analysis.keywords`, `analysis.backlinks`, `analysis.onpage`, `analysis.intent`, `analysis.advanced_evidence`, `analysis.technical_diagnostics`, `analysis.comparison_engine` and `analysis.recommendations` perform the comparison. `run_analysis.validate_page` requires exact URL alignment, a complete crawl, and a minimum extracted word count; `validate_backlinks` requires verified exact-page target and scope. Lighthouse audits are withheld on URL mismatch. The output records non-causation limitations.

`analysis.recommendations.generate_recommendations` uses generic keyword and URL inputs. It provides rule-based opportunities for verified page backlink differences, filtered relevant generic query gaps, title/meta/H1 differences, and detailed mobile Lighthouse diagnostics. Recommendations include an ordinal triage score, actions, a verification check and caveats; it explicitly does not forecast ranking/traffic lift. This is separate from the newer Gemma focused recommendation layer.

### C. Manual exact-URL offline evidence execution

1. `create_page_investigation` invokes `scripts.investigation_offline.evidence_inventory` to look for raw saved files matching keyword, domain and URL metadata. It stores each eligible source path and SHA-256. “Available” means the source metadata matches, not that the evidence is fresh or analysis-ready.
2. The inventory checks 12 items: for each side, Labs ranked keywords, page/domain backlink summary, Playwright page, mobile Lighthouse; plus domain intersection and search intent.
3. `scripts.run_investigation_offline.run` / `_run_impl` rechecks inventory completeness, source hashes, keyword and exact page positions in the historical normalized Google SERP. It normalizes saved raw inputs into an investigation-local `processed/` folder, copies the historical SERP, and invokes the existing deterministic analysis with isolated paths and exact selected URLs.
4. It produces `results/<keyword>_comparison.json` and provenance in `offline_execution.json`. It makes no collection or model requests. The checked-in supported historical executive replay is restricted to the exact Aviator/Hollywoodbets/Betway pairing; mismatched pairs cannot reuse it. The legacy PDF pathway has Aviator/pair limitations. For some manual selections, a comparison can be made only if all required pre-existing evidence matches; arbitrary new evidence is not gathered by this runner.

The implementation uses existing module globals in `scripts.run_analysis` and temporarily replaces them inside a lock before restoring them. This is a compatibility bridge, not a clean investigation-context API.

### D. Canonical evidence and four Gemma specialists

`scripts.build_llm_foundation` calls `llm_foundation.foundation.build` on a saved comparison JSON. It makes no external request. In `llm_foundation/foundation.py`:

- `canonicalize` creates a versioned canonical representation and checks ranking page identity, crawl quality, exact URL, Lighthouse target/final URL, and backlink scope.
- `scrub` drops selected sensitive or bulky fields (`text_sample`, `seo_content_text`, `raw_html`, `screenshot`, credentials, and location coordinates) and strips URL query strings.
- `SPECIALISTS` defines four focused packets: onpage, backlinks, technical, competition. `make_packets` copies only each task’s listed sections plus shared investigation metadata.
- `build_coverage_manifest` records categories selected/omitted and reasons.

`scripts.run_llm_specialist` runs one task using `llm_foundation.inference` and a local OpenAI-compatible configured endpoint. It supports dry run; actual calls happen only without `--dry-run`. It validates and stores each specialist output and metadata separately. Prompts live in `llm_foundation/prompts/`.

### E. Executive evidence packet, recommendations, validation and recovery

There are two recommendation routes in the repository:

**Legacy fifth-request synthesis:** `scripts.run_llm_executive` calls `executive_synthesis.build_packet`, `build_prompt`, and `infer`. The executive packet explicitly constructs a whitelist of facts (`SERP`, `ON_TITLE`, `ON_LINKS`, `ON_CONTENT_SIMILARITY`, `BL_PAGE`, `BL_DOMAIN`, `TECH_LAB`, `TECH_INV`, `KW_SHARED`, and verified `KW_QUERY_GAPS`). It adds stable specialist finding IDs and hashes via `information_preservation.specialist_records`, marks specialist prose as unverified interpretation, and maps finding evidence paths to fact IDs. The validator checks schema, citation lineage, numeric claims, metric direction, scope and factual consistency. `infer` retains the original model text, may issue targeted repair requests restricted to invalid fields, and only publishes after validation. `structured_facts.publish_verified_response` keeps the validated model summary/findings/decisions and appends separately labeled deterministic factual summaries/findings. It does not create missing implementation plans from old outputs.

**Focused recommendation-development route:** `scripts.run_llm_focused_recommendations` uses `focused_recommendations.task_packet`, `task_request`, `validate_task`, and `merge_tasks`. It makes up to four independently scoped LLM requests (onpage, backlinks, technical, competition), each limited to five plans, rather than one fifth summarization call. Every original specialist finding must receive a disposition; an action/merged disposition must point to a plan citing that finding; plan facts must be permitted by that finding’s `specialist_fact_links`. The deterministic merger preserves all four validated outputs and lineage. Resume fingerprints avoid repeating matching successful task calls; partial successful task outputs survive a later failure.

After per-task retries, `evidence_recovery.recover_invalid_task` can reanalyse only saved evidence. It sanitizes narrowly localized unsupported numeric explanation fields or quarantines connected invalid plan/finding groups and replaces their dispositions with investigate/review records. The original attempt and detailed recovery audit are retained. Unknown/unlocalized failures fail closed. `recommendation_quality.audit_recommendations` checks scope, unsupported inference, internal-link direction, unmeasured traffic-loss claims, thin procedures/explanations, post-change verification, technical safeguards and audience mismatch. It is heuristic, not an SEO correctness oracle. `quality_repair.py` offers targeted repair while retaining audit history; dashboard reporting checks evidence and quality before publication.

### F. Reports, reporting jobs and stored history

`scripts.generate_executive_pdf.py` is an offline renderer. It requires an explicit saved comparison and validated executive JSON with plans, dispositions and verified facts, checks recommendation quality and reciprocal specialist-plan lineage, then writes a management PDF, full Markdown technical appendix, quality report and hash manifest. The appendix includes all implementation steps, dispositions and original specialist findings. The management PDF is shorter and not a substitute for technical detail.

`scripts.reporting_jobs.py::_preflight` verifies that a manual investigation’s saved comparison, canonical packet, and four specialist outputs match its exact keyword and URLs. `start` explicitly launches an opt-in Gemma reporting job. `_execute` copies sources into a run-specific folder with hashes, runs focused recommendation requests, validates/repairs, and generates a report draft. It has no collector stage. The state becomes `draft_ready` pending human review, and `approve` requires an explicit action. Jobs/artifacts are scoped to a run and hash-checked. This is implemented in code and exercised by test mocks, but not live-inference verified here.

### G. Independent competitor change and promotion monitoring

`monitoring/` has its own SQLite store, page capture, change diff, promotion analysis, activity aggregation and scheduler. `monitoring.capture.capture` uses `crawl_page(..., public_only=True)`, tracking-quality checks, screenshots, text/field diffs, and optionally OCR-backed promotion signals. `monitoring.store.validate_public_host` and the crawler’s public-only handling guard public fetches. Capture and schedule are explicit; the scheduler is separately started by `scripts.run_monitoring_scheduler`. Monitoring observations are not ranking-analysis inputs by default. Promotion matches remain candidates and need review; pixel changes are not semantic image understanding.

## 2. Responsibilities of major components

| Component | Responsibility | Key files |
|---|---|---|
| Dashboard/API | Keyword search UI, exact URL/domain selection, evidence/history/reporting endpoints, monitoring UI | `frontend/index.html`, `frontend/js/app.js`, `scripts/serve_dashboard.py` |
| SERP collection | Browser-based Google organic result capture, pagination/diagnostics, tracked-site discovery | `scripts/collect_team_serp.py`, `collectors/team_serp_*`, `collectors/tracked_serp.py`, `scripts/dashboard_serp_search.py` |
| Data acquisition | DataForSEO Labs/backlinks; Playwright page and Lighthouse captures | `collectors/dataforseo_client.py`, `collectors/labs_collector.py`, `collectors/backlinks_collector.py`, `collectors/playwright_collector.py`, scripts under `scripts/collect_*` |
| Identity/normalization | Normalize raw data and attach keyword, page/domain scope, target identity and quality | `scripts/resolve_pages.py`, `scripts/normalize_data.py`, `normalization/*` |
| Deterministic analysis | Rank, on-page, content, backlink, keyword, intent, technical comparisons and baseline actions | `analysis/*`, `scripts/run_analysis.py` |
| Evidence preparation | Canonical schema, privacy scrub, coverage, task-scoped packets | `llm_foundation/foundation.py`, `llm_foundation/evidence_coverage.py` |
| Specialist inference | Four focused Gemma analyses with schema/diagnostic/retry handling | `llm_foundation/inference.py`, prompts, `scripts/run_llm_specialist.py` |
| Recommendation development | Four task-specific action requests, evidence-to-finding links, merge and validation | `llm_foundation/focused_recommendations.py`, `scripts/run_llm_focused_recommendations.py` |
| Executive validation/publication | Fifth-request legacy route, numeric/citation/factual validation, deterministic fact appendices | `llm_foundation/executive_synthesis.py`, `structured_facts.py`, `factual_consistency.py` |
| Recovery/quality | Scoped retry guidance, citation repair, partial recovery, output audit/repair | `grounded_retry.py`, `evidence_recovery.py`, `recommendation_quality.py`, `quality_repair.py` |
| Historical investigation | Manual selection manifest, saved-source inventory, offline replay, history search | `scripts/serp_investigations.py`, `investigation_offline.py`, `run_investigation_offline.py`, `search_investigation_history.py` |
| Report generation | Concise PDF plus full technical appendix and provenance | `scripts/generate_executive_pdf.py`, `scripts/reporting_jobs.py` |
| Monitoring | Independent page snapshots, differences, promotion candidates, scheduling | `monitoring/*`, `scripts/run_monitoring_scheduler.py` |

## 3. Exact evidence-preparation and recommendation functions

The central preparation chain is:

1. `scripts.run_analysis.main` builds the comparison from normalized evidence and saves `<slug>_comparison.json`.
2. `scripts.build_llm_foundation.main` selects that file and calls `llm_foundation.foundation.build`.
3. `foundation.canonicalize` validates and transforms evidence. Confirmed transformations/omissions are detailed in section 4 below.
4. `foundation.make_packets` chooses task-specific canonical sections.
5. `scripts.run_llm_specialist.main` loads the task packet, skills and specialist prompt, then calls `inference.run_specialist` unless dry-run.
6. For focused actions, `executive_synthesis.build_packet` combines canonical evidence and all specialists. `specialist_fact_links` maps specialist evidence paths to whitelisted facts.
7. `focused_recommendations.task_packet` selects each task’s facts/findings and allowable links; `task_request` gives the contract; `validate_task` checks output and invokes the executive validators; `generate_task` in the CLI performs bounded retries and evidence recovery; `merge_tasks` performs deterministic assembly.
8. `recommendation_quality.audit_recommendations` audits narrative/procedural quality. `publish_verified_response` appends deterministic factual sections and lineage without replacing validated LLM content.
9. Optional `quality_repair.repair_with_client` operates on flagged fields. Reporting then verifies evidence errors and lineage and calls `generate_executive_pdf.main`.

For the older synthesis route, steps 6–8 call `executive_synthesis.infer` once with targeted invalid-field patch retries; the path is still present and has tests. The active reporting bridge calls the focused four-task route.

## 4. Confirmed evidence loss, exclusion, compression and transformation

“Evidence loss” is not always a defect: privacy filtering, exact-target gating and task focus are deliberate safeguards. The risks below concern whether useful action detail survives or reaches the right stage.

### Confirmed transformations/exclusions

1. **Raw page copy is intentionally dropped before Gemma.** `foundation.scrub` removes `text_sample` and `seo_content_text`; `canonicalize` also limits per-page fields to title, meta description, headings/counts, link counts, structured-data count and standardized word-count/status fields. Exact main-content text and link destinations therefore do not reach the specialist prompts through canonical page evidence. The deterministic analyzer may use cleaned text to compute keyword/topic summaries, but the packet does not retain the source passages needed for the model to substantiate specific missing subtopics or produce grounded copy recommendations. This is the strongest confirmed cause of generic “investigate content differences” actions.
2. **Outbound internal link inventory is discarded.** Raw crawl normalization retains internal/external link arrays, but canonical `safe_pages` retains only counts. The recommendation validator correctly blocks inferring inbound-link deficits from outbound totals; however, the focused packet then lacks the actual anchor text/destination/source-page detail needed to recommend precise supported internal-link edits. It must recommend a separate audit instead.
3. **Topical content comparison is narrow.** `analysis.onpage.compare_pages` derives title keyword flags, term hits from a fixed term list, token Jaccard and top shared tokens. It does not provide an open-vocabulary topic taxonomy, search-question evidence or section-by-section gap map. Canonicalization removes some descriptive raw counts and removes content-comparison fields entirely unless both pages meet strict comparable-content and URL requirements.
4. **Canonicalization hard-requires both primary ranking URLs.** `foundation.canonicalize` raises if either URL is missing. The general manual investigation accepts URLs that are not present in the SERP, but executive packet construction requires integer positions for both and `build_packet` requires ranking URLs. As a result, the LLM/reporting path cannot operate in a no-rank/manual-page mode even where page evidence could otherwise be usable.
5. **Canonical SEO page evidence and executive fact whitelist are partial.** Page safe fields include headings and selected metadata, but focused factual facts mainly expose title keyword presence, aggregate internal-link counts and lexical similarity. There is no explicit fact schema for each heading/topic gap, page link destination, FAQ presence, schema details, canonical/robots configuration or content passage. Such raw comparison output is not directly citeable for plans.
6. **Technical detail is truncated twice.** `foundation.canonicalize` keeps detailed analysis only if both mobile audits and the detailed comparison are usable; `executive_synthesis.build_packet` adds only the first four investigations to `TECH_INV`. Thus evidence can be available in the source Lighthouse artifacts/comparison but withheld if one side is unusable, and investigations after index 4 do not enter the executive facts. The path is appropriately exact-URL scoped but can suppress actionable diagnostics.
7. **Keyword intersection is capped and filtered.** Canonicalization takes at most ten `top_generic_benchmark_leads`; fact construction only keeps rows with positive integer ranks, internally consistent gaps and `relevance_class == relevant_generic`. This avoids bad or third-party terms but can omit relevant lower-ranked rows and the method’s reasons from action prompts.
8. **Domain discovery is descriptive only.** Canonical competitor candidates are limited to the first thirty and carry selected identity/rank fields. Candidate domains are explicitly not verified ranking competitors; they cannot stand in for exact-page comparison.
9. **DataForSEO backlink collection stores summaries in the normal CLI.** The collector can request backlink samples, but the default full pipeline and offline inventory expect page/domain summaries. Without separate sample collection, referring URLs, anchors, status, relevance and topical context are missing; raw totals cannot justify a specific link-building target.
10. **Executive fact layer excludes some original comparison fields.** The deterministic report can include more than the Gemma task facts. The LLM gets a conservative curated subset by design; information not mapped in `SPECIALIST_FACT_PATHS` cannot support a recommendation even if it exists elsewhere in source files.
11. **Location/device provenance is incomplete for comparable business claims.** SERP and DataForSEO Labs have separate location settings; the dashboard SERP context is Google `gl=za` in historical notes, and precise coordinate settings do not necessarily apply there. Lighthouse is separately collected and device-scoped. Canonical `investigation` retains Labs location but does not fully bind per-source capture time, device, language, exact SERP location method and freshness into every fact. This is a provenance limitation, not proof of wrong data.
12. **Some outputs are capped at publication.** Legacy executive schema allows up to eight key findings and three decisions; `publish_verified_response` appends factual findings but does not synthesize implementation plans for older saved model outputs. The focused route preserves all findings/dispositions and all generated plans; the management PDF displays a summary/action brief, while the technical appendix carries full steps.

### What is deliberately preserved

The focused route preserves full specialist findings verbatim with task IDs and hashes and stores each raw model attempt. Historical old executive responses have no plans; the project correctly records that gap rather than inventing plans. Focused plan failures may be quarantined, but raw proposals and recovery audits remain. This is controlled action exclusion, not silent evidence deletion.

## 5. Existing safeguards to preserve

- Exact ranking URL identity gates page crawl, backlinks and Lighthouse comparisons; no same-domain URL substitution.
- Redirected, incomplete, blocked, thin, mismatched or unusable evidence is withheld rather than scored as zero/poor.
- Page and domain backlinks remain separate, and provider “rank” is not treated as Google rank.
- Saved SERP is labeled historical; there is no causal ranking claim from one observation.
- Fact whitelisting prevents model prose from becoming measurements; numeric claim checks also validate metric direction and units.
- Specialist findings are retained as interpretation, not verified fact. Evidence paths map to allowed fact IDs; unknown, orphaned or cross-specialist references fail validation.
- Retry and repair modify only failing paths where safely localizable. Partial recovery quarantines connected invalid action groups, preserves other valid plans, records original text and demands review.
- Recommendation-quality checks cover internal-link direction, traffic loss, query/page scope, post-change verification, technical safeguards and explanations that overpromise.
- Report generator refuses blocking quality failures, incomplete lineage, missing verified facts or stale implicit source files; report manifest records input hashes.
- Dashboard reporting requires explicit start and separate approval; model inference is not silently triggered by page view or offline replay.
- DataForSEO calls require explicit `--execute`; dashboard SERP refresh is a separate user action; test fixtures/mock models avoid external service calls.
- Manual URL validation and public-only monitoring checks prevent common unsafe URL classes. Monitoring is isolated from ranking analysis and labeled as candidate evidence.
- Investigation source files are hash-checked and outputs are run-isolated; history search is scoped to a specific saved investigation.

## 6. Implemented vs incomplete business capabilities

| Capability | Status from code inspection | Limitation |
|---|---|---|
| Search arbitrary keyword | **Implemented** | Local Google browser capture; user location/network and language/device control are not a complete reproducible search-context contract. Search job status is in-memory. |
| Select any two exact pages, manual URLs | **Implemented for selection** | Exact public URLs can be saved; ranking is populated only for exact URL matches in a saved SERP. |
| Collect fresh SEO evidence for arbitrary pair | **Incomplete** | No dashboard/API orchestration runs selected-pair Playwright, Lighthouse and DataForSEO collection into isolated investigation storage. Existing generic CLI collection uses configured tracked/benchmark domains and global keyword paths. |
| Reuse saved exact-match evidence offline | **Implemented with gates** | Requires all inventory items and historical exact-page SERP ranks. Staleness is not assessed. |
| Four specialist analyses | **Implemented for the saved-comparison CLI** | Requires canonical packet; fresh specialist run is a local model request and not connected automatically to arbitrary investigation selection. |
| Explain possible competitive differences | **Implemented with constraints** | Whitelist facts, scope limitations and no-causation policy; content/topic evidence is too compressed for rich specific recommendations. |
| Evidence-backed actionable recommendations | **Implemented as pipeline capability** | Focused plan path exists; actual quality depends on evidence richness and model output. The checked-in PDF and saved outputs are historical; no live recommendation quality was verified in this inspection. |
| Business + technical explanation | **Schema and prompts implemented** | Quality checks are heuristic and may not guarantee meaningful plain language or technically complete procedures. |
| Management and technical reports | **Implemented** | Exact matching saved specialists/comparison required; drafts are gated for human approval. Existing legacy PDF restrictions remain in offline path. |
| Save/retrieve completed investigations | **Partly implemented** | Selection, offline execution, reporting runs and history exist. Search returns saved artifacts/status; completeness and freshness semantics need a coherent run manifest. |
| Competitor page change/promotion monitoring | **Implemented separately** | Registered URLs only, explicit capture/scheduler, heuristic text/OCR/pixel signals, review required; does not crawl/monitor every URL on a domain. |
| Arbitrary keyword/domain independence | **Partially implemented** | Core CLI and focused prompts are dynamic. Current analysis uses `settings.keyword` and configured domains; offline replay is constrained by existing files and ranking assumptions; dashboard main state reads configured keyword. |

## 7. Reference documents and benchmark critique

### `OUTPUTSERP 1 1.txt`

Useful quality patterns include: tie each action to an observed difference; inspect topic coverage rather than raw word count; retain existing advantages; distinguish exact page and domain authority; ask for source review where evidence is insufficient; specify match/improve/outperform options and a verification measure; avoid copying competitor wording.

The text is a console transcript, not a validated evidence export. Its substantive limits include:

- It is Aviator/Hollywoodbets/Betway-specific and gives one snapshot’s ranks/page fields; capture date/context and source lineage are not fully described in the excerpt.
- The 12-topic coverage map uses hand-chosen concepts and presence scores, not a validated measure of topical completeness or semantic quality. “No evidence detected” is not proof of absence.
- It infers FAQ/demo gaps from links or token signals and then recommends further research; the competitor page’s actual answer content and user demand are not established in that transcript.
- It reports internal-link totals without showing whether they are unique, contextual, repeated navigation links, incoming links, or links into the selected page. Its improved recommendation correctly pivots to cluster/link audit rather than count matching.
- It states backlink counts without provider, scope or full timestamp in the transcript. It says domain totals do not explain the gap, which is appropriately cautious but cannot settle page-level link quality.
- Promotion conclusions are inconsistent: the initial investigation says “Promotion evidence: None detected” for both pages, later says HWB has “verified Aviator promotion evidence,” and the printed evidence/actions report an on-page campaign. These statements need a single evidence definition and source record before being treated as fact.
- “Domain intersection returned 1 candidate referring domains/records” mixes keyword intersection and referring-domain language; count semantics need source validation.
- Suggested rank, CTR, engagement and traffic measures are reasonable evaluation ideas but aren’t currently integrated with Search Console or controlled experiments in the inspected engine.

The repository contains real work toward the benchmark’s gap-to-action concept only in its `analysis.*` deterministic recommendations and focused Gemma task prompts; the benchmark’s separate `test_topical_comparison`, `test_gap_to_action`, and action-plan scripts are present in transcript but not as current source modules in this checkout.

### `aviator_executive_report (1).pdf`

The PDF is present (7,855 bytes), but no local PDF text extraction/rendering utility was available in this read-only inspection, so I could not verify its actual pages or wording. **Not confirmed:** its specific recommendation text, measurements, and page structure. The current report generator code establishes the intended current format (concise management brief plus full technical appendix), but cannot prove that this supplied historical PDF was produced by the current code/version. Compare it to its matching comparison JSON, executive JSON, and generation manifest before treating its facts as current.

## 8. Prioritised implementation plan

### P0 — Make one run-scoped investigation contract

Define a single investigation manifest for keyword, two exact URLs, observed ranking identity/status, search engine, language, location method/value, device, collection timestamps, source versions, consent/authorization state, evidence availability, freshness, and provenance hashes. Make collectors accept this context and write only under `data/investigations/<id>/...`. Stop routing arbitrary investigations through global domain settings/module globals. Support “rank unknown” without allowing an unrelated SERP URL or requiring fabricated integer positions.

### P1 — Wire optional fresh collection for the selected pair

Add a resumable orchestration stage, with explicit per-source opt-in and paid-call confirmation, that collects (a) live SERP context, (b) selected public-page crawls, (c) mobile/desktop Lighthouse, and (d) page/domain backlinks and relevant Labs evidence. Preserve source snapshots and per-source freshness/status. Keep offline replay as its own mode. Do not silently fetch on selection or report view.

### P2 — Preserve topic and implementation evidence without exposing raw pages wholesale

Add a privacy-conscious evidence representation: selected visible content blocks/passages with headings, exact page identity, extraction method and source hash; relevant query/PAA/Search Console evidence when supplied; topic/question coverage with evidence snippets and explicit confidence; internal link source → destination → anchor → placement/type; and schema/canonical/robots details. Keep full raw content local and out of model prompts by default. Let a reviewer inspect evidence snippets. This enables specific content/link recommendations rather than a generic “compare pages” instruction.

### P3 — Make technical recommendations actionable from the diagnostic source

Carry all verified, priority-ranked Lighthouse investigations (or a transparent capped selection plus “additional omitted” manifest), preserve audit IDs/resource paths and measurements, map each specialist technical finding to precise diagnostic facts, and require each engineering plan to state target resource, proposed safe change, dependency, regression/security checks, rollback condition and repeatable before/after measurement. Don’t turn lab opportunity savings into guaranteed real-world savings.

### P4 — Strengthen quality checks with evidence coverage and objective validation

Keep current lineage, strict numeric checks, and recovery. Add structured recommendation classes (change vs investigate vs defend), evidence sufficiency criteria by class, plan acceptance criteria, evidence excerpt links, freshness checks, source-level checks for every claim and scoring that never treats incomplete evidence as a competitor weakness. Add expert-reviewed gold cases for arbitrary verticals and non-Aviator page pairs. Human review remains required.

### P5 — Connect lifecycle, approved reports and monitoring clearly

Persist run status and artifacts under one investigation record; add deterministic history filters for keyword, URLs, capture context and source freshness; track report schema/version and approval. Keep page-change monitoring as a separate product lane, with an explicit link only when a report cites a specific monitored snapshot.

### P6 — Productize and verify the dashboard path

Expose location/language/device inputs and their real semantics; show SERP source/context, exact URL rank status, evidence coverage/freshness, paid/model-request stages and report status. Label live capture versus saved replay consistently. Wire user-visible inability-to-collect cases to clear “unknown/missing” status rather than implying the investigation failed entirely.

## 9. Risks of modifying the current architecture

- **Evidence mixing:** global keyword folders and side labels can associate stale evidence with a new pair; preserve exact URL/keyword/source hash checks and use investigation-local paths.
- **Backward compatibility:** normalizers, `run_analysis`, historic JSON schema v0.5 and multiple report formats are consumed by many tests/artifacts. Refactor via adapters and explicit schema versions, not in-place field meaning changes.
- **Loss of useful evidence through over-scrubbing:** expanding prompts without a reviewed, minimized evidence design risks exposing full page text, query parameters, user data, cookies or secrets. Keep raw artifacts local, redact, cite and bound excerpts.
- **Validation regressions:** numeric/citation validators and recovery are interdependent. A broader fact registry or new metric units can create false acceptance or false quarantine; preserve failing raw model responses and run existing offline regression tests before enabling new inference.
- **Incorrect recommendation automation:** heuristic content maps can mistake absence for a gap; generated copy/content plans can introduce compliance, product or responsible-gambling issues. Require evidence and accountable review.
- **Technical change impact:** performance fixes can break login, payments, fraud/security, consent, analytics or product functionality. Current safeguards recognize this; preserve them in any plan schema.
- **External costs and operational limits:** DataForSEO calls may incur cost; Google browser collection may block or vary; local LLM may truncate/time out; Lighthouse is variable lab data. Keep these independently opt-in, resumable and visibly reported.
- **History/provenance drift:** source files can change after selection. Current offline flow hashes inputs, but a single run manifest must also preserve the exact SERP snapshot, configurations, software/prompt versions and model identity.
- **Monitoring misinterpretation:** OCR, pixel and rule-based promotion candidates can be wrong or missed. Avoid conflating “not detected” with ended offer or page change with ranking cause.
- **Report contradictions:** legacy deterministic recommendation text may reflect a different prioritization than a repaired focused report. Preserve one clearly marked current action set and label historical comparison sections.

## 10. Existing test baseline

There are **75 `tests/test_*.py` files** at inspection time. No tests were executed for this assessment. `README_INFORMATION_PRESERVATION.md` documents **12 known pre-existing full-suite failures** and says they were present before that update; that is a documentation claim, not independently reproduced in this task. `validation_results.txt` records a prior Aviator structural comparison check with 15 passes and 0 warnings, explicitly describing it as structural rather than independent proof of rankings. These logs should not replace a fresh baseline run when code changes are authorized.

Key existing offline regression files and the baseline they protect:

| Test file(s) | Baseline behavior covered |
|---|---|
| `tests/test_core.py`, `test_phase2_pipeline_integration.py`, `test_url_first_pipeline.py`, `test_evidence_alignment.py`, `test_evidence_path_alignment.py` | Deterministic analysis, exact SERP page identity, target/scope checks, recommendation output |
| `tests/test_manual_page_investigations.py`, `test_serp_investigation_selection.py`, `test_dashboard_keyword_search.py`, `test_tracked_serp_discovery.py` | Generic keyword/URL selection, URL rejection, SERP snapshot binding, dashboard endpoints |
| `tests/test_investigation_offline_execution.py`, `test_offline_historical_report_compat.py`, `test_keyword_isolation.py` | Offline evidence completeness, exact selected URLs, source integrity, zero external calls, keyword isolation |
| `tests/test_llm_foundation.py`, `test_information_preservation.py`, `test_shared_evidence_grounding.py`, `test_structured_facts.py`, `test_evidence_coverage` (if present under the test tree) | Canonical packet construction, full specialist finding retention, factual publisher behavior and evidence coverage |
| `tests/test_focused_recommendations.py`, `test_focused_evidence_mapping.py`, `test_focused_competition_evidence.py`, `test_focused_numeric_retry.py`, `test_evidence_recovery.py`, `test_backlinks_retry_grounding.py` | Focused task plans, mapping/lineage, numeric retries, partial recovery and backlink scope |
| `tests/test_recommendation_quality.py`, `test_recommendation_quality_v4.py`, `test_quality_repair.py`, `test_quality_repair_all_fields.py`, `test_quality_repair_direction.py`, `test_finding_action_coverage.py` | Quality flags, exact field repair, action coverage and evidence scope |
| `tests/test_executive_factual_consistency.py`, `test_executive_numeric_context.py`, `test_executive_backlink_evidence.py`, `test_executive_targeted_repair.py`, `test_output_repair.py` | Numeric/metric direction, page/domain fact semantics and targeted repair |
| `tests/test_technical_diagnostics.py`, `test_technical_recommendations.py`, `test_technical_recommendation_sync.py`, `test_technical_integration.py`, `test_lighthouse_integration.py`, `test_lighthouse_inspector.py` | Technical evidence details, priorities, implementation cues, post-change verification |
| `tests/test_reporting_split.py`, `test_final_quality_reporting.py`, `test_reporting_dashboard_integration.py`, `test_phase3_report_integration.py`, `test_final_report.py` | Full appendix preservation, management PDF, report manifest, current-source selection and human approval flow |
| `tests/test_monitoring.py`, `test_promotions.py`, `test_promotion_intelligence.py`, `test_shadow_dom_capture.py` | Independent page diff/promotion candidate and capture behavior |

Some table names are grouped for prioritization, not assertions that every listed concern is completely covered. Check the test source itself before treating a passing fixture as real-world accuracy evidence. Live Google, DataForSEO, Lighthouse and local Gemma integration are not established by offline/mock tests.

## Conclusion

The repository has a sound evidence-first foundation and a meaningful, tested design for preserving specialist reasoning while converting supported findings into scoped action plans. Recommendation detail remains constrained by what the canonical packet retains: especially page text/topics and actual link destinations. More fundamentally, a user can select arbitrary pages but cannot yet trigger a fresh, run-isolated end-to-end evidence collection and reporting lifecycle for an arbitrary pair through the dashboard. The highest-value next work is to unify investigation context/provenance, wire opt-in collection into isolated per-investigation outputs, and enrich minimized evidence so content and technical recommendations can identify a specific justified change and how to verify it.

