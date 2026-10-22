import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from courseagent.code_sandbox import execute, available
from courseagent.programming_verification import build_verification_graph, current_report


def question():
    return {'id': 'q-private', 'title': '序列求和', 'description': '输入一行1至100个整数，每个整数在-100至100之间。输出它们的和。',
            'public_examples': [{'input': '1 2\n', 'output': '3\n'}], 'test_cases': [], 'selected': True,
            'languages': [{'language': 'Python', 'starter_code': ''}], 'difficulty': 0,
            'score': 10, 'time_limit_seconds': 3}


SOLVER = 'import sys\nprint(sum(map(int,sys.stdin.read().split())))'
INDEPENDENT = 'import sys\na=[int(x) for x in sys.stdin.read().split()]\ns=0\nfor v in a:s+=v\nprint(s)'
VALIDATOR = 'import sys\ntry:\n a=list(map(int,sys.stdin.read().split()))\n print("VALID" if 1<=len(a)<=100 and all(-100<=x<=100 for x in a) else "INVALID")\nexcept:print("INVALID")'


def responses():
    cases = [{'input': f'{i}\n', 'purpose': '单元素和负数边界', 'category': 'boundary', 'small': True} for i in (-100,-99,-1,0,1)]
    cases += [{'input': f'{i} 1 2\n', 'purpose': '多元素累加', 'category': 'normal', 'small': True} for i in (3,4,5)]
    cases += [{'input': '-100 100\n', 'purpose': '正负抵消', 'category': 'adversarial', 'small': True},
              {'input': ' '.join(['100']*100)+'\n', 'purpose': '最大长度', 'category': 'scale', 'small': False}]
    for case in cases:case['obligation_ids']=['normal','edge','fault']
    return {'assessment_planner': {'specification':{'input_format':'一行整数','output_format':'整数和','constraints':'1至100个整数，每个在-100至100','output_kind':'unique_tokens','ambiguities':[]},
                'obligations':[{'id':i,'description':i,'category':c} for i,c in [('normal','normal'),('edge','boundary'),('fault','adversarial')]]},
            'mutation_designer':{'wrong_solutions':[{'id':'drop_negative','fault':'丢弃负数','code':'import sys\na=list(map(int,sys.stdin.read().split()))\nprint(sum(x for x in a if x>=0))'},
                                                    {'id':'absolute','fault':'错误取绝对值','code':'import sys\nprint(sum(abs(int(x)) for x in sys.stdin.read().split()))'}]},
            'solver': {'code': SOLVER}, 'validator': {'code': INDEPENDENT, 'brute_code': SOLVER, 'input_validator_code': VALIDATOR},
            'test_designer': {'generator_code': 'print('+repr(json.dumps({'cases': cases}))+')'}}


@unittest.skipUnless(available(), 'Linux isolation unavailable')
class SandboxTests(unittest.TestCase):
    def test_execute_io(self):
        self.assertEqual(execute(SOLVER, '2 3\n')['output'].strip(), '5')

    def test_host_files_and_secrets_not_available(self):
        import os
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'PRIVATE_SENTINEL': 'secret'}):
            p = Path(tmp)/'secret'; p.write_text('private')
            code = f'import os\nprint(os.path.exists({str(p)!r}))\nprint(os.environ.get("PRIVATE_SENTINEL"))'
            self.assertEqual(execute(code)['output'].split(), ['False', 'None'])

    def test_no_network(self):
        result = execute('import socket\nsocket.create_connection(("1.1.1.1",443),timeout=.2)')
        self.assertFalse(result['ok'])

    def test_timeout_and_output_limits(self):
        self.assertFalse(execute('while True:pass', timeout=1)['ok'])
        result = execute('print("x"*1000000)')
        self.assertFalse(result['ok']); self.assertLessEqual(len(result['output']), 65536)


@unittest.skipUnless(available(), 'Linux isolation unavailable')
class VerificationTests(unittest.TestCase):
    def run_graph(self, answers):
        calls = []
        def ask(role, prompt, data):
            calls.append((role, copy.deepcopy(data)))
            return answers[role]
        with tempfile.TemporaryDirectory() as tmp, patch('courseagent.programming_verification.ROOT', Path(tmp)):
            state = build_verification_graph(ask, execute).invoke({'question': question(), 'attempts': 0})
            files = list(Path(tmp).rglob('reference.py'))
            return state, calls, len(files)

    def test_execute_calculates_outputs_and_keeps_solutions_private(self):
        state, calls, files = self.run_graph(responses())
        self.assertTrue(state['result']['passed']); self.assertEqual(files, 1)
        self.assertGreaterEqual(state['result']['brute_checked_count'], 4)
        self.assertEqual(state['question']['reference_code'], '')
        self.assertNotIn('solver', calls[2][1]); self.assertNotIn('test_cases', calls[2][1]['spec'])
        self.assertEqual(current_report(state['question'])['status'], 'verified')
        self.assertFalse(any(c['verified'] for c in state['question']['test_cases']))

    def test_legitimate_empty_hidden_output_is_local_only_not_false_disagreement(self):
        answers=responses()
        answers['assessment_planner']['specification'].update(allows_empty_output=True,output_format='和为0时不输出，其余输出和')
        code='import sys\ns=sum(map(int,sys.stdin.read().split()))\nif s!=0:print(s)'
        answers['solver']['code']=code
        answers['validator']['code']=code;answers['validator']['brute_code']=code
        q=question();q['description']='输入一行1至100个整数，每个整数在-100至100之间。求和，和为0时不输出，否则输出和。'
        with tempfile.TemporaryDirectory() as folder,patch('courseagent.programming_verification.ROOT',Path(folder)):
            state=build_verification_graph(lambda role,*a:answers[role],execute).invoke({'question':q})
        self.assertTrue(state['result']['passed']);self.assertGreater(state['result']['local_only_empty_output_count'],0)
        self.assertTrue(all(c['output'].strip() for c in state['question']['test_cases']))
        self.assertEqual(state['result']['mutation_testing']['detected_count'],2)

    def test_empty_output_adjudication_uses_statement_evidence_per_input(self):
        answers=responses()
        code='import sys\ns=sum(map(int,sys.stdin.read().split()))\nif s!=0:print(s)'
        answers['solver']['code']=code
        answers['validator']['code']=code;answers['validator']['brute_code']=code
        q=question();q['description']='输入一行1至100个整数，每个整数在-100至100之间。求和，和为0时不输出，否则输出和。'
        checked=[]
        def ask(role,prompt,data):
            if '标准输出是否允许为空' in prompt:
                checked.append(data['input'])
                return {'allows_empty_output':True,'evidence':'和为0时不输出，否则输出和','reason':'零和不输出'}
            return answers[role]
        with tempfile.TemporaryDirectory() as folder,patch('courseagent.programming_verification.ROOT',Path(folder)):
            state=build_verification_graph(ask,execute).invoke({'question':q})
        self.assertTrue(state['result']['passed'])
        self.assertEqual(set(checked),{'0\n','-100 100\n'})
        self.assertEqual(len(state['result']['empty_output_adjudication']),2)

    def test_zero_numeric_output_cannot_be_excused_as_empty(self):
        answers=responses()
        code='import sys\ns=sum(map(int,sys.stdin.read().split()))\nif s!=0:print(s)'
        answers['solver']['code']=code
        answers['validator']['code']=code;answers['validator']['brute_code']=code
        def ask(role,prompt,data):
            if '标准输出是否允许为空' in prompt:
                return {'allows_empty_output':False,'evidence':'输出它们的和','reason':'零也应输出整数0'}
            return answers[role]
        with tempfile.TemporaryDirectory() as folder,patch('courseagent.programming_verification.ROOT',Path(folder)):
            state=build_verification_graph(ask,execute).invoke({'question':question()})
        self.assertFalse(state['result']['passed'])

    def test_missing_goal_labels_do_not_fake_coverage_or_discard_executed_cases(self):
        answers=responses();code=answers['test_designer']['generator_code']
        import re
        code=re.sub(r', "obligation_ids": \["normal", "edge", "fault"\]', '', code)
        answers['test_designer']['generator_code']=code
        state,_,_=self.run_graph(answers)
        self.assertTrue(state['result']['passed']);self.assertEqual(state['result']['coverage_obligations']['declared'],[])
        self.assertEqual(len(state['result']['coverage_obligations']['missing']),3)
        self.assertTrue(state['result']['coverage_advisories'])

    def test_surviving_wrong_solvers_trigger_automatic_test_redesign(self):
        answers=responses();design_calls=[]
        weak=[{'input':str(i)+'\n','purpose':'positive only','category':'normal','small':True,
               'obligation_ids':['normal','edge','fault']} for i in range(10)]
        weak_code='print('+repr(json.dumps({'cases':weak}))+')'
        def ask(role,prompt,data):
            if role=='test_designer':
                design_calls.append(copy.deepcopy(data))
                if len(design_calls)==1:return {'generator_code':weak_code}
            return answers[role]
        with tempfile.TemporaryDirectory() as tmp,patch('courseagent.programming_verification.ROOT',Path(tmp)):
            state=build_verification_graph(ask,execute).invoke({'question':question(),'attempts':0})
        self.assertTrue(state['result']['passed']);self.assertEqual(state['result']['attempts'],2)
        self.assertEqual(state['result']['mutation_testing']['detected_count'],2)
        self.assertTrue(design_calls[1]['previous_design_failures'][0]['mutation_results'])

    def test_wrong_solution_retries_without_claiming_success(self):
        answers = responses(); answers['solver'] = {'code': 'print(0)'}
        state, calls, files = self.run_graph(answers)
        self.assertFalse(state['result']['passed']); self.assertEqual(state['attempts'], 2)
        self.assertEqual(files, 0); self.assertTrue(next(data for role,data in calls if role=='solver' and data.get('counterexamples'))['counterexamples'])
        self.assertNotIn('code', next(data for role,data in calls if role=='solver' and data.get('counterexamples'))['counterexamples'][0])

    def test_bad_public_output_rejected(self):
        q = question(); q['public_examples'][0]['output'] = '4'
        answers = responses()
        state = build_verification_graph(lambda role,*_: answers[role], execute).invoke({'question': q})
        self.assertFalse(state['result']['passed'])

    def test_stale_report_invalid_after_edit(self):
        state, _, _ = self.run_graph(responses()); q = state['question']
        q['test_cases'][0]['output'] = '999'
        self.assertIsNone(current_report(q))

    def test_unavailable_executor_never_passes(self):
        answers = responses()
        state = build_verification_graph(lambda role,*_: answers[role], lambda *_: {'ok': False, 'status': 'unavailable'}).invoke({'question': question()})
        self.assertFalse(state['result']['passed'])

    def test_invalid_generated_input_is_filtered_without_weakening_output_checks(self):
        answers = responses()
        source = answers['test_designer']['generator_code']
        # Add one illegal input to an otherwise sufficient and valid design.
        code = source.replace('print(', 'data=', 1)
        code = code[:-1] + '\nimport json\na=json.loads(data)\na["cases"].append({"input":"9999\\n","purpose":"illegal","category":"boundary","small":True,"obligation_ids":["edge"]})\nprint(json.dumps(a))'
        answers['test_designer']['generator_code'] = code
        state, _, _ = self.run_graph(answers)
        self.assertTrue(state['result']['passed']); self.assertEqual(state['result']['rejected_input_count'], 1)
        self.assertNotIn('9999\n', [c['input'] for c in state['question']['test_cases']])

    def test_role_schema_correction_is_automatic(self):
        answers = responses(); counts = {}
        def ask(role, prompt, data):
            counts[role]=counts.get(role,0)+1
            if role=='test_designer' and counts[role]==1:return {'cases': []}
            if role=='test_designer':self.assertIn('format_correction', data)
            return answers[role]
        with tempfile.TemporaryDirectory() as tmp, patch('courseagent.programming_verification.ROOT', Path(tmp)):
            state=build_verification_graph(ask,execute).invoke({'question':question()})
        self.assertTrue(state['result']['passed']);self.assertEqual(counts['test_designer'],2)

    def test_source_algorithm_reused_verbatim_and_hidden_from_independent_role(self):
        original='class Solution:\n def total(self,a):return sum(a)'
        q=question();q['source_reference']={'code':original,'language':'Python','url':'https://example.org/editorial','status':'public_editorial','accepted_verified':False}
        answers=responses();seen=[]
        def ask(role,prompt,data):
            seen.append((role,copy.deepcopy(data)))
            if role=='solver':return {'prelude_code':'pass','driver_code':'import sys\nprint(Solution().total(list(map(int,sys.stdin.read().split()))))'}
            return answers[role]
        with tempfile.TemporaryDirectory() as tmp,patch('courseagent.programming_verification.ROOT',Path(tmp)):
            state=build_verification_graph(ask,execute,source_first=False).invoke({'question':q})
            artifact=next(Path(tmp).rglob('reference.py')).read_text()
        self.assertIn(original,artifact);self.assertTrue(state['result']['passed'])
        self.assertEqual(state['result']['reference_origin'],'source_reused')
        self.assertFalse(state['result']['source_accepted_verified'])
        self.assertNotIn('source_code',seen[2][1]);self.assertNotIn('source_reference',seen[2][1]['spec'])


class RoleTests(unittest.TestCase):
    def test_roles_share_budget_use_langchain_and_restore_context(self):
        from courseagent.agent_roles import ask_role, ROLE
        from courseagent.model_client import model_budget
        backends = []
        def capture(*_):
            from courseagent.model_client import configuration
            backends.append((configuration()['backend'], ROLE.get())); return {}
        with patch('courseagent.model_client._chat_json_langchain', side_effect=capture):
            with model_budget(2) as budget:
                ask_role('solver', 's', {}); ask_role('validator', 'v', {})
                self.assertEqual(budget['calls'], 2)
                with self.assertRaises(ValueError): ask_role('solver', 's', {})
        self.assertEqual(backends, [('langchain', 'solver'), ('langchain', 'validator')])
        self.assertIsNone(ROLE.get())


if __name__ == '__main__': unittest.main()
