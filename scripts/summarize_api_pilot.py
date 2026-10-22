"""Check the three real-API CourseAgent pilot snapshots without new API requests."""
import json
import math
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]


def summarize(folder):
    folder = Path(folder)

    def load(name):
        return json.loads((folder / name).read_text(encoding='utf-8'))

    cases = load('cases.json')
    runs = load('runs.json')
    protocol = load('protocol.json')
    expected = load('summary.json')
    scales = load('input-scales.json')
    provenance = load('provenance.json')
    errors = []

    def require(condition, message):
        if not condition:
            errors.append(message)

    by_case = {case['id']: case for case in cases}
    require(len(cases) == 3 and set(by_case) == {'stack-A', 'sort-B', 'tree-C'},
            'Expected three distinct pilot requests')
    require(len(runs) == 3 and {r['case_id'] for r in runs} == set(by_case),
            'Expected one run per pilot request')
    require(len({r['run_id'] for r in runs}) == len(runs), 'Duplicate run identities')
    require(protocol['study_design'] == 'single_arm_real_api_pilot' and
            protocol['independent_general_agent_runs'] == 0, 'Unexpected study design')
    require(protocol['platform_delivery_measured'] is False, 'Platform delivery was not measured')
    for run in runs:
        case = by_case.get(run['case_id'])
        if case is None:
            errors.append('Unknown request: ' + run['case_id'])
            continue
        require(run['model'] == protocol['requested_model'], 'Requested model mismatch')
        require(run['ordinary_questions'] == sum(case['counts'].values()) and
                run['programming_questions'] == case['programming_count'], 'Question count mismatch')
        for key in ('ordinary_questions', 'programming_questions', 'public_cases', 'hidden_cases',
                    'logical_model_calls', 'reported_tokens', 'empty_explicit_explanation_fields'):
            require(type(run[key]) is int and run[key] >= 0, 'Invalid non-negative count: ' + key)
        require(math.isfinite(run['export_seconds']) and
                0 < run['export_seconds'] <= protocol['deadline_seconds'], 'Invalid elapsed time')
        require(run['platform_operations'] == 0 and run['manual_resume_count'] == 0 and
                run['operator_interventions'] == 0, 'Unexpected platform write or intervention')
        require(run['teacher_operation_seconds'] is None and run['teacher_quality_score'] is None and
                run['actual_http_requests'] is None and run['actual_cost'] is None,
                'Unknown measurements must remain null')
        require(run['complete_stdio_reference_files_delivered'] == 0 and
                run['delivery_requirements_met'] is False, 'Missing exports cannot be accepted')
        require(0 <= run['questions_meeting_case_count_minimum'] <= run['programming_questions'],
                'Invalid sample-minimum denominator')
        audit = run['finite_oracle_comparisons']
        require(set(audit) == {'passed', 'flagged', 'unassessed'} and
                all(type(v) is int and v >= 0 for v in audit.values()) and
                sum(audit.values()) == run['public_cases'] + run['hidden_cases'],
                'External audit denominator mismatch')
    require(len(scales) == 3 and len({s['source_slug'] for s in scales}) == 3 and
            all(type(s['maximum_saved_input_size']) is int and s['maximum_saved_input_size'] > 0
                for s in scales), 'Invalid saved input scales')
    require(provenance['raw_content_distributed'] is False, 'Private source evidence is excluded')
    require(bool(provenance['original_evidence_sha256']) and
            all(len(digest) == 64 and all(c in '0123456789abcdef' for c in digest)
                for digest in provenance['original_evidence_sha256'].values()), 'Malformed evidence hashes')
    values = {
        'runs': len(runs), 'independent_general_agent_runs': 0,
        'ordinary_questions': sum(r['ordinary_questions'] for r in runs),
        'programming_questions': sum(r['programming_questions'] for r in runs),
        'questions': sum(r['ordinary_questions'] + r['programming_questions'] for r in runs),
        'public_cases': sum(r['public_cases'] for r in runs),
        'hidden_cases': sum(r['hidden_cases'] for r in runs),
        'total_cases': sum(r['public_cases'] + r['hidden_cases'] for r in runs),
        'machine_complete': sum(r['machine_complete'] for r in runs),
        'delivery_requirements_met': sum(r['delivery_requirements_met'] for r in runs),
        'median_export_seconds': statistics.median(r['export_seconds'] for r in runs),
        'logical_model_calls': sum(r['logical_model_calls'] for r in runs),
        'reported_tokens': sum(r['reported_tokens'] for r in runs),
        'manual_resumes': sum(r['manual_resume_count'] for r in runs),
        'empty_explicit_explanation_fields': sum(r['empty_explicit_explanation_fields'] for r in runs),
        'finite_oracle_comparisons': {k: sum(r['finite_oracle_comparisons'][k] for r in runs)
                                     for k in ('passed', 'flagged', 'unassessed')},
    }
    for key, value in values.items():
        target = expected.get(key)
        consistent = (isinstance(target, (int, float)) and math.isclose(value, target, rel_tol=1e-9)
                      if isinstance(value, (int, float)) else value == target)
        require(consistent, 'Aggregate mismatch: ' + key)
    require(expected['supports_general_agent_superiority'] is False and
            expected['supports_teacher_time_savings'] is False, 'Unsupported comparative conclusion')
    return {'passed': not errors, 'scope': 'arithmetic_check_of_three_real_api_project_runs',
            'requested_model': protocol['requested_model'], 'metrics': values, 'errors': errors,
            'new_model_requests': 0, 'platform_writes': 0,
            'limitations': 'Project-only pilot, no independent general-agent arm or teacher ratings. '
                           'Logical model spans are not measured HTTP requests. Hashes do not certify content.'}


if __name__ == '__main__':
    result = summarize(ROOT / 'evaluations/api-pilot')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
