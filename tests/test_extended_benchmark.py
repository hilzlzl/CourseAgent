"""Protect retry reporting against discarding failures or their incurred usage."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts.summarize_extended_benchmark import summarize

SOURCE = Path(__file__).resolve().parents[1] / 'evaluations/extended-benchmark'


class ExtendedBenchmarkTests(unittest.TestCase):
    def mutated(self, filename, change):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / 'evidence'
            shutil.copytree(SOURCE, folder)
            path = folder / filename
            data = json.loads(path.read_text(encoding='utf-8'))
            change(data)
            path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            result = summarize(folder)
        self.assertFalse(result['passed'])
        return result['errors']

    def test_saved_cohort_recalculates(self):
        self.assertTrue(summarize()['passed'])

    def test_better_first_attempt_cannot_silently_replace_worse_retry(self):
        def change(rows):
            row = next(r for r in rows if r['original_run_id'] == 'graph-A-R2')
            row['programming_count'] = 5  # The retained retry actually delivered zero.
        errors = self.mutated('retries.json', change)
        self.assertIn('replaced.combined.programming_questions', errors)

    def test_selected_usage_cannot_stand_in_for_actual_incurred_usage(self):
        def change(data):
            data['total_incurred_including_superseded_attempts']['reported_tokens'] = data['replaced']['combined']['reported_tokens']
        self.assertIn('total incurred.reported_tokens', self.mutated('summary.json', change))

    def test_duplicate_pair_cannot_inflate_repeat_statistics(self):
        self.assertIn('duplicate repeat pair', self.mutated('repeat-pairs.json', lambda rows: rows.append(rows[0])))


if __name__ == '__main__':
    unittest.main()
