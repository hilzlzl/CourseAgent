"""Aggregate benchmark checks use synthetic numbers, never server results."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.summarize_server_benchmark import COUNT_FIELDS, GROUPS, NUMBER_FIELDS, summarize

ROOT = Path(__file__).resolve().parents[1]


class ServerBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)
        source = ROOT / 'evaluations/server-benchmark'
        self.experiment = json.loads((source / 'experiment.json').read_text())
        self.data = {'groups': {g: {f: None for f in COUNT_FIELDS + NUMBER_FIELDS} for g in GROUPS}}

    def check_summary(self):
        (self.path / 'experiment.json').write_text(json.dumps(self.experiment))
        (self.path / 'summary.json').write_text(json.dumps(self.data))
        return summarize(self.path)

    def test_empty_template_never_becomes_zero_or_success(self):
        result = self.check_summary()
        self.assertTrue(result['valid'], result['errors'])
        self.assertEqual(result['runs_per_group'], 60)
        for row in result['by_group'].values():
            self.assertIsNone(row['completion_rate'])
            self.assertIsNone(row['judge_cases'])
            self.assertIsNone(row['actual_api_cost_cny'])

    def test_three_group_rates_keep_their_own_denominator(self):
        for group, count, minutes in [('courseagent', 48, 20), ('openai_api', 42, 40), ('human', 54, 80)]:
            self.data['groups'][group].update(completed_assignments=count,
                requested_question_occurrences=960, delivered_question_occurrences=930,
                human_time_assessed_runs=60, human_minutes_mean=minutes)
        result = self.check_summary()
        self.assertTrue(result['valid'], result['errors'])
        self.assertEqual(result['by_group']['courseagent']['completion_rate'], .8)
        self.assertIsNone(result['by_group']['human']['unassisted_rate'])
        self.assertAlmostEqual(result['descriptive_comparisons']['openai_api']['completion_difference_percentage_points'], 10)
        self.assertEqual(result['descriptive_comparisons']['human']['human_time_reduction_fraction'], .75)

    def test_partial_review_does_not_become_full_acceptance(self):
        self.data['groups']['courseagent'].update(completed_assignments=48,
            requirements_assessed_runs=40, requirements_passed_runs=32,
            human_time_assessed_runs=20, human_minutes_mean=5)
        result = self.check_summary()
        row = result['by_group']['courseagent']
        self.assertTrue(result['valid'], result['errors'])
        self.assertEqual(row['requirements_pass_rate_among_assessed'], .8)
        self.assertIsNone(row['requirements_pass_rate_all_runs'])
        self.assertIsNone(result['descriptive_comparisons']['human']['human_time_reduction_fraction'])

    def test_impossible_counts_missing_coverage_and_numeric_values_are_rejected(self):
        original = copy.deepcopy(self.data)
        invalid = [dict(completed_assignments=61),
                   dict(completed_assignments=-1), dict(completed_assignments=True),
                   dict(latency_p50_seconds=float('nan')),
                   dict(latency_p50_seconds=100),
                   dict(latency_success_n=10, latency_p50_seconds=100, latency_p90_seconds=80),
                   dict(independent_quality_score=95),
                   dict(requirements_assessed_runs=10, requirements_passed_runs=11),
                   dict(requested_question_occurrences=0)]
        for patch in invalid:
            with self.subTest(patch=patch):
                self.data = copy.deepcopy(original)
                self.data['groups']['courseagent'].update(patch)
                self.assertFalse(self.check_summary()['valid'])

    def test_group_protocol_and_human_automation_cannot_be_silently_changed(self):
        self.experiment['expected_runs_per_group'] = 180
        self.assertFalse(self.check_summary()['valid'])
        self.experiment['expected_runs_per_group'] = 60
        self.data['groups']['human']['unassisted_within_deadline'] = 60
        self.assertFalse(self.check_summary()['valid'])

    def test_latency_samples_can_include_failed_runs_without_claiming_success(self):
        row = self.data['groups']['openai_api']
        row.update(completed_assignments=48, latency_all_runs_n=60,
                   latency_p50_seconds=490)
        result = self.check_summary()
        self.assertTrue(result['valid'], result['errors'])
        self.assertEqual(result['by_group']['openai_api']['latency_sample_scope'], 'all_submitted_runs')
        self.assertEqual(result['by_group']['openai_api']['completion_rate'], .8)
        row.update(latency_success_n=48)
        self.assertFalse(self.check_summary()['valid'])
        row.update(latency_all_runs_n=None, latency_success_n=60)
        self.assertFalse(self.check_summary()['valid'])
        row.update(latency_all_runs_n=61, latency_success_n=None)
        self.assertFalse(self.check_summary()['valid'])

    def test_workload_is_not_restricted_to_the_archived_50_case_plan(self):
        for group in GROUPS:
            self.data['groups'][group]['requested_question_occurrences'] = 2880
        self.assertTrue(self.check_summary()['valid'])
        self.data['groups']['human']['requested_question_occurrences'] = 960
        self.assertFalse(self.check_summary()['valid'])


if __name__ == '__main__':
    unittest.main()
