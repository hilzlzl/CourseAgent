import unittest

from courseagent.course_concepts import build_concept_plan
from courseagent.programming_search_plan import retrieval_topics
from courseagent.web_questions import search_topic


class CourseConceptPlanTests(unittest.TestCase):
    def spec(self, topics):
        plan = build_concept_plan({'topics': topics, 'teaching_plan': {'goals': []}})
        return {'topics': topics, 'teaching_plan': {'goals': [], 'concept_plan': plan}}

    def test_traversal_keeps_algorithm_family_and_graph_bank(self):
        spec = self.spec(['DFS', 'BFS'])
        plan = spec['teaching_plan']['concept_plan']
        self.assertEqual([c['name'] for c in plan['concepts']], ['图遍历'])
        self.assertEqual(plan['bank_tags'], ['graph'])
        self.assertEqual(retrieval_topics(spec)[:3], ['图遍历', 'DFS', 'BFS'])
        self.assertEqual(search_topic(spec), '数据结构 图遍历')

    def test_specific_concepts_do_not_trigger_substring_chapter(self):
        spec = self.spec(['拓扑排序'])
        plan = spec['teaching_plan']['concept_plan']
        self.assertEqual([c['name'] for c in plan['concepts']], ['有向图拓扑排序'])
        self.assertEqual(plan['bank_tags'], ['graph'])
        self.assertNotIn('排序算法', retrieval_topics(spec))

    def test_other_families_share_the_same_shape(self):
        for topic, concept, tag in [('最短路径', '图上的最短路径', 'graph'),
                                    ('二叉树遍历', '二叉树遍历', 'binary-tree'),
                                    ('栈', '栈', 'stack'),
                                    ('链表', '链表', 'linked-list')]:
            plan = build_concept_plan({'topics': [topic], 'teaching_plan': {'goals': []}})
            self.assertIn(concept, [c['name'] for c in plan['concepts']])
            self.assertIn(tag, plan['bank_tags'])

    def test_graph_property_does_not_claim_dfs_bfs(self):
        plan = build_concept_plan({'topics': ['连通图'], 'teaching_plan': {'goals': []}})
        self.assertEqual([c['name'] for c in plan['concepts']], ['图'])
        self.assertEqual(plan['search_terms'], ['图', '连通图'])

    def test_searching_reports_all_native_bank_tags(self):
        plan = build_concept_plan({'topics': ['哈希查找'], 'teaching_plan': {'goals': []}})
        self.assertEqual(plan['bank_tags'], ['binary-search', 'hash-table', 'binary-search-tree'])


if __name__ == '__main__':
    unittest.main()
