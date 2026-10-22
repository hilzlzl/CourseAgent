"""Recompute recorded assistant labels, not automatic or independent grading."""
import argparse
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = dict(scope=30, correctness=30, completeness=15, suitability=15)


def summarize(review, runs):
    if review['review_status'] != 'retrospective_assistant_review_not_independent_acceptance':
        raise ValueError('This scorer supports recorded assistant reviews only.')
    rubric = review['rubric']
    if (rubric['question_weights'] != WEIGHTS or rubric['assignment_coverage_weight'] != 10
            or rubric['mixed_task_weighting'] != 'ordinary_and_programming_equal_50_percent_each'):
        raise ValueError('Unexpected historical scoring convention')
    run_map = {r['run_id']: r for r in runs}
    assignments = {r['run_id']: r for r in review['assignments']}
    if len(run_map) != len(runs) or len(assignments) != len(review['assignments']) or set(assignments) != set(run_map):
        raise ValueError('Assignments must match the run denominator exactly')
    questions = review['questions']
    seen = set()
    for q in questions:
        identity = q['run_id'], q['kind'], q['ordinal']
        if (identity in seen or q['run_id'] not in run_map
                or q['kind'] not in ('ordinary', 'programming')
                or type(q['ordinal']) is not int or q['ordinal'] < 1):
            raise ValueError('Invalid or duplicate question identity')
        seen.add(identity)
        if set(q['scores']) != set(WEIGHTS) or not q['reasons']:
            raise ValueError('Each question needs four labels and a rationale')
        for value in q['scores'].values():
            if value is not None and (type(value) is not int or value not in (0, 1, 2)):
                raise ValueError('Labels must be 0/1/2 or null; never fill missing evidence with 2')
        if q['kind'] == 'programming':
            e = q['evidence']
            counts = e['finite_oracle']
            if (set(counts) != {'passed', 'flagged', 'unassessed'}
                    or any(type(v) is not int or v < 0 for v in counts.values())
                    or sum(counts.values()) != e['saved_cases']):
                raise ValueError('Invalid independent audit denominator')
            all_agree = e['saved_cases'] > 0 and counts['passed'] == e['saved_cases']
            expected = 2 if all_agree else 1
            if not e['execution_passed'] or counts['flagged']:
                expected = 0
            if q['scores']['correctness'] is not None and q['scores']['correctness'] != expected:
                raise ValueError('Correctness label disagrees with this run evidence')
    results = []
    for run_id, run in run_map.items():
        groups = {}
        for kind in ('ordinary', 'programming'):
            group = [q for q in questions if q['run_id'] == run_id and q['kind'] == kind]
            count = run[kind + '_questions']
            if sorted(q['ordinal'] for q in group) != list(range(1, count + 1)):
                raise ValueError('Missing or extra question labels: ' + run_id)
            if group:
                groups[kind] = group
        breakdown = {}
        for dimension, weight in WEIGHTS.items():
            labels = [q['scores'][dimension] for group in groups.values() for q in group]
            breakdown[dimension] = (statistics.mean(
                statistics.mean(q['scores'][dimension] for q in group) / 2
                for group in groups.values()) * weight
                if labels and all(v is not None for v in labels) else None)
        coverage = assignments[run_id]['coverage_label']
        if coverage is not None and (type(coverage) is not int or coverage not in (0, 1, 2)):
            raise ValueError('Invalid assignment coverage label')
        breakdown['whole_assignment_coverage'] = coverage / 2 * 10 if coverage is not None else None
        for kind, group in groups.items():
            if kind == 'programming':
                for field, run_field in [('passed', 'passed'), ('flagged', 'flagged'), ('unassessed', 'unassessed')]:
                    if sum(q['evidence']['finite_oracle'][field] for q in group) != run['finite_oracle_comparisons'][run_field]:
                        raise ValueError('Run-level audit mismatch')
        content_complete = run.get('content_complete', run.get('machine_complete', False))
        total = (sum(breakdown.values()) if content_complete
                 and all(v is not None for v in breakdown.values()) else None)
        results.append(dict(run_id=run_id, assistant_reference_breakdown=breakdown,
                            assistant_reference_total=total, independent_quality_total=None,
                            independent_teacher_score=None,
                            delivery_requirements_met=run['delivery_requirements_met']))
    if review['reviewed_questions'] != len(questions):
        raise ValueError('Review count mismatch')
    totals = [r['assistant_reference_total'] for r in results]
    mean = statistics.mean(totals) if totals and all(v is not None for v in totals) else None
    return dict(review_status=review['review_status'], reviewed_questions=len(questions),
                runs=results, assistant_reference_macro_mean=mean,
                independent_quality_total=None, independent_teacher_score=None,
                independent_general_agent_runs=review['independent_general_agent_runs'],
                new_model_requests=0, platform_writes=0,
                warning='Recorded assistant content labels only; missing independent quality remains null. '
                        'The reference score cannot override delivery failures or establish a causal comparison.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review', type=Path, default=ROOT / 'evaluations/api-pilot/content-review.json')
    parser.add_argument('--runs', type=Path, default=ROOT / 'evaluations/api-pilot/runs.json')
    args = parser.parse_args()
    result = summarize(json.loads(args.review.read_text(encoding='utf-8')),
                       json.loads(args.runs.read_text(encoding='utf-8')))
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
