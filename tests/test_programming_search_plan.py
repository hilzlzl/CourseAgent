import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from courseagent.programming_search_plan import retrieval_topics,bank_query_schedule


class ProgrammingSearchPlanTests(unittest.TestCase):
    def spec(self):
        return {'topics':['数据结构','搜索'],'programming_count':1,'teaching_plan':{'goals':[
            {'name':'理解查找方法','keywords':['顺序查找','折半查找','哈希查找','二叉排序树']}]}}

    def test_broad_chapter_reuses_existing_goal_keywords_for_native_discovery(self):
        self.assertEqual(retrieval_topics(self.spec()),['折半查找','哈希查找','二叉排序树'])
        from courseagent.algorithm_sources import search_questions
        filters=[]
        def graphql(query,variables):
            filters.append(variables['filters'])
            return {'problemsetQuestionList':{'questions':[]}}
        with tempfile.TemporaryDirectory() as tmp,patch('courseagent.web_questions.CACHE',Path(tmp)),\
             patch('courseagent.algorithm_sources.graphql',side_effect=graphql):
            search_questions(retrieval_topics(self.spec()))
        self.assertEqual({f['tags'][0] for f in filters},{'binary-search','hash-table','binary-search-tree'})

    def test_explicit_supported_scope_is_not_broadened_by_goal_suggestions(self):
        spec=self.spec();spec['topics']=['二叉树']
        self.assertEqual(retrieval_topics(spec),['二叉树'])

    def test_traversal_algorithm_names_use_separate_precise_tags(self):
        from courseagent.algorithm_sources import search_questions
        filters=[]
        def graphql(query,variables):
            filters.append(variables['filters'])
            return {'problemsetQuestionList':{'questions':[]}}
        spec={'topics':['深度优先搜索','广度优先搜索'],
              'teaching_plan':{'goals':[{'keywords':['图遍历','DFS','BFS']}]}}
        with tempfile.TemporaryDirectory() as tmp,patch('courseagent.web_questions.CACHE',Path(tmp)),\
             patch('courseagent.algorithm_sources.graphql',side_effect=graphql):
            search_questions(retrieval_topics(spec))
        self.assertEqual(filters, [{'tags':['depth-first-search']},{'tags':['breadth-first-search']}])

    def test_unknown_terms_are_independent_queries_instead_of_one_ambiguous_string(self):
        from courseagent.algorithm_sources import search_questions
        filters=[]
        def graphql(query,variables):
            filters.append(variables['filters'])
            return {'problemsetQuestionList':{'questions':[]}}
        with tempfile.TemporaryDirectory() as tmp,patch('courseagent.web_questions.CACHE',Path(tmp)),\
             patch('courseagent.algorithm_sources.graphql',side_effect=graphql):
            search_questions(['课程A','算法B'])
        self.assertEqual({f['searchKeywords'] for f in filters},{'课程A','算法B'})

    def test_nowcoder_preserves_problem_route_constraint(self):
        from courseagent.source_adapters import search_source
        with patch('courseagent.web_questions.search',return_value=([],False)) as search:
            search_source('nowcoder','折半查找 输入输出 site:nowcoder.com/acm/problem/')
        self.assertIn('site:nowcoder.com/acm/problem/',search.call_args.args[0])

    def test_query_history_survives_more_than_two_supervisor_rounds_and_exhausts(self):
        from courseagent.programming_sourcing import source_programming
        s={'document':{'questions':[]},'spec':{'topics':['栈'],'programming_count':1},
           'request':{'source_mode':'web','fresh_questions':True},'trace':[]}
        issued=[]
        def search(query):issued.append(query);return [],False
        with patch('courseagent.algorithm_sources.search_questions',return_value=([],False)),\
             patch('courseagent.web_questions.search',side_effect=search),\
             patch('courseagent.model_client.model_status',return_value={'configured':True}):
            for i in range(4):
                s['request'].update(continue_web=bool(i),agent_round=i)
                s.update(source_programming(s))
        report=s['document']['programming_search']
        self.assertEqual(len(issued),len(set(issued)))
        self.assertEqual(len(report['query_history']),9)
        self.assertEqual(report['queries'],[])
        self.assertTrue(report['search_exhausted'])

    def test_native_question_reaches_model_without_literal_request_keyword(self):
        from courseagent.programming_sourcing import source_programming
        page={'url':'https://leetcode.cn/problems/example/','title':'有序数组定位',
              'text':'给定有序整数数组和目标，返回目标下标。',
              'source_statement':'给定有序整数数组和目标，返回目标下标。',
              'source_examples':[{'input':'nums = [1,2]','output':'3'}],
              'source_metadata':{'provider':'leetcode','tags':['二分查找'],
                'interface':{'name':'total','params':[{'name':'nums','type':'integer[]'}],
                             'return':{'type':'integer'}}}}
        s={'document':{'questions':[]},'spec':self.spec(),'trace':[],
           'request':{'source_mode':'web','fresh_questions':True,'use_model':True,'prompt':'数据结构搜索1编程'}}
        with patch('courseagent.algorithm_sources.search_questions',return_value=([{'url':page['url']}],False)),\
             patch('courseagent.source_adapters.read_question_page',return_value=(page,False)),\
             patch('courseagent.programming_sourcing.native_course_fit',return_value=True) as fit,\
             patch('courseagent.programming_sourcing.executable_source_gate',return_value=True),\
             patch('courseagent.model_client.model_status',return_value={'configured':True}):
            result=source_programming(s)
        fit.assert_called_once()
        self.assertEqual(len(result['programming_candidates']),1)
        # Native discovery did not actually issue the first domain query.
        self.assertEqual(result['document']['programming_search']['queries'],[])


if __name__=='__main__':unittest.main()
