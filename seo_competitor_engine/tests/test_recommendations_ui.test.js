const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('frontend/js/recommendations.js', 'utf8');
const context = { window: {} };
vm.runInNewContext(source, context);

const sample = [
  {title: 'Moderate', evidence_tier: 'tier_2_moderate_evidence', priority_score: 9, evidence: 'observed c', interpretation: 'qualified c', actions: ['Action c']},
  {title: 'Strong lower', evidence_tier: 'tier_1_strong_evidence', priority_score: 5, evidence: 'observed b', interpretation: 'qualified b', actions: ['Action b']},
  {title: 'Strong first', evidence_tier: 'tier_1_strong_evidence', priority_score: 3, evidence: 'observed a', interpretation: 'qualified a', actions: ['Action a']},
  {title: 'Strong higher', evidence_tier: 'tier_1_strong_evidence', priority_score: 12, evidence: 'observed b2', interpretation: 'qualified b2', actions: ['Action b2']},
];

test('renders exactly two tier groups with cards ordered by evidence then score', () => {
  const html = context.window.renderRecommendations(sample);
  const positions = ['Tier 1 — Strong Evidence', 'Tier 2 — Moderate Evidence'].map((text) => html.indexOf(text));
  assert.ok(positions[0] >= 0 && positions[0] < positions[1]);
  assert.ok(html.indexOf('Strong higher') < html.indexOf('Strong lower'));
  assert.equal((html.match(/class="recommendation-tier"/g) || []).length, 2);
  for (const heading of ['Difference Observed', 'Potential Impact', 'Recommended Action']) assert.ok(html.includes(heading));
});

test('does not promote unclassified legacy records and escapes their visible content', () => {
  const html = context.window.renderRecommendations([
    {title: '<img src=x>', evidence_tier: 'legacy', evidence: '<script>bad</script>'},
  ]);
  assert.ok(!html.includes('<img'));
  assert.ok(!html.includes('<script>'));
  assert.ok(html.includes('no validated evidence tier'));
});

test('accepts an empty saved recommendation list and displays only two tiers', () => {
  const html = context.window.renderRecommendations([]);
  assert.equal((html.match(/class="recommendation-tier"/g) || []).length, 2);
});

test('uses concise validated display action while full technical detail stays in the appendix data', () => {
  const html = context.window.renderRecommendations([{
    title: 'Improve image delivery', evidence_tier: 'tier_1_strong_evidence',
    priority_score: 12, evidence: 'Lighthouse identified an image candidate.',
    interpretation: 'Smaller responsive assets may improve load experience.',
    display_action: 'Optimise the verified image dimensions and retest the page.',
    actions: ['Inspect https://example.test/very-long/raw/resource/image.webp and change only if oversized.'],
  }]);
  assert.ok(html.includes('Optimise the verified image dimensions'));
  assert.ok(!html.includes('very-long/raw/resource'));
});

test('renders a grounded proposed title in the visible Recommended Action', () => {
  const candidate = 'Residential Solar Inverter: How to Choose | Sun Example';
  const html = context.window.renderRecommendations([{
    title: 'Improve HTML title', evidence_tier: 'tier_1_strong_evidence',
    priority_score: 10, evidence: 'The captured HTML title omits the selected topic.',
    interpretation: 'A descriptive title may better communicate page topic.',
    display_action: `Replace the captured title with proposed copy (not observed): "${candidate}". Verify the rendered result.`,
    proposed_copy: {field: 'title', candidate, status: 'proposed_not_observed'},
  }]);
  assert.ok(html.includes(candidate));
  assert.ok(html.includes('Recommended Action'));
});
