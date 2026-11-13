let activityOffset = 0;
let activityRequest = 0;
let activityPages = [];

function renderActivityEvent(event) {
  const evidenceLink = (id, label) => id ? `<a href="/api/monitoring/artifacts/${encodeURIComponent(id)}/screenshot" target="_blank" rel="noreferrer">${label}</a>` : '';
  return `<article class="change-card"><div class="change-heading"><strong>${esc(event.title)}</strong><small>${esc(formatDate(event.occurred_at))}</small></div><small>${esc(event.domain)} · ${esc(event.page_url)}</small><p>${esc(event.summary)}</p><button type="button" class="review-page" data-page-id="${esc(event.page_id)}">Review this page</button><details><summary>View supporting evidence</summary><p>${evidenceLink(event.previous_snapshot_id, 'Before screenshot')} ${evidenceLink(event.snapshot_id, 'Observed screenshot')}</p>${!event.snapshot_id ? '<p>An original screenshot reference is unavailable for this historical event.</p>' : ''}${event.previous_value != null || event.current_value != null ? `<div class="change-values"><div><b>Before</b><pre>${esc(displayValue(event.previous_value))}</pre></div><div><b>After</b><pre>${esc(displayValue(event.current_value))}</pre></div></div>` : ''}</details></article>`;
}

function setOptions(selector, values, allLabel) {
  const select = $(selector), previous = select.value;
  select.innerHTML = `<option value="">${allLabel}</option>` + values.map(([value, label]) => `<option value="${esc(value)}">${esc(label)}</option>`).join('');
  select.value = values.some(([value]) => value === previous) ? previous : '';
}

function activityPageOptions() {
  const domain = $('#activity-domain').value;
  setOptions('#activity-page', activityPages.filter((p) => !domain || p.domain === domain).map((p) => [p.id, p.url]), 'All pages');
}

async function loadActivity(append = false) {
  const request = ++activityRequest;
  if (!append) activityOffset = 0;
  const parameters = new URLSearchParams({offset: activityOffset, limit: 40});
  for (const [key, id] of [['domain','domain'],['page_id','page'],['kind','kind'],['category','category'],['since','since'],['until','until'],['q','query']]) {
    const value = $(`#activity-${id}`).value;
    if (value) parameters.set(key, value);
  }
  if ($('#activity-since').value && $('#activity-until').value && $('#activity-since').value > $('#activity-until').value) {
    $('#activity-count').textContent = 'Choose an end date on or after the start date.';
    return;
  }
  $('#activity-count').textContent = 'Loading saved activity…';
  $('#activity-more').disabled = true;
  try {
    const response = await fetch(`/api/monitoring/activity?${parameters}`, {cache:'no-store'});
    if (!response.ok) throw new Error(`Activity service returned ${response.status}`);
    const data = await response.json();
    if (request !== activityRequest) return;
    activityPages = data.pages || [];
    setOptions('#activity-domain', [...new Set(activityPages.map((p) => p.domain))].sort().map((d) => [d,d]), 'All competitors');
    activityPageOptions();
    setOptions('#activity-category', Object.entries(data.categories || {}), 'All categories');
    const html = data.events.map(renderActivityEvent).join('');
    if (append) $('#activity-events').insertAdjacentHTML('beforeend', html);
    else $('#activity-events').innerHTML = html || '<div class="empty">No recorded events match these filters.</div>';
    activityOffset += data.events.length;
    $('#activity-count').textContent = `${activityOffset} of ${data.total} events · registered pages only · dates use South Africa time`;
    $('#activity-more').hidden = !data.has_more;
  } catch (error) {
    if (request === activityRequest) $('#activity-count').textContent = `Activity could not load: ${error.message}`;
  } finally {
    if (request === activityRequest) $('#activity-more').disabled = false;
  }
}

async function loadPageTimeline(pageId) {
  $('#monitor-timeline').textContent = 'Loading recorded activity…';
  try {
    const response = await fetch(`/api/monitoring/activity?page_id=${encodeURIComponent(pageId)}&limit=20`, {cache:'no-store'});
    if (!response.ok) throw new Error('Activity could not load');
    const data = await response.json();
    if (selectedPageId !== pageId) return;
    $('#monitor-timeline').innerHTML = data.events.map(renderActivityEvent).join('') || '<div class="empty">No recorded activity yet.</div>';
    if (data.has_more) $('#monitor-timeline').insertAdjacentHTML('beforeend', '<p>Showing the latest 20 events. Open Competitor activity to browse the complete history.</p>');
  } catch (error) {
    if (selectedPageId === pageId) $('#monitor-timeline').textContent = error.message;
  }
}

$('#promotion-categories').addEventListener('click', (event) => {
  const button = event.target.closest('[data-category]');
  if (!button || !currentMonitoringDetail) return;
  selectedPromotionCategory = button.dataset.category;
  renderPromotions(currentMonitoringDetail);
});
$('#promotion-verification').addEventListener('change', () => {
  if (currentMonitoringDetail) renderPromotions(currentMonitoringDetail);
});
$('#promotions-list').addEventListener('submit', async (event) => {
  const form=event.target.closest('.category-editor');
  if (!form) return;
  event.preventDefault();
  const button=form.querySelector('button');
  button.disabled=true;
  try {
    const response=await fetch('/api/monitoring/promotions/categories',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({promotion_id:form.dataset.promotion,categories:[...form.querySelectorAll('input:checked')].map((box)=>box.value)})});
    const data=await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not save categories');
    await loadMonitoring();
  } catch (error) { $('#promotions-meta').textContent=error.message; button.disabled=false; }
});
$('#activity-domain').addEventListener('change', () => { activityPageOptions(); loadActivity(); });
for (const id of ['page','kind','category','since','until']) $(`#activity-${id}`).addEventListener('change', () => loadActivity());
$('#activity-query').addEventListener('search', () => loadActivity());
$('#activity-query').addEventListener('keydown', (event) => { if (event.key === 'Enter') loadActivity(); });
$('#activity-refresh').addEventListener('click', () => loadActivity());
$('#activity-more').addEventListener('click', () => loadActivity(true));
document.addEventListener('click', async (event) => {
  const button = event.target.closest('.review-page');
  if (!button) return;
  selectedPageId = button.dataset.pageId;
  showPage('monitoring');
  await loadMonitoring();
});
$('#monitor-settings').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!selectedPageId) return;
  const pageId = selectedPageId;
  const button = event.currentTarget.querySelector('button');
  button.disabled = true;
  try {
    const response = await fetch('/api/monitoring/settings', {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({page_id:pageId, active:$('#schedule-enabled').checked, frequency_hours:Number($('#schedule-hours').value)})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not save the schedule');
    $('#schedule-message').textContent = 'Schedule saved. Recurring checks run while the separate monitoring scheduler is running.';
    await loadMonitoring();
  } catch (error) { $('#schedule-message').textContent = error.message; }
  finally { button.disabled = false; }
});
loadActivity();
