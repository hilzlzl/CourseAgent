"""Recovery invariants, using trusted deterministic fixtures rather than paid APIs."""
import ast
import copy
import json
import tempfile
import threading
import unittest
from types import SimpleNamespace
from collections import Counter
from contextvars import copy_context
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch, Mock

from courseagent.verification_state import StageCache, merge_updates, failure_info, task_budget
from courseagent.programming_verification import build_verification_graph, verify_document, basis, case_basis, VERSION
from tests.test_programming_verification import question, responses, SOLVER, INDEPENDENT, VALIDATOR


def fixture_execute(code, text=''):
    # This interprets a closed set of trusted fixture programs, never generated code.
    if code.startswith('print('):
        return {'ok': True, 'output': ast.literal_eval(ast.parse(code).body[0].value.args[0])}
    values = list(map(int, text.split()))
    if code == VALIDATOR: output = 'VALID' if 1 <= len(values) <= 100 and all(-100 <= v <= 100 for v in values) else 'INVALID'
    elif code in (SOLVER, INDEPENDENT): output = str(sum(values))
    elif 'if x>=0' in code: output = str(sum(x for x in values if x >= 0))
    elif 'abs(' in code: output = str(sum(map(abs, values)))
    else: raise AssertionError('Unexpected trusted fixture')
    return {'ok': True, 'output': output}


def ordinary():
    return {'id': 'o', 'type': 1, 'stem': '栈的访问顺序？', 'options': ['先进先出', '后进先出'], 'answer': 'B', 'selected': True}


class StageRecoveryTests(unittest.TestCase):
    def test_partial_independent_generation_survives_third_program_failure(self):
        answers=responses(); calls=[]
        def ask(role,prompt,data):
            calls.append((role,prompt,data))
            if role=='validator' and '唯一字段为input_validator_code' in prompt:
                raise TimeoutError('fixture stalled input validator')
            return copy.deepcopy(answers[role])
        with tempfile.TemporaryDirectory() as folder:
            cache=StageCache(folder)
            with self.assertRaises(TimeoutError) as caught:
                build_verification_graph(ask,fixture_execute,cache).invoke({'question':question()})
            self.assertEqual(caught.exception.verification_stage,'independent_input_validator_code')
            resumed=[]
            def resume(role,prompt,data):
                resumed.append((role,prompt,data));return copy.deepcopy(answers[role])
            result=build_verification_graph(resume,fixture_execute,cache).invoke({'question':question()})
            self.assertTrue(result['result']['passed'])
            validators=[p for r,p,d in resumed if r=='validator']
            self.assertEqual(len(validators),1)
            self.assertIn('唯一字段为input_validator_code',validators[0])
            self.assertFalse(any('solver' in d or 'reference_code' in d for r,p,d in resumed if r=='validator'))

    def test_interrupted_stage_resumes_without_regenerating_private_solutions(self):
        answers = responses(); calls = Counter(); gate = threading.Barrier(2)
        def first(role, *args):
            calls[role] += 1
            if role=='solver' or (role=='validator' and calls[role]==1): gate.wait(timeout=3)
            if role == 'test_designer': raise TimeoutError('fixture timeout')
            return copy.deepcopy(answers[role])
        with tempfile.TemporaryDirectory() as tmp, patch('courseagent.programming_verification.ROOT', Path(tmp)/'artifacts'):
            cache = StageCache(Path(tmp)/'cache')
            with self.assertRaises(TimeoutError):
                build_verification_graph(first, fixture_execute, cache, True).invoke({'question': question()})
            self.assertEqual(calls['solver'], 1); self.assertEqual(calls['validator'], 3)
            resumed = Counter()
            def second(role, *args):
                resumed[role] += 1
                return copy.deepcopy(answers[role])
            result = build_verification_graph(second, fixture_execute, StageCache(Path(tmp)/'cache'), True).invoke({'question': question()})
            self.assertTrue(result['result']['passed'])
            self.assertEqual(resumed, {'test_designer': 1})
            self.assertGreaterEqual(result['result']['hidden_count'], 1)
            self.assertEqual(result['result']['mutation_testing']['detected_count'], 2)
            self.assertTrue(all(p.stat().st_mode & 0o077 == 0 for p in (Path(tmp)/'cache').glob('*.json')))

    def test_bad_input_generator_only_regenerates_inputs(self):
        answers=responses();calls=Counter()
        bad=copy.deepcopy(answers['test_designer'])
        cases=[{'input':str(i),'purpose':'fixture','category':'normal','small':False} for i in range(6)]
        bad['generator_code']='print('+repr(json.dumps({'cases':cases}))+')'
        def ask(role,*args):
            calls[role]+=1
            return bad if role=='test_designer' and calls[role]==1 else copy.deepcopy(answers[role])
        with tempfile.TemporaryDirectory() as tmp,patch('courseagent.programming_verification.ROOT',Path(tmp)):
            result=build_verification_graph(ask,fixture_execute,StageCache(Path(tmp)/'cache'),True).invoke({'question':question()})
        self.assertTrue(result['result']['passed'])
        self.assertEqual(calls,{'assessment_planner':1,'solver':1,'validator':3,'mutation_designer':1,'test_designer':2})

    def test_question_edit_invalidates_stage_cache(self):
        calls=Counter();answers=responses()
        def ask(role,*args):calls[role]+=1;return copy.deepcopy(answers[role])
        with tempfile.TemporaryDirectory() as tmp,patch('courseagent.programming_verification.ROOT',Path(tmp)):
            cache=StageCache(Path(tmp)/'cache')
            graph=build_verification_graph(ask,fixture_execute,cache)
            graph.invoke({'question':question()})
            q=question();q['description']+=' 输入末尾允许换行。'
            graph.invoke({'question':q})
        self.assertEqual(calls['solver'],2);self.assertEqual(calls['assessment_planner'],2)

    def test_corrupt_checkpoint_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=StageCache(tmp);cache.save('s',{'id':'q'},{'code':'valid'})
            p=cache.path('s',{'id':'q'});d=json.loads(p.read_text());d['delta']['code']='corrupt';p.write_text(json.dumps(d))
            self.assertIsNone(cache.load('s',{'id':'q'}))

    def test_failed_report_with_hidden_cases_is_retried(self):
        q=question();q['test_cases']=[{'input':'-1','output':'-1','visibility':'hidden'}]
        q['execution_verification']={'passed':False,'status':'role_failed','method':VERSION,'basis':basis(q),'case_basis':case_basis(q)}
        graph=Mock();graph.invoke.return_value={'result':{'passed':False,'status':'counterexample'},'failures':[]}
        with tempfile.TemporaryDirectory() as tmp,patch('courseagent.programming_verification.ROOT',Path(tmp)),patch('courseagent.programming_verification.available',return_value=True),patch('courseagent.programming_verification.build_verification_graph',return_value=graph) as build:
            verify_document({'programming_questions':[q]})
        build.assert_called_once();graph.invoke.assert_called_once()


class OrdinaryRecoveryTests(unittest.TestCase):
    def test_same_requirement_repair_reuses_model_parse_but_keeps_new_locks(self):
        from courseagent.workflow import parse_request
        request={'prompt':'栈2道单选题','use_model':True}
        with patch('courseagent.workflow.ask_role',return_value={'counts':{'1':2},'programming_count':0,'topics':['栈'],'difficulty':1,'target_minutes':0}) as ask:
            first=parse_request({'request':request})['spec']
            second=parse_request({'document':{'plan':{'spec':first}},'request':{**request,'continue_web':True,'locked_ids':['o']}})['spec']
            self.assertEqual(ask.call_count,1);self.assertEqual(second['locked_ids'],['o'])
            parse_request({'document':{'plan':{'spec':first}},'request':{**request,'prompt':'队列2道单选题','continue_web':True}})
            self.assertEqual(ask.call_count,2)

    def test_judge_failure_retains_blind_solve_and_answer_edit_only_rechecks(self):
        from courseagent.ordinary_verification import verify_document
        q={**ordinary(),'type':4,'stem':'栈遵循____原则。','options':[],
           'answer':'','blanks':['后进先出']}
        d={'questions':[q]};calls=Counter()
        def ask(role,*args):
            calls[role]+=1
            if role=='ordinary_solver':return {'answers':[{'id':'o','blanks':['LIFO'],'reason':'后进先出'}]}
            if calls[role]==1:raise TimeoutError('fixture')
            return {'checks':[{'id':'o','verdict':'pass','reason':'一致'}]}
        verify_document(d,ask);verify_document(d,ask)
        self.assertEqual(calls,{'ordinary_solver':1,'answer_judge':2})
        d['questions'][0]['blanks']=['先进先出'];verify_document(d,ask)
        self.assertEqual(calls,{'ordinary_solver':1,'answer_judge':3})
        d['questions'][0]['stem']='队列的访问顺序？';verify_document(d,ask)
        self.assertEqual(calls,{'ordinary_solver':2,'answer_judge':4})

    def test_merge_keeps_user_edits_and_deselection(self):
        q=ordinary();update=copy.deepcopy(q);update['ordinary_blind_check']={'verdict':'pass'}
        q['selected']=False
        d=merge_updates({'questions':[q]},{('ordinary','o'):update})
        self.assertFalse(d['questions'][0]['selected']);self.assertIn('ordinary_blind_check',d['questions'][0])
        q['answer']='A';d=merge_updates({'questions':[q]},{('ordinary','o'):update})
        self.assertNotIn('ordinary_blind_check',d['questions'][0])

    def test_failure_routing_and_workload_budget(self):
        from courseagent.model_client import BudgetExhausted
        self.assertEqual(failure_info(BudgetExhausted())['action'],'pause')
        self.assertEqual(failure_info(ValueError('模型接口返回 HTTP 402'))['action'],'pause')
        self.assertEqual(failure_info(TimeoutError())['code'],'transport')
        small=task_budget({'prompt':'栈2道单选题'})
        large=task_budget({'prompt':'栈6道单选题和3道编程题'})
        self.assertGreater(large['max_seconds'],small['max_seconds'])
        self.assertGreater(large['max_calls'],small['max_calls'])

    def test_model_concurrency_is_bounded_across_copied_contexts(self):
        from courseagent.model_client import chat_json,model_budget
        lock=threading.Lock();active=0;peak=0;three=threading.Event();release=threading.Event()
        def transport(*args):
            nonlocal active,peak
            with lock:
                active+=1;peak=max(peak,active)
                if active==3:three.set()
            release.wait(timeout=3)
            with lock:active-=1
            return {}
        with model_budget(20,30) as budget,patch('courseagent.model_client.configuration',return_value={'backend':'direct'}),patch('courseagent.model_client._chat_json',side_effect=transport),ThreadPoolExecutor(max_workers=6) as pool:
            futures=[pool.submit(copy_context().run,chat_json,'fixture',{}) for _ in range(6)]
            try:self.assertTrue(three.wait(timeout=3))
            finally:release.set()
            for f in futures:f.result()
        self.assertEqual(peak,3);self.assertEqual(budget['calls'],6)


class SupervisorRecoveryTests(unittest.TestCase):
    def test_replacing_bad_ordinary_question_preserves_truncated_program(self):
        from courseagent.autonomous_agent import build_agent
        from tests.test_autonomous_agent import document
        d=document();p=question();p['test_cases']=[{'input':'1 2','output':'3','visibility':'public'},{'input':'-1','output':'-1','visibility':'hidden'}];d['programming_questions']=[p];qid=d['questions'][0]['id'];calls=Counter()
        def planner(doc,*args):
            calls['plan']+=1
            if calls['plan']==2:
                self.assertTrue(doc['programming_questions'][0]['selected'])
                self.assertFalse(next(q for q in doc['questions'] if q['id']==qid)['selected'])
            return doc
        def checker(doc):
            calls['check']+=1
            return {'blocking':calls['check']==1,'issues':[
                {'kind':'ordinary_answer','question_ids':[qid],'severity':'blocking','message':'wrong answer'},
                {'kind':'programming_verification','question_ids':[p['id']],'severity':'blocking','message':'truncated model response','failure':{'code':'output_limit','retryable':True}},
                {'kind':'programming_verification','question_ids':[p['id']],'severity':'blocking','message':'unverified outputs'}
            ] if calls['check']==1 else []}
        result=build_agent(planner,checker,lambda *a:{'action':'replace','reason':'replace defective ordinary question'}).invoke({'document':d,'request':{'prompt':'fixture'},'sources':[],'rounds':0,'events':[]})
        self.assertEqual(result['action'],'deliver')
        self.assertNotIn(p['id'],result['avoid_ids']);self.assertIn(qid,result['avoid_ids'])

    def test_mixed_answer_fix_retains_program_reference_and_avoids_replanning(self):
        from courseagent.autonomous_agent import build_agent
        from tests.test_autonomous_agent import document
        d=document();p=question();p['execution_verification']={'failure':{'code':'transport','retryable':True}}
        p['test_cases']=[{'input':'1 2','output':'3','visibility':'public'},{'input':'-1','output':'-1','visibility':'hidden'}]
        d['programming_questions']=[p];qid=d['questions'][0]['id'];calls=Counter()
        def planner(doc,*args):calls['compose']+=1;return doc
        def checker(doc):
            calls['inspect']+=1
            return {'blocking':calls['inspect']==1,'issues':[
                {'kind':'answer','severity':'blocking','question_ids':[qid],'message':'fixture answer'},
                {'kind':'programming_verification','severity':'blocking','question_ids':[p['id']],'message':'fixture transport','failure':{'code':'transport','retryable':True}}
            ] if calls['inspect']==1 else []}
        def author(role,instructions,payload):
            self.assertEqual({q['id'] for q in payload['questions']},{qid})
            return {'patches':[{'id':qid,'changes':{'explanation':'修复后的依据'},'reason':'fixture'}]}
        with patch('courseagent.agent_roles.ask_role',side_effect=author),patch('courseagent.verification_tools.verify_ordinary_answers',SimpleNamespace(invoke=lambda a:{'document':a['document']})),patch('courseagent.verification_tools.verify_programming_answers',SimpleNamespace(invoke=lambda a:{'document':a['document']})):
            result=build_agent(planner,checker,lambda *a:{'action':'fix','reason':'fix ordinary and retry coding'}).invoke({'document':d,'request':{'prompt':'fixture'},'sources':[],'rounds':0,'events':[]})
        self.assertEqual(result['action'],'deliver');self.assertEqual(calls['compose'],1)
        self.assertTrue(result['document']['programming_questions'][0]['selected']);self.assertNotIn('avoid_ids',result)

    def test_ready_program_branch_starts_verifying_while_ordinary_search_is_pending(self):
        from courseagent.workflow import parallel_sources
        ready=threading.Event();o=ordinary();o['selected']=False;p=question();p['selected']=False
        doc={'questions':[o],'programming_questions':[p]}
        state={'document':doc,'request':{'verify_as_ready':True},'spec':{'counts':{'1':1},'programming_count':1},'sources':[],'trace':[]}
        class OrdinaryGraph:
            def stream(self,current,*args,**kwargs):
                if not ready.wait(timeout=3):raise AssertionError('programming verification waited for the ordinary branch')
                yield {'assembled':{'result':copy.deepcopy(doc),'candidates':[copy.deepcopy(o)],'web':{}}}
        def verify_program(args):
            args['document']['programming_questions'][0]['verification_state']={'fixture_checked':True};ready.set()
            return {'document':args['document']}
        def verify_ordinary(args):
            self.assertTrue(args['document']['questions'][0]['selected'])
            args['document']['questions'][0]['verification_state']={'fixture_checked':True}
            return {'document':args['document']}
        with patch('courseagent.workflow.build_graph',return_value=OrdinaryGraph()),patch('courseagent.programming_sourcing.source_programming_round',return_value={'document':copy.deepcopy(doc),'programming_candidates':[p]}),patch('courseagent.programming_sourcing.programming_next_step',return_value='done'),patch('courseagent.verification_tools.verify_programming_answers',SimpleNamespace(invoke=verify_program)),patch('courseagent.verification_tools.verify_ordinary_answers',SimpleNamespace(invoke=verify_ordinary)):
            result=parallel_sources(state)
        self.assertTrue(result['document']['questions'][0]['verification_state']['fixture_checked'])
        self.assertTrue(result['document']['programming_questions'][0]['verification_state']['fixture_checked'])

    def run_task(self, forever=False):
        from courseagent.autonomous_agent import build_agent
        from tests.test_autonomous_agent import document
        counts=Counter();d=document();qid=d['questions'][0]['id']
        def planner(d,*args):counts['compose']+=1;return d
        def checker(d):
            counts['inspect']+=1
            failure=forever or counts['inspect']==1
            return {'blocking':failure,'issues':[{'kind':'ordinary_answer_uncertain','severity':'blocking','question_ids':[qid],
                'message':'fixture transport','failure':{'code':'transport','action':'retry_verification','retryable':True}}] if failure else []}
        def verify(args):counts['verify']+=1;return {'document':args['document']}
        decider=Mock(side_effect=AssertionError('deterministic failure routing must not spend model call'))
        with patch('courseagent.verification_tools.verify_ordinary_answers',SimpleNamespace(invoke=verify)),patch('courseagent.verification_tools.verify_programming_answers',SimpleNamespace(invoke=lambda a:{'document':a['document']})):
            result=build_agent(planner,checker,decider).invoke({'document':d,'request':{'prompt':'fixture'},'sources':[],'rounds':0,'events':[]})
        return result,counts

    def test_transient_failure_retries_verification_without_replanning(self):
        result,counts=self.run_task()
        self.assertEqual(result['action'],'deliver');self.assertEqual(counts['compose'],1)
        self.assertEqual(counts['verify'],1);self.assertEqual(result['events'][0]['action'],'retry_verification')

    def test_new_stage_has_its_own_retry_allowance(self):
        from courseagent.autonomous_agent import build_agent
        from tests.test_autonomous_agent import document
        d=document();qid=d['questions'][0]['id'];calls=Counter()
        def checker(doc):
            calls['inspect']+=1
            stage='blind_solve' if calls['inspect']<=2 else 'answer_compare'
            doc['questions'][0]['verification_state']={'stage':stage}
            blocking=calls['inspect']<=4
            return {'blocking':blocking,'issues':[{'kind':'ordinary_answer_uncertain','severity':'blocking','question_ids':[qid],'message':'fixture','failure':{'code':'transport','action':'retry_verification','retryable':True}}] if blocking else []}
        def verify(args):calls['verify']+=1;return {'document':args['document']}
        with patch('courseagent.verification_tools.verify_ordinary_answers',SimpleNamespace(invoke=verify)),patch('courseagent.verification_tools.verify_programming_answers',SimpleNamespace(invoke=lambda a:{'document':a['document']})):
            result=build_agent(lambda doc,*args:doc,checker,Mock(side_effect=AssertionError('no replanning'))).invoke({'document':d,'request':{'prompt':'fixture'},'sources':[],'rounds':0,'events':[]})
        self.assertEqual(result['action'],'deliver')
        self.assertEqual(calls['verify'],4)

    def test_persistent_transport_pauses_instead_of_replacing_question(self):
        result,counts=self.run_task(True)
        self.assertEqual(result['action'],'stop');self.assertEqual(counts['compose'],1)
        self.assertEqual(counts['verify'],2);self.assertNotIn('avoid_ids',result)


if __name__=='__main__':unittest.main()
