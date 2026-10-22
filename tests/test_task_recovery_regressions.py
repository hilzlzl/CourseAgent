"""Regressions for interleaved counts and an exhausted format retry loop."""
import copy
import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

from courseagent.autonomous_agent import build_agent
from tests.test_autonomous_agent import document


class TaskRecoveryTests(unittest.TestCase):
    def state(self):
        return {'document':document(),'request':{'prompt':'测试作业'},'sources':[],'events':[],'rounds':0}

    def passthrough(self,stack):
        for name in ('verify_ordinary_answers','verify_programming_answers'):
            stack.enter_context(patch('courseagent.verification_tools.'+name,
                MagicMock(invoke=lambda data:{'document':data['document']})))

    def checker(self,qid,code='format'):
        return lambda doc:{'blocking':True,'issues':[{'kind':'ordinary_answer_uncertain','severity':'blocking',
            'question_ids':[qid],'message':'验证尚未完成','failure':{'code':code,'action':'retry_verification','retryable':True}}]}

    def test_exhausted_format_retry_really_removes_only_target(self):
        s=self.state();qid=next(q['id'] for q in s['document']['questions'] if q.get('selected'))
        original={q['id'] for q in s['document']['questions'] if q.get('selected')}
        graph=build_agent(planner=lambda d,r,s:d,checker=self.checker(qid))
        with ExitStack() as stack:
            self.passthrough(stack)
            updates=graph.stream(s,{'recursion_limit':64},stream_mode='updates')
            try:
                for change in updates:
                    if 'repair' in change:
                        result=change['repair'];break
                else:self.fail('Replacement did not happen')
            finally:updates.close()
        self.assertIn(qid,result['avoid_ids'])
        self.assertEqual({q['id'] for q in result['document']['questions'] if q.get('selected')},original-{qid})

    def test_global_decision_limit_cannot_be_bypassed_by_retry_branch(self):
        s=self.state();qid=s['document']['questions'][0]['id']
        graph=build_agent(planner=lambda d,r,s:d,checker=self.checker(qid),max_decisions=1)
        with ExitStack() as stack:
            self.passthrough(stack);out=graph.invoke(s,{'recursion_limit':40})
        self.assertEqual([e['action'] for e in out['events']],['retry_verification','stop'])
        self.assertIn('防循环',out['reason'])

    def test_no_progress_limit_precedes_another_format_replacement(self):
        s=self.state();qid=s['document']['questions'][0]['id'];fixed=copy.deepcopy(s['document'])
        with ExitStack() as stack:
            self.passthrough(stack)
            stack.enter_context(patch('courseagent.workflow.plan',return_value=fixed))
            out=build_agent(checker=self.checker(qid)).invoke(s,{'recursion_limit':64})
        self.assertEqual(out['action'],'stop');self.assertIn('连续3轮',out['reason'])
        self.assertLessEqual(len(out['events']),5)

    def test_explicit_resume_gets_new_decision_window_and_preserves_history(self):
        s=self.state();qid=s['document']['questions'][0]['id']
        history=[{'action':'replace','round':i} for i in range(70)]
        s.update(events=copy.deepcopy(history),resume=True,no_gain_rounds=90)
        graph=build_agent(planner=lambda d,r,s:d,checker=self.checker(qid),max_decisions=1)
        with ExitStack() as stack:
            self.passthrough(stack);out=graph.invoke(s,{'recursion_limit':40})
        self.assertEqual(out['events'][:70],history)
        self.assertEqual([e['action'] for e in out['events'][70:]],['retry_verification','stop'])
        self.assertIn('防循环',out['reason'])

    def test_transport_failure_still_preserves_candidate_after_retries(self):
        s=self.state();qid=s['document']['questions'][0]['id']
        with ExitStack() as stack:
            self.passthrough(stack)
            out=build_agent(planner=lambda d,r,s:d,checker=self.checker(qid,'transport')).invoke(s)
        self.assertEqual(out['action'],'stop');self.assertNotIn('replace',[e['action'] for e in out['events']])
        self.assertTrue(next(q for q in out['document']['questions'] if q['id']==qid)['selected'])

    def test_explicit_resume_of_source_budget_stop_reenters_planning(self):
        s=self.state();s.update(resume=True,rounds=7,events=[{'action':'stop','round':7}])
        s['document']['plan']['complete']=False
        s['document']['web_search']={'search_exhausted':True,'read_attempts':48}
        with patch('courseagent.workflow.plan',return_value=s['document']) as plan:
            stream=build_agent().stream(s,stream_mode='updates')
            try:
                for update in stream:
                    if 'compose' in update:break
                else:self.fail('Explicit continuation did not reach planning')
            finally:stream.close()
        request=plan.call_args.args[1]
        self.assertTrue(request['continue_web'])
        self.assertFalse(request['automatic_continuation'])
        self.assertEqual(plan.call_args.args[0]['web_search']['read_attempts'],48)

    def test_source_resume_does_not_skip_budget_initialization_for_spare_candidates(self):
        from courseagent.workflow import parallel_sources
        s=self.state();doc=s['document'];spec=doc['plan']['spec']
        doc['plan']['request']=s['request']['prompt']
        doc['web_search']={'search_exhausted':True,'candidate_ids':[q['id'] for q in doc['questions']]}
        spec['locked_ids']=[q['id'] for q in doc['questions'] if q.get('selected')]
        s.update(spec=spec,trace=[])
        s['request'].update(source_mode='web',continue_web=True,automatic_continuation=False)
        graph=MagicMock();graph.stream.return_value=[]
        with patch('courseagent.workflow.build_graph',return_value=graph) as build:
            parallel_sources(s)
        build.assert_called_once()
        graph.stream.assert_called_once()

    def test_explicit_resume_of_programming_exhaustion_reenters_planning(self):
        s=self.state();s.update(resume=True,rounds=4,events=[{'action':'stop','round':4}])
        s['document']['plan']['complete']=False
        s['document']['programming_search']={'search_exhausted':True,'attempted_urls':['https://leetcode.cn/problems/old/']}
        retained=copy.deepcopy(s['document'])
        with patch('courseagent.workflow.plan',return_value=s['document']) as plan:
            stream=build_agent().stream(s,stream_mode='updates')
            try:
                for update in stream:
                    if 'compose' in update:break
                else:self.fail('Programming continuation did not reach planning')
            finally:stream.close()
        request=plan.call_args.args[1]
        self.assertTrue(request['continue_web'])
        self.assertFalse(request['automatic_continuation'])
        self.assertEqual(plan.call_args.args[0],retained)

    def test_verification_stage_advancement_counts_as_progress(self):
        s=self.state();qid=s['document']['questions'][0]['id'];stage=[0]
        def verify(data):
            stage[0]+=1
            data['document']['questions'][0]['verification_state']={'stage':'stage'+str(stage[0]),'status':'running'}
            return {'document':data['document']}
        def checker(doc):
            return {'blocking':False,'issues':[]} if stage[0]>=5 else self.checker(qid)(doc)
        with ExitStack() as stack:
            self.passthrough(stack)
            stack.enter_context(patch('courseagent.verification_tools.verify_ordinary_answers',MagicMock(invoke=verify)))
            stack.enter_context(patch('courseagent.workflow.plan',return_value=s['document']))
            out=build_agent(checker=checker).invoke(s,{'recursion_limit':64})
        self.assertEqual(out['action'],'deliver')
        self.assertEqual(out['no_gain_rounds'],0)

    def test_new_source_attempts_are_progress_but_repeated_counts_are_not(self):
        s=self.state();attempts=[]
        def plan(doc,request,sources,**kwargs):
            attempts.append('query'+str(len(attempts)))
            doc['programming_search']={'query_history':attempts.copy()}
            return doc
        def checker(doc):
            return {'blocking':False,'issues':[]} if len(attempts)>=5 else {
                'blocking':True,'issues':[{'kind':'count','question_ids':[],'message':'缺1题'}]}
        with ExitStack() as stack:
            self.passthrough(stack)
            stack.enter_context(patch('courseagent.workflow.plan',side_effect=plan))
            out=build_agent(checker=checker).invoke(s,{'recursion_limit':64})
        self.assertEqual(out['action'],'deliver')
        self.assertEqual(out['no_gain_rounds'],0)

    def test_advancing_bank_pages_counts_as_progress_without_new_candidates(self):
        s=self.state();pages=[]
        def plan(doc,request,sources,**kwargs):
            pages.append(len(pages)*20)
            doc['programming_search']={'native_pool':{'next_offset':pages[-1]+20,'has_more':True}}
            return doc
        def checker(doc):
            return {'blocking':False,'issues':[]} if len(pages)>=5 else {
                'blocking':True,'issues':[{'kind':'count','question_ids':[],'message':'缺1题'}]}
        with ExitStack() as stack:
            self.passthrough(stack)
            stack.enter_context(patch('courseagent.workflow.plan',side_effect=plan))
            out=build_agent(checker=checker,decider=lambda *a:{'action':'search','reason':'继续下一页'}).invoke(s,{'recursion_limit':64})
        self.assertEqual(out['action'],'deliver')
        self.assertEqual(out['no_gain_rounds'],0)

    def test_pending_programming_branch_keeps_previous_pool_even_if_ordinary_has_empty_field(self):
        from courseagent.agent_jobs import merge_source_progress
        from tests.test_programming_questions import ProgrammingTests
        doc=document();coding=ProgrammingTests().sample();coding.update(id='retained-coding',selected=True)
        doc['programming_questions']=[coding];doc['plan']['spec']['programming_count']=1
        ordinary={'document':copy.deepcopy(doc),'request':{},'spec':doc['plan']['spec'],'trace':[],
                  'programming_candidates':[],'candidates':doc['questions']}
        ordinary['document']['programming_questions'][0]['selected']=False
        merged=merge_source_progress(ordinary,{'ordinary':ordinary},baseline=doc)
        self.assertEqual(merged['plan']['programming_count']['selected'],1)
        # An explicit empty programming result is authoritative, not monotonic.
        coding_branch={'document':copy.deepcopy(doc),'programming_candidates':[]}
        merged=merge_source_progress(ordinary,{'ordinary':ordinary,'programming':coding_branch},baseline=doc)
        self.assertEqual(merged['plan']['programming_count']['selected'],0)

    def test_ordinary_candidate_callback_does_not_publish_programming_zero(self):
        from courseagent.workflow import build_graph
        from courseagent.model_client import model_budget
        s={'document':{'questions':[]},'request':{'source_mode':'web'},'sources':[],
           'trace':[],'spec':{'counts':{'1':1},'programming_count':4}}
        observed=[]
        with model_budget() as budget,patch('courseagent.web_questions.plan_search',return_value={'web':{}}),\
             patch('courseagent.ordinary_web_search.collect_question_sets',return_value={}),\
             patch('courseagent.web_questions.extract_candidates',return_value={}),\
             patch('courseagent.ordinary_answers.complete_answers',return_value={}),\
             patch('courseagent.question_adaptation.adapt_questions',return_value={}),\
             patch('courseagent.web_replenishment.check_gaps',return_value={'web':{'next_step':'done'}}):
            budget['on_candidates']=observed.append
            build_graph(_ordinary_branch=True).invoke(s)
        self.assertTrue(observed);self.assertTrue(all('programming_count' not in row for row in observed))

    def test_interleaved_snapshots_keep_four_until_programming_branch_removes_them(self):
        from courseagent.agent_jobs import merge_source_progress
        from tests.test_programming_questions import ProgrammingTests
        doc=document();doc['plan']['spec']['programming_count']=4
        doc['programming_questions']=[]
        for i in range(4):
            q=ProgrammingTests().sample();q.update(id='coding-'+str(i),selected=True)
            doc['programming_questions'].append(q)
        ordinary={'document':copy.deepcopy(doc),'request':{},'spec':doc['plan']['spec'],
                  'trace':[],'programming_candidates':[],'candidates':doc['questions']}
        ordinary['document']['programming_questions']=[]
        branches={};counts=[]
        for branch,remaining in [('ordinary',None),('ordinary',None),('programming',4),
                                 ('ordinary',None),('programming',3),('ordinary',None),
                                 ('programming',0),('ordinary',None)]:
            current=copy.deepcopy(ordinary) if branch=='ordinary' else {
                'document':copy.deepcopy(doc),'programming_candidates':copy.deepcopy(doc['programming_questions'][:remaining])}
            branches[branch]=current
            merged=merge_source_progress(current,branches,baseline=doc)
            counts.append(merged['plan']['programming_count']['selected'])
        self.assertEqual(counts,[4,4,4,4,3,3,0,0])


if __name__=='__main__':unittest.main()
