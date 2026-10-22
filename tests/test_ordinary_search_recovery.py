"""Exhausted search paths must recover without losing validated questions."""
import copy
import unittest
from unittest.mock import patch

from courseagent.model_client import model_budget
from courseagent.ordinary_search_plan import question_set_queries
from courseagent.ordinary_search_recovery import recover_queries
from tests.test_question_set_search import tool
from tests import test_question_set_search as fixtures


class SearchRecoveryTests(unittest.TestCase):
    def state(self):
        fixture=fixtures.QuestionSetSearchTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        s=copy.deepcopy(fixture.state)
        s['web'].update(queries=[],searched_queries=['排序 判断题 答案'])
        return s,fixture

    def response(self):
        return {'queries':[{'type':'3','query':'排序 稳定性 判断正误 练习题','reason':'换用题型同义表达，聚焦课程内稳定性'}]}

    def test_planned_topic_does_not_get_narrowed_to_one_normalized_concept(self):
        spec={'topics':['二叉树的基本性质','二叉树的先序遍历','利用遍历序列构造二叉树'],
              'counts':{'3':2},'teaching_plan':{
                  'concept_plan':{'concepts':[{'id':'binary_tree_traversal','name':'二叉树遍历'}]},
                  'goals':[{'keywords':['完全二叉树','叶子结点']}],
                  'search_intents':[{'type':'3','query':'二叉树 判断题 完全二叉树 叶子结点'}]}}
        # Even when the concept catalog prefers traversal, a teacher-requested
        # property topic must be searched independently, never ANDed with it.
        rows=question_set_queries(spec,round_no=1)
        seen=[]
        for _ in range(8):
            seen.extend(r['query'] for r in rows)
            rows=question_set_queries(spec,previous=seen,round_no=1)
        self.assertIn('二叉树的基本性质 判断题 习题 答案',seen)
        self.assertTrue(any(r['origin']=='model' for r in question_set_queries(spec)))

    def test_common_chapter_root_is_used_and_io_words_are_not_search_topics(self):
        spec={'topics':['二叉树的基本性质','二叉树的先序遍历','二叉树的实际应用'],
              'counts':{'3':2},'teaching_plan':{'goals':[{'keywords':['标准输入','标准输出']}]}}
        rows=question_set_queries(spec,round_no=1)
        self.assertTrue(any('二叉树 判断题' in r['query'] for r in rows))
        self.assertTrue(all('标准输入' not in r['query'] and '标准输出' not in r['query'] for r in rows))

    def test_supervisor_queries_are_executed_and_only_missing_types_get_slots(self):
        rows=question_set_queries({'topics':['排序'],'counts':{'1':8,'3':6}},counts={'3':2},
             suggestions=['归并排序 判断题 正误辨析'])
        self.assertEqual(rows[0]['query'],'归并排序 判断题 正误辨析')
        self.assertEqual(rows[0]['origin'],'supervisor')
        self.assertFalse(any(r['type']=='1' for r in rows))

    def test_real_search_route_uses_replan_then_retains_existing_programming(self):
        from courseagent.ordinary_web_search import collect_question_sets
        state,fixture=self.state()
        state['document']['programming_questions']=[{'id':'kept','selected':True,'test_cases':[{'input':'1'}]}]
        before=copy.deepcopy(state['document']['programming_questions'])
        with model_budget(40,600),patch('courseagent.web_budget.model_cached',return_value=self.response()) as replan,\
             tool('retrieval_tools.search_public_questions',return_value={'items':fixture.links()} ) as search,\
             tool('retrieval_tools.read_public_question_page',return_value={'page':fixture.page}),\
             patch('courseagent.web_questions.extract_candidates',side_effect=lambda current:{'document':{
                 **current['document'],'questions':[{'id':'new','type':3}]},'web':current['web']}),\
             patch('courseagent.ordinary_web_search.candidate_gaps',side_effect=lambda current:{'3':0 if current['document']['questions'] else 1}):
            result=collect_question_sets(state)
        self.assertEqual(replan.call_count,1)
        search.invoke.assert_called_once_with({'query':self.response()['queries'][0]['query']})
        self.assertEqual(result['document']['programming_questions'],before)
        self.assertFalse(result['web']['search_paths_exhausted'])
        self.assertEqual(result['web']['query_replans'][0]['status'],'planned')

    def test_replan_is_bounded_across_retries_and_rejects_old_queries(self):
        state,_=self.state()
        response=self.response();response['queries'][0]['query']=' 排序 判断题 答案 '
        with model_budget(40,600),patch('courseagent.web_budget.model_cached',return_value=response) as model:
            self.assertEqual(recover_queries(state),[])
            self.assertEqual(recover_queries(state),[])
            self.assertEqual(recover_queries(state),[])
        self.assertEqual(model.call_count,2)
        self.assertEqual(state['web']['adaptation_failure']['stage'],'search_plan')
        self.assertEqual(len(state['web']['query_replans']),2)

    def test_two_batches_without_gain_replan_before_unused_static_queries(self):
        from courseagent.ordinary_web_search import collect_question_sets
        state,fixture=self.state()
        with model_budget(40,600),patch('courseagent.web_budget.model_cached',return_value=self.response()) as model,\
             tool('retrieval_tools.search_public_questions',side_effect=[{'items':[]},{'items':[]},{'items':fixture.links()}]) as search,\
             tool('retrieval_tools.read_public_question_page',return_value={'page':fixture.page}),\
             patch('courseagent.web_questions.extract_candidates',side_effect=lambda current:{'document':{
                 **current['document'],'questions':[{'id':'new','type':3}]},'web':current['web']}),\
             patch('courseagent.ordinary_web_search.candidate_gaps',side_effect=lambda current:{'3':0 if current['document']['questions'] else 1}):
            for i in range(2):
                state['web']['queries']=['排序 判断题 焦点'+str(i)]
                state.update(collect_question_sets(state))
            model.assert_not_called()
            self.assertEqual(state['web']['discovery_stagnation'],2)
            state['web']['queries']=['排序 判断题 未尝试焦点']
            state.update(collect_question_sets(state))
        self.assertEqual(model.call_count,1)
        self.assertEqual(search.invoke.call_args.args[0]['query'],self.response()['queries'][0]['query'])
        self.assertEqual(state['web']['discovery_stagnation'],0)

    def test_reserved_budget_and_deadline_prevent_more_search_planning(self):
        state,_=self.state()
        with model_budget(10,600) as budget,patch('courseagent.web_budget.model_cached') as model:
            budget['calls']=7
            self.assertEqual(recover_queries(state),[])
            model.assert_not_called()
        with model_budget(40,30),patch('courseagent.web_budget.model_cached') as model:
            self.assertEqual(recover_queries(state),[])
            model.assert_not_called()

    def test_replan_history_survives_source_continuation(self):
        from courseagent.web_questions import plan_search
        from courseagent.workflow import retrieve
        state,_=self.state();state['request'].update(continue_web=True,prompt='排序判断题')
        state['document']['plan']={'request':'排序判断题','spec':state['spec']}
        state['document']['web_search']={**state['web'],'query_replans':[{'status':'failed'},{'status':'planned'}]}
        with patch('courseagent.workflow.retrieve',return_value={'candidates':[]}):
            result=plan_search(state)
        self.assertEqual(len(result['web']['query_replans']),2)


if __name__=='__main__':unittest.main()
