(() => {
  const tierNames = {
    tier_1_strong_evidence: 'Tier 1 — Strong Evidence',
    tier_2_moderate_evidence: 'Tier 2 — Moderate Evidence',
  };
  const escapeHtml = (value) => String(value ?? 'Not recorded').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;',
  })[char]);
  const tiers = Object.keys(tierNames);

  window.renderRecommendations = (actions = []) => {
    const rows = Array.isArray(actions) ? actions.filter((item) => item && typeof item === 'object') : [];
    const validated = rows.filter((item) => tiers.includes(item.evidence_tier));
    const unclassified = rows.some((item) => !tiers.includes(item.evidence_tier));
    const byPriority = (a, b) => {
      const scoreA = Number.isFinite(Number(a.priority_score)) ? Number(a.priority_score) : -Infinity;
      const scoreB = Number.isFinite(Number(b.priority_score)) ? Number(b.priority_score) : -Infinity;
      return scoreB - scoreA || String(a.title || '').localeCompare(String(b.title || ''));
    };
    const card = (item, index) => {
      const difference = item.evidence ?? item.difference_observed ?? item.simple_explanation ?? item.observation;
      const impact = item.potential_impact_text ?? item.expected_benefit ?? item.benefit ?? item.interpretation ?? item.rationale;
      const steps = item.actions ?? item.implementation_steps ?? item.implementation_details ?? [];
      const action = item.display_action || (Array.isArray(steps) ? steps.join(' ') : String(steps || item.recommended_action || ''));
      return `<details class="recommendation-card" ${index === 0 ? 'open' : ''}><summary><span class="recommendation-title">${escapeHtml(item.title || 'SEO improvement')}</span><span class="tier-badge ${escapeHtml(item.evidence_tier)}">${escapeHtml(tierNames[item.evidence_tier])}</span></summary><div class="recommendation-copy"><section><h4>Difference Observed</h4><p>${escapeHtml(difference || 'Difference details are not available in this saved record.')}</p></section><section><h4>Potential Impact</h4><p>${escapeHtml(impact || 'Potential benefit is uncertain; no ranking outcome is guaranteed.')}</p></section><section class="recommendation-action"><h4>Recommended Action</h4><p>${escapeHtml(action || 'A specific implementation action was not recorded in this saved recommendation.')}</p></section></div></details>`;
    };
    const content = tiers.map((tier) => {
      const group = validated.filter((item) => item.evidence_tier === tier).sort(byPriority);
      return `<section class="recommendation-tier"><h4>${escapeHtml(tierNames[tier])}<span>${group.length}</span></h4>${group.length ? group.map(card).join('') : '<p class="tier-empty">No recommendations in this tier for this saved investigation.</p>'}</section>`;
    }).join('');
    return content + (unclassified ? '<p class="tier-empty">Some older saved recommendations have no validated evidence tier. Refresh their analysis from saved evidence to include them here.</p>' : '');
  };
})();
