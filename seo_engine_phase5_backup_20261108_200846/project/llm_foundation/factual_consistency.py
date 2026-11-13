"""Conservative executive factual guardrails; ambiguous claims require human review."""
from __future__ import annotations
import re

METRICS = {
    'lcp': ('largest_contentful_paint_ms', 'lower'),
    'tbt': ('total_blocking_time_ms', 'lower'),
    'performance score': ('performance', 'higher'),
    'seo score': ('seo', 'higher'),
}

def _facts(packet):
    return {f.get('id'): f.get('values') for f in packet.get('facts', []) if isinstance(f, dict)}

def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)

def _technical(packet):
    data = _facts(packet).get('TECH_LAB') or {}
    result = {}
    for side in ('ours', 'benchmark'):
        side_data = data.get(side) or {}
        result[side] = {}
        for label, (key, _) in METRICS.items():
            field = 'scores' if 'score' in label else 'lab_metrics'
            value = (side_data.get(field) or {}).get(key)
            # Lighthouse score values are sometimes wrapped in a score dict.
            if isinstance(value, dict):
                value = value.get('score', value.get('value'))
            result[side][label] = value if _number(value) else None
    return result

def _sentences(text):
    return re.split(r'(?<=[.!?])\s+|;\s*', text or '')

def _mentions(text, phrase):
    return bool(re.search(r'\b' + re.escape(phrase) + r'\b', text, re.I))

def _direction_error(sentence, metric, values, tracked_names, benchmark_names):
    """Reject clear reversals, not ambiguous wording; avoid unsupported auto-correction."""
    s = sentence.lower()
    a, b = values['ours'].get(metric), values['benchmark'].get(metric)
    if not (_number(a) and _number(b)) or a == b:
        return False
    _, preferred = METRICS[metric]
    # Bind direction words to their nearest metric, avoiding cross-metric bleed.
    tokens = re.findall(r"[a-z]+", s)
    if metric == 'performance score':
        labels = [('performance', 'score')]
    elif metric == 'seo score':
        labels = [('seo', 'score')]
    else:
        labels = [(metric,)]
    claims = []
    direction_words = ('higher','lower','greater','less','slower','faster','worse','better','longer','shorter')
    for j in range(len(tokens)):
        for label in labels:
            if tuple(tokens[j:j+len(label)]) != label:
                continue
            before = tokens[max(0,j-3):j]
            after = tokens[j+len(label):j+len(label)+3]
            preceding = [w for w in before if w in direction_words]
            following = [w for w in after if w in direction_words]
            if preceding:
                claims.append(preceding[-1])
            elif following:
                claims.append(following[0])
    # Only compare when the tracked/ours and benchmark are both in the same sentence
    # or when the sentence explicitly says 'than the benchmark'.
    if not (re.search(tracked_names, s, re.I) and re.search(benchmark_names, s, re.I)):
        return False
    for claim in claims:
        expected = (a > b) if claim in ('higher','greater','longer','slower') else (a < b)
        if claim in ('worse','better'):
            is_better = (a < b) if preferred == 'lower' else (a > b)
            expected = (not is_better) if claim == 'worse' else is_better
        # Wording assumes tracked site is subject; exclude benchmark-first sentences.
        subject = re.search(tracked_names + '|' + benchmark_names, s, re.I)
        if subject and re.fullmatch(benchmark_names, subject.group(), re.I):
            continue
        if not expected:
            return True
    return False

def check_factual_consistency(result, packet):
    errors = []
    technical = _technical(packet)
    tracked = packet.get('tracked') or {}
    benchmark = packet.get('benchmark') or {}
    def aliases(side, defaults):
        domain = str((packet.get(side) or {}).get('domain') or '').removeprefix('www.')
        label = domain.split('.')[0] if domain else ''
        names = defaults + ([label] if label else [])
        return r'\b(?:' + '|'.join(re.escape(name) for name in names) + r')\b'
    tracked_names = aliases('tracked', ['tracked', 'ours'])
    benchmark_names = aliases('benchmark', ['benchmark', 'competitor'])
    texts = [('executive_summary', result.get('executive_summary', ''))]
    for i, finding in enumerate(result.get('key_findings', [])):
        if isinstance(finding, dict):
            texts.append((f'key_findings[{i}].statement', finding.get('statement', '')))
    for i, decision in enumerate(result.get('proposed_decisions', [])):
        if not isinstance(decision, dict):
            continue
        texts.append((f'proposed_decisions[{i}].action', decision.get('action', '')))
        success = decision.get('success_check', '') or ''
        action = decision.get('action', '') or ''
        if re.search(r'\b(title|meta description)\b', action + ' ' + decision.get('title', ''), re.I):
            if re.search(r'\b(update|change|revision)\s+(?:has been\s+)?implemented\b', success, re.I) and not re.search(r'\b(if approved|if a revision is approved|after approval|subject to approval)\b', success, re.I):
                errors.append(f'proposed_decisions[{i}].success_check: presumes unapproved metadata edit')
    for location, text in texts:
        if not isinstance(text, str):
            continue
        for sentence in _sentences(text):
            # Reject categorical SEO ranking causation, but not explicit disclaimers.
            if re.search(r'\b(caused|causes|guarantees|proves)\b.{0,55}\b(ranking|rankings|rank higher)\b', sentence, re.I) and not re.search(r'\b(not|cannot|does not|unverified)\b', sentence, re.I):
                errors.append(f'{location}: unsupported ranking causation')
            for metric in METRICS:
                if _direction_error(sentence, metric, technical, tracked_names, benchmark_names):
                    errors.append(f'{location}: metric direction conflicts with TECH_LAB ({metric})')
    # DataForSEO backlink rank is an index where the larger value is the stronger rank metric.
    fact_values = _facts(packet)
    for scope in ('BL_PAGE', 'BL_DOMAIN'):
        values = fact_values.get(scope) or {}
        ours = (values.get('ours') or {}).get('rank')
        other = (values.get('benchmark') or {}).get('rank')
        if not (_number(ours) and _number(other)) or ours == other:
            continue
        ours_stronger = ours > other
        for location, text in texts:
            for sentence in _sentences(text):
                if not re.search(r'\b(backlink\s+)?rank\b', sentence, re.I):
                    continue
                first = re.search(r'(?<![A-Za-z])' + re.escape(str(ours)) + r'(?!\d)', sentence)
                second = re.search(r'(?<![A-Za-z])' + re.escape(str(other)) + r'(?!\d)', sentence[first.end():]) if first else None
                if not (first and second):
                    continue
                second_start = first.end() + second.start()
                nearby = sentence[max(0, first.start()-70):second_start+second.end()]
                directions = list(re.finditer(r'\b(higher|lower|stronger|weaker|better|worse)\b', nearby, re.I))
                if not directions:
                    continue
                direction = directions[-1].group(1).lower()
                claims_higher = direction in ('higher','stronger','better')
                if claims_higher != ours_stronger:
                    errors.append(f'{location}: {scope} backlink-rank comparison conflicts with evidence (higher DataForSEO value is stronger)')
        # Numeric claims need semantic review beyond these checks.
    return list(dict.fromkeys(errors))
