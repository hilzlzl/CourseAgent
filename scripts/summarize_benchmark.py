"""Recompute arithmetic from sanitized historical runs, with explicit denominators."""
import json
import math
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]


def wilson(passed, total):
    z = 1.959963984540054
    fraction = passed/total
    denominator = 1+z*z/total
    center = (fraction+z*z/(2*total))/denominator
    radius = z*math.sqrt(fraction*(1-fraction)/total+z*z/(4*total*total))/denominator
    return [round(center-radius, 4), round(center+radius, 4)]


def summarize(folder):
    runs = json.loads((folder/'runs.json').read_text())
    cases = json.loads((folder/'cases.json').read_text())
    metrics = json.loads((folder/'metrics.json').read_text())
    errors = []
    def require(condition, message):
        if not condition:
            errors.append(message)
    require(len({r['run_id'] for r in runs}) == len(runs), 'duplicate run IDs')
    require(len(cases) == 12 and len(runs) == 36, 'unexpected experiment size')
    for case in cases:
        subset = [r for r in runs if r['case_id'] == case['id']]
        require(sorted(r['round'] for r in subset) == [1, 2, 3], 'missing repetitions: '+case['id'])
        for run in subset:
            require(run['execute'] is False, 'platform execution enabled')
            exact = run['ordinary_count'] == sum(case['counts'].values()) and run['programming_count'] == case['programming_count']
            require(exact == run['complete'], 'count/completion mismatch: '+run['run_id'])
    values = {
        'runs': len(runs), 'complete_assignments': sum(r['complete'] for r in runs),
        'unassisted_within_deadline': sum(r['unassisted_within_deadline'] for r in runs),
        'ordinary_questions': sum(r['ordinary_count'] for r in runs),
        'programming_questions': sum(r['programming_count'] for r in runs),
        'planned_questions': 3*sum(sum(c['counts'].values())+c['programming_count'] for c in cases),
        'public_cases': sum(r['case_counts']['public'] for r in runs),
        'hidden_cases': sum(r['case_counts']['hidden'] for r in runs),
        'logical_model_calls': sum(r['logical_model_calls'] for r in runs),
        'finite_oracle_passed': sum(r['finite_oracle_comparisons']['passed'] for r in runs),
        'finite_oracle_unassessed': sum(r['finite_oracle_comparisons']['unassessed'] for r in runs),
        'finite_oracle_flagged': sum(r['finite_oracle_comparisons']['flagged'] for r in runs),
    }
    values['test_cases'] = values['public_cases']+values['hidden_cases']
    times = sorted(r['export_elapsed_seconds'] for r in runs if r['unassisted_within_deadline'])
    values['latency_p50_seconds'] = statistics.median(times)
    values['latency_p90_seconds'] = times[math.ceil(.9*len(times))-1]
    for key, value in values.items():
        require(math.isclose(value, metrics[key], rel_tol=1e-9), 'aggregate mismatch: '+key)
    values['completion_rate'] = values['complete_assignments']/len(runs)
    values['completion_wilson_95'] = wilson(values['complete_assignments'], len(runs))
    values['unassisted_rate'] = values['unassisted_within_deadline']/len(runs)
    values['unassisted_wilson_95'] = wilson(values['unassisted_within_deadline'], len(runs))
    return {'passed': not errors, 'scope': 'arithmetic_check_of_historical_sanitized_snapshot',
            'metrics': values, 'errors': errors, 'live_model_calls': 0, 'platform_writes': 0}


if __name__ == '__main__':
    result = summarize(ROOT/'evaluations/final-acceptance')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
