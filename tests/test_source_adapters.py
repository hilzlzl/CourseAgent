import unittest
from unittest.mock import patch
from courseagent.source_adapters import provider_for,read_question_page,search_source,manifest

class SourceAdapterTests(unittest.TestCase):
    def test_domain_identity_is_exact_or_subdomain(self):
        self.assertEqual(provider_for('https://www.nowcoder.com/practice/abc'),'nowcoder')
        self.assertEqual(provider_for('https://leetcode.cn.attacker.example/problems/a'),'web')
        self.assertEqual(provider_for('https://www.luogu.com.cn/problem/P1000'),'luogu')
    def test_native_failure_falls_back_to_public_reader_with_metadata(self):
        page={'url':'https://leetcode.cn/problems/two-sum/','title':'两数之和','text':'source text'}
        with patch('courseagent.algorithm_sources.read_question',side_effect=ValueError('native unavailable')),patch('courseagent.web_questions.read_page',return_value=(page,False)) as read:
            value,hit=read_question_page(page['url'])
        read.assert_called_once();self.assertFalse(hit);self.assertTrue(value['source_metadata']['native_read_fallback'])
        self.assertFalse(value['source_metadata']['private_tests_available'])
    def test_unsafe_native_url_is_rejected_before_dispatch(self):
        with patch('courseagent.algorithm_sources.read_question') as read:
            for url in ('https://u:password@leetcode.cn/problems/two-sum/','file:///tmp/private','http://leetcode.cn:123/problems/two-sum/'):
                with self.assertRaises(ValueError):read_question_page(url)
        read.assert_not_called()
    def test_domain_search_is_real_engine_call_not_fake_native_api(self):
        with patch('courseagent.web_questions.search',return_value=([],False)) as search:
            search_source('nowcoder','栈 site:wrong.example')
            self.assertEqual(search.call_args.args[0],'栈 site:nowcoder.com')
            search_source('luogu','队列');self.assertIn('site:luogu.com.cn/problem/',search.call_args.args[0])
    def test_native_topic_queries_are_unioned_and_paid_items_excluded(self):
        import tempfile
        from pathlib import Path
        from courseagent.algorithm_sources import search_questions
        def graphql(query,variables):
            tag=variables['filters']['tags'][0]
            return {'problemsetQuestionList':{'questions':[{'title':tag,'titleSlug':tag+'-exercise','difficulty':'Easy'},
                        {'title':'paid','titleSlug':'paid-exercise','difficulty':'Easy','paidOnly':True}]}}
        with tempfile.TemporaryDirectory() as folder,patch('courseagent.web_questions.CACHE',Path(folder)),patch('courseagent.algorithm_sources.graphql',side_effect=graphql) as api:
            items,_=search_questions(['栈','队列'])
        self.assertEqual(len(items),2);self.assertEqual(api.call_count,2)
        self.assertEqual({i['title'] for i in items},{'stack','queue'})
    def test_public_difficulty_is_explicit_metadata_not_inferred_teacher_grade(self):
        page={'url':'https://www.luogu.com.cn/problem/P1000','title':'题面','text':'难度：入门\n输入输出题面'}
        with patch('courseagent.web_questions.read_page',return_value=(page,False)):
            result,_=read_question_page(page['url'])
        self.assertEqual(result['source_metadata']['difficulty_raw'],'入门')
        self.assertNotIn('teacher_difficulty',result['source_metadata'])

    def test_capabilities_do_not_claim_private_tests_or_missing_native_apis(self):
        entries={s['provider']:s for s in manifest()}
        self.assertEqual(len(entries),7);self.assertTrue(all(not s['private_tests'] for s in entries.values()))
        self.assertEqual(entries['nowcoder']['discovery'],'public_acm_list_or_domain_search')
        self.assertEqual(entries['luogu']['reader'],'public_html')
    def test_final_redirect_provider_used_for_provenance(self):
        page={'url':'https://www.luogu.com.cn/problem/P1000','title':'题面','text':'text'}
        with patch('courseagent.web_questions.read_page',return_value=(page,True)):
            result,hit=read_question_page('https://public.example/redirect')
        self.assertTrue(hit);self.assertEqual(result['source_metadata']['provider'],'luogu')

if __name__=='__main__':unittest.main()
