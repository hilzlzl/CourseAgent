import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from courseagent.code_sandbox import available, execute
from courseagent.programming_verification import build_verification_graph, current_report
from courseagent.source_references import discover_reference, extract_references
from courseagent.source_verification import VERSION
from tests.test_programming_verification import question, responses, VALIDATOR


SOURCE = 'class Solution:\n def total(self, a):\n  return sum(a)'


def reference_question():
    q = question()
    q['source_reference'] = {'code': SOURCE, 'language': 'Python',
                             'url': 'https://leetcode.cn/problems/sum/solutions/example/',
                             'status': 'public_editorial', 'accepted_verified': False}
    return q


class ReferenceDiscoveryTests(unittest.TestCase):
    def test_literal_html_and_markdown_preserve_code_without_inventing_ac(self):
        for content in ('```python\n' + SOURCE + '\n```', '<pre><code class="language-python">' + SOURCE + '</code></pre>'):
            refs = extract_references(content, 'https://www.luogu.com.cn/article/example')
            self.assertEqual(refs[0]['code'], SOURCE)
            self.assertFalse(refs[0]['accepted_verified'])
            self.assertEqual(refs[0]['status'], 'public_editorial')

    def test_json_markdown_and_incomplete_or_nonpython_blocks(self):
        html = '<script type="application/json">' + json.dumps({'article': {'content': '```Python3\n' + SOURCE + '\n```'}}) + '</script>'
        self.assertEqual(extract_references(html, 'https://www.nowcoder.com/discuss/1')[0]['code'], SOURCE)
        self.assertFalse(extract_references('```python\ndef unfinished(\n```', 'https://example.org'))
        self.assertFalse(extract_references('```cpp\nint main() {}\n```', 'https://example.org'))

    def test_luogu_linked_editorial_must_identify_original_problem(self):
        q = question(); q.pop('source_reference', None)
        url = 'https://www.luogu.com.cn/problem/P1001'
        article = 'https://www.luogu.com.cn/article/answer'
        q['source_refs'] = [{'url': url}]
        def fetch(target):
            if target == url:
                return '<a href="/article/answer">P1001题解</a>', target
            if '/problem/solution/' in target:
                return 'P1001没有代码', target
            return 'P1001\n```python\n' + SOURCE + '\n```', target
        with tempfile.TemporaryDirectory() as tmp, patch('courseagent.web_questions.CACHE', Path(tmp)), patch('courseagent.source_access.fetch_source', side_effect=fetch):
            ref = discover_reference(q)
        self.assertEqual(ref['url'], article)
        self.assertEqual(ref['problem_url'], url)

    def test_nowcoder_wrong_problem_is_not_accepted_and_failure_is_cached(self):
        q = question(); url = 'https://www.nowcoder.com/practice/abc123'
        q['source_refs'] = [{'url': url}]
        def fetch(target):
            return ('正文' if target == url else 'another problem\n```python\n' + SOURCE + '\n```'), target
        with tempfile.TemporaryDirectory() as tmp, patch('courseagent.web_questions.CACHE', Path(tmp)), patch('courseagent.source_access.fetch_source', side_effect=fetch) as read, patch('courseagent.web_questions.search', return_value=([{'url': 'https://www.nowcoder.com/discuss/42'}], False)):
            self.assertIsNone(discover_reference(q)); count = read.call_count
            self.assertIsNone(discover_reference(q)); self.assertEqual(read.call_count, count)

    def test_existing_reference_needs_no_network(self):
        with patch('courseagent.web_questions.fetch') as fetch:
            self.assertEqual(discover_reference(reference_question())['code'], SOURCE)
        fetch.assert_not_called()


@unittest.skipUnless(available(), 'Linux isolation unavailable')
class SourceVerificationTests(unittest.TestCase):
    def run_graph(self, modifier=None, cache=None):
        calls = []; answers = responses()
        def ask(role, prompt, data):
            calls.append(role)
            if modifier:
                changed = modifier(role, prompt, data)
                if changed is not None:
                    return changed
            if role == 'solver' and 'source_code' in data:
                return {'prelude_code': 'pass', 'driver_code': 'import sys\nprint(Solution().total(list(map(int,sys.stdin.read().split()))))'}
            if role == 'test_designer' and 'known_faults' not in data:
                return {**answers[role], 'input_validator_code': VALIDATOR}
            return answers[role]
        state = build_verification_graph(ask, execute, stage_cache=cache).invoke({'question': reference_question()})
        return state, calls

    def test_source_fast_path_no_independent_brute_or_mutations(self):
        with tempfile.TemporaryDirectory() as tmp, patch('courseagent.programming_verification.ROOT', Path(tmp)):
            state, calls = self.run_graph()
            self.assertTrue(list(Path(tmp).rglob('reference.py')))
        self.assertEqual(calls, ['solver', 'assessment_planner', 'test_designer'])
        report = current_report(state['question'])
        self.assertTrue(report['passed']); self.assertEqual(report['method'], VERSION)
        self.assertGreaterEqual(report['hidden_count'], 4)
        self.assertFalse(report['source_accepted_verified'])
        self.assertFalse(report['mutation_testing']['performed'])
        self.assertEqual(state['question']['reference_code'], '')
        self.assertTrue(all(not c['verified'] for c in state['question']['test_cases']))
        from courseagent.programming_judge import validate_autonomous_cases
        self.assertGreaterEqual(len(validate_autonomous_cases(state['question'])), 4)

    def test_bad_adapter_escalates_to_model_written_reference(self):
        def bad(role, prompt, data):
            if role == 'solver' and 'source_code' in data:
                return {'prelude_code': 'pass', 'driver_code': 'print(Solution().total([0]))'}
        with tempfile.TemporaryDirectory() as tmp, patch('courseagent.programming_verification.ROOT', Path(tmp)):
            state, calls = self.run_graph(bad)
        self.assertTrue(state['result']['passed'])
        self.assertIn('validator', calls); self.assertIn('mutation_designer', calls)
        self.assertEqual(state['result']['reference_origin'], 'model_written')

    def test_bad_source_public_sample_never_spends_a_source_design_call(self):
        source_design_calls = []
        answers = responses()
        def ask(role, prompt, data):
            if role == 'solver' and 'source_code' in data:
                return {'prelude_code':'pass', 'driver_code':'import sys\nprint(Solution().total(list(map(int,sys.stdin.read().split())))+1)'}
            if role == 'test_designer' and 'known_faults' not in data:
                source_design_calls.append(1)
            return answers[role]
        with tempfile.TemporaryDirectory() as tmp, patch('courseagent.programming_verification.ROOT', Path(tmp)):
            result = build_verification_graph(ask, execute).invoke({'question': reference_question()})
        self.assertEqual(source_design_calls, [])
        self.assertIn('公开样例', result['result']['source_first_fallback'])

    def test_public_sample_execution_precedes_hidden_design(self):
        events = []
        def execute_logged(code, stdin=''):
            if SOURCE in code:
                events.append('reference_execution')
            return execute(code, stdin)
        answers = responses()
        def ask(role, prompt, data):
            if role == 'solver' and 'source_code' in data:
                return {'prelude_code':'pass', 'driver_code':'import sys\nprint(Solution().total(list(map(int,sys.stdin.read().split()))))'}
            if role == 'test_designer':
                events.append('hidden_design')
                return {**answers[role], 'input_validator_code': VALIDATOR}
            return answers[role]
        with tempfile.TemporaryDirectory() as tmp, patch('courseagent.programming_verification.ROOT', Path(tmp)):
            result = build_verification_graph(ask, execute_logged).invoke({'question': reference_question()})
        self.assertTrue(result['result']['passed'])
        self.assertLess(events.index('reference_execution'), events.index('hidden_design'))

    def test_hidden_execution_failure_escalates_instead_of_redesigning_inputs(self):
        def bad(role, prompt, data):
            if role == 'solver' and 'source_code' in data:
                return {'prelude_code': 'pass', 'driver_code': 'import sys\na=list(map(int,sys.stdin.read().split()))\nif any(x<0 for x in a):raise ValueError("adapter bug")\nprint(Solution().total(a))'}
        with tempfile.TemporaryDirectory() as tmp, patch('courseagent.programming_verification.ROOT', Path(tmp)):
            state, calls = self.run_graph(bad)
        self.assertTrue(state['result']['passed'])
        self.assertEqual(state['result']['reference_origin'], 'model_written')
        self.assertIn('隐藏输入执行失败', state['result']['source_first_fallback'])

    def test_hidden_cases_cannot_duplicate_public_examples_by_whitespace(self):
        def duplicates(role, prompt, data):
            if role == 'test_designer' and 'known_faults' not in data:
                cases = [{'input': '1' + ' ' * i + '2\n', 'purpose': 'duplicate', 'category': 'boundary',
                          'obligation_ids': ['normal', 'edge', 'fault']} for i in range(1, 12)]
                return {'generator_code': 'print(' + repr(json.dumps({'cases': cases})) + ')', 'input_validator_code': VALIDATOR}
        with tempfile.TemporaryDirectory() as tmp, patch('courseagent.programming_verification.ROOT', Path(tmp)):
            state, calls = self.run_graph(duplicates)
        self.assertFalse(state['result']['passed'])
        self.assertEqual(calls.count('test_designer'), 2)

    def test_public_goal_coverage_does_not_force_unnecessary_model_retry(self):
        def design(role, prompt, data):
            if role == 'test_designer':
                cases = [{'input': '1 2\n', 'purpose': '公开目标', 'category': 'normal',
                          'obligation_ids': ['normal', 'edge', 'fault']}]
                cases += [{'input': str(i) + '\n', 'purpose': '独立隐藏输入',
                           'category': ('normal', 'boundary', 'adversarial')[j % 3], 'obligation_ids': []}
                          for j, i in enumerate(range(5, 12))]
                return {'generator_code': 'print(' + repr(json.dumps({'cases': cases})) + ')',
                        'input_validator_code': VALIDATOR}
        with tempfile.TemporaryDirectory() as tmp, patch('courseagent.programming_verification.ROOT', Path(tmp)):
            state, calls = self.run_graph(design)
        self.assertTrue(state['result']['passed'])
        self.assertEqual(calls.count('test_designer'), 1)
        self.assertEqual(state['result']['hidden_count'], 7)
        self.assertEqual(state['result']['public_count'], 1)

    def test_stale_categories_and_missing_evidence_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch('courseagent.programming_verification.ROOT', Path(tmp)):
            state, _ = self.run_graph()
        q = state['question']; changed = copy.deepcopy(q)
        changed['test_cases'][-1]['category'] = 'normal'
        self.assertIsNone(current_report(changed))
        changed = copy.deepcopy(q); changed['execution_verification']['source_evidence'].pop('reference_sha256')
        self.assertIsNone(current_report(changed))
        changed = copy.deepcopy(q); changed['source_refs'] = [{'url': 'https://example.org/other-problem'}]
        self.assertIsNone(current_report(changed))

    def test_interrupted_design_reuses_specification_and_adapter(self):
        from courseagent.verification_state import StageCache
        def timeout(role, prompt, data):
            if role == 'test_designer':
                raise TimeoutError('fixture timeout')
        with tempfile.TemporaryDirectory() as tmp, patch('courseagent.programming_verification.ROOT', Path(tmp)):
            cache = StageCache(Path(tmp) / 'cache')
            with self.assertRaises(TimeoutError):
                self.run_graph(timeout, cache)
            state, calls = self.run_graph(cache=cache)
        self.assertTrue(state['result']['passed'])
        self.assertEqual(calls, ['test_designer'])

    def test_continuation_reuses_all_successful_model_stages(self):
        from courseagent.verification_state import StageCache
        with tempfile.TemporaryDirectory() as tmp, patch('courseagent.programming_verification.ROOT', Path(tmp)):
            cache = StageCache(Path(tmp) / 'cache')
            first, _ = self.run_graph(cache=cache)
            second, calls = self.run_graph(cache=cache)
        self.assertTrue(first['result']['passed']); self.assertTrue(second['result']['passed'])
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
