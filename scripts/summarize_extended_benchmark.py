"""Recompute the 60-slot first pass and retry replacement; no model requests."""
from collections import defaultdict
import json
import math
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]


def aggregate(rows, cases, pairs, scope):
    planned_ordinary = sum(sum(cases[r['case_id']]['counts'].values()) for r in rows)
    planned_programming = sum(cases[r['case_id']]['programming_count'] for r in rows)
    ordinary = sum(r['ordinary_count'] for r in rows)
    programming = sum(r['programming_count'] for r in rows)
    complete = sum(r['complete'] for r in rows)
    unassisted = sum(r['unassisted_within_deadline'] for r in rows)
    times = sorted(r['export_elapsed_seconds'] for r in rows if r['unassisted_within_deadline'])
    ids = {r['run_id'] for r in rows}
    repeat = {}
    for kind in ('ordinary', 'programming'):
        grouped = defaultdict(list)
        for p in pairs:
            if p['scope'] == scope and p['kind'] == kind and {p['left'], p['right']} <= ids:
                grouped[p['case_id']].append(p['matched'] / p['denominator'])
        repeat[kind] = {
            'macro_request_repeat_rate': statistics.mean(statistics.mean(v) for v in grouped.values()) if grouped else None,
            'comparable_pairs': sum(len(v) for v in grouped.values()), 'requests_with_pairs': len(grouped),
        }
    return {
        'planned_runs': len(rows), 'finished_runs': len(rows), 'pending_runs': 0, 'is_final': True,
        'complete_assignments': complete, 'unassisted_within_deadline': unassisted,
        'completion_rate_final': complete / len(rows), 'observed_completion_rate': complete / len(rows),
        'unassisted_rate_final': unassisted / len(rows),
        'planned_ordinary_questions': planned_ordinary, 'planned_programming_questions': planned_programming,
        'planned_questions': planned_ordinary + planned_programming,
        'ordinary_questions': ordinary, 'programming_questions': programming,
        'question_completion_rate_final': (ordinary + programming) / (planned_ordinary + planned_programming),
        'missing_questions_in_finished_runs': {'ordinary': planned_ordinary - ordinary, 'programming': planned_programming - programming},
        'latency_sample_n': len(times), 'latency_p50_seconds': statistics.median(times) if times else None,
        'latency_p90_seconds': times[math.ceil(.9 * len(times)) - 1] if times else None,
        'logical_model_calls': sum(r['logical_model_calls'] for r in rows),
        'reported_tokens': sum(r['usage']['reported_tokens'] for r in rows),
        'spans_missing_usage': sum(r['usage']['spans_missing_usage'] for r in rows),
        'spans_with_reported_usage': sum(r['usage']['spans_with_reported_usage'] for r in rows),
        'public_cases': sum(r['case_counts'].get('public', 0) for r in rows),
        'hidden_cases': sum(r['case_counts'].get('hidden', 0) for r in rows),
        'unspecified_cases': sum(r['case_counts'].get('unspecified', 0) for r in rows),
        'finite_oracle_comparisons': {k: sum(r['finite_oracle_comparisons'][k] for r in rows)
                                     for k in ('passed', 'unassessed', 'flagged')},
        'repeat': repeat, 'independent_teacher_score': None, 'actual_http_requests': None, 'actual_api_cost': None,
    }


def summarize(folder=ROOT / 'evaluations/extended-benchmark'):
    folder = Path(folder)
    def load(name):
        return json.loads((folder / name).read_text(encoding='utf-8'))
    cases_list, initial, retries = load('cases.json'), load('runs.json'), load('retries.json')
    expected, pairs, protocol = load('summary.json'), load('repeat-pairs.json'), load('protocol.json')
    errors = []
    def require(condition, label):
        if not condition:
            errors.append(label)
    def compare(actual, saved, label):
        if isinstance(actual, dict) and isinstance(saved, dict):
            require(actual.keys() == saved.keys(), label + ': keys')
            for key in actual.keys() & saved.keys():
                compare(actual[key], saved[key], label + '.' + key)
        elif type(actual) is float and type(saved) in (int, float):
            require(math.isclose(actual, saved, rel_tol=1e-10, abs_tol=1e-10), label)
        else:
            require(type(actual) is type(saved) and actual == saved, label)
    cases = {c['id']: c for c in cases_list}
    require(len(cases) == len(cases_list) == 20 and len(initial) == 60 and len(retries) == 7, 'cohort sizes')
    by_id = {r['run_id']: r for r in initial}
    all_rows = initial + retries
    require(len({r['run_id'] for r in all_rows}) == 67, 'unique attempt IDs')
    require({(r['case_id'], r['round']) for r in initial} ==
            {(case, round_) for case in cases for round_ in (1, 2, 3)}, '60 unique case-round slots')
    for r in all_rows:
        c = cases[r['case_id']]
        o, p = sum(c['counts'].values()), c['programming_count']
        for key, limit in [('ordinary_count', o), ('programming_count', p)]:
            require(type(r[key]) is int and 0 <= r[key] <= limit, r['run_id'] + ': ' + key)
        require(not r['complete'] or (r['ordinary_count'], r['programming_count']) == (o, p), r['run_id'] + ': complete quota')
        require(not r['unassisted_within_deadline'] or (r['complete'] and
                0 < r['export_elapsed_seconds'] <= protocol['deadline_seconds']), r['run_id'] + ': time/complete')
        require(r['execute'] is False, r['run_id'] + ': local-only')
        require(sum(r['finite_oracle_comparisons'].values()) == sum(r['case_counts'].values()), r['run_id'] + ': case coverage')
        require(r['usage']['logical_model_spans'] == r['logical_model_calls'] ==
                r['usage']['spans_with_reported_usage'] + r['usage']['spans_missing_usage'], r['run_id'] + ': usage coverage')
    replacement = {r['original_run_id']: r['run_id'] for r in retries}
    compare(replacement, expected['replacements'], 'replacement map')
    required = {r['run_id'] for r in initial if not r['complete'] and cases[r['case_id']]['cohort'] == 'extension'}
    require(set(replacement) == required, 'retry every incomplete extension slot exactly once')
    require(len(replacement) == len(retries), 'unique retry targets')
    for r in retries:
        old = by_id[r['original_run_id']]
        require(not old['complete'] and (old['case_id'], old['round']) == (r['case_id'], r['round']), r['run_id'] + ': original slot')
    retry_by_original = {r['original_run_id']: r for r in retries}
    selected = [retry_by_original.get(r['run_id'], r) for r in initial]
    scopes = {'initial': initial, 'replaced': selected, 'retry': retries}
    pair_ids = set()
    for p in pairs:
        key = (p['scope'], p['kind'], *sorted((p['left'], p['right'])))
        require(key not in pair_ids, 'duplicate repeat pair')
        pair_ids.add(key)
        rows = {r['run_id']: r for r in scopes[p['scope']]}
        a, b = rows[p['left']], rows[p['right']]
        count = 'ordinary_count' if p['kind'] == 'ordinary' else 'programming_count'
        require(a['complete'] and b['complete'] and a['case_id'] == b['case_id'] == p['case_id']
                and a['round'] != b['round'] and 0 <= p['matched'] <= p['denominator']
                == min(a[count], b[count]) and p['denominator'] > 0, 'invalid repeat pair')
    for scope, rows in scopes.items():
        wanted = {(scope, kind, *sorted((a['run_id'], b['run_id'])))
                  for i, a in enumerate(rows) for b in rows[i + 1:]
                  for kind, count in [('ordinary', 'ordinary_count'), ('programming', 'programming_count')]
                  if a['complete'] and b['complete'] and a['case_id'] == b['case_id'] and a[count] and b[count]}
        require({p for p in pair_ids if p[0] == scope} == wanted, scope + ': repeat pair coverage')
    values = {}
    for scope in ('initial', 'replaced'):
        rows = scopes[scope]
        values[scope] = {}
        for group in ('historical', 'extension', 'combined'):
            subset = rows if group == 'combined' else [r for r in rows if cases[r['case_id']]['cohort'] == group]
            actual = aggregate(subset, cases, pairs, scope)
            compare(actual, expected[scope][group], scope + '.' + group)
            values[scope][group] = actual
    compare(aggregate(retries, cases, pairs, 'retry'), expected['retry'], 'retry')
    incurred = {'attempts': len(all_rows),
                'logical_model_calls': sum(r['logical_model_calls'] for r in all_rows),
                'reported_tokens': sum(r['usage']['reported_tokens'] for r in all_rows),
                'spans_missing_usage': sum(r['usage']['spans_missing_usage'] for r in all_rows)}
    compare(incurred, expected['total_incurred_including_superseded_attempts'], 'total incurred')
    require(protocol['unique_slots'] == 60 and protocol['execute'] is False and protocol['platform_writes'] == 0, 'protocol scope')
    compare(protocol['required_questions'], {'ordinary': values['initial']['combined']['planned_ordinary_questions'],
                                           'programming': values['initial']['combined']['planned_programming_questions'],
                                           'total': values['initial']['combined']['planned_questions']}, 'required questions')
    return {'passed': not errors, 'errors': errors, 'metrics': values,
            'total_incurred_including_superseded_attempts': incurred,
            'scope': 'numeric_recalculation_only_not_independent_content_review',
            'new_model_requests': 0, 'platform_writes': 0}


if __name__ == '__main__':
    result = summarize()
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    raise SystemExit(0 if result['passed'] else 1)
