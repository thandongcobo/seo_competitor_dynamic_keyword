const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const esc = (value) => String(value ?? '—').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' })[char]);
let selectedPageId = '';
let currentMonitoringDetail = null;
let selectedPromotionCategory = '';
let comparisonScope = '';
let monitoringRequest = 0;

function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? String(value) : new Intl.DateTimeFormat('en-ZA', {dateStyle:'medium',timeStyle:'short',timeZone:'Africa/Johannesburg'}).format(date);
}

function displayValue(value) {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed) && parsed.length > 8) return `${parsed.length} items (showing first 8)\n${JSON.stringify(parsed.slice(0, 8), null, 2)}`;
      return JSON.stringify(parsed, null, 2);
    } catch { return value; }
  }
  return typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
}

function showPage(pageId, updateLocation = true) {
  const page = document.getElementById(pageId);
  const button = $$('.nav').find((item) => item.dataset.page === pageId);
  if (!page || !button) return false;
  $$('.nav').forEach((item) => item.classList.toggle('active', item === button));
  $$('.page').forEach((item) => item.classList.toggle('active', item === page));
  $('#page-title').textContent = button.textContent.trim();
  $('#scope').textContent = pageId === 'activity' ? 'Changes across all registered public competitor pages' : pageId === 'monitoring' ? 'Public page captures, promotion details, and observed changes' : comparisonScope;
  if (updateLocation) history.replaceState(null, '', `#${pageId}`);
  return true;
}

$$('.nav').forEach((button) => button.addEventListener('click', () => showPage(button.dataset.page)));
if (!showPage(location.hash.length > 1 ? decodeURIComponent(location.hash.slice(1)) : 'actions', false)) showPage('actions', false);

function makeTable(rows, columns, emptyMessage = 'No data available.') {
  if (!rows?.length) return `<div class="empty">${esc(emptyMessage)}</div>`;
  return `<table><thead><tr>${columns.map(([title]) => `<th>${esc(title)}</th>`).join('')}</tr></thead><tbody>${rows.map((row) => `<tr>${columns.map(([, value]) => `<td>${esc(typeof value === 'function' ? value(row) : row[value])}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
}

function statusRow(name, available) {
  return `<div class="pipe-row"><b>${esc(name)}</b><span class="${available ? 'ok' : 'waiting'}">${available ? 'Available' : 'Missing'}</span></div>`;
}

const EVIDENCE_LABELS = {
  SERP: 'Saved Google search result',
  ON_TITLE: 'Captured HTML title comparison',
  ON_LINKS: 'Captured internal-link counts',
  TECH_LAB: 'Mobile Lighthouse lab run',
  TECH_INV: 'Lighthouse investigation diagnostics',
  BL_PAGE: 'Page-level backlink data',
  BL_DOMAIN: 'Domain-level backlink data',
  KW_SHARED: 'Related-query domain comparison',
};

function explainEvidence(ids) {
  return ids.map((id) => `${EVIDENCE_LABELS[id] || id} (${id})`).join(' · ') || 'Not cited';
}

function finding(title, body, extra = '') {
  return `<div class="finding"><strong>${esc(title)}</strong><p>${esc(body || '—')}</p>${extra}</div>`;
}

// Move the selected finding into a full-width reading area, keeping the other
// cards in their original order and preserving native keyboard activation.
function selectDecisionCard(card) {
  const grid = $('#decision-findings');
  const opening = !card.open;
  const cards = [...grid.querySelectorAll('.decision-card')];
  cards.forEach((item, index) => {
    if (!item.dataset.position) item.dataset.position = String(index + 1);
    item.open = false;
  });
  cards.sort((a, b) => Number(a.dataset.position) - Number(b.dataset.position));
  cards.forEach((item) => grid.append(item));
  if (opening) {
    card.open = true;
    grid.prepend(card);
  }
  grid.classList.toggle('has-selection', opening);
  const summary = card.querySelector('summary');
  summary.focus({preventScroll: true});
  card.scrollIntoView({behavior: 'instant', block: 'start'});
}

$('#decision-findings').addEventListener('click', (event) => {
  const summary = event.target.closest('.decision-card > summary');
  if (!summary) return;
  event.preventDefault();
  selectDecisionCard(summary.parentElement);
});
$('#decision-findings').addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    const openCard = $('#decision-findings .decision-card[open]');
    if (openCard) { event.preventDefault(); selectDecisionCard(openCard); }
  }
});

function renderDashboard(state) {
  const meta = state.meta || {};
  const comparison = state.comparison || {};
  const executive = state.executive || {};
  const executiveMeta = state.executive_meta || {};
  const executiveStatus = state.executive_status || {};

  comparisonScope = `${meta.keyword || 'Aviator'} · ${meta.our_domain || 'Hollywoodbets'} vs ${meta.benchmark_domain || 'Betway'}`;
  showPage($('.nav.active')?.dataset.page || 'actions', false);
  $('#updated').textContent = 'Saved evidence loaded · ' + new Date().toLocaleTimeString();
  $('#rankings-table').innerHTML = makeTable((state.rankings || []).slice(0, 8), [
    ['Rank', (item) => item.rank_group ? `#${item.rank_group}` : '—'], ['Domain', 'domain'], ['Title', 'title'], ['URL', (item) => item.url || item.ranking_url],
  ]);
  $('#competitors-table').innerHTML = makeTable(state.competitors || [], [
    ['Domain', 'domain'], ['SERP rank', (item) => item.nearest_serp_rank ?? '—'],
    ['Source', (item) => `${item.serp_present ? 'SERP ' : ''}${item.labs_present ? 'Labs' : ''}` || 'Discovery'],
    ['Status', (item) => item.benchmark ? 'Confirmed benchmark' : 'Provisional'],
  ]);

  const decisions = executive.proposed_decisions || [];
  const actions = comparison.recommendations || state.recommendations || [];
  const keyFindings = executive.key_findings || [];
  const assessment = executive.executive_summary || 'No validated executive assessment is saved for this run.';
  const assessmentSentences = assessment.split(/(?<=\.)\s+(?=[A-Z])/);
  const assessmentPreview = assessmentSentences.slice(0, 2).join(' ');
  $('#executive-summary').textContent = assessmentPreview;
  $('#executive-summary-full').textContent = assessment;
  $('#executive-summary-more').hidden = assessmentPreview === assessment;
  const generatedAt = executiveMeta.generated_at_utc;
  $('#executive-status').textContent = executiveMeta.status === 'validated' ? 'Local LLM · validated' : 'No current validated run';
  $('#executive-freshness').textContent = generatedAt ? `Analysis generated ${formatDate(generatedAt)} · model ${executiveMeta.model || 'local model'}` : 'Run the Aviator analysis to generate a timestamped local-model assessment.';
  if (executiveStatus.status === 'failed') {
    $('#executive-freshness').textContent = `Latest local LLM run failed${executiveStatus.error ? `: ${executiveStatus.error}` : ''}. ${generatedAt ? `Showing the last validated analysis from ${formatDate(generatedAt)}.` : 'No validated analysis is available.'}`;
    $('#executive-status').textContent = 'Latest LLM run failed';
    $('#executive-status').classList.add('badge', 'yellow');
  }
  const related = (rows, ids) => rows.find((row) => (row.evidence_ids || []).some((id) => ids.includes(id)));
  const assignedDecisions = new Set();
  $('#decision-count').textContent = `${keyFindings.length} ${keyFindings.length === 1 ? 'finding' : 'findings'}`;
  $('#decision-findings').innerHTML = keyFindings.map((item, index) => {
    const ids = item.evidence_ids || [];
    const decision = decisions.find((row) => !assignedDecisions.has(row) && (row.evidence_ids || []).some((id) => ids.includes(id)));
    if (decision) assignedDecisions.add(decision);
    const action = related(actions, ids);
    const nextCheck = item.next_check || decision?.success_check || action?.success_check || action?.validation;
    const actionText = decision?.action || (Array.isArray(action?.actions) ? action.actions[0] : action?.action);
    const owner = decision?.owner;
    const recommendation = actionText || nextCheck || 'Review this finding with the team and decide whether a follow-up check is needed.';
    return `<details class="decision-card"><summary><span class="decision-card-number">${String(index + 1).padStart(2, '0')}</span><span class="decision-card-main"><span class="decision-card-label">Recommended next step${owner ? ` · ${esc(owner)}` : ''}</span><strong>${esc(recommendation)}</strong><span class="decision-card-finding">${esc(item.statement)}</span></span><span class="decision-card-toggle" aria-hidden="true">+</span></summary><div class="decision-card-detail"><div><h4>What we observed</h4><p>${esc(item.interpretation || item.statement)}</p></div><div><h4>Why it matters</h4><p>${esc(item.why_it_matters || 'Not specified.')}</p></div>${nextCheck && nextCheck !== recommendation ? `<div><h4>How to check it</h4><p>${esc(nextCheck)}</p></div>` : ''}<div class="decision-card-evidence"><h4>Evidence and limits</h4><p><b>Sources:</b> ${esc(explainEvidence(ids))}</p><p><b>What we cannot conclude yet:</b> ${esc(item.limitation || decision?.limitation || action?.limitations || 'Not specified.')}</p></div></div></details>`;
  }).join('') || '<div class="empty">No validated findings are available. Run the Aviator analysis with the local LLM to generate them.</div>';
}

function renderSnapshot(snapshot) {
  if (!snapshot) return '<div class="empty">No successful page capture is saved yet.</div>';
  const headings = snapshot.headings || {};
  const headingSummary = Object.entries(headings).flatMap(([level, values]) => (values || []).map((text) => `${level.toUpperCase()}: ${text}`));
  const titleAndDescription = `<div class="snapshot-fact"><span>Title</span><strong>${esc(snapshot.title || 'Not captured')}</strong></div><div class="snapshot-fact"><span>Meta description</span><p>${esc(snapshot.meta_description || 'Not captured')}</p></div><div class="snapshot-fact"><span>Canonical URL</span><p>${esc(snapshot.canonical || 'Not captured')}</p></div>`;
  const shadowCount = Number(snapshot.shadow_dom_open_root_count || 0);
  const uninspected = snapshot.shadow_dom_uninspected_custom_elements || [];
  const coverageNote = uninspected.length ? `<p class="muted">Coverage note: traversed ${shadowCount} open Shadow DOM roots. ${uninspected.length} custom-element host(s) did not expose an open root (${esc(uninspected.join(', '))}); their internal content may not be extractable.</p>` : `<p class="muted">Rendered-content traversal inspected ${shadowCount} accessible open Shadow DOM roots.</p>`;
  const metrics = `<div class="snapshot-metrics"><span>${esc(snapshot.status_code ?? '—')} HTTP status</span><span>${esc(snapshot.word_count ?? 0)} words</span><span>${esc(snapshot.h1_count ?? 0)} H1 headings</span><span>${esc(snapshot.internal_link_count ?? 0)} internal links</span><span>${esc(snapshot.external_link_count ?? 0)} external links</span><span>${esc(snapshot.structured_data_count ?? 0)} structured data blocks</span><span>${esc(shadowCount)} open Shadow DOM roots</span></div>`;
  const headingsHtml = headingSummary.length ? `<details class="snapshot-detail"><summary>Captured headings (${headingSummary.length})</summary>${headingSummary.map((text) => `<p>${esc(text)}</p>`).join('')}</details>` : '<p class="muted">No headings were extracted.</p>';
  return `<div class="snapshot-overview">${titleAndDescription}${metrics}${headingsHtml}<p class="muted">Capture status: ${esc(snapshot.extraction_status || 'unknown')} · Final URL: ${esc(snapshot.final_url || snapshot.requested_url || '—')}</p>${coverageNote}</div>`;
}

function renderMainContent(snapshot, capturedAt) {
  const content = snapshot?.rendered_page_text || snapshot?.seo_content_text || snapshot?.text_sample || '';
  const fullPage = Boolean(snapshot?.rendered_page_text);
  const wordCount = fullPage ? snapshot.rendered_page_word_count : content.trim().split(/\s+/).filter(Boolean).length;
  $('#main-content-label').textContent = `${(wordCount || 0).toLocaleString()} words · ${fullPage ? 'rendered page' : 'partial extract'}`;
  $('#main-content-meta').textContent = content
    ? `Captured ${formatDate(capturedAt)} · ${fullPage ? `Rendered public-page text across ${snapshot.rendered_text_blocks?.length || 0} text blocks, including accessible open Shadow DOM, after bounded scrolling` : 'A partial text extract'}. Closed shadow roots, inaccessible frames, image-only copy, and click-only content may still be unavailable.`
    : 'No text content was saved in the latest successful scrape.';
  $('#main-content-display').innerHTML = content
    ? `<pre>${esc(content)}</pre>`
    : '<div class="empty">No captured text is available for this snapshot.</div>';
}

function renderCaptureArtifacts(snapshot, snapshotMeta) {
  const id = snapshotMeta.id;
  if (!snapshot || !id) {
    $('#monitor-screenshot').innerHTML = '<div class="empty">No successful screenshot is available.</div>';
    $('#monitor-visual-diff').innerHTML = '<div class="empty">Capture a page to establish a screenshot baseline.</div>';
    return;
  }
  const screenshotUrl = `/api/monitoring/artifacts/${encodeURIComponent(id)}/screenshot`;
  const htmlUrl = `/api/monitoring/artifacts/${encodeURIComponent(id)}/html`;
  const screenshotMode = snapshot.screenshot_mode === 'stitched_full_page_v2'
    ? 'stitched page · fixed overlays shown once'
    : snapshot.screenshot_mode || 'page screenshot';
  $('#monitor-screenshot').innerHTML = snapshot.screenshot_path
    ? `<a href="${screenshotUrl}" target="_blank" rel="noreferrer">Open full-page screenshot</a> · <a href="${htmlUrl}" target="_blank" rel="noreferrer">Open captured HTML</a><img src="${screenshotUrl}" alt="Full-page screenshot captured ${esc(formatDate(snapshotMeta.captured_at))}"><p class="muted">${esc((snapshot.screenshot_dimensions || []).join(' × ') || snapshot.document_height || '—')} px · ${esc(screenshotMode)} · capture ${esc(id)}</p>`
    : '<div class="empty">Screenshot could not be saved for this capture.</div>';
  const visual = snapshot.visual_comparison || {};
  if (visual.status === 'compared' && visual.diff_image_path) {
    $('#monitor-visual-diff').innerHTML = `<p><b>${esc(visual.changed_pixel_percent)}%</b> of screenshot pixels differ beyond the noise threshold.</p><img class="diff-preview" src="/api/monitoring/artifacts/${encodeURIComponent(id)}/visual-diff" alt="Pixel difference between captures"><p class="muted">Pixel differences can include dynamic banners, animation, or layout shifts; review the screenshots before interpreting them.</p>`;
  } else {
    $('#monitor-visual-diff').innerHTML = `<div class="empty">${esc(visual.reason || 'A second successful screenshot is needed for a visual comparison.')}</div>`;
  }
}

function renderChange(change) {
  return `<article class="change-card"><div class="change-heading"><strong>${esc(change.title || change.element_type)}</strong><small>Detected ${esc(formatDate(change.first_detected_at))}</small></div><p>${esc(change.summary || 'The captured page information changed.')}</p><details><summary>View supporting comparison</summary><div class="change-values"><div><span>Previous</span><pre>${esc(displayValue(change.previous_value))}</pre></div><div><span>Current</span><pre>${esc(displayValue(change.current_value))}</pre></div></div></details></article>`;
}

function renderPromotions(detail) {
  const analysis = detail.promotion_analysis || {};
  const items = detail.promotions || [];
  const sourceFilter = $('#promotion-source-filter')?.value || 'all';
  const latestSnapshotId = detail.snapshots?.[0]?.id;
  const query = ($('#promotion-search')?.value || '').trim().toLowerCase();
  const matching = items.filter((item) => {
    if (['not_seen', 'not_detected'].includes(item.status) && sourceFilter !== 'history') return false;
    if (sourceFilter === 'history' && item.last_snapshot_id === latestSnapshotId) return false;
    if (!['history', 'dismissed'].includes(sourceFilter) && item.last_snapshot_id !== latestSnapshotId) return false;
    if (sourceFilter === 'dismissed' && item.review_status !== 'dismissed') return false;
    if (sourceFilter !== 'dismissed' && item.review_status === 'dismissed') return false;
    const type = item.source_type || 'image';
    if (!['dismissed', 'history'].includes(sourceFilter) && sourceFilter === 'text' && !type.includes('text')) return false;
    if (!['dismissed', 'history'].includes(sourceFilter) && sourceFilter === 'image' && !type.includes('image')) return false;
    const haystack = `${item.title || ''} ${item.extracted_text || ''} ${JSON.stringify(item.details || {})}`.toLowerCase();
    const verification = $('#promotion-verification').value;
    if (verification === 'confirmed' && item.review_status !== 'confirmed') return false;
    if (verification && verification !== 'confirmed' && item.verification?.status !== verification) return false;
    return !query || haystack.includes(query);
  });
  const categories = detail.categories || {};
  $('#promotion-categories').innerHTML = [['', 'All promotions'], ...Object.entries(categories)].map(([key,label]) => {
    const count = key ? matching.filter((item) => (item.categories || ['unclassified']).includes(key)).length : matching.length;
    return `<button type="button" data-category="${esc(key)}" class="category-tile ${selectedPromotionCategory === key ? 'selected' : ''}" aria-pressed="${selectedPromotionCategory === key}"><strong>${count}</strong><span>${esc(label)}</span></button>`;
  }).join('');
  const visible = matching.filter((item) => !selectedPromotionCategory || (item.categories || ['unclassified']).includes(selectedPromotionCategory));
  const domain = detail.page?.domain || 'this company';
  const scopeNote = `Candidates found on monitored public pages for ${domain}; unmonitored pages are not included.`;
  const scanNote = analysis.text_scan_complete ? 'Rendered text was scanned.' : 'Text-scan status unavailable.';
  const countNote = analysis.auto_investigated_count ? `${analysis.auto_investigated_count} public-link investigation(s) attempted in the latest capture.` : (analysis.message || 'Capture a page to inspect its text and banner images.');
  $('#promotions-meta').textContent = `${scopeNote} ${scanNote} ${countNote} Candidate details are evidence, not guaranteed or inferred offer terms.`;
  $('#promotions-list').innerHTML = visible.map((item) => {
    const image = Number.isInteger(item.image_index) ? `/api/monitoring/artifacts/${encodeURIComponent(item.last_snapshot_id)}/promotion-image/${encodeURIComponent(item.image_index)}` : '';
    const type = item.source_type || 'image';
    const typeLabel = type.includes('text') && type.includes('image') ? 'Text + image' : type.includes('text') ? 'Text candidate' : 'Image/banner candidate';
    const target = item.target_url ? `<p><b>Related public link:</b> <a href="${esc(item.target_url)}" target="_blank" rel="noreferrer">${esc(item.target_url)}</a></p>` : '';
    const statusNames = {automatically_corroborated:'Automatically corroborated', details_available:'Public details available', needs_review:'Needs more evidence'};
    const extracted = `<p>${(item.categories || ['unclassified']).map((key) => `<span class="badge">${esc(categories[key] || key)}</span>`).join(' ')}</p><p><b>${esc(statusNames[item.verification?.status] || 'Needs more evidence')}:</b> ${esc(item.verification?.reason || '')}</p>` + (item.extracted_text ? `<p class="promotion-copy">${esc(item.extracted_text)}</p>` : '<p class="muted">No text was extracted; review the captured artwork.</p>');
    const status = item.last_snapshot_id !== latestSnapshotId ? 'Earlier capture · not seen in latest scan' : 'Seen in latest successful capture';
    const details = item.details || {};
    const fields = [['Amounts', details.amounts], ['Percentages', details.percentages], ['Promo codes', details.promo_codes], ['Dates found', details.dates], ['Promotion hours', details.time_windows], ['Eligibility / terms', details.eligibility_or_terms]].filter(([, values]) => values?.length);
    const fieldHtml = fields.map(([label, values]) => `<li><b>${esc(label)}:</b> ${values.map(esc).join(' · ')}</li>`).join('');
    const termsLink = details.terms_url ? `<p><b>Terms page:</b> <a href="${esc(details.terms_url)}" target="_blank" rel="noreferrer">${esc(details.terms_url)}</a></p>` : '';
    const investigation = item.investigation || {};
    const termsPage = investigation.terms_page || {};
    const investigationHtml = investigation.status === 'captured'
      ? `<div class="promotion-investigation"><b>Public page investigated:</b> ${esc(investigation.title || investigation.source_url || 'Captured')} · <a href="${esc(investigation.source_url)}" target="_blank" rel="noreferrer">Open source</a>${investigation.text_excerpt ? `<details class="promotion-details"><summary>View linked page evidence</summary><p>${esc(investigation.text_excerpt)}</p></details>` : ''}${termsLink}${termsPage.status === 'captured' ? `<details class="promotion-details"><summary>View public terms evidence</summary><p><a href="${esc(termsPage.source_url)}" target="_blank" rel="noreferrer">${esc(termsPage.title || termsPage.source_url)}</a></p><p>${esc(termsPage.text_excerpt || '')}</p></details>` : ''}</div>`
      : `<div class="promotion-investigation"><b>Investigation:</b> ${esc(investigation.reason || (investigation.status === 'not_started' ? 'Awaiting a high-confidence match.' : investigation.status || 'Not started'))}</div>`;
    const reviewState = item.review_status === 'confirmed' ? 'Team confirmed candidate' : item.review_status === 'dismissed' ? 'Team dismissed candidate' : item.review_status === 'auto_investigated' ? 'Auto-investigated · team review pending' : 'Team review needed';
    const reviewButtonLabel = item.review_status === 'confirmed' ? 'Confirmed' : 'Confirm candidate';
    const categoryEditor = `<details class="promotion-details"><summary>Correct categories (${esc(item.category_source || 'automatic')} labels)</summary><form class="category-editor" data-promotion="${esc(item.id)}">${Object.entries(categories).map(([key,label]) => `<label><input type="checkbox" value="${esc(key)}" ${(item.categories || []).includes(key) ? 'checked' : ''}> ${esc(label)}</label>`).join('')}<p>Clear all boxes to restore automatic labels.</p><button type="submit">Save categories</button></form></details>`;
    const imageHtml = image ? `<img src="${image}" alt="Captured promotion or banner candidate">` : '';
    const detailHtml = categoryEditor + (fields.length || details.evidence_excerpts?.length
      ? `<details class="promotion-details"><summary>Extracted offer details and evidence</summary>${fieldHtml ? `<ul>${fieldHtml}</ul>` : '<p>No amount, code, date, or eligibility details were found yet.</p>'}${(details.evidence_excerpts || []).map((excerpt) => `<p>${esc(excerpt)}</p>`).join('')}</details>`
      : '<p class="muted">No structured offer details found yet. Review the captured wording.</p>');
    return `<article class="promotion-card">${imageHtml}<div><div class="promotion-title"><strong>${esc(item.title)}</strong><span class="badge yellow">${esc(item.confidence)} confidence · ${esc(typeLabel)}</span></div><small>${esc(status)} · first seen ${esc(formatDate(item.first_seen_at))} · last seen ${esc(formatDate(item.last_seen_at))}</small>${extracted}<p class="muted">${esc(item.reason || 'Promotion-like content found')} · ${esc(item.page_url || '')}${item.heading ? ` · Section: ${esc(item.heading)}` : ''}</p>${target}${detailHtml}${investigationHtml}<div class="promotion-review"><span class="review-state">${esc(reviewState)}</span><button type="button" data-promotion-id="${esc(item.id)}" data-decision="confirmed">${esc(reviewButtonLabel)}</button><button type="button" class="dismiss" data-promotion-id="${esc(item.id)}" data-decision="dismissed">Dismiss</button></div></div></article>`;
  }).join('') || '<div class="empty">No promotions match these filters. Choose All promotions or adjust the source, evidence status, or search.</div>';
}

function renderMonitoring(detail) {
  currentMonitoringDetail = detail;
  const page = detail.page;
  $('#schedule-enabled').checked = Boolean(page.active);
  $('#schedule-hours').value = page.frequency_hours || 24;
  const snapshots = detail.snapshots || [];
  const captures = detail.captures || [];
  const latest = detail.latest_snapshot || null;
  const latestMeta = snapshots[0] || {};
  const successfulIds = new Set(snapshots.map((snapshot) => snapshot.id));
  const changes = (detail.changes || []).filter((change) => successfulIds.has(change.previous_snapshot_id) && successfulIds.has(change.current_snapshot_id));

  $('#monitor-status').textContent = page.active ? 'Active' : 'Paused';
  $('#monitor-keyword').textContent = `Keyword: ${JSON.parse(page.keywords || '[]').join(', ') || 'aviator'}`;
  $('#snapshot-count').textContent = snapshots.length;
  $('#change-count').textContent = changes.length;
  $('#last-capture').textContent = page.last_success_at ? formatDate(page.last_success_at) : 'No capture yet';
  $('#capture-frequency').textContent = `Every ${page.frequency_hours || 24} hours`;
  $('#monitor-source').textContent = page.source_evidence ? 'SERP evidence linked' : 'Monitoring source';
  const latestCapture = captures[0] || null;
  const captureQuality = latestCapture?.diagnostics?.tracking_quality || latest?.tracking_quality || null;
  const health = $('#capture-health');
  const healthBadge = $('#capture-health-badge');
  if (latestCapture?.status === 'failed') {
    healthBadge.textContent = 'Capture failed';
    health.innerHTML = `<p><b>Latest attempt:</b> Failed · ${esc(formatDate(latestCapture.finished_at || latestCapture.started_at))}</p><p>${esc(latestCapture.error || 'No failure detail was recorded.')}</p><p>Promotion state was not updated from this attempt.</p>`;
  } else if (captureQuality) {
    healthBadge.textContent = captureQuality.eligible ? 'Eligible for tracking' : 'Review required';
    health.innerHTML = `<p><b>Latest eligible capture:</b> ${esc(formatDate(latestMeta.captured_at || page.last_success_at))} · ${Number(captureQuality.word_count || 0).toLocaleString()} visible words · ${captureQuality.same_host ? 'same host' : 'host changed'}</p>${captureQuality.reasons?.length ? `<ul>${captureQuality.reasons.map((reason) => `<li>${esc(reason)}</li>`).join('')}</ul>` : '<p>Capture passed basic host, completeness, stability, and content-volume checks. This is a quality gate, not proof that every page element was captured.</p>'}${captureQuality.warnings?.length ? `<ul class="capture-warnings">${captureQuality.warnings.map((warning) => `<li>${esc(warning)}</li>`).join('')}</ul>` : ''}${latestCapture && latestCapture.status === 'success' && latestCapture.diagnostics?.tracking_quality?.eligible === false ? '<p><b>The newest attempt was not used to update comparisons or promotion lifecycle state.</b></p>' : ''}`;
  } else {
    healthBadge.textContent = 'No capture yet';
    health.textContent = 'Capture diagnostics will appear after the first attempt.';
  }
  $('#monitor-target').innerHTML = `<p><b>Competitor:</b> ${esc(page.domain)}</p><p><b>Page URL:</b> <a href="${esc(page.url)}" target="_blank" rel="noreferrer">${esc(page.url)}</a></p><p><b>Registered:</b> ${esc(formatDate(page.created_at))}</p><p><b>Source evidence:</b> ${esc(page.source_evidence || '—')}</p>`;
  renderPromotions(detail);
  $('#monitor-current').innerHTML = renderSnapshot(latest);
  renderMainContent(latest, latestMeta.captured_at || page.last_success_at);
  renderCaptureArtifacts(latest, latestMeta);
  $('#monitor-fields').innerHTML = '<div class="field-chips">' + ['Page title', 'Meta description', 'Canonical URL', 'Headings', 'Full rendered text', 'Visible images', 'Background images', 'Internal links', 'External links', 'Structured data'].map((label) => `<span>${esc(label)}</span>`).join('') + '</div><p class="muted">Fields are compared only between successful captures. Failed or incomplete captures are recorded separately.</p>';
  $('#snapshot-history').innerHTML = makeTable(snapshots, [
    ['Captured at', (item) => formatDate(item.captured_at)], ['Final URL', 'final_url'], ['Extraction', 'extraction_method'],
    ['Content fingerprint', (item) => item.content_hash ? item.content_hash.slice(0, 16) + '…' : '—'], ['Snapshot ID', 'id'],
  ], 'No saved snapshots yet.');
  $('#monitor-changes').innerHTML = changes.map(renderChange).join('') || '<div class="empty">No meaningful changes detected yet. A second successful capture is needed for comparison.</div>';
  const added = changes.filter((change) => change.category === 'added');
  $('#monitor-new').innerHTML = added.map(renderChange).join('') || '<div class="empty">No newly added fields have been detected. Wording added within existing fields appears in the change summaries.</div>';
  if (latestCapture?.status === 'failed') $('#monitor-new').insertAdjacentHTML('afterbegin', finding('Latest capture failed', latestCapture.error || latestCapture.diagnostics || 'Capture error details were not saved.'));
  loadPageTimeline(page.id);
  $('#capture-compare').dataset.pageId = page.id;
  $('#capture-compare').disabled = false;
}

async function loadMonitoring() {
  const request = ++monitoringRequest;
  try {
    const response = await fetch(`/api/monitoring/pages?ts=${Date.now()}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`Monitoring service returned ${response.status}`);
    const data = await response.json();
    if (request !== monitoringRequest) return;
    const pages = data.pages || [];
    $('#monitor-page-select').innerHTML = pages.map((item) => {
      let label = item.url;
      try { const parsed = new URL(item.url); label = parsed.hostname + parsed.pathname; } catch { /* saved URL will be shown as-is */ }
      return `<option value="${esc(item.id)}">${esc(label)}</option>`;
    }).join('') || '<option value="">No pages registered</option>';
    const page = pages.find((item) => item.id === selectedPageId) || pages.find((item) => item.active) || pages[0];
    if (!page) {
      selectedPageId = '';
      currentMonitoringDetail = null;
      $('#capture-compare').dataset.pageId = '';
      $('#capture-compare').disabled = true;
      $('#monitor-status').textContent = 'Not registered';
      $('#monitor-target').innerHTML = '<div class="empty">No page is registered yet. Add a public URL above to start monitoring.</div>';
      $('#monitor-current').innerHTML = renderSnapshot(null);
      $('#snapshot-history').innerHTML = '<div class="empty">No snapshots have been recorded.</div>';
      $('#monitor-changes').innerHTML = '<div class="empty">No changes to compare yet.</div>';
      return;
    }
    selectedPageId = page.id;
    $('#monitor-page-select').value = selectedPageId;
    const detailResponse = await fetch(`/api/monitoring/pages/${encodeURIComponent(page.id)}?ts=${Date.now()}`, { cache: 'no-store' });
    if (!detailResponse.ok) throw new Error(`Page history returned ${detailResponse.status}`);
    const detail = await detailResponse.json();
    if (request === monitoringRequest) renderMonitoring(detail);
  } catch (error) {
    if (request !== monitoringRequest) return;
    $('#monitor-status').textContent = 'Unavailable';
    $('#monitor-target').innerHTML = finding('Monitoring data could not load', error.message);
  }
}

$('#monitor-page-select').addEventListener('change', async (event) => {
  selectedPageId = event.currentTarget.value;
  await loadMonitoring();
});

$('#promotion-source-filter').addEventListener('change', () => {
  if (currentMonitoringDetail) renderPromotions(currentMonitoringDetail);
});
$('#promotion-search').addEventListener('input', () => {
  if (currentMonitoringDetail) renderPromotions(currentMonitoringDetail);
});

$('#add-monitor-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const input = $('#monitor-url');
  const button = $('#add-monitor-run');
  let url = input.value.trim();
  if (url && !/^https?:\/\//i.test(url)) url = `https://${url}`;
  button.disabled = true;
  $('#monitor-form-status').textContent = 'Registering the public page…';
  try {
    const registerResponse = await fetch('/api/monitoring/register', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, keyword: 'aviator', source_evidence: 'dashboard.user_added_public_url' }),
    });
    const registered = await registerResponse.json();
    if (!registerResponse.ok) throw new Error(registered.error || `Registration returned ${registerResponse.status}`);
    selectedPageId = registered.page_id;
    await loadMonitoring();
    input.value = '';
    $('#monitor-form-status').textContent = 'Public page added and selected. Use “Capture & compare” to capture it and inspect text, images, and promotion candidates.';
  } catch (error) {
    $('#monitor-form-status').textContent = `Could not complete the page capture: ${error.message}`;
    if (selectedPageId) await loadMonitoring();
  } finally {
    button.disabled = false;
  }
});

$('#promotions-list').addEventListener('click', async (event) => {
  const button = event.target.closest('button[data-promotion-id]');
  if (!button) return;
  button.disabled = true;
  try {
    const response = await fetch('/api/monitoring/promotions/review', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ promotion_id: button.dataset.promotionId, decision: button.dataset.decision }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `Review returned ${response.status}`);
    await loadMonitoring();
  } catch (error) {
    button.disabled = false;
    $('#promotions-meta').textContent = `Could not save review: ${error.message}`;
  }
});

$('#capture-compare').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  const pageId = button.dataset.pageId;
  if (!pageId) return;
  button.disabled = true;
  button.textContent = 'Capturing page…';
  try {
    const response = await fetch('/api/monitoring/capture', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ page_id: pageId }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `Capture returned ${response.status}`);
    await loadMonitoring();
    loadActivity();
  } catch (error) {
    $('#monitor-changes').innerHTML = finding('Capture failed', error.message);
  } finally {
    button.disabled = false;
    button.textContent = 'Capture & compare';
  }
});

async function loadDashboard() {
  try {
    const response = await fetch(`/api/dashboard?ts=${Date.now()}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`Dashboard service returned ${response.status}`);
    renderDashboard(await response.json());
  } catch (error) {
    $('#updated').textContent = 'Dashboard data unavailable';
    console.error('Dashboard data could not load:', error);
  } finally {
    loadMonitoring();
  }
}

loadDashboard();
