"""Recompute saved direct-API and project metrics; no live requests or grading."""
import json
import math
from pathlib import Path
import statistics
from score_content_review import summarize as score_labels

ROOT = Path(__file__).resolve().parents[1]


def summarize(root=ROOT):
    root = Path(root)

    def load(relative):
        return json.loads((root / relative).read_text(encoding='utf-8'))

    direct = load('evaluations/direct-api-baseline/runs.json')
    project = load('evaluations/api-pilot/runs.json')
    protocol = load('evaluations/direct-api-baseline/protocol.json')
    expected = load('evaluations/direct-api-baseline/comparison.json')
    errors = []

    def require(condition, message):
        if not condition:
            errors.append(message)

    require(len(direct) == len(project) == 3, 'Expected three first results per arm')
    require({r['case_id'] for r in direct} == {r['case_id'] for r in project}
            == {'stack-A', 'sort-B', 'tree-C'}, 'Requests must be paired')
    require(protocol['arm'] == 'direct_model_API_without_CourseAgent_workflow'
            and protocol['tools'] == [] and protocol['courseagent_modules_imported'] is False
            and protocol['prior_question_or_answer_outputs_provided'] is False,
            'Direct API isolation boundary changed')
    require(protocol['requests_per_case'] == 1 and protocol['automatic_retries'] == 0,
            'First-response protocol changed')
    by_case = {r['case_id']: r for r in project}
    for run in direct:
        other = by_case[run['case_id']]
        require(run['model'] == run['response_model'] == protocol['requested_model']
                == other['model'] == 'gpt-6.1-sol', 'Model identifier mismatch')
        require(run['ordinary_questions'] == other['ordinary_questions']
                and run['programming_questions'] == other['programming_questions'],
                'Question quotas differ')
        require(run['http_requests_sent'] == 1 and run['tools_used'] == []
                and run['courseagent_workflow_used'] is False
                and run['manual_continuations'] == run['code_repairs'] == run['platform_writes'] == 0,
                'Unexpected tool use, retry, repair or platform operation')
        require(run['retrieval_performed_during_generation'] is False
                and run['execution_performed_during_generation'] is False
                and run['machine_complete'] is False and run['content_complete'] is True,
                'External audit cannot be credited to model generation')
        count = run['programming_questions']
        require(run['posthoc_materialization_passed'] is True
                and run['posthoc_reference_files'] == count
                and run['complete_reference_programs_in_generator'] == count
                and run['questions_meeting_case_count_minimum_after_materialization'] == count
                and run['posthoc_public_cases'] == 2 * count
                and run['posthoc_hidden_cases'] == 8 * count
                and run['posthoc_paired_cases'] == run['posthoc_reference_execution_passed_cases'] == 10 * count,
                'Post-response file and execution denominator mismatch')
        require(run['finite_oracle_comparisons'] == {'passed': 0, 'flagged': 0,
                                                    'unassessed': run['posthoc_paired_cases']},
                'Self-consistency cannot become independent verification')
        require(run['independent_teacher_score'] is None and run['actual_cost'] is None,
                'Unknown measurements must remain null')
        require(math.isfinite(run['response_seconds']) and 0 < run['response_seconds'] <= 3600,
                'Invalid request duration')
    direct_scores = score_labels(load('evaluations/direct-api-baseline/content-review.json'), direct)
    project_scores = score_labels(load('evaluations/api-pilot/content-review.json'), project)
    require(direct_scores == load('evaluations/direct-api-baseline/content-review-summary.json'),
            'Saved direct score summary differs from labels')
    require(project_scores == load('evaluations/api-pilot/content-review-summary.json'),
            'Saved project score summary differs from labels')
    values = {
        'direct_api_runs': len(direct), 'project_runs': len(project),
        'direct_api_reported_tokens': sum(r['reported_tokens'] for r in direct),
        'direct_api_observed_http_requests': sum(r['http_requests_sent'] for r in direct),
        'project_logical_model_calls': sum(r['logical_model_calls'] for r in project),
        'direct_api_response_seconds_median': statistics.median(r['response_seconds'] for r in direct),
        'project_export_seconds_median': statistics.median(r['export_seconds'] for r in project),
        'direct_api_questions': sum(r['ordinary_questions'] + r['programming_questions'] for r in direct),
        'project_questions': sum(r['ordinary_questions'] + r['programming_questions'] for r in project),
        'direct_api_posthoc_cases': sum(r['posthoc_paired_cases'] for r in direct),
        'project_exported_cases': sum(r['public_cases'] + r['hidden_cases'] for r in project),
        'direct_api_posthoc_reference_consistency_passed': sum(r['posthoc_reference_execution_passed_cases'] for r in direct),
        'direct_api_independently_verified_output_cases': sum(r['finite_oracle_comparisons']['passed'] for r in direct),
        'project_independently_verified_output_cases': sum(r['finite_oracle_comparisons']['passed'] for r in project),
        'direct_api_assistant_content_macro_mean': direct_scores['assistant_reference_macro_mean'],
        'project_assistant_content_macro_mean': project_scores['assistant_reference_macro_mean'],
    }
    for key, value in values.items():
        require(type(expected.get(key)) in (int, float)
                and math.isclose(value, expected[key], rel_tol=1e-10), 'Aggregate mismatch: ' + key)
    require(expected['supports_overall_project_superiority'] is False
            and expected['supports_isolated_workflow_causal_effect'] is False
            and expected['time_endpoints_comparable'] is False
            and expected['independent_teacher_scores'] is None
            and expected['teacher_active_time'] is None, 'Unsupported comparative claim')
    return {'passed': not errors, 'scope': 'saved_three_pair_direct_API_comparison_arithmetic',
            'metrics': values, 'errors': errors, 'new_model_requests': 0, 'platform_writes': 0,
            'limitations': 'Retrospective assistant review; different tools, cumulative budgets '
                           'and timing endpoints. Neither independent teacher acceptance nor causal superiority.'}


if __name__ == '__main__':
    result = summarize()
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    raise SystemExit(0 if result['passed'] else 1)
