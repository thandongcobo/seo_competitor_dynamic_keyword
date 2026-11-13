# Technical evidence and implementation appendix

The current management action list is derived from the explicitly selected repaired executive JSON. The deterministic comparison below is preserved as historical evidence and may contain an older, independent prioritization. It is **not** a second approved action list.

## Part A — Original deterministic comparison (preserved)

# SEO Competitive Investigation — aviator

**Search market:** South Africa  
**Primary search engine:** Google  
**Our domain:** hollywoodbets.net  
**Comparison domain:** betway.co.za  
**Source:** `comparison.json` (existing local analysis; no new search performed)  
**Report generated (UTC):** 2026-11-03 09:03  

## 1. Executive summary

In the saved Google organic SERP, **betway.co.za ranked #1** and **hollywoodbets.net ranked #2**, a gap of 1 position(s).

The report compares **observed evidence**, not Google's internal ranking weights. A stronger measured signal is a possible explanation to investigate, not proof of causation.

**Recommended investigation order:** 1. Verify HTML title targeting for the selected keyword; 2. Investigate mobile page-loading bottlenecks; 3. Review intent coverage for relevant generic searches; 4. Investigate page-specific backlink quality and relevant link-earning opportunities; 5. Verify meta description targeting for the selected keyword.

## 2. Rankings and exact page identity

| Source | hollywoodbets.net | betway.co.za |
| --- | --- | --- |
| Saved Google organic position | #2 | #1 |
| Exact ranking URL | https://www.hollywoodbets.net/aviator | https://www.betway.co.za/aviator |
| Page evidence aligned | Yes | Yes |

**Evidence paths:** `ranking_summary.google`, `primary_ranking_urls`, `evidence_quality`, `page_level_evidence`. Ranking positions reflect the saved SERP context, not a continuously updated Google result.

**Confirmed comparison competitor:** betway.co.za — #1 in the saved Google SERP. A discovery-specific label such as 'not local-rank' means that the discovery record lacks a local rank; it does not negate the confirmed SERP position.

**Separate DataForSEO observation for the exact keyword:** hollywoodbets.net #1; betway.co.za #4. This is a different ranking dataset and must not overwrite the saved Google SERP positions.

## 3. On-page SEO comparison

| Page factor | hollywoodbets.net | betway.co.za |
| --- | --- | --- |
| HTML title | Online Sports Betting and Online Casino \| Hollywoodbets | Play Aviator and reach for the sky \| Betway Sports betting |
| Meta description | Sign up with the top online betting and casino! In addition to the R25 sign-up bonus, we are now giving new players 50 free spins on slot games! Join today! | Place your Aviator Bets at Betway, cash out before the plane flies off and WIN big, daily rain is predicted so check the weather forecast. |
| H1 headings | AVIATOR | Aviator; PLAY AVIATOR AT BETWAY |
| Body word count (includes non-main content) | 867 | 2,801 |
| Standardized cleaned rendered SEO-content words (same method only) | 795 | 446 |
| Internal links | 9 | 28 |
| Structured data blocks | 1 | 0 |

- **Title keyword presence:** ours No; competitor Yes.
- **Meta description keyword presence:** ours No; competitor Yes.
- **H1 keyword presence:** ours Yes; competitor Yes.

**Measurement policy:** Only `seo_content_word_count` from the matching `rendered-main-innertext-v2` method is comparable. Both pages must have `verified_candidate` status, complete crawls, and exact ranking/requested/final URL alignment. Old HTML, body, and rendered-main counts remain diagnostics, not substitutes.

**Standardized measurement:** hollywoodbets.net 795 words; betway.co.za 446 words. This is not a content-quality or keyword-relevance ranking.

**Interpretation:** Exact-match keyword presence, content length and token similarity are diagnostic context, not standalone ranking scores. Body text can include navigation or unrelated content. A missing main-content measurement is not zero content.

**Evidence paths:** `page_level_evidence.ours`, `page_level_evidence.benchmark`, `onpage_comparison`.

## 4. Backlink comparison — page versus domain

| Metric | hollywoodbets.net | betway.co.za | Measured advantage |
| --- | --- | --- | --- |
| Page — DataForSEO backlink rank | 18 | 36 | betway.co.za |
| Page — Total backlinks | 1,853 | 2,809 | betway.co.za |
| Page — Referring domains | 1,184 | 1,259 | betway.co.za |
| Page — Referring main domains | 598 | 816 | betway.co.za |
| Page — Backlink spam score | 56 | 43 | Not inferred from score alone |
| Domain — DataForSEO backlink rank | 70 | 65 | hollywoodbets.net |
| Domain — Total backlinks | 1,806,871 | 578,056 | hollywoodbets.net |
| Domain — Referring domains | 8,050 | 7,370 | hollywoodbets.net |
| Domain — Referring main domains | 6,288 | 5,837 | hollywoodbets.net |
| Domain — Backlink spam score | 35 | 32 | Not inferred from score alone |

**Interpretation:** Page-level and domain-level backlink profiles are different evidence scopes. Backlink rank is a third-party metric, not Google's ranking position. More backlinks or a higher backlink rank does not prove that links caused a SERP difference. Aggregate spam scores do not establish that individual links are harmful.

**Evidence paths:** `page_level_evidence.backlinks_ours`, `page_level_evidence.backlinks_benchmark`, `domain_level_evidence.backlinks_*`, `advanced_evidence.backlinks`.

## 5. Technical SEO and Lighthouse mobile lab results

| Mobile Lighthouse measure | hollywoodbets.net | betway.co.za | Better lab result |
| --- | --- | --- | --- |
| Performance score /100 | 28 | 16 | hollywoodbets.net |
| Lighthouse SEO score /100 | 100 | 85 | hollywoodbets.net |
| Accessibility score /100 | 72 | 76 | betway.co.za |
| Best practices score /100 | 73 | 69 | hollywoodbets.net |
| Largest Contentful Paint (LCP) | 24.91 s | 19.51 s | betway.co.za |
| First Contentful Paint (FCP) | 10.41 s | 4.39 s | betway.co.za |
| Total Blocking Time (TBT) | 2,122.50 ms | 3,272.90 ms | hollywoodbets.net |
| Cumulative Layout Shift (CLS) | 0 | 0.29 | hollywoodbets.net |
| Speed Index | 10.41 s | 6.94 s | betway.co.za |

**Audit timestamps (UTC):** ours 2026-10-12T09:38:45.793Z; competitor 2026-10-12T09:39:13.273Z.

**Desktop audits:** not collected in this comparison.

**Interpretation:** These are single-run Lighthouse lab observations, not real-user Core Web Vitals. A higher overall score does not imply that every individual metric is better. Raw Lighthouse diagnostic opportunities are required to identify root causes.

**Evidence paths:** `page_level_evidence.lighthouse`, `technical_comparison`, `advanced_evidence.technical`.

### Detailed engineering investigations (mobile Lighthouse)

#### 1. Profile JavaScript boot-up and main-thread execution

**Engineering priority:** high  
**Audit:** `bootup-time`  
**Supporting observation:** Lighthouse reports JavaScript boot-up work on the selected page.  
**Measurement:** 6.0 s  
**Priority basis:** Conservative engineering triage based on audit category and measured severity; not a ranking forecast.  

| Affected resource | Observed measurement (original units) |
| --- | --- |
| https://mpsnare.iesnare.com/general5/wdp.js | total: 1,612.08, scripting: 1,599.96 |
| https://www.hollywoodbets.net/js/vendors-node_modules_reduxjs_toolkit_dist_redux-toolkit_esm_js-node_modules_camelcase-keys_in-cc43f7.8c786ed2557193d67336.min.js | total: 669.04, scripting: 470.06 |
| https://www.hollywoodbets.net/iojs/5.13.0/dyn_wdp.js | total: 623.46, scripting: 622.34 |
| Unattributed resource | total: 586.70, scripting: 104.83 |

**Engineering actions:**
- Profile the identified scripts in Chrome Performance before editing load order.
- Identify initialization that is nonessential for first render; test deferral without disrupting security, fraud checks or core interactions.
- Repeat comparable mobile Lighthouse audits and inspect boot-up time, TBT and application functionality.

**Validation:** Repeat comparable mobile Lighthouse audits and inspect boot-up time, TBT and application functionality.  
**Evidence confidence:** investigation_only  
**Limitation:** Single-run Lighthouse lab evidence. Estimated savings are not guaranteed and do not establish ranking causation.

#### 2. Review JavaScript delivery and initial bundle utilization

**Engineering priority:** high  
**Audit:** `unused-javascript`  
**Supporting observation:** Lighthouse flags potentially unused JavaScript in the measured load.  
**Measurement:** Est savings of 1,108 KiB  
**Priority basis:** Conservative engineering triage based on audit category and measured severity; not a ranking forecast.  

| Affected resource | Observed measurement (original units) |
| --- | --- |
| https://www.hollywoodbets.net/js/main.38c4d2ededa66bb008c8.min.js | wastedBytes: 335,735, totalBytes: 629,253 |
| https://www.hollywoodbets.net/js/vendors-node_modules_reduxjs_toolkit_dist_redux-toolkit_esm_js-node_modules_camelcase-keys_in-cc43f7.8c786ed2557193d67336.min.js | wastedBytes: 213,672, totalBytes: 424,539 |
| https://www.googletagmanager.com/gtm.js | wastedBytes: 118,233, totalBytes: 178,497 |
| https://js-cdn.dynatrace.com/jstag/15fc9f135f3/bf45082quw/889f44e01580ed7b_complete.js | wastedBytes: 78,557, totalBytes: 87,528 |

**Engineering actions:**
- Review code splitting and defer only features not needed for initial rendering.
- Check script coverage during real user flows before removing code or third-party tags.
- Repeat mobile audits and verify bundle sizes, feature behavior and conversion paths.

**Validation:** Repeat mobile audits and verify bundle sizes, feature behavior and conversion paths.  
**Evidence confidence:** investigation_only  
**Limitation:** Single-run Lighthouse lab evidence. Estimated savings are not guaranteed and do not establish ranking causation.

#### 3. Review image sizing and delivery

**Engineering priority:** medium  
**Audit:** `image-delivery-insight`  
**Supporting observation:** Lighthouse identifies image-delivery opportunities in the measured load.  
**Measurement:** Est savings of 245 KiB  
**Priority basis:** Conservative engineering triage based on audit category and measured severity; not a ranking forecast.  

| Affected resource | Observed measurement (original units) |
| --- | --- |
| https://content.hollywoodbets.net/blog_make_it_rain_799c949bfb.jpg | wastedBytes: 69,890, totalBytes: 72,450 |
| https://content.hollywoodbets.net/blog_big_win_2fee2707bb.jpg | wastedBytes: 61,725, totalBytes: 63,986 |
| https://content.hollywoodbets.net/blog_competition_a68476182e.jpg | wastedBytes: 47,959, totalBytes: 49,716 |
| https://content.hollywoodbets.net/advert_banner_0b488a2d32.jpg | wastedBytes: 47,445, totalBytes: 62,412 |

**Engineering actions:**
- Inspect flagged image assets for excessive dimensions and compression opportunities.
- Test responsive image delivery and appropriate formats without harming visual quality.
- Repeat mobile audits and check image transfer sizes and LCP separately.

**Validation:** Repeat mobile audits and check image transfer sizes and LCP separately.  
**Evidence confidence:** investigation_only  
**Limitation:** Single-run Lighthouse lab evidence. Estimated savings are not guaranteed and do not establish ranking causation.

#### 4. Review render-blocking resource dependencies

**Engineering priority:** low  
**Audit:** `render-blocking-insight`  
**Supporting observation:** Lighthouse identifies render-blocking resources in the measured load.  
**Measurement:** Est savings of 160 ms  
**Priority basis:** Conservative engineering triage based on audit category and measured severity; not a ranking forecast.  

| Affected resource | Observed measurement (original units) |
| --- | --- |
| https://onelinksmartscript.appsflyer.com/onelink-smart-script-latest.js | totalBytes: 26,185, wastedMs: 1,734 |
| https://www.hollywoodbets.net/config/config.js | totalBytes: 3,822 |

**Engineering actions:**
- Trace critical CSS and JS dependencies identified by Lighthouse.
- Test safe changes to loading order; preserve configuration and required tracking functionality.
- Repeat mobile audits and check FCP, LCP and regressions.

**Validation:** Repeat mobile audits and check FCP, LCP and regressions.  
**Evidence confidence:** investigation_only  
**Limitation:** Single-run Lighthouse lab evidence. Estimated savings are not guaranteed and do not establish ranking causation.

**Interpretation:** Engineering priorities are not SEO ranking priorities. Lighthouse measurements come from individual lab runs; resource-level timings and overall estimated savings must not be added together. Technical improvements do not establish search-ranking causation.

**Evidence path:** `technical_comparison.mobile.detailed_analysis`.

## 6. Keyword competition and search intent

**Shared keyword records:** 82 of 82 reported. Our domain ahead on 44; competitor ahead on 38; ties 0.

| Related shared query | hollywoodbets.net | betway.co.za | Estimated monthly searches | Relevance class |
| --- | --- | --- | --- | --- |
| play aviator | #2 | #1 | 6,600 | relevant_generic |
| aviator betting | #8 | #2 | 1,000 | relevant_generic |
| aviator bet | #5 | #1 | 1,000 | relevant_generic |
| how to play aviator | #10 | #1 | 880 | relevant_generic |
| play aviator now | #2 | #1 | 590 | relevant_generic |
| what is aviator | #4 | #3 | 480 | relevant_generic |
| play aviator online | #2 | #1 | 480 | relevant_generic |
| aviator app | #4 | #3 | 480 | relevant_generic |
| aviator casino | #10 | #1 | 260 | relevant_generic |
| aviator play online | #4 | #2 | 260 | relevant_generic |

These are **domain-level keyword observations**. Each query may rank a different landing page; do not attribute every query's rank to the two primary URLs.

**Keyword intent classification:** informational; model probability 0.97. A classifier probability is not a measured percentage of searchers with that intent. For ambiguous terms, the broad keyword classification may not represent the specific intent of the captured SERP or the landing pages being compared; check the actual search results and page purpose.

**Domain-wide ranked-keyword samples:** 100 returned for hollywoodbets.net; 100 for betway.co.za. Absence from a limited sample does not establish that a domain fails to rank for a keyword.

**Evidence paths:** `advanced_evidence.keyword_intersection`, `domain_level_evidence.domain_intersection`, `domain_level_evidence.ranked_*`, `intent_alignment`.

## 7. Evidence-supported ranking hypotheses

### 1. Page-specific backlink advantage

**Evidence scope:** Direct page-level comparison (third-party link metric)

**Supporting observation:** The competitor page has a higher third-party backlink rank (36 vs 18).

**Counterevidence or alternative:** However, domain-wide backlink rank favors hollywoodbets.net (70 vs 65).

**Confidence/limitation:** Measured page difference; causal ranking contribution unverified; individual link quality not audited.

### 2. Title/topic signaling difference

**Evidence scope:** Direct page-level HTML observation

**Supporting observation:** The captured competitor HTML title includes the selected keyword while ours does not.

**Counterevidence or alternative:** Exact-match keyword presence alone does not determine title quality or rankings.

**Confidence/limitation:** Verified as a captured-page difference, not as a ranking cause; check the live title and intent fit.

### 3. Slower observed LCP

**Evidence scope:** Direct page-level lab measurement (single run)

**Supporting observation:** Our mobile LCP was 24.91 s versus 19.51 s for the competitor.

**Counterevidence or alternative:** Overall Lighthouse performance favors hollywoodbets.net (28 vs 16).

**Confidence/limitation:** Observed in one Lighthouse lab run; no verified field performance or causal ranking effect.

### 4. Related-query coverage

**Evidence scope:** Domain-level context (not evidence about the exact ranking page)

**Supporting observation:** The competitor leads on 31 classified generic shared queries.

**Counterevidence or alternative:** These domain-level ranks may belong to different pages; branded and generic intent must be distinguished.

**Confidence/limitation:** Context only for the primary query; inspect query-specific ranking URLs before applying content changes.

**Overall assessment:** The saved data supports competitive hypotheses, not a causal ranking attribution. Do not add these signals into an invented Google ranking score.

### Current analysis-engine findings

| Category | Evidence confidence | Direction | Recorded observation |
| --- | --- | --- | --- |
| ranking | high | competitor | On google, benchmark position is 1 and our position is 2; gap = 1 positions. |
| content_length | low | context | Standardized cleaned SEO-content word counts are ours 795 vs benchmark 446 (method: rendered-main-innertext-v2; verified comparable SERP ranking pages). Content length is descriptive context, not content quality or a proven ranking factor. |
| content_similarity | low | context | Our page and benchmark page have a token-set similarity of 0.143; this is a topical similarity signal, not a ranking score. |
| search_intent | low | neutral | No clear heuristic difference in informational intent alignment (1 vs 1 term signals). |
| keyword_intersection | medium | context | Among 82 returned shared keyword comparisons, ours leads on 44, benchmark leads on 38; generic (non-domain-branded) terms: ours 24, benchmark 31. These are historical domain-level positions, not the live primary SERP or proof of absent rankings. |
| backlinks | medium | context | Ranking-page DataForSEO backlink rank: ours 18 vs benchmark 36; page referring domains: ours 1184 vs benchmark 1259. Domain-wide ranks: ours 70 vs benchmark 65. Link-profile metrics are not Google ranking weights or proof of causation. |
| lighthouse | low | context | Mobile Lighthouse lab performance: ours 28, benchmark 16; LCP ms: ours 24907.979723543547, benchmark 19506.780129999996; TBT ms: ours 2122.5, benchmark 3272.8982099999866. One lab run is not field CWV or ranking causation. |
| onpage_keyword_targeting | medium | competitor | The selected keyword is absent from our HTML title but present in the benchmark HTML title. |
| onpage_keyword_targeting | medium | competitor | The selected keyword is absent from our meta description but present in the benchmark meta description. |

**Discovery reconciliation:** A confirmed benchmark's SERP position takes precedence over missing rank metadata in the discovery candidate list. The source finding remains unchanged in the comparison JSON; this report corrects its presentation only.

**Evidence path:** `findings`. These observations are reported separately from the causal hypotheses above.

## 8. Prioritized action plan

| Order | Recommendation | Priority | Potential impact | Effort | Evidence confidence | Action type |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Verify HTML title targeting for the selected keyword | high | medium | low | medium | verify_before_edit |
| 2 | Investigate mobile page-loading bottlenecks | high | high | high | high | investigate |
| 3 | Review intent coverage for relevant generic searches | medium | medium | medium | medium | investigate |
| 4 | Investigate page-specific backlink quality and relevant link-earning opportunities | medium | high | high | medium | investigate |
| 5 | Verify meta description targeting for the selected keyword | medium | low | low | medium | verify_before_edit |

### 1. Verify HTML title targeting for the selected keyword

**Target URL:** https://www.hollywoodbets.net/aviator  
**Priority rationale:** Triage rubric: 2*relevance + potential_impact + evidence_confidence + inverse_effort; ordinal only.  
**Evidence:** Keyword 'aviator' was not detected in our captured HTML title, but was detected in the competitor's.  
**Interpretation:** This is a captured-page difference, not a verified defect. HTML title can help communicate page topic to search engines.  
**Impact:** medium (qualitative, not a rank-lift forecast)  
**Effort:** low  
**Action type:** verify_before_edit  

- First verify the current rendered HTML and canonical response at the exact ranking URL.
- If the HTML title is genuinely generic or misleading, propose an accurate, natural topic-specific revision.
- Review the proposed text with the SEO/content owner before publishing.

**Success check:** Recrawl the exact URL after approval and compare search appearance over time.  
**Limitations:** Google may rewrite the displayed search-result title; exact keyword presence alone is not a ranking-quality metric.

### 2. Investigate mobile page-loading bottlenecks

**Target URL:** https://www.hollywoodbets.net/aviator  
**Priority rationale:** Triage rubric: 2*relevance + potential_impact + evidence_confidence + inverse_effort; ordinal only.  
**Evidence:** Our mobile Lighthouse lab audit: LCP 24.91s, TBT 2122ms.  
**Interpretation:** Lab measurements indicate potential user-experience issues; they do not establish a ranking cause.  
**Impact:** high (qualitative, not a rank-lift forecast)  
**Effort:** high  
**Action type:** investigate  

- Review the verified resource-level Lighthouse investigations in the technical section of the report.
- Profile identified scripts and assets before modifying their loading behavior; preserve essential security and business functionality.
- Repeat controlled mobile Lighthouse audits and test core user flows after changes.

**Success check:** Repeat controlled lab audits and check field Core Web Vitals separately where available.  
**Limitations:** Detailed Lighthouse diagnostics identify investigation targets (JavaScript execution, unused JavaScript, image delivery, render-blocking resources), but the precise cause of slow LCP and any ranking impact remain unverified.

### 3. Review intent coverage for relevant generic searches

**Target URL:** https://www.hollywoodbets.net/aviator  
**Priority rationale:** Triage rubric: 2*relevance + potential_impact + evidence_confidence + inverse_effort; ordinal only.  
**Evidence:** Shared keyword intersection, filtered generic competitor leads: play aviator (ours #2, benchmark #1), aviator betting (ours #8, benchmark #2), aviator bet (ours #5, benchmark #1), how to play aviator (ours #10, benchmark #1), play aviator now (ours #2, benchmark #1).  
**Interpretation:** The competitor leads for these related queries in the saved DataForSEO dataset; these may rank different landing pages.  
**Impact:** medium (qualitative, not a rank-lift forecast)  
**Effort:** medium  
**Action type:** investigate  

- Verify the exact ranking URLs for each selected related query.
- Compare the relevant page sections, user intent and internal linking for those URLs.
- Only improve this page when the verified query intent matches its purpose.

**Success check:** Monitor those same query positions and verify content changes against their intent.  
**Limitations:** Lexical relevance screening is conservative, not semantic intent analysis; third-party or unfamiliar terms require review.

### 4. Investigate page-specific backlink quality and relevant link-earning opportunities

**Target URL:** https://www.hollywoodbets.net/aviator  
**Priority rationale:** Triage rubric: 2*relevance + potential_impact + evidence_confidence + inverse_effort; ordinal only.  
**Evidence:** Page backlink rank: ours 18, competitor 36; referring domains: ours 1184, competitor 1259. Domain backlink rank: ours 70, competitor 65.  
**Interpretation:** The competitor page has stronger measured link signals, but aggregate counts cannot establish link quality or ranking causation.  
**Impact:** high (qualitative, not a rank-lift forecast)  
**Effort:** high  
**Action type:** investigate  

- Review referring-domain-level data for topical relevance, placement and editorial quality before acting.
- Identify legitimate opportunities to earn references to this exact ranking page.
- Improve useful resources and relevant internal links; avoid manipulative link schemes.

**Success check:** Recheck the same page-level link metrics and independent SERP observations over time.  
**Limitations:** Referring-domain exports are needed to establish link quality; effort is an estimate.

### 5. Verify meta description targeting for the selected keyword

**Target URL:** https://www.hollywoodbets.net/aviator  
**Priority rationale:** Triage rubric: 2*relevance + potential_impact + evidence_confidence + inverse_effort; ordinal only.  
**Evidence:** Keyword 'aviator' was not detected in our captured meta description, but was detected in the competitor's.  
**Interpretation:** This is a captured-page difference, not a verified defect. Meta descriptions can affect search-result snippets and clicks; keyword presence is not a direct ranking boost.  
**Impact:** low (qualitative, not a rank-lift forecast)  
**Effort:** low  
**Action type:** verify_before_edit  

- First verify the current rendered HTML and canonical response at the exact ranking URL.
- If the meta description is genuinely generic or misleading, propose an accurate, natural topic-specific revision.
- Review the proposed text with the SEO/content owner before publishing.

**Success check:** Recrawl the exact URL after approval and compare search appearance over time.  
**Limitations:** Google may generate its own search-result snippet instead of using the meta description. Editing it does not guarantee higher rankings or clicks.

**Impact methodology:** Potential impact and effort are qualitative assessments. No precise ranking lift, traffic lift or monetary return can be inferred from the current dataset.

## 9. Evidence quality, provenance and limitations

| Evidence component | Validation status |
| --- | --- |
| backlinks_benchmark_page | usable |
| backlinks_ours_page | usable |
| lighthouse_benchmark_mobile | usable |
| lighthouse_ours_mobile | usable |
| page_benchmark | usable |
| page_ours | usable |

- Desktop Lighthouse data was not collected.
- Dofollow backlink counts are unavailable; missing values are not zero.
- Google SERP rankings and DataForSEO historical keyword rankings are separate sources and may disagree.
- Keyword-intersection ranks are domain-wide, not necessarily for the primary landing pages.
- Lighthouse is lab data; field Core Web Vitals and repeated controlled audits are not included.
- Search-volume and traffic estimates are modeled, not verified clicks or conversions.
- The comparison file does not establish which SEO signals Google actually weighted.

### Source and reproducibility

- Primary local source: `comparison.json`.
- Original data was collected and normalized by the existing SEO pipeline; this report performs no network requests.
- Evidence-path labels above identify where each comparison is read from the local JSON.
- Collection timestamps are shown where provided (e.g. Lighthouse); absent timestamps are not invented.
- To evaluate another keyword, generate its comparison JSON and run this report generator with that keyword.

---

*Report generated from available evidence. Observed differences do not establish ranking causality or guaranteed improvements.*

---

## Part B — Current repaired implementation plans

These are proposals, not proof of ranking causation. Validate current URLs and dependencies before changes.

### Plan 1: Optimize Title Tag for Keyword Relevance

**Priority:** high | **Owner:** SEO Specialist

**Plain-language explanation:** Add 'Aviator' to the title tag to match user search intent.

**Technical explanation:** Title tags are HTML meta elements that influence SERP display. Including the primary keyword improves relevance without altering content structure.

**Rationale (model proposal):** The current title tag lacks the primary keyword 'Aviator', which may reduce click-through rates for users specifically searching for the Aviator game. Including the keyword can improve relevance for specific queries.

**Implementation procedure (as validated in the selected JSON):**

1. Audit the current title tag: 'Online Sports Betting and Online Casino | Hollywoodbets'.
2. Update the title tag to include 'Aviator' while preserving brand context, e.g., 'Aviator Game - Play Online at Hollywoodbets'.
3. Verify the updated title tag is implemented via CMS or HTML source.
4. Test the updated title tag in SERP preview tools to confirm rendering.

**Proposed success measure:** Title tag includes 'Aviator' and renders correctly in SERP.

**Uncertainty:** Title tag changes may not directly impact ranking, but can improve CTR and user intent alignment.

**Verified fact IDs:** ON_TITLE

**Original specialist finding IDs:** ONPAGE_01

**Implementation review:** Confirm prerequisites and repeatable baseline, obtain owner approval, and compare like-for-like results after any change. These checks are editorial guidance, not new observations.

### Plan 2: Audit and Enhance Internal Linking Structure

**Priority:** medium | **Owner:** Technical SEO Lead

**Plain-language explanation:** Add more internal links to the Aviator page from relevant sections to improve navigation and context.

**Technical explanation:** Internal links help search engines understand content relationships and improve user journey. Adding links from high-value pages can boost page authority indirectly.

**Rationale (model proposal):** The benchmark page has 28 internal links compared to 9 on the ranking page. While link count alone does not prove authority, it may indicate better navigation or content hierarchy, which can support SEO performance.

**Implementation procedure (as validated in the selected JSON):**

1. Audit internal links on the ranking page to identify high-value pages (e.g., 'Aviator Rules', 'How to Play', 'Payouts').
2. Identify key internal pages that should link to the Aviator landing page (e.g., homepage, casino games section).
3. Implement new internal links from relevant pages to the Aviator page, ensuring anchor text includes 'Aviator'.
4. Verify link implementation via site audit tools (e.g., Screaming Frog, Ahrefs).

**Proposed success measure:** New internal links added from relevant pages to the Aviator page with keyword-rich anchor text.

**Uncertainty:** Internal link count is not a direct ranking factor, but improved navigation may support crawlability and user engagement.

**Verified fact IDs:** ON_LINKS

**Original specialist finding IDs:** ONPAGE_02

**Implementation review:** Confirm prerequisites and repeatable baseline, obtain owner approval, and compare like-for-like results after any change. These checks are editorial guidance, not new observations.

### Plan 3: Verify Content Intent and Lexical Similarity

**Priority:** medium | **Owner:** Content Strategist

**Plain-language explanation:** Ensure the Aviator page covers the same user intents as the benchmark page to improve relevance.

**Technical explanation:** Content should address user queries directly. Lexical similarity alone doesn't indicate quality or ranking impact, but semantic alignment can improve user satisfaction and engagement.

**Rationale (model proposal):** The content token Jaccard overlap between the two pages is 0.14, indicating low lexical similarity. This suggests the pages address user intent differently, which may be intentional or require alignment.

**Implementation procedure (as validated in the selected JSON):**

1. Review the content on both pages to identify key user intents (e.g., game rules, payout structure, gameplay tips).
2. Compare content structure and keyword usage to determine if the ranking page covers the same user needs as the benchmark.
3. If gaps exist, update the ranking page to include missing content (e.g., 'Aviator Rules', 'How to Win').
4. Verify content changes via CMS and ensure no duplication or redundancy.

**Proposed success measure:** Content on the ranking page aligns with user intent and includes key topics covered by the benchmark page.

**Uncertainty:** Jaccard overlap measures lexical similarity, not semantic relevance or content quality. Content updates may improve user experience but not necessarily ranking.

**Verified fact IDs:** ON_CONTENT_SIMILARITY

**Original specialist finding IDs:** ONPAGE_03

**Implementation review:** Confirm prerequisites and repeatable baseline, obtain owner approval, and compare like-for-like results after any change. These checks are editorial guidance, not new observations.

### Plan 4: Analyze Betway.co.za’s Content and Backlink Profile for Ranking Factors

**Priority:** high | **Owner:** SEO Strategy Team

**Plain-language explanation:** Betway is #1 for 'aviator' — we must reverse-engineer its ranking factors.

**Technical explanation:** The SERP snapshot confirms Betway’s #1 position and KW_QUERY_GAPS shows it leads on high-volume modifiers. We must analyze its page to isolate technical and content factors driving this dominance.

**Rationale (model proposal):** Betway.co.za holds #1 for 'aviator' and leads on high-volume modifiers. Understanding its content structure and backlink profile can reveal specific ranking factors to emulate or address gaps.

**Implementation procedure (as validated in the selected JSON):**

1. Verify that the betway.co.za/aviator page is live and accessible before initiating any audit or analysis.
2. Audit the betway.co.za/aviator page for content depth, keyword targeting, and internal linking structure.
3. Analyze backlink profile using Ahrefs or SEMrush to identify authoritative referring domains and anchor text patterns.
4. Compare content structure and metadata with Hollywoodbets.net’s page to identify key differentiators.

**Proposed success measure:** Identify 3+ specific ranking factors (e.g., content depth, backlink authority, schema markup) that explain Betway’s #1 position, verified through technical and content analysis.

**Uncertainty:** Ranking factors may vary by search engine algorithm updates or regional SERP differences.

**Verified fact IDs:** SERP, KW_QUERY_GAPS

**Original specialist finding IDs:** COMPETITION_01

**Implementation review:** Confirm prerequisites and repeatable baseline, obtain owner approval, and compare like-for-like results after any change. These checks are editorial guidance, not new observations.

### Plan 5: Develop Comprehensive 'How-To' Content to Close Rank Gaps on Instructional Queries

**Priority:** medium | **Owner:** Content Strategy Team

**Plain-language explanation:** We’re ranked lower on instructional queries — we need to create better guides to compete.

**Technical explanation:** KW_QUERY_GAPS shows Hollywoodbets.net ranks 8th and 10th respectively on 'aviator betting' and 'how to play aviator', with gaps of 6 and 9 positions. Content optimization targeting these queries can bridge the gap.

**Rationale (model proposal):** Hollywoodbets.net lags behind Betway by 6-9 positions on queries like 'aviator betting' and 'how to play aviator', indicating a content gap in instructional intent.

**Implementation procedure (as validated in the selected JSON):**

1. Create a detailed 'How to Play Aviator' guide with step-by-step instructions, visuals, and embedded game examples.
2. Optimize for long-tail keywords like 'aviator betting' and 'how to play aviator' using semantic keywords and internal links.
3. Publish content on a dedicated subpage or blog section and track performance via UTM parameters.

**Proposed success measure:** Achieve top-5 positions for 'aviator betting' and 'how to play aviator' within 3 months.

**Uncertainty:** Content performance depends on user engagement, backlinks, and algorithmic updates.

**Verified fact IDs:** KW_QUERY_GAPS

**Original specialist finding IDs:** COMPETITION_02

**Implementation review:** Confirm prerequisites and repeatable baseline, obtain owner approval, and compare like-for-like results after any change. These checks are editorial guidance, not new observations.

## Part C — Specialist finding dispositions (complete)

### ONPAGE_01 — action

**Linked plan numbers:** 1

**Plain-language explanation:** The title tag lacks the keyword 'Aviator', which can reduce click-through rates for targeted users.

**Technical explanation:** Title tags are critical for SERP display and user intent alignment. Including the primary keyword improves relevance without altering content structure.

**Next step:** Update the title tag to include 'Aviator' and verify rendering in SERP preview tools.

**Reason:** Title tag optimization is a low-risk, high-impact change that aligns with user search intent.

**Evidence IDs:** ON_TITLE

### ONPAGE_02 — action

**Linked plan numbers:** 2

**Plain-language explanation:** The benchmark page has significantly more internal links, which may support better navigation or authority.

**Technical explanation:** Internal links help search engines understand content relationships and improve user journey. Adding links from high-value pages can boost page authority indirectly.

**Next step:** Audit internal links and implement new internal links from relevant pages to the Aviator page with keyword-rich anchor text.

**Reason:** Internal linking structure can improve crawlability and user engagement, even if it doesn't directly impact ranking.

**Evidence IDs:** ON_LINKS

### ONPAGE_03 — action

**Linked plan numbers:** 3

**Plain-language explanation:** The content has low lexical similarity, which may indicate different user intent coverage.

**Technical explanation:** Content should address user queries directly. Lexical similarity alone doesn't indicate quality or ranking impact, but semantic alignment can improve user satisfaction and engagement.

**Next step:** Review content on both pages to identify gaps and update the ranking page to include missing topics (e.g., 'Aviator Rules', 'How to Win').

**Reason:** Content alignment with user intent can improve relevance and user experience, even if it doesn't directly impact ranking.

**Evidence IDs:** ON_CONTENT_SIMILARITY

### BACKLINKS_01 — investigate

**Linked plan numbers:** none

**Plain-language explanation:** A proposed explanation could not be verified against the saved evidence. Further review is needed.

**Technical explanation:** Recheck the original source measurement, metric scope and cited evidence before approving a change.

**Next step:** Review the saved source records and rerun the scoped comparison if new data is authorized and required.

**Reason:** The original recommendation contained an unresolved factual or citation validation issue.

**Evidence IDs:** BL_PAGE, SERP

### BACKLINKS_02 — investigate

**Linked plan numbers:** none

**Plain-language explanation:** A proposed explanation could not be verified against the saved evidence. Further review is needed.

**Technical explanation:** Recheck the original source measurement, metric scope and cited evidence before approving a change.

**Next step:** Review the saved source records and rerun the scoped comparison if new data is authorized and required.

**Reason:** The original recommendation contained an unresolved factual or citation validation issue.

**Evidence IDs:** BL_DOMAIN, SERP

### TECHNICAL_01 — investigate

**Linked plan numbers:** none

**Plain-language explanation:** A proposed explanation could not be verified against the saved evidence. Further review is needed.

**Technical explanation:** Recheck the original source measurement, metric scope and cited evidence before approving a change.

**Next step:** Review the saved source records and rerun the scoped comparison if new data is authorized and required.

**Reason:** The original recommendation contained an unresolved factual or citation validation issue.

**Evidence IDs:** TECH_LAB

### TECHNICAL_02 — investigate

**Linked plan numbers:** none

**Plain-language explanation:** A proposed explanation could not be verified against the saved evidence. Further review is needed.

**Technical explanation:** Recheck the original source measurement, metric scope and cited evidence before approving a change.

**Next step:** Review the saved source records and rerun the scoped comparison if new data is authorized and required.

**Reason:** The original recommendation contained an unresolved factual or citation validation issue.

**Evidence IDs:** TECH_LAB

### TECHNICAL_03 — investigate

**Linked plan numbers:** none

**Plain-language explanation:** A proposed explanation could not be verified against the saved evidence. Further review is needed.

**Technical explanation:** Recheck the original source measurement, metric scope and cited evidence before approving a change.

**Next step:** Review the saved source records and rerun the scoped comparison if new data is authorized and required.

**Reason:** The original recommendation contained an unresolved factual or citation validation issue.

**Evidence IDs:** TECH_INV

### COMPETITION_01 — action

**Linked plan numbers:** 4

**Plain-language explanation:** Betway is #1 for 'aviator' — we must reverse-engineer its ranking factors.

**Technical explanation:** The SERP snapshot confirms Betway’s #1 position and KW_QUERY_GAPS shows it leads on high-volume modifiers. We must analyze its page to isolate technical and content factors driving this dominance.

**Next step:** Audit betway.co.za/aviator for content depth, backlinks, and metadata.

**Reason:** Directly actionable based on confirmed SERP and query gap data.

**Evidence IDs:** SERP, KW_QUERY_GAPS

### COMPETITION_02 — action

**Linked plan numbers:** 5

**Plain-language explanation:** We’re ranked lower on instructional queries — we need to create better guides to compete.

**Technical explanation:** KW_QUERY_GAPS shows Hollywoodbets.net ranks 8th and 10th respectively on 'aviator betting' and 'how to play aviator', with gaps of 6 and 9 positions. Content optimization targeting these queries can bridge the gap.

**Next step:** Create a 'How to Play Aviator' guide and optimize for long-tail keywords.

**Reason:** Directly actionable based on verified query gap data.

**Evidence IDs:** KW_QUERY_GAPS

### COMPETITION_03 — investigate

**Linked plan numbers:** none

**Plain-language explanation:** A proposed explanation could not be verified against the saved evidence. Further review is needed.

**Technical explanation:** Recheck the original source measurement, metric scope and cited evidence before approving a change.

**Next step:** Review the saved source records and rerun the scoped comparison if new data is authorized and required.

**Reason:** The original recommendation contained an unresolved factual or citation validation issue.

**Evidence IDs:** 

## Part D — Original specialist findings (unabridged, not independently verified)

The original specialist statements are retained verbatim for traceability. They may include hypotheses that were qualified or corrected in the repaired recommendations.

### ONPAGE_01 — onpage

**Original source:** llm_outputs/onpage_validated.json#/findings/0

**Source SHA-256:** 5fe87f361dbf517f0ae1a0874d1e9b69087d113903f8447ab6b0631bc56cbaa7

**Status:** specialist_interpretation_not_independently_verified

**Observation:** The ranking page title 'Online Sports Betting and Online Casino | Hollywoodbets' does not contain the primary keyword 'Aviator', whereas the benchmark title does.

**Interpretation:** The current title is broad and may result in lower click-through rates for users specifically searching for the Aviator game compared to the benchmark.

**Counterevidence:** The H1 tag correctly contains the keyword 'AVIATOR'.

**Recommended Action:** Verify if the current title aligns with the primary landing page intent; consider incorporating 'Aviator' into the title tag to improve relevance for specific queries.

**Original evidence paths:** evidence.onpage.comparison.title_keyword_match.ours, evidence.onpage.pages.ours.title, evidence.onpage.pages.benchmark.title

### ONPAGE_02 — onpage

**Original source:** llm_outputs/onpage_validated.json#/findings/1

**Source SHA-256:** bdc894d879bdae7e8384451c47dd7b7abe07221ff9154cbeba810017f37e6096

**Status:** specialist_interpretation_not_independently_verified

**Observation:** The benchmark page contains 28 internal links compared to 9 on the ranking page.

**Interpretation:** The benchmark page has a significantly higher density of internal linking, which may contribute to its higher authority or navigation structure.

**Counterevidence:** Internal link count does not directly prove authority or navigation quality.

**Recommended Action:** Audit internal linking structure to identify high-value pages that could be linked from the Aviator landing page.

**Original evidence paths:** evidence.onpage.comparison.internal_link_count.ours, evidence.onpage.comparison.internal_link_count.competitor

### ONPAGE_03 — onpage

**Original source:** llm_outputs/onpage_validated.json#/findings/2

**Source SHA-256:** 74c81c860aa2b8aee185d231afe40fa9c013f00b36818df5d2e443af81ccbe03

**Status:** specialist_interpretation_not_independently_verified

**Observation:** The content token Jaccard overlap between the two pages is 0.14285714285714285.

**Interpretation:** There is low lexical overlap between the two pages, suggesting distinct content approaches despite both being 'comparable' in scope.

**Counterevidence:** Jaccard overlap measures lexical similarity, not semantic relevance or quality.

**Recommended Action:** Verify if the unique content on the ranking page addresses the same user intents as the benchmark page.

**Original evidence paths:** evidence.onpage.comparison.content_token_jaccard

### BACKLINKS_01 — backlinks

**Original source:** llm_outputs/backlinks_validated.json#/findings/0

**Source SHA-256:** 5563edaae1580a7b8372a9e60b84abfa19814e28b1fd48f2312068fe44d2f553

**Status:** specialist_interpretation_not_independently_verified

**Observation:** The benchmark page (betway.co.za/aviator) has a higher backlink count (2809) and more referring domains (1259) than the tracked page (hollywoodbets.net/aviator) which has 1853 backlinks and 1184 referring domains.

**Interpretation:** The benchmark page possesses a stronger page-level backlink profile, which correlates with its higher ranking position (1) compared to the tracked page (2).

**Counterevidence:** The tracked domain (hollywoodbets.net) has a significantly higher total domain backlink count (1,806,871) compared to the benchmark domain (578,056).

**Recommended Action:** Analyze the specific referring domains for the benchmark page to identify high-authority sources that are not currently linking to the tracked page.

**Original evidence paths:** evidence.backlinks.page.ours, evidence.backlinks.page.benchmark, evidence.serp.ranking_summary

### BACKLINKS_02 — backlinks

**Original source:** llm_outputs/backlinks_validated.json#/findings/1

**Source SHA-256:** 5a7471e6771bf661feec26d513a74391a0eeb08983239bc3461cf5bd7bead928

**Status:** specialist_interpretation_not_independently_verified

**Observation:** The tracked domain has a much larger total backlink volume (1,806,871) than the benchmark domain (578,056), despite the benchmark domain holding the #1 position for the specific keyword.

**Interpretation:** Domain-level authority for the tracked site is high, but the specific page-level backlink profile for the 'aviator' URL is less dense than the competitor's equivalent page.

**Counterevidence:** None

**Recommended Action:** Focus on increasing page-specific referring domains for the /aviator URL to bridge the gap with the benchmark page.

**Original evidence paths:** evidence.backlinks.domain.ours, evidence.backlinks.domain.benchmark, evidence.serp.ranking_summary

### TECHNICAL_01 — technical

**Original source:** llm_outputs/technical_validated.json#/findings/0

**Source SHA-256:** e2bae404584f9f3d158b35177f8e39303c2995518b935da62d5f56a8d46f0748

**Status:** specialist_interpretation_not_independently_verified

**Observation:** The tracked website (hollywoodbets.net) has a mobile performance score of 28, while the benchmark (betway.co.za) has a lower performance score of 16.

**Interpretation:** While the tracked website has a higher performance score than the benchmark, the absolute score of 28 indicates significant performance issues on mobile devices.

**Counterevidence:** The benchmark's SEO score is lower (85) than the tracked website's SEO score (100).

**Recommended Action:** Investigate the specific bottlenecks contributing to the low performance score of 28 to improve mobile user experience.

**Original evidence paths:** evidence.serp.ranking_summary, evidence.technical.mobile_audits.ours.scores, evidence.technical.mobile_audits.benchmark.scores

### TECHNICAL_02 — technical

**Original source:** llm_outputs/technical_validated.json#/findings/1

**Source SHA-256:** 213be04819b3f8f27e51d9bd1fb1a61c88e5eff430c740d442cec6ddb8ebf583

**Status:** specialist_interpretation_not_independently_verified

**Observation:** The tracked website shows a Largest Contentful Paint (LCP) of 24,907.98 ms and a Total Blocking Time (TBT) of 2,122.5 ms.

**Interpretation:** The LCP is significantly high, indicating a slow perceived loading speed for the main content on mobile.

**Counterevidence:** The benchmark's LCP is also high at 19,506.78 ms.

**Recommended Action:** Optimize the critical rendering path to reduce LCP, specifically addressing the high TBT which suggests main-thread contention.

**Original evidence paths:** evidence.technical.mobile_audits.ours.lab_metrics

### TECHNICAL_03 — technical

**Original source:** llm_outputs/technical_validated.json#/findings/2

**Source SHA-256:** e6fbe7058fb6d17ab2dd2bdb782fd7e7c77b0dca00c2d5ea6e7277430429bcc0

**Status:** specialist_interpretation_not_independently_verified

**Observation:** JavaScript execution and unused JavaScript are identified as high-priority issues, with 6.0 s of boot-up time and 1,108 KiB of estimated savings from unused JS.

**Interpretation:** Excessive JavaScript execution and large, underutilized bundles are likely contributing to the high TBT and slow LCP.

**Counterevidence:** None provided in the JSON.

**Recommended Action:** Audit the main.38c4d2ededa66bb008c8.min.js bundle to remove unused code and optimize the boot-up sequence of external scripts like wdp.js.

**Original evidence paths:** evidence.technical.detailed_analysis.investigations[0], evidence.technical.detailed_analysis.investigations[1]

### COMPETITION_01 — competition

**Original source:** llm_outputs/competition_validated.json#/findings/0

**Source SHA-256:** e686b00eab723baeae45c8044727f37f0695ca1c981c90bb897a56dd3b579339

**Status:** specialist_interpretation_not_independently_verified

**Observation:** Betway.co.za holds the #1 position for the primary keyword 'aviator' and leads on high-volume generic modifiers like 'play aviator' and 'aviator bet'.

**Interpretation:** Betway.co.za is the primary confirmed benchmark, maintaining a competitive edge in both the core head term and high-volume intent-based modifiers.

**Counterevidence:** Hollywoodbets.net maintains a close proximity at position #2 for the primary keyword.

**Recommended Action:** Analyze the content structure and backlink profile of the betway.co.za/aviator page to identify specific ranking factors for the #1 position.

**Original evidence paths:** evidence.serp.ranking_summary, evidence.keywords.intersection.top_generic_benchmark_leads

### COMPETITION_02 — competition

**Original source:** llm_outputs/competition_validated.json#/findings/1

**Source SHA-256:** b286f40b975891effa40c16f3fe6c8b2c0360a3a05a257186f6715f153668102

**Status:** specialist_interpretation_not_independently_verified

**Observation:** Hollywoodbets.net shows a significant rank gap (6-9 positions) on specific long-tail queries such as 'aviator betting' and 'how to play aviator'.

**Interpretation:** The competitor has stronger authority or relevance for instructional and specific betting intent queries compared to the tracked domain.

**Counterevidence:** Hollywoodbets.net remains competitive on 'play aviator' and 'play aviator now' with a rank gap of only 1.

**Recommended Action:** Develop more comprehensive 'how-to' content and specific betting guides to close the gap on instructional queries.

**Original evidence paths:** evidence.keywords.intersection.top_generic_benchmark_leads

### COMPETITION_03 — competition

**Original source:** llm_outputs/competition_validated.json#/findings/2

**Source SHA-256:** aa3c96ed2313602b05b8a37528db165db9a0ae2b5d5c055ff92ddb990a180781

**Status:** specialist_interpretation_not_independently_verified

**Observation:** Multiple non-benchmark domains including app.aviator.co and aviator.co are present in the SERP discovery.

**Interpretation:** The SERP is populated by various entities, including potential direct game providers or app-specific landing pages, which may dilute traffic for the primary betting platforms.

**Counterevidence:** These candidates are not verified as ranking benchmarks and their specific positions are not provided.

**Recommended Action:** Monitor the visibility of these non-benchmark domains to determine if they are capturing significant share of the 'aviator' search intent.

**Original evidence paths:** evidence.competitor_discovery.candidates

## Part E — Verified factual findings

### Fact 1: Saved Google result: hollywoodbets.net is #2 and betway.co.za is #1 for 'aviator'.

**Interpretation:** betway.co.za leads by 1 position in this snapshot. The result confirms a visibility difference for this captured query and market only.

**Why it matters:** The higher-listed result is encountered earlier on this search-results page, giving the benchmark greater visibility in this snapshot.

**Next check:** Repeat the same query with the same market and device context over multiple dates; compare the exact ranking URLs before treating the gap as persistent.

**Limitation:** A single saved SERP is not a trend. Rankings vary, and this comparison does not identify a cause.

**Evidence IDs:** SERP

### Fact 2: The captured HTML title for the tracked ranking page does not include 'aviator'; the benchmark title includes it.

**Interpretation:** This is a difference in the page title text captured by the crawler. Google may rewrite the title shown in results, so the HTML title and visible search-result title are related but not always identical.

**Why it matters:** A clear, accurate title can help search engines and people understand what the page is about. Keyword presence by itself is not a ranking recipe.

**Next check:** Open both cited ranking URLs, verify their current rendered title tags and Google result titles, then assess whether the tracked title accurately matches the page and search intent before proposing an edit.

**Limitation:** The snapshot establishes title wording only. It does not prove that title wording caused the position gap or that adding the keyword would improve ranking or clicks.

**Evidence IDs:** ON_TITLE

### Fact 3: The crawler counted 9 internal links on the tracked page and 28 on the benchmark page (benchmark page: 19 more).

**Interpretation:** This is a count of links detected in the captured pages. More links do not automatically mean better internal linking; their destinations, anchor wording, placement, and usefulness matter.

**Why it matters:** Relevant internal links can help visitors move through a site and help crawlers discover related pages. A raw total cannot tell whether those links meaningfully support the selected ranking page.

**Next check:** Review the captured link lists and compare unique, relevant links pointing to each exact ranking URL. Separate repeated navigation/footer links from contextual links before deciding whether there is a useful gap.

**Limitation:** A page-level count is not link density or quality, may include repeated site-wide links, and does not establish ranking causation.

**Evidence IDs:** ON_LINKS

### Fact 4: Largest Contentful Paint: tracked page 24.9s vs benchmark 19.5s. The tracked page was about 5.4 seconds slower in this lab run.

**Interpretation:** LCP estimates when the main visible content finished appearing during this test. A longer time is a reason to investigate loading experience, not proof of a specific technical cause.

**Why it matters:** If repeated under comparable conditions and reflected in real-user data, slow visible loading can be a user-experience concern. This measurement alone cannot show how visitors experienced the page.

**Next check:** Repeat several mobile Lighthouse runs with the same settings, identify the LCP element and its loading dependencies, and compare with real-user Core Web Vitals if available.

**Limitation:** These are single-run synthetic Lighthouse measurements, not field data. Device/network conditions affect results; the metric does not identify a root cause or prove a ranking effect.

**Evidence IDs:** TECH_LAB

### Fact 5: Total Blocking Time: tracked page 2.1s vs benchmark 3.3s. The tracked page was about 1.2 seconds faster in this lab run.

**Interpretation:** TBT estimates how much long-running main-thread work delayed interaction during this lab test. Lower is better; it is distinct from LCP and does not describe the whole page experience.

**Why it matters:** A high or worsening TBT can make a page feel less responsive. Read it alongside LCP and other measures rather than treating one metric as an overall performance score.

**Next check:** Repeat comparable mobile Lighthouse runs and inspect the long tasks shown in the diagnostic report; confirm any proposed fix improves responsiveness without harming loading.

**Limitation:** These are single-run synthetic Lighthouse measurements, not field data. Device/network conditions affect results; the metric does not identify a root cause or prove a ranking effect.

**Evidence IDs:** TECH_LAB

### Fact 6: Page-specific third-party backlink rank favors betway.co.za (18 tracked versus 36 benchmark).

**Interpretation:** This is a third-party index score for the two ranking URLs. It is not a Google position; a larger score is stronger only within this provider metric.

**Why it matters:** Links from relevant, trusted pages can contribute to discovery and authority, but this aggregate score does not reveal which referring links are valuable.

**Next check:** Compare the referring domains and linking pages for these exact URLs, confirm the links are live and relevant, and investigate unusual or low-quality patterns before proposing outreach.

**Limitation:** Provider index scores are estimates. Individual link quality, relevance, freshness, and any ranking effect are unverified.

**Evidence IDs:** BL_PAGE

### Fact 7: Domain-wide third-party backlink rank favors hollywoodbets.net (70 tracked versus 65 benchmark).

**Interpretation:** This describes the provider’s estimate for each whole domain, not the selected ranking pages.

**Why it matters:** Domain-level link profiles provide broad competitive context, but they cannot explain a page-versus-page ranking difference on their own.

**Next check:** Use the page-level backlink evidence for the ranking URLs and inspect the strongest relevant referring pages; keep domain and page findings separate.

**Limitation:** Third-party index score, not Google rank. Domain-wide metrics cannot be attributed to either exact ranking page or to ranking causation.

**Evidence IDs:** BL_DOMAIN

### Fact 8: In the saved related-keyword set, the tracked domain leads on 24 shared queries and the benchmark leads on 31.

**Interpretation:** These are counts of queries where each domain leads, not average ranking positions or traffic totals.

**Why it matters:** The split offers broader context about which site appears to lead across the measured query set; it does not measure the value of each query to the business.

**Next check:** Review the actual query list, search volumes, intent, and ranking URLs, then prioritize queries that match the business objective.

**Limitation:** Domain-level context only. Different URLs may rank, and the counts do not prove page-level relevance, traffic, or causation.

**Evidence IDs:** KW_SHARED

## Part F — Recommendation quality audit

**Status:** review_required; **Blocking flags:** 0; **Review flags:** 4.

These are heuristic checks, not proof of technical correctness or SEO ranking causation.

- **review: domain_rank_scope (implementation_plans[4])** — Domain-level keyword positions may belong to different ranking URLs. Next check: Identify exact ranking URLs for each query and verify intent BEFORE proposing new content.
- **review: missing_post_change_verification (implementation_plans[4])** — The plan changes a website without an explicit post-change verification step. Next check: Add a repeatable post-deployment check after the final change.
- **review: missing_verification_step (implementation_plans[4])** — Implementation steps omit a verification activity. Next check: Add a concrete before/after check with repeatable conditions.
- **review: no_precondition (implementation_plans[4])** — Plan has no explicit verification or implementation precondition. Next check: State what must be verified before deployment.
