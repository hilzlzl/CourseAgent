"""Regression for novel candidates starving usable, previously selected sources."""
import copy
import json
import time
import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

from courseagent.model_client import model_budget
from courseagent.programming_search_plan import bank_query_schedule
from courseagent.programming_sourcing import candidate_fallback, source_programming
from courseagent.selection_policy import canonical_source, link_priority


class CandidateFallbackTests(unittest.TestCase):
    def test_trigger_boundary_and_single_event(self):
        report={'events':[], 'candidate_fallback':{'active':False,'unproductive_reads':11}}
        self.assertFalse(candidate_fallback(report,6))
        report['candidate_fallback']['unproductive_reads']=12
        self.assertTrue(candidate_fallback(report,6))
        report['candidate_fallback']['unproductive_reads']=0
        self.assertTrue(candidate_fallback(report,6))
        self.assertEqual(len(report['events']),1)

    def test_call_and_time_limits_use_sourcing_reserve(self):
        for trigger in ('calls','time'):
            with self.subTest(trigger=trigger), model_budget(160,2400) as budget:
                report={'events':[]}
                self.assertFalse(candidate_fallback(report,6))
                if trigger=='calls':budget['calls']=92  # 140 - 48; 20 checking calls untouched.
                else:budget['deadline']=time.monotonic()+budget['reserved_seconds']+179
                self.assertTrue(candidate_fallback(report,6))
                self.assertEqual(report['candidate_fallback']['reason'],
                    'sourcing_calls_low' if trigger=='calls' else 'sourcing_time_low')

    def links(self,names):
        return [{'url':'https://leetcode.cn/problems/'+name+'/', 'title':name,
                 'discovery_topics':['排序算法']} for name in names]

    def state(self,names,streak=12):
        links=self.links(names)
        return {'document':{'name':'fallback regression','questions':[],'programming_questions':[],
            'programming_search':{'query_history':bank_query_schedule(['排序算法'],0,[]),
                'candidate_fallback':{'active':False,'unproductive_reads':streak},
                'native_pool':{'pending_links':links,'next_offset':20,'has_more':True},
                'provider_pages':{'nowcoder':{'has_more':True,'next_offset':20,
                    'query':'排序算法 site:nowcoder.com/acm/problem/'}}}},
            'spec':{'topics':['排序算法'],'counts':{},'programming_count':1},'trace':[],
            'request':{'prompt':'排序算法 1 道编程题','source_mode':'web','use_model':True,
                'continue_web':True,'fresh_questions':True,
                'selection_policy':{'seed':'fixed','history':{'counts':{
                    'url:'+canonical_source(links[-1]['url']):5}}}}}

    def run_source(self,state,fit=True,gate=True,attempts=12):
        from tests.test_programming_questions import ProgrammingTests
        reads=[]
        def read(payload):
            reads.append(payload['url'])
            return {'page':{'url':payload['url'],'text':'排序算法的输入输出','source_metadata':{}},
                    'cache_hit':False}
        def native(page,languages):
            q=ProgrammingTests().sample()
            q.update(id=page['url'],title=page['url'].split('/')[-2],knowledge='排序算法',
                     description=q['description']+page['url'],selected=False,
                     source_refs=[{'url':page['url']}])
            return q
        with ExitStack() as stack:
            stack.enter_context(patch('courseagent.model_client.model_status',return_value={'configured':True}))
            stack.enter_context(patch('courseagent.programming_sourcing.LIMITS',
                {'search_rounds':1,'read_attempts':attempts,'pages':20,'model_calls':6}))
            search=stack.enter_context(patch('courseagent.retrieval_tools.search_question_source',MagicMock(
                invoke=MagicMock(side_effect=AssertionError('Must consume pending candidates first')))))
            stack.enter_context(patch('courseagent.retrieval_tools.read_public_question_page',MagicMock(
                invoke=MagicMock(side_effect=read))))
            stack.enter_context(patch('courseagent.native_questions.leetcode_candidate',side_effect=native))
            fit_mock=stack.enter_context(patch('courseagent.programming_sourcing.native_course_fit',
                side_effect=fit if callable(fit) else None,return_value=fit))
            gate_mock=stack.enter_context(patch('courseagent.programming_sourcing.executable_source_gate',
                side_effect=gate if callable(gate) else None,return_value=gate))
            result=source_programming(state)
        search.invoke.assert_not_called()
        return result,reads,fit_mock,gate_mock

    def test_default_keeps_novelty_but_fallback_promotes_known_source(self):
        new,old=self.links(['new','known'])
        context=self.state(['new','known'])['request']['selection_policy']
        self.assertLess(link_priority(new,[],context,['排序算法']),
                        link_priority(old,[],context,['排序算法']))
        self.assertLess(link_priority(old,[],context,['排序算法'],fallback=True),
                        link_priority(new,[],context,['排序算法'],fallback=True))

    def test_fallback_stops_pagination_and_still_runs_both_gates(self):
        state=self.state(['new','known'])
        result,reads,fit,gate=self.run_source(state)
        self.assertEqual(reads,[self.links(['known'])[0]['url']])
        fit.assert_called_once();gate.assert_called_once()
        report=result['document']['programming_search']
        self.assertEqual(report['candidate_count'],1)
        self.assertEqual(report['candidate_fallback']['unproductive_reads'],0)
        self.assertTrue(report['candidate_fallback']['active'])
        self.assertEqual(report['native_pool']['pending_links'],self.links(['new']))
        self.assertEqual(report['provider_pages']['nowcoder']['next_offset'],20)
        self.assertIn('candidate_fallback_accepted',[e['status'] for e in report['events']])

    def test_known_source_with_bad_fit_or_failed_execution_is_not_admitted(self):
        for failed in ('fit','gate'):
            with self.subTest(failed=failed):
                state=self.state(['new','known'])
                kwargs={failed:lambda q,*args:q['title']!='known'}
                result,reads,fit,gate=self.run_source(state,**kwargs)
                self.assertEqual([q['title'] for q in result['programming_candidates']],['new'])
                self.assertEqual(reads,[self.links(['known'])[0]['url'],self.links(['new'])[0]['url']])
                self.assertEqual(fit.call_count,2)
                self.assertEqual(gate.call_count,1 if failed=='fit' else 2)

    def test_streak_survives_batches_and_switches_before_thirteenth_read(self):
        state=self.state(['novel','other','known'],streak=11)
        # No extra query scheduled, so the first batch only drains pending links.
        state['document']['programming_search']['provider_pages']={}
        first,reads,_,_=self.run_source(state,fit=False,attempts=1)
        self.assertNotIn('known',reads[0])
        state['document']=first['document']
        # JSON roundtrip mirrors persisted checkpoint recovery.
        state=json.loads(json.dumps(state))
        second,reads,_,_=self.run_source(state)
        self.assertEqual(reads[0],self.links(['known'])[0]['url'])
        self.assertEqual(len(second['programming_candidates']),1)

    def test_accepted_new_source_breaks_consecutive_failure_streak(self):
        state=self.state(['new','known'],streak=11)
        state['document']['programming_search']['provider_pages']={}
        result,reads,_,_=self.run_source(state)
        self.assertNotIn('known',reads[0])
        self.assertEqual(result['document']['programming_search']['candidate_fallback']['unproductive_reads'],0)
        self.assertFalse(result['document']['programming_search']['candidate_fallback']['active'])

    def test_empty_pending_pool_can_discover_more_in_fallback(self):
        state=self.state(['old','known'])
        state['document']['programming_search']['native_pool']['pending_links']=[]
        with patch('courseagent.model_client.model_status',return_value={'configured':True}), \
             patch('courseagent.algorithm_sources.search_questions',return_value=([],False,{'has_more':False})) as search, \
             patch('courseagent.nowcoder_sources.search_questions',return_value=([],False)):
            # Direct tool mock keeps this a network-free exhaustion check.
            with patch('courseagent.retrieval_tools.search_question_source',MagicMock(invoke=MagicMock(
                return_value={'items':[],'cache_hit':False,'pagination':{'has_more':False}}))) as tool:
                source_programming(state)
        self.assertGreaterEqual(tool.invoke.call_count,1)


if __name__=='__main__':unittest.main()
