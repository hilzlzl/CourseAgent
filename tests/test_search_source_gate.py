import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from courseagent.ordinary_search_plan import plan_queries
from courseagent.web_questions import plan_search, search_read
from courseagent.programming_sourcing import executable_source_gate, source_programming
from courseagent.programming_verification import build_verification_graph
from courseagent.verification_state import StageCache
from courseagent.code_sandbox import available, execute
from tests.test_source_verification import reference_question
from tests.test_programming_verification import responses, VALIDATOR


class OrdinarySearchAllocationTests(unittest.TestCase):
    def state(self):
        return {'request':{'source_mode':'web','verify_as_ready':True},
                'spec':{'topics':['栈','队列'],'counts':{'1':5,'3':5}},
                'document':{'questions':[]},'sources':[],'trace':[]}

    def test_each_requested_type_survives_small_initial_batch_and_supervisor_override(self):
        state=self.state()
        state['request']['agent_queries']=['栈 队列 通用资料']*3
        state['spec']['teaching_plan']={'search_intents':[
            {'type':'1','query':'栈 出栈序列 单选题'},
            {'type':'3','query':'循环队列 空满条件 判断题'}]}
        with patch('courseagent.model_client.model_status',return_value={'configured':True}):
            web=plan_search(state)['web']
        self.assertEqual([r['type'] for r in web['query_plan']],['1','3'])
        self.assertTrue(all(r['origin']=='model' for r in web['query_plan']))
        self.assertIn('选择题',web['queries'][0]);self.assertIn('判断题',web['queries'][1])
        self.assertIn('出栈序列',web['queries'][0])
        self.assertIn('循环队列',web['queries'][1]);self.assertNotIn('栈',web['queries'][1])
        self.assertTrue(all('通用资料' not in q for q in web['queries']))

    def test_five_types_are_not_truncated_to_two_queries(self):
        state=self.state();state['spec']['counts']={str(t):1 for t in range(1,6)}
        with patch('courseagent.model_client.model_status',return_value={'configured':True}):
            web=plan_search(state)['web']
        self.assertEqual({r['type'] for r in web['query_plan']},{'1','2','3','4','5'})
        self.assertEqual(web['max_pages'],5)

    def test_large_ordinary_request_gets_a_real_initial_page_pool(self):
        state=self.state();state['spec']['counts']={'1':10,'4':10}
        with patch('courseagent.model_client.model_status',return_value={'configured':True}):
            web=plan_search(state)['web']
        self.assertGreaterEqual(web['max_pages'],6)
        self.assertGreaterEqual(web['max_attempts'],web['max_pages']*2)
        self.assertGreaterEqual(len(web['query_plan']),3)

    def test_gap_search_targets_only_missing_types_and_avoids_previous_queries(self):
        spec=self.state()['spec'];initial=plan_queries(spec)
        previous=[r['query'] for r in initial]
        rows=plan_queries(spec,{'3':2},previous,round_no=1)
        self.assertEqual([r['type'] for r in rows if r['type']],['3'])
        self.assertTrue(set(r['query'] for r in rows).isdisjoint(previous))
        self.assertNotIn('答案',rows[0]['query'])

    def test_page_tiers_and_cached_pages_do_not_starve_the_second_type(self):
        state=self.state();queries=['栈 单选题','队列 判断题']
        state['web']={'queries':queries,'pages':[],'events':[],'cache_hits':0,'max_pages':2}
        groups=[([{'url':'https://cs.example.edu.cn/choice1'},{'url':'https://cs.example.edu.cn/choice2'}],False),
                ([{'url':'https://blog.example/judgment'}],False)]
        def read(url):
            return {'url':url,'title':'栈和队列习题','text':'栈遵循后进先出，队列遵循先进先出。'},False
        with patch('courseagent.web_questions.search',side_effect=groups),patch('courseagent.source_adapters.read_question_page',side_effect=read),\
             patch('courseagent.web_questions.known_source_links',return_value=[{'url':'https://cache.example/a','query':'缓存'}]):
            web=search_read(state)['web']
        self.assertEqual([p['query'] for p in web['pages']],queries)

    def test_model_keyword_planning_uses_existing_goal_call(self):
        from courseagent.teaching_plan import plan_goals
        state=self.state();state['request'].update(use_model=True,prompt='栈和队列5单选5判断')
        reply={'goals':[{'name':'基本操作','keywords':['入栈','出栈']}],
               'search_intents':[{'type':'1','query':'栈 出栈序列 单选题'},
                                 {'type':'3','query':'队列 空满条件 判断题'}]}
        with tempfile.TemporaryDirectory() as folder,patch('courseagent.web_questions.CACHE',Path(folder)),\
             patch('courseagent.model_client.model_status',return_value={'model':'fixture'}),\
             patch('courseagent.model_client.chat_json',return_value=reply) as ask:
            result=plan_goals(state)
        self.assertEqual(ask.call_count,1)
        self.assertEqual(len(result['spec']['teaching_plan']['search_intents']),2)


@unittest.skipUnless(available(),'Linux isolation unavailable')
class ExecutableSourceGateTests(unittest.TestCase):
    def test_model_output_limit_is_not_misclassified_as_an_unusable_source(self):
        report={'events':[],'model_calls':0}
        with tempfile.TemporaryDirectory() as folder,patch('courseagent.programming_verification.ROOT',Path(folder)),\
             patch('courseagent.programming_sourcing.ask_role',side_effect=ValueError('模型输出达到 token 上限')):
            with self.assertRaises(ValueError) as caught:executable_source_gate(reference_question(),report)
        self.assertTrue(caught.exception.source_gate_interrupted)
        self.assertFalse(any(r['status']=='source_candidate_replaced' for r in report['events']))

    def test_sandbox_outage_does_not_trigger_search_for_different_questions(self):
        report={'events':[],'model_calls':0}
        with patch('courseagent.code_sandbox.available',return_value=False):
            with self.assertRaises(RuntimeError) as caught:executable_source_gate(reference_question(),report)
        self.assertTrue(caught.exception.source_gate_interrupted)
        self.assertFalse(any(r['status']=='source_candidate_replaced' for r in report['events']))

    def test_strict_verification_without_source_routes_to_replacement(self):
        q=reference_question();q.pop('source_reference')
        with patch('courseagent.source_references.discover_reference',return_value=None):
            state=build_verification_graph(lambda *_:self.fail('No heavy fallback allowed'),execute,
                require_source=True).invoke({'question':q})
        self.assertEqual(state['result']['failure']['action'],'replace')

    def test_missing_source_never_generates_any_solution(self):
        q=reference_question();q.pop('source_reference');report={'events':[]}
        with patch('courseagent.source_references.discover_reference',return_value=None),\
             patch('courseagent.programming_verification.ask_role',side_effect=AssertionError('No model needed')):
            self.assertFalse(executable_source_gate(q,report))
        self.assertEqual(report['events'][-1]['status'],'source_candidate_replaced')

    def test_bad_public_samples_replace_without_heavy_fallback(self):
        q=reference_question();q['source_reference']['code']='import sys\nprint(999999)'
        q['source_protocol']='standard_io'
        q['source_reference']['code']='s=input()\nprint(999999)'
        calls=[]
        def ask(role,*_):
            calls.append(role);self.fail('Bad source should be rejected before assessment/design')
        state=build_verification_graph(ask,execute,require_source=True,preflight_only=True).invoke({'question':q})
        self.assertFalse(state['result']['passed'])
        self.assertEqual(state['result']['failure']['action'],'replace');self.assertEqual(calls,[])

    def test_preflight_adapter_is_reused_by_final_verification(self):
        calls=[];answers=responses()
        def ask(role,prompt,data):
            calls.append(role)
            if role=='solver':
                return {'prelude_code':'pass','driver_code':'import sys\nprint(Solution().total(list(map(int,sys.stdin.read().split()))))'}
            if role=='test_designer':return {**answers[role],'input_validator_code':VALIDATOR}
            return answers[role]
        q=reference_question();q['source_execution_policy']='replace_on_failure'
        with tempfile.TemporaryDirectory() as folder,patch('courseagent.programming_verification.ROOT',Path(folder)):
            cache=StageCache(Path(folder)/'cache')
            preflight=build_verification_graph(ask,execute,stage_cache=cache,require_source=True,preflight_only=True).invoke({'question':q})
            self.assertTrue(preflight['result']['passed']);self.assertEqual(calls,['solver'])
            result=build_verification_graph(ask,execute,stage_cache=cache,require_source=True).invoke({'question':q})
        self.assertTrue(result['result']['passed']);self.assertEqual(calls,['solver','assessment_planner','test_designer'])

    def test_source_failure_on_hidden_inputs_replaces_without_mutation_generation(self):
        q=reference_question();answers=responses();calls=[]
        def ask(role,prompt,data):
            calls.append(role)
            if role=='solver':
                return {'prelude_code':'pass','driver_code':'import sys\na=list(map(int,sys.stdin.read().split()))\nif any(x<0 for x in a):raise ValueError("adapter bug")\nprint(Solution().total(a))'}
            if role=='test_designer':return {**answers[role],'input_validator_code':VALIDATOR}
            return answers[role]
        with tempfile.TemporaryDirectory() as folder,patch('courseagent.programming_verification.ROOT',Path(folder)):
            state=build_verification_graph(ask,execute,require_source=True).invoke({'question':q})
        self.assertFalse(state['result']['passed']);self.assertEqual(state['result']['failure']['action'],'replace')
        self.assertNotIn('mutation_designer',calls);self.assertNotIn('validator',calls)

    def test_autonomous_sourcing_skips_codeless_problem_and_accepts_next(self):
        def page(name,source):
            return {'url':'https://leetcode.cn/problems/'+name+'/', 'title':'栈'+name,
                'text':'栈：输入一个整数，返回同一个整数。范围1至100。',
                'source_statement':'栈练习：输入一个整数，返回同一个整数。范围1至100。',
                'source_examples':[{'input':'1','output':'1'}],
                'source_metadata':{'provider':'leetcode','tags':['栈'],'interface_kind':'function',
                    'interface':{'name':'identity','params':[{'name':'x','type':'integer'}],'return':{'type':'integer'}}},
                'reference_solutions':[{'url':'https://leetcode.cn/problems/'+name+'/solutions/a/',
                    'status':'public_editorial','language':'Python',
                    'code':'class Solution:\n def identity(self,x):return x'}] if source else []}
        missing,good=page('missing',False),page('good',True)
        prose_calls=[]
        def prose(prompt,data):
            if 'adapted_statement' in data:
                prose_calls.append('audit');return {'passed':True,'issues':[]}
            prose_calls.append('author')
            return {'task':'读取一个整数 x，输出相同的整数 x。',
                    'methods':[{'params':[{'name':'x','label':'输入整数 x','empty':'unspecified','empty_evidence':''}],
                                'result':'相同的整数'}]}
        state={'request':{'prompt':'栈 1道编程题','source_mode':'web','verify_as_ready':True,'fresh_questions':True},
               'spec':{'topics':['栈'],'counts':{},'programming_count':1},
               'document':{'questions':[]},'trace':[]}
        with tempfile.TemporaryDirectory() as folder,patch('courseagent.programming_verification.ROOT',Path(folder)),\
             patch('courseagent.web_questions.CACHE',Path(folder)/'web'),\
             patch('courseagent.algorithm_sources.search_questions',return_value=([{'url':missing['url']},{'url':good['url']}],False)),\
             patch('courseagent.algorithm_sources.read_question',return_value=(missing,False)),\
             patch('courseagent.web_questions.search',return_value=([],False)),\
             patch('courseagent.source_adapters.read_question_page',side_effect=lambda url:({missing['url']:missing,good['url']:good}[url],False)),\
             patch('courseagent.model_client.model_status',return_value={'configured':True}),\
             patch('courseagent.model_client.chat_json',side_effect=prose):
            result=source_programming(state)
        self.assertEqual([q['title'] for q in result['programming_candidates']],['栈good'])
        self.assertEqual(result['document']['programming_search']['missing'],0)
        self.assertTrue(any(e['status']=='source_candidate_replaced' for e in result['document']['programming_search']['events']))
        self.assertEqual(prose_calls,['author','audit'])


if __name__=='__main__':unittest.main()
