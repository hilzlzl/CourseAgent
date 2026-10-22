"""Recompute three-group aggregate results; never treat unfilled metrics as zero."""
import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FOLDER = ROOT / 'evaluations/server-benchmark'
GROUPS = ('courseagent', 'openai_api', 'human')
COUNT_FIELDS = ('completed_assignments', 'unassisted_within_deadline',
                'requested_question_occurrences', 'delivered_question_occurrences',
                'requirements_assessed_runs', 'requirements_passed_runs',
                'latency_success_n', 'latency_all_runs_n', 'human_time_assessed_runs',
                'independent_quality_assessed_runs', 'quality_assessed_questions',
                'severe_defect_questions', 'public_cases', 'hidden_cases',
                'logical_model_calls', 'http_requests', 'reported_tokens')
NUMBER_FIELDS = ('latency_p50_seconds', 'latency_p90_seconds', 'human_minutes_mean',
                 'independent_quality_score', 'actual_api_cost_cny',
                 'ordinary_cross_run_repeat_rate', 'programming_cross_run_repeat_rate')


def summarize(folder=DEFAULT_FOLDER):
    folder = Path(folder)
    experiment = json.loads((folder / 'experiment.json').read_text(encoding='utf-8'))
    data = json.loads((folder / 'summary.json').read_text(encoding='utf-8'))
    errors = []
    runs = experiment['expected_runs_per_group']
    cases = experiment['expected_cases']
    repetitions = experiment['repetitions_per_case']
    if (type(cases) is not int or cases <= 0
            or type(repetitions) is not int or repetitions <= 0
            or runs != cases * repetitions or experiment['expected_runs'] != runs * len(GROUPS)
            or set(experiment['groups']) != set(GROUPS)
            or len(experiment['groups']) != 3):
        errors.append('experiment case/repetition/group dimensions do not match run denominators')
    if set(data['groups']) != set(GROUPS):
        errors.append('aggregate results must contain exactly the three experiment groups')
    result_groups = {}
    for group in GROUPS:
        row = data['groups'].get(group, {})
        values = {}
        for field in COUNT_FIELDS + NUMBER_FIELDS:
            value = row.get(field)
            if value is not None:
                valid = type(value) is int if field in COUNT_FIELDS else type(value) in (int, float)
                if not valid or not math.isfinite(value) or value < 0:
                    errors.append(group + ': invalid nonnegative metric: ' + field)
                    value = None
            values[field] = value
        def bound(field, maximum):
            value = values[field]
            if value is not None and maximum is not None and value > maximum:
                errors.append(group + ': out-of-range metric: ' + field)
        for field in ('completed_assignments', 'unassisted_within_deadline', 'requirements_assessed_runs',
                      'requirements_passed_runs', 'latency_success_n', 'latency_all_runs_n', 'human_time_assessed_runs',
                      'independent_quality_assessed_runs'):
            bound(field, runs)
        bound('unassisted_within_deadline', values['completed_assignments'])
        bound('requirements_passed_runs', values['requirements_assessed_runs'])
        bound('requirements_passed_runs', values['completed_assignments'])
        bound('latency_success_n', values['completed_assignments'])
        bound('severe_defect_questions', values['quality_assessed_questions'])
        bound('independent_quality_score', 100)
        for field in ('ordinary_cross_run_repeat_rate', 'programming_cross_run_repeat_rate'):
            bound(field, 1)
        requested = values['requested_question_occurrences']
        if requested is not None and requested == 0:
            errors.append(group + ': requested question occurrences must be positive when provided')
        if values['latency_success_n'] is not None and values['latency_all_runs_n'] is not None:
            errors.append(group + ': latency sample cannot mix successful-only and all-run counts')
        latency_n = (values['latency_all_runs_n'] if values['latency_all_runs_n'] is not None
                     else values['latency_success_n'])
        for field in ('latency_p50_seconds', 'latency_p90_seconds'):
            if values[field] is not None and not latency_n:
                errors.append(group + ': latency requires its sample count and scope')
        p50, p90 = values['latency_p50_seconds'], values['latency_p90_seconds']
        if p50 is not None and p90 is not None and p90 < p50:
            errors.append(group + ': P90 cannot be below P50')
        for score, coverage in (('human_minutes_mean', 'human_time_assessed_runs'),
                                ('independent_quality_score', 'independent_quality_assessed_runs')):
            if values[score] is not None and not values[coverage]:
                errors.append(group + ': ' + score + ' requires assessment coverage')
        if values['requirements_passed_runs'] is not None and values['requirements_assessed_runs'] is None:
            errors.append(group + ': requirement acceptance needs its assessed denominator')
        if group == 'human' and values['unassisted_within_deadline'] is not None:
            errors.append('human: automatic completion without intervention is not applicable; leave null')
        def ratio(numerator, denominator):
            return numerator / denominator if numerator is not None and denominator else None
        values['completion_rate'] = ratio(values['completed_assignments'], runs)
        values['unassisted_rate'] = ratio(values['unassisted_within_deadline'], runs)
        values['question_completion_ratio'] = ratio(values['delivered_question_occurrences'], requested)
        values['latency_sample_scope'] = ('all_submitted_runs' if values['latency_all_runs_n'] is not None
                                          else 'successful_runs' if values['latency_success_n'] is not None else None)
        values['approximate_metrics'] = row.get('approximate_metrics', [])
        assessed = values['requirements_assessed_runs']
        values['requirements_pass_rate_among_assessed'] = ratio(values['requirements_passed_runs'], assessed)
        values['requirements_pass_rate_all_runs'] = ratio(values['requirements_passed_runs'], runs) if assessed == runs else None
        values['judge_cases'] = (values['public_cases'] + values['hidden_cases']
                                 if values['public_cases'] is not None and values['hidden_cases'] is not None else None)
        result_groups[group] = values
    targets = {v['requested_question_occurrences'] for v in result_groups.values() if v['requested_question_occurrences'] is not None}
    if len(targets) > 1:
        errors.append('three groups must share the same requested question occurrences')
    comparisons = {}
    project = result_groups['courseagent']
    for group in ('openai_api', 'human'):
        other = result_groups[group]
        complete = project['completion_rate'], other['completion_rate']
        covered = project['human_time_assessed_runs'] == runs and other['human_time_assessed_runs'] == runs
        minutes = project['human_minutes_mean'], other['human_minutes_mean']
        comparisons[group] = {
            'completion_difference_percentage_points': (complete[0] - complete[1]) * 100 if None not in complete else None,
            'human_time_reduction_fraction': 1 - minutes[0] / minutes[1] if covered and None not in minutes and minutes[1] > 0 else None}
    return {'valid': not errors, 'scope': 'aggregate_arithmetic_only_not_raw_evidence_validation',
            'execution_state': experiment['execution_state'], 'runs_per_group': runs,
            'by_group': result_groups, 'descriptive_comparisons': comparisons, 'errors': errors,
            'limitations': ['Blank aggregate cells remain unknown, not zeros.',
                           'Aggregate arithmetic does not independently verify private server records.',
                           'Partial quality/acceptance reviews do not become all-run quality scores.',
                           'Group differences are descriptive, not significance tests or causal claims.',
                           'Use requirement-level paired records on the server for uncertainty estimates.'],
            'live_model_calls': 0, 'platform_writes': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, default=DEFAULT_FOLDER)
    args = parser.parse_args()
    try:
        result = summarize(args.folder)
    except (OSError, ValueError, KeyError, TypeError) as error:
        result = {'valid': False, 'errors': [str(error)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['valid'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
