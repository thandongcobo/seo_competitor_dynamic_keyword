const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const esc = (value) => String(value ?? '—').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' })[char]);
let selectedPageId = '';
let currentMonitoringDetail = null;
let selectedPromotionCategory = '';
let comparisonScope = '';
let monitoringRequest = 0;
let selectedComparisonId = '';
let comparisonHistoryPage = 1;
let latestComparisonHistory = null;
let decisionOpenedFromHistory = false;
const workflowDecisionOpened = new Set();

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
  $('#scope').textContent = pageId === 'search' ? 'Collect and inspect real Google organic results for any keyword' : pageId === 'activity' ? 'Changes across all registered public competitor pages' : pageId === 'monitoring' ? 'Public page captures, promotion details, and observed changes' : comparisonScope;
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

function renderDashboard(state) {
  const meta = state.meta || {};
  comparisonScope = `${meta.our_domain || 'Hollywoodbets'} vs ${meta.benchmark_domain || 'Betway'} · ${meta.location || 'Configured location'}`;
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

  clearDecisionView();
}

function clearDecisionView(message = 'Complete a saved investigation or open a validated comparison from Comparison History.') {
  selectedComparisonId = '';
  $('#executive-status').textContent = 'No investigation selected';
  $('#executive-summary').textContent = message;
  $('#executive-freshness').textContent = '';
  $('#recommendations-list').textContent = 'Recommendations are shown only after selecting a validated investigation.';
  $('#decision-report-links').replaceChildren();
  $('#decision-report-links').hidden = true;
  $('#decision-back-history').hidden = true;
}

function renderDecisionView(record, {fromHistory = false} = {}) {
  selectedComparisonId = record.investigation_id;
  decisionOpenedFromHistory = fromHistory;
  try { sessionStorage.setItem('seoSelectedComparisonId', selectedComparisonId); } catch {}
  const ours = record.selection.ours;
  const competitor = record.selection.benchmark;
  const rank = (page) => Number.isInteger(page.rank) ? `#${page.rank}` : 'not recorded';
  const searchContext = record.selection.search_context?.location_note || (record.source === 'manual_exact_webpage_urls' ? 'Manual exact-page selection' : 'Saved search context');
  comparisonScope = `${ours.domain || 'Hollywoodbets'} vs ${competitor.domain || 'Competitor'} · ${searchContext}`;
  $('#scope').textContent = comparisonScope;
  $('#executive-status').textContent = 'Validated recommendations available';
  $('#executive-status').classList.remove('yellow');
  $('#executive-summary').textContent = `${record.keyword} · Hollywoodbets ${ours.url} (${rank(ours)}) · ${competitor.domain || 'Competitor'} ${competitor.url} (${rank(competitor)})`;
  $('#executive-freshness').textContent = `Investigation ${record.investigation_id} · completed ${formatDate(record.completed_at || record.created_at)} · ${record.recommendation_count} validated recommendation(s) · workflow: ${record.workflow_status}.`;
  const links = $('#decision-report-links');
  links.replaceChildren();
  if (record.has_pdf) {
    const pdf = document.createElement('a'); pdf.href = `/api/comparisons/${encodeURIComponent(record.investigation_id)}/artifacts/pdf`; pdf.textContent = 'Download management PDF'; links.appendChild(pdf);
  }
  if (record.has_appendix) {
    const appendix = document.createElement('a'); appendix.href = `/api/comparisons/${encodeURIComponent(record.investigation_id)}/artifacts/appendix`; appendix.textContent = 'Download technical appendix'; links.appendChild(appendix);
  }
  if (record.has_serp_snapshot) {
    const serp = document.createElement('a'); serp.href = `/api/comparisons/${encodeURIComponent(record.investigation_id)}/serp`; serp.target = '_blank'; serp.rel = 'noopener'; serp.textContent = 'Open original saved SERP'; links.appendChild(serp);
  }
  if (!record.has_pdf) {
    const note = document.createElement('span'); note.className = 'muted'; note.textContent = 'Management PDF unavailable; saved validated recommendations remain available.'; links.appendChild(note);
  }
  links.hidden = false;
  $('#decision-back-history').hidden = !fromHistory;
  $('#recommendations-list').innerHTML = window.renderRecommendations(record.recommendations || []);
}

async function openDecision(investigationId, {fromHistory = false, navigate = true} = {}) {
  $('#executive-status').textContent = 'Checking saved recommendation integrity…';
  try {
    const response = await fetch(`/api/comparisons/${encodeURIComponent(investigationId)}`, {cache:'no-store'});
    const record = await response.json();
    if (!response.ok) throw new Error(record.error || `Comparison returned ${response.status}`);
    renderDecisionView(record, {fromHistory});
    if (navigate) showPage('actions');
    return record;
  } catch (error) {
    clearDecisionView(`Saved recommendations could not be opened: ${error.message}`);
    $('#executive-status').textContent = 'Comparison unavailable';
    if (navigate) showPage(fromHistory ? 'history' : 'actions');
    return null;
  }
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
    void loadComparisonHistory(1);
    let savedId = '';
    try { savedId = sessionStorage.getItem('seoSelectedComparisonId') || ''; } catch {}
    if (savedId) void openDecision(savedId, {navigate:false});
    loadMonitoring();
  }
}

async function loadComparisonHistory(page = comparisonHistoryPage) {
  const status = $('#comparison-history-status');
  const results = $('#comparison-history-results');
  const pagination = $('#comparison-history-pagination');
  if (!status || !results) return;
  const params = new URLSearchParams({page:String(page), page_size:'20', sort:$('#comparison-history-sort').value});
  for (const [key, selector] of [
    ['q','#comparison-history-query'], ['keyword','#comparison-history-keyword'],
    ['competitor','#comparison-history-competitor'], ['url','#comparison-history-url'],
    ['date_from','#comparison-history-from'], ['date_to','#comparison-history-to'],
  ]) {
    const value = $(selector).value.trim();
    if (value) params.set(key, value);
  }
  status.textContent = 'Loading validated saved comparisons…';
  results.replaceChildren();
  try {
    const response = await fetch(`/api/comparisons/history?${params}`, {cache:'no-store'});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `History returned ${response.status}`);
    latestComparisonHistory = payload;
    comparisonHistoryPage = payload.page;
    status.textContent = `${payload.total} completed comparison(s) with validated recommendation sets. Search results are saved records; no collection or model requests were made.`;
    if (!payload.comparisons.length) {
      results.textContent = 'No validated completed comparisons match these filters.';
    }
    for (const row of payload.comparisons) {
      const card = document.createElement('article'); card.className = 'comparison-history-card';
      const title = document.createElement('h3'); title.textContent = `${row.keyword} · ${row.selection.benchmark.domain || 'Competitor'}`; card.appendChild(title);
      const pages = document.createElement('p'); pages.textContent = `Hollywoodbets: ${row.selection.ours.url} (${Number.isInteger(row.selection.ours.rank) ? `#${row.selection.ours.rank}` : 'rank not recorded'}) · Competitor: ${row.selection.benchmark.url} (${Number.isInteger(row.selection.benchmark.rank) ? `#${row.selection.benchmark.rank}` : 'rank not recorded'})`; card.appendChild(pages);
      const counts = document.createElement('div'); counts.className = 'history-counts';
      for (const label of [
        `Tier 1: ${row.tier_1_count}`, `Tier 2: ${row.tier_2_count}`,
        `Total: ${row.recommendation_count}`, `Report: ${row.report_status}`,
      ]) { const badge = document.createElement('span'); badge.textContent = label; counts.appendChild(badge); }
      card.appendChild(counts);
      const meta = document.createElement('p'); meta.textContent = `Investigation ${row.investigation_id} · ${formatDate(row.completed_at || row.created_at)} · ${row.workflow_status}`; card.appendChild(meta);
      const open = document.createElement('button'); open.type = 'button'; open.textContent = 'Open saved recommendations';
      open.addEventListener('click', () => void openDecision(row.investigation_id, {fromHistory:true})); card.appendChild(open);
      results.appendChild(card);
    }
    pagination.hidden = payload.pages <= 1;
    $('#comparison-history-page').textContent = payload.pages ? `Page ${payload.page} of ${payload.pages}` : 'No pages';
    $('#comparison-history-prev').disabled = payload.page <= 1;
    $('#comparison-history-next').disabled = payload.page >= payload.pages;
  } catch (error) {
    status.textContent = `Comparison history could not load: ${error.message}`;
    pagination.hidden = true;
  }
}

$('#comparison-history-form').addEventListener('submit', (event) => {
  event.preventDefault(); void loadComparisonHistory(1);
});
$('#comparison-history-prev').addEventListener('click', () => {
  if (comparisonHistoryPage > 1) void loadComparisonHistory(comparisonHistoryPage - 1);
});
$('#comparison-history-next').addEventListener('click', () => {
  if (latestComparisonHistory && comparisonHistoryPage < latestComparisonHistory.pages) void loadComparisonHistory(comparisonHistoryPage + 1);
});
$('#decision-back-history').addEventListener('click', () => showPage('history'));

loadDashboard();


// Manual exact-page investigations can run the verified offline Aviator comparison.
let manualInvestigationId = null;
$('#keyword-manual-run').addEventListener('click', async () => {
  const button = $('#keyword-manual-run');
  const result = $('#keyword-manual-result');
  if (!manualInvestigationId) return;
  button.disabled = true;
  result.textContent = 'Processing saved evidence locally; no API, browser, Lighthouse or LLM requests…';
  try {
    const response = await fetch(`/api/investigations/${encodeURIComponent(manualInvestigationId)}/run-offline`, {method:'POST'});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    result.textContent = `Offline comparison completed using historical evidence. No external or LLM requests. ${data.historical_pdf_warning || ""} `;
    if (data.pdf_path) {
      const link = document.createElement('a');
      link.href = `/api/investigations/${encodeURIComponent(manualInvestigationId)}/report.pdf`;
      link.textContent = 'Download historical executive PDF';
      result.appendChild(link);
    }
    await refreshReportingState(manualInvestigationId);
    await openDecision(manualInvestigationId, {navigate:true});
    void loadComparisonHistory(1);
  } catch (error) { result.textContent = `Offline comparison unavailable: ${error.message}`; }
});

$('#keyword-manual-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = $('#keyword-manual-save');
  const status = $('#keyword-manual-status');
  button.disabled = true;
  manualInvestigationId = null;
  $('#keyword-manual-run').disabled = true;
  $('#keyword-manual-result').textContent = '';
  $('#keyword-reporting-start').disabled = true;
  $('#keyword-reporting-approve').hidden = true;
  $('#keyword-reporting-files').hidden = true;
  $('#keyword-reporting-status').textContent = 'Complete a supported offline investigation first.';
  status.textContent = 'Checking saved evidence locally. No network collection requests will run…';
  try {
    const payload = {
      keyword: $('#keyword-manual-keyword').value,
      ours_url: $('#keyword-manual-first').value,
      benchmark_url: $('#keyword-manual-second').value,
    };
    const response = await fetch('/api/investigations/manual', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const saved = await response.json();
    if (!response.ok) throw new Error(saved.error || `HTTP ${response.status}`);
    const inventory = saved.offline_evidence_summary || {};
    manualInvestigationId = saved.investigation_id;
    $('#keyword-manual-run').disabled = !inventory.complete;
    const formatRank = (item) => item.rank == null ? 'not observed in saved SERP' : `#${item.rank}`;
    status.textContent = `Saved ${saved.investigation_id}. Page A: ${formatRank(saved.ours)}; page B: ${formatRank(saved.benchmark)}. Matching saved evidence: ${inventory.available ?? 0}/${inventory.total ?? 0} items. No API, browser or LLM requests made. Use Run offline comparison when the saved evidence is complete.`;
  } catch (error) {
    status.textContent = `Cannot save investigation: ${error.message}`;
  } finally {
    button.disabled = false;
  }
});

// Phase 1: real Google SERP keyword search. Results are never inferred from the
// pre-existing Aviator dashboard, and failed refreshes never display old data.
let activeKeywordJob = null;
let keywordPollTimer = null;
let keywordSelection = null;

function setKeywordBusy(busy) {
  $('#keyword-search-run').disabled = busy;
  $('#keyword-load-saved').disabled = busy;
  $('#keyword-input').disabled = busy;
  $('#keyword-depth').disabled = busy;
}

let currentSerpRenderId = 0;
let hollywoodbetsParentId = null;
let hollywoodbetsInvestigationId = null;
let selectedCompetitorUrl = null;
let displayedKeywordResults = null;
let fallbackIdempotencyKeys = new Map();

function renderKeywordResults(data, saved = false) {
  const renderId = ++currentSerpRenderId;
  const rows = data.organic_results || [];
  displayedKeywordResults = data;
  keywordSelection = null;
  selectedCompetitorUrl = null;
  hollywoodbetsParentId = null;
  hollywoodbetsInvestigationId = null;
  $('#keyword-results-panel').hidden = false;
  $('#keyword-results-heading').textContent = `Google results · ${data.keyword}`;
  $('#keyword-result-source').textContent = saved ? 'Saved snapshot · not live' : 'New Google collection';
  $('#keyword-results-meta').textContent = `${rows.length} observed organic results · ${data.status === 'partial' ? 'Partial collection' : 'Collection complete'} · ${formatDate(data.collected_at)} · ${data.location_note || 'Google search context not provided'}${data.stop_reason ? ` · Stop: ${data.stop_reason.replaceAll('_', ' ')}` : ''}`;
  const tracked = data.tracked_site || {};
  const trackedDomain = tracked.domain || 'Configured tracked site';
  const trackedLabel = tracked.status === 'found'
    ? `${trackedDomain} was observed at organic sequence #${tracked.rank}. ${tracked.results_above ?? 0} results above and ${tracked.results_below ?? 0} below. Ranking page: ${tracked.ranking_url || 'Unavailable'}.`
    : tracked.status === 'not_found' && trackedDomain.toLowerCase().endsWith('hollywoodbets.net')
      ? 'Hollywoodbets was not found in the returned organic search results for this keyword.'
      : `${trackedDomain} was not found in ${rows.length} collected organic results. This does not prove the site has no Google ranking.`;
  $('#keyword-tracked-site').textContent = `${trackedLabel} ${tracked.complete ? 'Minimum depth and two following results captured.' : 'Collection may be incomplete.'} Observed sequence positions are not independently verified absolute Google ranks.`;
  const diagnostic = data.diagnostics;
  const diagnosticPanel = $('#keyword-diagnostics');
  diagnosticPanel.hidden = !diagnostic || !data.serp_diagnostics_enabled;
  if (diagnostic && data.serp_diagnostics_enabled) {
    const flags = diagnostic.flags || [];
    diagnosticPanel.textContent = `Search diagnostics · Run ${diagnostic.run_id || 'unknown'} · ${diagnostic.pages_diagnosed ?? '—'} page(s) recorded · ${flags.length ? `Review required: ${flags.join(', ').replaceAll('_', ' ')}` : 'No automated warnings; screenshot/HTML verification still needed'}. Different SERPs across searches are allowed. Private per-page evidence is saved locally under data/diagnostics/google/; it is not exposed over the dashboard.`;
  }
  if (diagnostic && data.serp_diagnostics_enabled && data.previous_observation_comparison) {
    const c = data.previous_observation_comparison;
    diagnosticPanel.textContent += ` Previous search comparison: ${c.shared_exact_urls} shared URLs among the first ${c.comparison_limit} observed positions (previous ${c.previous_results_compared}, current ${c.current_results_compared}). ${c.configured_context_comparable ? (Object.keys(c.configured_context_changes || {}).length ? 'Configured context changes detected; inspect the saved run reports.' : 'No configured context differences detected.') : 'Previous browser context was not recorded.'} Differences are not automatically considered failures.`;
  }
  $('#hollywoodbets-selection').hidden = true;
  $('#hollywoodbets-investigation').hidden = true;
  $('#hollywoodbets-compare-status').textContent = '';
  if (!rows.length) {
    $('#keyword-results-table').innerHTML = '<div class="empty">No organic results were returned.</div>';
    return;
  }
  renderSerpRows(data, null);
  loadHollywoodbetsOptions(data, renderId).catch((error) => {
    if (renderId !== currentSerpRenderId) return;
    $('#hollywoodbets-selection').hidden = false;
    $('#hollywoodbets-selection-status').textContent = `Hollywoodbets selection is unavailable: ${error.message}`;
  });
}

function renderSerpRows(data, options) {
  const primary = new Set((options?.primary_options || []).map((item) => item.url));
  const competitor = new Set((options?.competitor_options || []).map((item) => item.url));
  $('#keyword-results-table').innerHTML = `<table><thead><tr><th>Organic rank</th><th>Domain</th><th>Page title</th><th>Exact ranking URL</th><th>Comparison selection</th></tr></thead><tbody>${(data.organic_results || []).map((row) => {
    const url = String(row.url || '');
    const safeUrl = /^https?:\/\//i.test(url) ? url : '';
    const rank = Number.isInteger(row.rank_group) && row.rank_group > 0 ? `#${row.rank_group}` : 'Position unavailable';
    const isPrimary = primary.has(url);
    const canSelect = competitor.has(url);
    const choose = canSelect ? `<label class="competitor-radio"><input type="radio" name="serp-competitor" value="${esc(url)}" ${selectedCompetitorUrl === url ? 'checked' : ''}><span>Select competitor</span></label>`
      : isPrimary ? '<span class="serp-role-badge">Hollywoodbets primary</span>' : '<span class="muted">—</span>';
    return `<tr class="${isPrimary ? 'hollywoodbets-result-row' : canSelect ? 'eligible-competitor-row' : ''}"><td class="rank">${esc(rank)}</td><td>${esc(row.domain)}</td><td>${esc(row.title)}</td><td class="keyword-url">${safeUrl ? `<a href="${esc(safeUrl)}" target="_blank" rel="noopener noreferrer">${esc(safeUrl)}</a>` : esc(url)}</td><td>${choose}</td></tr>`;
  }).join('')}</tbody></table>`;
  $('#keyword-results-table').onchange = (event) => {
    if (event.target?.name !== 'serp-competitor') return;
    selectedCompetitorUrl = event.target.value;
    updateHollywoodbetsSelection();
  };
}

async function loadHollywoodbetsOptions(result, renderId) {
  const response = await fetch(`/api/serp/hollywoodbets-options?keyword=${encodeURIComponent(result.keyword)}`, {cache:'no-store'});
  const options = await response.json();
  if (!response.ok) throw new Error(options.error || `SERP selection returned ${response.status}`);
  if (renderId !== currentSerpRenderId) return;
  if (options.keyword?.toLowerCase() !== result.keyword?.toLowerCase() ||
      options.search_context?.collected_at !== result.collected_at) {
    throw new Error('Saved result identity changed. Load the saved snapshot again before selecting pages.');
  }
  keywordSelection = options;
  $('#hollywoodbets-selection').hidden = false;
  if (options.status !== 'ready') {
    $('#hollywoodbets-selection-status').textContent = options.message || 'No competitor webpage from this saved SERP is eligible.';
    $('#hollywoodbets-primary-wrap').hidden = true;
    $('#hollywoodbets-selected-pages').hidden = true;
    $('#hollywoodbets-compare').disabled = true;
    renderSerpRows(result, options);
    return;
  }
  const primaryOptions = options.primary_options || [];
  const primarySelect = $('#hollywoodbets-primary-select');
  primarySelect.innerHTML = primaryOptions.map((item) => `<option value="${esc(item.url)}">#${esc(item.rank)} · ${esc(item.domain)} · ${esc(item.title || item.url)}</option>`).join('');
  primarySelect.value = options.default_primary_url;
  $('#hollywoodbets-primary-wrap').hidden = primaryOptions.length <= 1;
  $('#hollywoodbets-selection-status').textContent = primaryOptions.length > 1
    ? `Hollywoodbets appears ${primaryOptions.length} times. The highest-ranking observed result is selected by default; choose another if needed, then select a competitor from this same snapshot.`
    : `Hollywoodbets is selected at observed organic position #${primaryOptions[0]?.rank}. Choose one non-Hollywoodbets result below.`;
  renderSerpRows(result, options);
  updateHollywoodbetsSelection();
}

function addSelectionPage(container, label, item) {
  const card = document.createElement('div'); card.className = 'selected-page-card';
  const heading = document.createElement('strong'); heading.textContent = `${label} · #${item.rank} · ${item.domain}`;
  const title = document.createElement('span'); title.textContent = item.title || 'Untitled result';
  const link = document.createElement('a'); link.href = item.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = item.url;
  card.append(heading, title, link); container.appendChild(card);
}

function updateHollywoodbetsSelection() {
  const options = keywordSelection;
  if (!options || options.status !== 'ready') return;
  const primary = options.primary_options.find((item) => item.url === $('#hollywoodbets-primary-select').value) || options.primary_options[0];
  const competitor = options.competitor_options.find((item) => item.url === selectedCompetitorUrl);
  const cards = $('#hollywoodbets-selected-pages'); cards.replaceChildren();
  if (primary) addSelectionPage(cards, 'Hollywoodbets primary', primary);
  if (competitor) addSelectionPage(cards, 'Selected competitor', competitor);
  cards.hidden = !primary;
  $('#hollywoodbets-compare').disabled = !primary || !competitor;
  $('#hollywoodbets-selection-status').textContent = competitor
    ? 'Both pages are selected from this saved SERP. Compare is ready.'
    : 'Select a competitor result to enable Compare.';
}

function comparisonIdempotencyKey(selection) {
  const key = `hollywoodbets-compare:${JSON.stringify([selection.snapshot_sha256,
    $('#hollywoodbets-primary-select').value, selectedCompetitorUrl, hollywoodbetsParentId])}`;
  try {
    let token = localStorage.getItem(key);
    if (!token) {
      token = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}_${Math.random().toString(36).slice(2)}_${Math.random().toString(36).slice(2)}`;
      localStorage.setItem(key, token);
    }
    return token;
  } catch {
    if (!fallbackIdempotencyKeys.has(key)) fallbackIdempotencyKeys.set(key, `${Date.now()}_${Math.random().toString(36).slice(2)}_${Math.random().toString(36).slice(2)}`);
    return fallbackIdempotencyKeys.get(key);
  }
}

$('#hollywoodbets-primary-select').addEventListener('change', () => {
  selectedCompetitorUrl = null;
  if (displayedKeywordResults) renderSerpRows(displayedKeywordResults, keywordSelection);
  updateHollywoodbetsSelection();
});

$('#hollywoodbets-compare').addEventListener('click', async () => {
  const options = keywordSelection;
  if (!options || options.status !== 'ready' || !selectedCompetitorUrl) return;
  const primary = options.primary_options.find((item) => item.url === $('#hollywoodbets-primary-select').value) || options.primary_options[0];
  const button = $('#hollywoodbets-compare');
  button.disabled = true;
  $('#hollywoodbets-compare-status').textContent = 'Saving this exact-page selection and initializing its workflow. No collectors or models will run.';
  try {
    const response = await fetch('/api/investigations/hollywoodbets-compare', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({keyword:options.keyword, snapshot_sha256:options.snapshot_sha256,
        primary_url:primary.url, competitor_url:selectedCompetitorUrl,
        idempotency_key:comparisonIdempotencyKey(options),
        parent_investigation_id:hollywoodbetsParentId})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `Compare returned ${response.status}`);
    hollywoodbetsInvestigationId = data.investigation.investigation_id;
    const summary = data.collection_plan.summary || {};
    $('#hollywoodbets-investigation-id').textContent = `Investigation ${hollywoodbetsInvestigationId}`;
    $('#hollywoodbets-investigation-summary').textContent = `Saved SERP ${options.snapshot_sha256.slice(0, 12)}… · ${summary.available_or_reusable || 0}/${summary.required_items || 12} evidence items reusable · ${summary.missing_items || 0} missing · 0 requests started. The exact ranks and URLs are saved.`;
    $('#hollywoodbets-compare-status').textContent = data.idempotent_replay
      ? 'Resumed the previously created investigation for this selection.'
      : 'Comparison selection saved; no external collection, paid API or Gemma action was started.';
    $('#hollywoodbets-selection').hidden = true;
    $('#hollywoodbets-investigation').hidden = false;
    $('#hollywoodbets-workflow').replaceChildren();
    void openInvestigationWorkflow(hollywoodbetsInvestigationId, $('#hollywoodbets-workflow'));
  } catch (error) {
    $('#hollywoodbets-compare-status').textContent = `Comparison was not created: ${error.message}. Retry uses the same request key.`;
    button.disabled = false;
  }
});

$('#hollywoodbets-change-competitor').addEventListener('click', () => {
  if (hollywoodbetsInvestigationId) hollywoodbetsParentId = hollywoodbetsInvestigationId;
  hollywoodbetsInvestigationId = null;
  selectedCompetitorUrl = null;
  $('#hollywoodbets-investigation').hidden = true;
  $('#hollywoodbets-selection').hidden = false;
  $('#hollywoodbets-compare-status').textContent = 'Choose a different competitor from these saved results. The prior investigation will remain unchanged.';
  if (displayedKeywordResults && keywordSelection) renderSerpRows(displayedKeywordResults, keywordSelection);
  updateHollywoodbetsSelection();
});

async function fetchKeywordJob(jobId) {
  const response = await fetch(`/api/serp/jobs/${encodeURIComponent(jobId)}`, {cache:'no-store'});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Search status returned ${response.status}`);
  return data;
}

async function pollKeywordJob(jobId) {
  if (activeKeywordJob !== jobId) return;
  try {
    const job = await fetchKeywordJob(jobId);
    if (job.status === 'running') {
      $('#keyword-search-status').textContent = `Searching Google for “${job.keyword}” (minimum ${job.depth} results; up to 100 while locating the tracked site). Chrome may open and collection may take several minutes…`;
      keywordPollTimer = setTimeout(() => pollKeywordJob(jobId), 1500);
      return;
    }
    activeKeywordJob = null;
    setKeywordBusy(false);
    if (job.status === 'completed') {
      renderKeywordResults(job.result, false);
      $('#keyword-search-status').textContent = `Collected ${job.result.organic_results.length} actual Google organic results for “${job.keyword}”.`;
    } else {
      $('#keyword-search-status').textContent = `Search unsuccessful: ${job.error || 'No results collected.'} Previous saved evidence was not presented as a fresh result.`;
    }
  } catch (error) {
    activeKeywordJob = null;
    setKeywordBusy(false);
    $('#keyword-search-status').textContent = `Unable to check search status: ${error.message}`;
  }
}

$('#keyword-search-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const keyword = $('#keyword-input').value.trim();
  if (!keyword) return;
  if (keywordPollTimer) clearTimeout(keywordPollTimer);
  $('#keyword-results-panel').hidden = true;
  setKeywordBusy(true);
  $('#keyword-search-status').textContent = `Starting a fresh Google search for “${keyword}”…`;
  try {
    const response = await fetch('/api/serp/search', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({keyword, depth: Number($('#keyword-depth').value)}),
    });
    const job = await response.json();
    if (!response.ok) throw new Error(job.error || `Search returned ${response.status}`);
    activeKeywordJob = job.job_id;
    await pollKeywordJob(job.job_id);
  } catch (error) {
    setKeywordBusy(false);
    $('#keyword-search-status').textContent = `Could not start search: ${error.message}`;
  }
});

$('#keyword-load-saved').addEventListener('click', async () => {
  const keyword = $('#keyword-input').value.trim();
  if (!keyword) { $('#keyword-search-status').textContent = 'Enter a keyword before loading a saved snapshot.'; return; }
  $('#keyword-results-panel').hidden = true;
  $('#keyword-search-status').textContent = 'Looking for an existing saved Google observation…';
  try {
    const response = await fetch(`/api/serp/snapshot?keyword=${encodeURIComponent(keyword)}`, {cache:'no-store'});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `Saved lookup returned ${response.status}`);
    renderKeywordResults(result, true);
    $('#keyword-search-status').textContent = `Loaded saved results for “${result.keyword}”. These were not refreshed.`;
  } catch (error) {
    $('#keyword-search-status').textContent = `Saved results unavailable: ${error.message}`;
  }
});


// Reporting integration: opt-in Gemma requests, no collector or paid API calls.
let reportingPollTimer = null;
async function refreshReportingState(investigationId) {
  if (!investigationId || investigationId !== manualInvestigationId) return;
  const start = $('#keyword-reporting-start');
  const statusText = $('#keyword-reporting-status');
  const files = $('#keyword-reporting-files');
  const approve = $('#keyword-reporting-approve');
  const response = await fetch(`/api/investigations/${encodeURIComponent(investigationId)}/reporting`, {cache:'no-store'});
  const state = await response.json();
  if (investigationId !== manualInvestigationId) return;
  if (!response.ok) throw new Error(state.error || `Reporting status returned ${response.status}`);
  const active = ['preparing', 'running', 'repairing', 'generating'].includes(state.status);
  start.disabled = active || !state.available;
  start.textContent = state.status === 'draft_ready' || state.status === 'approved' ? 'Run a new Gemma analysis' : 'Run Gemma and generate draft reports';
  statusText.textContent = state.status === 'not_ready' ? `Not ready: ${state.message}`
    : state.status === 'draft_ready' ? `Draft ready · ${state.quality?.blocking ?? 0} blocking / ${state.quality?.review ?? 0} review flags. Review both documents before approving.`
    : state.status === 'approved' ? 'Reviewed and approved for internal use.'
    : active ? `Gemma reporting in progress: ${state.stage || state.status}. This may take several minutes.`
    : state.status === 'needs_review' ? `Needs review: ${state.message || 'Some recommendations could not be verified.'}`
    : state.status === 'failed' || state.status === 'interrupted' ? `Reporting ${state.status}: ${state.error || 'See server logs.'}`
    : state.message || 'Gemma reporting has not started.';
  files.hidden = !['draft_ready', 'approved'].includes(state.status);
  files.replaceChildren();
  if (!files.hidden) {
    for (const [kind, label] of [['pdf','Download draft management PDF'], ['appendix','Download technical appendix']]) {
      const link = document.createElement('a');
      link.href = `/api/investigations/${encodeURIComponent(investigationId)}/reporting/files/${kind}`;
      link.textContent = label;
      link.style.marginRight = '1.5rem';
      files.appendChild(link);
    }
  }
  approve.hidden = state.status !== 'draft_ready';
  approve.disabled = state.status !== 'draft_ready';
  if (reportingPollTimer) clearTimeout(reportingPollTimer);
  if (active) reportingPollTimer = setTimeout(() => refreshReportingState(investigationId).catch((e) => {
    statusText.textContent = `Reporting status unavailable: ${e.message}`;
  }), 2000);
}

$('#keyword-reporting-start').addEventListener('click', async () => {
  const id = manualInvestigationId;
  if (!id) return;
  if (!window.confirm('Run new requests to your configured local Gemma model using this investigation’s saved evidence? No paid SEO collectors will run.')) return;
  $('#keyword-reporting-start').disabled = true;
  $('#keyword-reporting-status').textContent = 'Starting Gemma reporting…';
  try {
    const response = await fetch(`/api/investigations/${encodeURIComponent(id)}/reporting`, {method:'POST'});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    await refreshReportingState(id);
  } catch (error) {
    $('#keyword-reporting-status').textContent = `Could not start Gemma reporting: ${error.message}`;
    await refreshReportingState(id).catch(() => {});
  }
});

$('#keyword-reporting-approve').addEventListener('click', async () => {
  const id = manualInvestigationId;
  if (!id || !window.confirm('Confirm you reviewed the management PDF and technical appendix and approve this draft for internal use?')) return;
  try {
    const response = await fetch(`/api/investigations/${encodeURIComponent(id)}/reporting/approve`, {method:'POST'});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    await refreshReportingState(id);
  } catch (error) {
    $('#keyword-reporting-status').textContent = `Approval failed: ${error.message}`;
  }
});


// Read-only investigation history. Do not substitute an old analysis for the
// current keyword/URL selection; every result retains its investigation ID.
async function openInvestigationWorkflow(investigationId, container) {
  container.replaceChildren();
  const status = document.createElement('p');
  status.className = 'muted';
  status.textContent = 'Loading saved workflow checkpoints…';
  container.appendChild(status);
  const request = async (suffix = '', method = 'GET', body = null) => {
    const response = await fetch(`/api/investigations/${encodeURIComponent(investigationId)}/workflow${suffix}`, {
      method, headers: body ? {'Content-Type':'application/json'} : {},
      body: body ? JSON.stringify(body) : undefined, cache:'no-store'
    });
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || `Workflow returned ${response.status}`);
    return value;
  };
  const loadCollectionPanel = async (state, panel, preferred = null) => {
    panel.replaceChildren();
    const heading = document.createElement('h4'); heading.textContent = 'Evidence collection'; panel.appendChild(heading);
    const status = document.createElement('p'); status.className = 'muted';
    status.textContent = 'Checking compatible saved evidence and request-cache entries…'; panel.appendChild(status);
    const refresh = document.createElement('input'); refresh.type = 'checkbox';
    refresh.checked = false;
    const refreshLabel = document.createElement('label'); refreshLabel.className = 'workflow-refresh-option';
    refreshLabel.append(refresh, document.createTextNode(' Create a fresh evidence version for selected collectors'));
    panel.appendChild(refreshLabel);
    const options = document.createElement('div'); panel.appendChild(options);
    const action = document.createElement('button'); action.type = 'button';
    action.textContent = 'Collect selected evidence'; panel.appendChild(action);
    const note = document.createElement('small'); note.className = 'muted';
    note.textContent = 'Playwright and Lighthouse make external public-site requests. DataForSEO is paid; exact USD cost is unknown until the API responds. The request count is shown before you confirm.';
    panel.appendChild(note);
    const loadPlan = async (defaults = true) => {
      const response = await fetch(`/api/investigations/${encodeURIComponent(investigationId)}/workflow/collection-plan?refresh=${refresh.checked ? '1' : '0'}`, {cache:'no-store'});
      const plan = await response.json();
      if (!response.ok) throw new Error(plan.error || `Collection plan returned ${response.status}`);
      options.replaceChildren();
      const categoryInfo = [
        ['dataforseo', 'DataForSEO (paid requests)'],
        ['playwright', 'Playwright page capture'],
        ['lighthouse', 'Lighthouse mobile audit']
      ];
      const selections = {};
      for (const [category, label] of categoryInfo) {
        const rows = plan.items.filter(item => item.collector === category);
        const pending = rows.filter(item => ['missing','refresh_required'].includes(item.status)).length;
        const cacheHits = rows.filter(item => item.status === 'cached').length;
        const available = rows.filter(item => item.status === 'available').length;
        const box = document.createElement('input'); box.type = 'checkbox';
        box.checked = preferred ? preferred.includes(category) : (pending > 0 || cacheHits > 0);
        selections[category] = box;
        const line = document.createElement('label'); line.className = 'workflow-collector-option';
        line.append(box, document.createTextNode(` ${label} — ${pending} to collect/refresh, ${cacheHits} exact request-cache hit(s), ${available} reusable`));
        options.appendChild(line);
      }
      status.textContent = `${plan.summary.available_or_reusable} reusable evidence items; ${plan.summary.request_cache_hits} request-cache hit(s); ${plan.summary.missing_items} items need collection or refresh.`;
      action.disabled = !Object.values(selections).some(box => box.checked);
      action.onclick = async () => {
        const collectors = Object.entries(selections).filter(([, box]) => box.checked).map(([name]) => name);
        if (!collectors.length) return;
        const chosen = plan.items.filter(item => collectors.includes(item.collector) && ['missing','refresh_required'].includes(item.status));
        const paidCount = chosen.filter(item => item.collector === 'dataforseo' && item.external_requests_if_run > 0).length;
        const pageCount = chosen.filter(item => item.collector === 'playwright').length;
        const lighthouseCount = chosen.filter(item => item.collector === 'lighthouse').length;
        const prompt = `Run these selected collectors?\n\nDataForSEO paid POST requests: ${paidCount}\nPlaywright page captures: ${pageCount} (each can load additional page resources)\nLighthouse runs: ${lighthouseCount} (npx may contact npm and the public page)\n\nDataForSEO USD cost is not available before the response. Existing compatible evidence and successful request-cache responses will be reused. A fresh run saves a new version.`;
        if (!window.confirm(prompt)) return;
        action.disabled = true; status.textContent = 'Collecting explicitly selected evidence…';
        try {
          const response = await fetch(`/api/investigations/${encodeURIComponent(investigationId)}/workflow/collection/execute`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body:JSON.stringify({collectors, refresh:refresh.checked,
              authorize_paid_dataforseo:paidCount > 0,
              authorize_external_page_requests:(pageCount + lighthouseCount) > 0})
          });
          const result = await response.json();
          if (!response.ok) throw new Error(result.error || `Collection returned ${response.status}`);
          const stats = result.collection?.statistics || {};
          status.textContent = `Collection ${result.collection?.status || 'finished'} · saved evidence reused: ${stats.evidence_reuse_hits || 0} · DataForSEO cache hits: ${stats.request_cache_hits || 0} · DataForSEO requests: ${stats.paid_requests_made || 0} · Playwright captures: ${stats.playwright_top_level_captures || 0} · Lighthouse runs: ${stats.lighthouse_runs || 0}.`;
          render(result.workflow);
        } catch (error) {
          status.textContent = `Collection did not complete: ${error.message}`;
          action.disabled = false;
        }
      };
    };
    refresh.addEventListener('change', async () => {
      try { await loadPlan(true); } catch (error) { status.textContent = `Collection plan failed: ${error.message}`; }
    });
    try { await loadPlan(true); }
    catch (error) { status.textContent = `Collection plan failed: ${error.message}`; action.disabled = true; }
  };
  const render = (state) => {
    container.replaceChildren();
    const title = document.createElement('h4');
    title.textContent = `Workflow · ${state.keyword} · current: ${state.stages[state.current_stage]?.label || state.current_stage}`;
    container.appendChild(title);
    const list = document.createElement('ol');
    list.className = 'workflow-stage-list';
    for (const [id, stage] of Object.entries(state.stages)) {
      const item = document.createElement('li');
      item.textContent = `${stage.label} — ${stage.status}`;
      list.appendChild(item);
    }
    container.appendChild(list);
    const controls = document.createElement('div');
    controls.className = 'workflow-controls';
    const previous = document.createElement('button');
    previous.type = 'button'; previous.textContent = 'Previous stage';
    previous.disabled = state.current_stage === Object.keys(state.stages)[0];
    previous.addEventListener('click', async () => act(() => request('/navigate', 'POST', {direction:'previous'})));
    const next = document.createElement('button');
    next.type = 'button'; next.textContent = 'Next stage';
    next.disabled = state.stages[state.current_stage]?.status !== 'completed' || Object.keys(state.stages).indexOf(state.current_stage) >= Object.keys(state.stages).length - 1;
    next.addEventListener('click', async () => act(() => request('/navigate', 'POST', {direction:'next'})));
    const run = document.createElement('button');
    run.type = 'button'; run.textContent = `Run current stage: ${state.stages[state.current_stage]?.label || state.current_stage}`;
    run.addEventListener('click', async () => act(() => request('/execute', 'POST', {stage:state.current_stage})));
    controls.append(previous, next, run);
    container.appendChild(controls);
    const note = document.createElement('small');
    note.className = 'muted';
    note.textContent = 'Opening and navigating reads saved state only. “Run current stage” reuses saved evidence and exact request-cache hits. New external or paid collection requires the separate collector selection and confirmation below. Later analysis and report stages remain bundled.';
    container.appendChild(note);
    if (state.current_stage === 'evidence_collection') {
      const collectionPanel = document.createElement('div'); collectionPanel.className = 'workflow-collection-panel';
      container.appendChild(collectionPanel);
      void loadCollectionPanel(state, collectionPanel);
    }
    if (state.stages.validation_classification?.status === 'completed' && !workflowDecisionOpened.has(investigationId)) {
      workflowDecisionOpened.add(investigationId);
      void openDecision(investigationId, {navigate:true});
      void loadComparisonHistory(1);
    }
  };
  const act = async (call) => {
    status.textContent = 'Saving workflow checkpoint…';
    try { render(await call()); }
    catch (error) { status.textContent = `Workflow action failed: ${error.message}`; }
  };
  try { render(await request()); }
  catch (error) { status.textContent = `Workflow could not be opened: ${error.message}`; }
}

$('#investigation-history-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = $('#history-search-run');
  const status = $('#history-search-status');
  const results = $('#history-search-results');
  button.disabled = true;
  status.textContent = 'Searching saved investigation history…';
  results.replaceChildren();
  try {
    const params = new URLSearchParams();
    const keyword = $('#history-keyword').value.trim();
    const url = $('#history-url-a').value.trim();
    if (keyword) params.set('keyword', keyword);
    if (url) params.set('url_a', url);
    const response = await fetch(`/api/investigations/history?${params}`, {cache:'no-store'});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `History returned ${response.status}`);
    const rows = payload.investigations || [];
    status.textContent = `${rows.length} saved investigation(s) found. Results are historical, not live.`;
    if (!rows.length) { results.textContent = 'No matching saved analysis was found.'; return; }
    for (const row of rows) {
      const card = document.createElement('article');
      card.className = 'finding';
      const heading = document.createElement('strong');
      heading.textContent = `${row.keyword || 'Unknown keyword'} · ${row.created_at || 'Date unavailable'}`;
      card.appendChild(heading);
      const info = document.createElement('p');
      info.textContent = `${row.page_a_url || 'Page A unavailable'} vs ${row.page_b_url || 'Page B unavailable'} · Offline: ${row.offline_status} · Reporting: ${row.reporting_status}`;
      card.appendChild(info);
      const details = document.createElement('small');
      details.textContent = `Investigation ID: ${row.investigation_id}`;
      card.appendChild(details);
      const workflowButton = document.createElement('button');
      workflowButton.type = 'button'; workflowButton.textContent = 'Open workflow';
      workflowButton.style.marginLeft = '1rem';
      const workflowPanel = document.createElement('div');
      workflowPanel.className = 'workflow-panel';
      workflowButton.addEventListener('click', () => openInvestigationWorkflow(row.investigation_id, workflowPanel));
      card.append(workflowButton, workflowPanel);
      if (row.offline_status === 'completed') {
        const offline = document.createElement('a');
        offline.href = `/api/investigations/${encodeURIComponent(row.investigation_id)}/offline-result`;
        offline.textContent = 'View saved offline comparison';
        offline.style.marginLeft = '1rem';
        card.appendChild(offline);
      }
      for (const [kind, title] of [['pdf','Management PDF'], ['appendix','Technical appendix']]) {
        if (!row[kind === 'pdf' ? 'has_pdf' : 'has_appendix']) continue;
        const link = document.createElement('a');
        link.href = `/api/investigations/${encodeURIComponent(row.investigation_id)}/reporting/files/${kind}`;
        link.textContent = title;
        link.style.marginLeft = '1rem';
        card.appendChild(link);
      }
      results.appendChild(card);
    }
  } catch (error) {
    status.textContent = `History lookup failed: ${error.message}`;
  } finally {
    button.disabled = false;
  }
});
