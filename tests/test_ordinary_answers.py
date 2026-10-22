import copy
import unittest
from unittest.mock import patch

from courseagent.ordinary_answers import answerless_but_complete, complete_answers
from courseagent.ordinary_verification import verify_document, current
from courseagent.workflow import retrieve, build_graph


def question(ident='choice', typ=1):
    return {'id': ident, 'type': typ, 'stem': '栈遵循后进先出的规则。' if typ == 3 else '栈遵循哪一种存取规则？',
            'options': ['先进先出', '后进先出'] if typ == 1 else [],
            'answer': '', 'blanks': [], 'reference_answer': '', 'score': 2,
            'origin': 'web', 'source_refs': [{'url': 'https://example.org/exercises',
              'answer_status': 'missing', 'answer_evidence': '', 'stem_evidence': '完整来源题目'}],
            'approved': False, 'selected': False}


def state(questions=None, counts=None):
    questions = questions if questions is not None else [question()]
    return {'request': {'source_mode': 'web', 'allow_adaptation': True},
            'document': {'name': 'fixture', 'questions': questions},
            'web': {'candidate_ids': [q['id'] for q in questions], 'events': [], 'pages': [], 'model_calls': 0},
            'spec': {'counts': counts or {'1': 1}, 'topics': ['栈']}, 'trace': []}


def solve(role, prompt, data):
    return {'answers': [{'id': q['id'], 'answer': '正确' if q['type'] == 3 else 'B',
                         'reason': '栈按后进先出的定义存取数据。'} for q in data['questions']]}


class AnswerCompletionTests(unittest.TestCase):
    def test_missing_answer_is_solved_but_never_presented_as_source_answer(self):
        original = state()
        result = complete_answers(original, ask=solve)
        q = result['document']['questions'][0]
        self.assertEqual(q['answer'], 'B')
        self.assertEqual(q['source_refs'][0]['answer_evidence'], '')
        self.assertEqual(q['source_refs'][0]['answer_status'], 'model_derived')
        self.assertEqual(q['answer_provenance']['kind'], 'model_derived')
        self.assertIsNone(current(q))
        self.assertFalse(q['approved'])
        self.assertEqual(original['document']['questions'][0]['answer'], '')
        self.assertEqual(len(retrieve({**original, **result})['candidates']), 1)
        calls = []
        q['selected'] = True
        def independent(role, prompt, data):
            calls.append(role)
            if role == 'ordinary_solver':
                self.assertEqual(set(data['questions'][0]), {'id', 'type', 'stem', 'options'})
                return solve(role, prompt, data)
            return {'checks': [{'id': q['id'], 'verdict': 'pass', 'reason': '独立定义推导一致'}]}
        verify_document(result['document'], ask=independent)
        self.assertEqual(calls, ['ordinary_solver'])
        self.assertEqual(current(q)['verdict'], 'pass')
        complete_answers({**original, **result}, ask=lambda *_: self.fail('Already completed'))

    def test_five_choices_five_judgments_do_not_trigger_another_search(self):
        # Give the fixture ten distinct statements; identical statements are
        # intentionally deduplicated by the assembly pipeline.
        questions = [dict(question('c' + str(i)), stem=f'栈遵循后进先出的规则（选择{i}）。', options=['先进先出', '后进先出']) for i in range(5)] + [
            dict(question('j' + str(i), 3), stem=f'栈遵循后进先出的规则（判断{i}）。') for i in range(5)]
        original = state(questions, {'1': 5, '3': 5})
        def plan_search(s): return {'web': original['web']}
        def extract(s): return {'document': original['document'], 'web': original['web']}
        with patch('courseagent.web_questions.plan_search', side_effect=plan_search), \
             patch('courseagent.web_questions.search_read', return_value={}) as search, \
             patch('courseagent.web_questions.extract_candidates', side_effect=extract), \
             patch('courseagent.ordinary_answers.complete_answers', side_effect=lambda s: complete_answers(s, ask=solve)), \
             patch('courseagent.web_replenishment.replenish', side_effect=AssertionError('No replenishment needed')):
            result = build_graph(_ordinary_branch=True).invoke(original)
        self.assertEqual(search.call_count, 0)  # retained answerless pool is processed first
        self.assertEqual(len(result['candidates']), 10)
        self.assertEqual(sum(q['type'] == 1 for q in result['candidates']), 5)
        self.assertEqual(sum(q['type'] == 3 for q in result['candidates']), 5)
        self.assertEqual(result['web']['model_calls'], 2)  # bounded batches, no ten per-question calls

    def test_fill_and_short_answers_and_broken_options(self):
        fill = {**question('f', 4), 'stem': '栈遵循____原则。'}
        short = {**question('s', 5), 'stem': '请说明栈遵循的存取原则。'}
        broken = {**question('broken'), 'options': ['后进先出']}
        self.assertFalse(answerless_but_complete(broken))
        def answers(*_):
            return {'answers': [{'id': 'f', 'blanks': ['后进先出'], 'reason': '栈的定义'},
                                {'id': 's', 'reference_answer': '后进先出：最后压入栈的数据最先弹出。', 'reason': '按栈的操作定义推导'}]}
        result = complete_answers(state([fill, short, broken], {'1': 1, '4': 1, '5': 1}), ask=answers)
        self.assertEqual(result['document']['questions'][0]['blanks'], ['后进先出'])
        self.assertEqual(result['document']['questions'][-1]['answer'], '')

    def test_uncertainty_is_not_solved_repeatedly_or_promoted(self):
        def uncertain(*_): return {'answers': [{'id': 'choice', 'uncertain': True, 'reason': '题干引用的图未提供'}]}
        original = state()
        result = complete_answers(original, ask=uncertain)
        self.assertFalse(retrieve({**original, **result})['candidates'])
        complete_answers({**original, **result}, ask=lambda *_: self.fail('Unchanged ambiguity'))

    def test_transport_failure_is_surfaced_instead_of_triggering_search(self):
        calls = []
        def fail(*_):
            calls.append(1)
            raise TimeoutError('provider timeout')
        result=complete_answers(state(), ask=fail)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result['web']['adaptation_failure']['stage'],'answers')
        self.assertEqual(result['document']['questions'][0]['answer'],'')
        resumed=complete_answers({**state(),**result},ask=solve)
        self.assertNotIn('adaptation_failure',resumed['web'])
        self.assertEqual(resumed['document']['questions'][0]['answer'],'B')

    def test_unused_unrequested_and_teacher_approved_questions_are_preserved(self):
        good = {**question('ready'), 'answer': 'B'}
        approved = {**question('teacher'), 'approved': True}
        original = state([good, approved, question('extra')])
        before = copy.deepcopy(original)
        self.assertEqual(complete_answers(original, ask=lambda *_: self.fail('Quota already met')), {})
        self.assertEqual(original, before)

    def test_no_ranking_model_call_when_every_candidate_is_needed(self):
        from courseagent.workflow import rank_candidates
        original = state([{**question(), 'answer': 'B'}])
        original['request']['use_model'] = True
        original.update(retrieve(original))
        with patch('courseagent.workflow.ask_role', side_effect=AssertionError('No selection decision to make')):
            result = rank_candidates(original)
        self.assertIn('跳过排序', result['trace'][-1])

    def test_batch_checkpoint_drops_stale_candidates(self):
        from courseagent.model_client import TASK_BUDGET
        previews = []
        original = state()
        original['candidates'] = []
        token = TASK_BUDGET.set({'on_source_checkpoint':lambda branch,s:previews.append(s)})
        try:
            complete_answers(original, ask=solve)
        finally:
            TASK_BUDGET.reset(token)
        self.assertEqual(len(previews), 1)
        self.assertNotIn('candidates', previews[0])
        self.assertEqual(previews[0]['document']['questions'][0]['answer'], 'B')


if __name__ == '__main__':
    unittest.main()
