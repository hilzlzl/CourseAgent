"""Behavioral regressions for arbitrary-page interpretation and source reuse."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from courseagent.ordinary_web_search import collect_question_sets
from courseagent.web_questions import extract_candidates


def tool(name, **kwargs):
    return patch('courseagent.'+name,SimpleNamespace(invoke=MagicMock(**kwargs)))


class QuestionSetSearchTests(unittest.TestCase):
    def setUp(self):
        self.url='https://example.org/exercise'
        self.stem='希尔排序是一种不稳定的排序算法。'
        self.page={'url':self.url,'title':'排序习题','retrieved_at':'fixture',
                   'text':'一．判断题（正确打√，错误打╳）\n（ ）（1）'+self.stem+'\n答案：正确'}
        self.item={'page_index':0,'type':3,'stem':self.stem,'options':[],'answer':'正确',
                   'stem_evidence':'（ ）（1）'+self.stem,'answer_evidence':'答案：正确','source_complete':True,
                   'in_scope':True,'fit_reason':'考查排序算法的稳定性'}
        self.state={'request':{'source_mode':'web','verify_as_ready':True},'spec':{'topics':['排序'],'counts':{'3':1}},
                    'document':{'questions':[]},'trace':[],'sources':[],
                    'web':{'queries':['排序 判断题 习题 答案'],'pages':[],'events':[],
                           'cache_hits':0,'model_calls':0,'duplicates':0,'candidate_ids':[],'max_pages':2,'max_attempts':4}}
        p=patch('courseagent.model_client.model_status',return_value={'configured':True,'model':'fixture'});p.start();self.addCleanup(p.stop)

    def result(self, items=None, **assessment):
        return {'questions':items if items is not None else [self.item],
                'page_assessment':{'kind':'question_set','types':['3'],'has_more':False,**assessment}}

    def links(self):
        return [{'url':self.url,'title':'排序判断习题'}]

    def test_arbitrary_format_always_uses_model_and_retains_type(self):
        self.state['web']['pages']=[self.page]
        with patch('courseagent.web_native.explicit_questions',side_effect=AssertionError('No format inference')),\
             patch('courseagent.web_budget.model_cached',return_value=self.result()) as model:
            result=extract_candidates(self.state)
        self.assertEqual(model.call_count,1)
        self.assertIn('in_scope',model.call_args.args[3])
        self.assertEqual(result['document']['questions'][0]['type'],3)
        self.assertFalse(any(e['status']=='native_page_complete' for e in result['web']['events']))

    def test_semantic_scope_does_not_require_literal_topic_in_page_or_stem(self):
        self.state['spec']['topics']=['算法稳定性']
        self.state['web']['discovered_links']=self.links()
        with tool('retrieval_tools.search_public_questions',side_effect=AssertionError('Reuse source')),\
             tool('retrieval_tools.read_public_question_page',return_value={'page':self.page}),\
             patch('courseagent.web_budget.model_cached',return_value=self.result()):
            result=collect_question_sets(self.state)
        self.assertEqual(len(result['web']['candidate_ids']),1)
        self.assertTrue(result['document']['questions'][0]['web_interpretation']['in_scope'])
        from courseagent.workflow import retrieve
        current={**self.state,**result}
        self.assertEqual(len(retrieve(current)['candidates']),1)
        current['spec']={**current['spec'],'topics':['数据库事务']}
        self.assertEqual(retrieve(current)['candidates'],[])
        current['spec']=self.state['spec']
        current['document']['questions'][0]['stem']='数据库事务的隔离级别有哪些？'
        self.assertEqual(retrieve(current)['candidates'],[])

    def test_irrelevant_or_missing_semantic_scope_cannot_enter_pool(self):
        for fields in ({'in_scope':False},{'in_scope':'true'},{'in_scope':None},{'fit_reason':''}):
            with self.subTest(fields=fields),patch('courseagent.web_budget.model_cached',return_value=self.result([{**self.item,**fields}])):
                result=extract_candidates({**self.state,'web':{**self.state['web'],'pages':[self.page]}})
            self.assertEqual(result['web']['candidate_ids'],[])

    def test_legacy_scope_rejection_reuses_raw_page_once_without_search(self):
        self.state['web'].update(pages=[{k:v for k,v in self.page.items() if k!='text'}],
            extracted_urls=[self.url],source_assessments={self.url:{'status':'consumed','passes':2,
                'rejected':[{'reason':'原题不在本次课程范围内'}]}})
        with tool('retrieval_tools.search_public_questions',side_effect=AssertionError('No new search')),\
             tool('retrieval_tools.read_public_question_page',return_value={'page':self.page}) as read,\
             patch('courseagent.web_budget.model_cached',return_value=self.result()) as model:
            result=collect_question_sets(self.state)
            again=collect_question_sets({**self.state,**result})
        self.assertEqual(read.invoke.call_count,1);self.assertEqual(model.call_count,1)
        self.assertEqual(again['web']['source_assessments'][self.url]['scope_version'],2)
        self.assertEqual(result['web'].get('read_attempts',0),0)

    def test_retained_discovery_is_read_before_any_search(self):
        self.state['web']['discovered_links']=self.links()
        with tool('retrieval_tools.search_public_questions',side_effect=AssertionError('Do not search')) as search,\
             tool('retrieval_tools.read_public_question_page',return_value={'page':self.page,'cache_hit':True}),\
             patch('courseagent.web_budget.model_cached',return_value=self.result()):
            result=collect_question_sets(self.state)
        search.invoke.assert_not_called()
        self.assertEqual(result['web']['acquisition']['candidate_gaps'],{'3':0})
        self.assertNotIn('research',result['web'])

    def test_stops_reading_after_source_supplies_enough_candidates(self):
        self.state['web']['discovered_links']=self.links()+[{'url':'https://other.example.org/next','title':'排序题集'}]
        with tool('retrieval_tools.search_public_questions') as search,\
             tool('retrieval_tools.read_public_question_page',return_value={'page':self.page,'cache_hit':False}) as read,\
             patch('courseagent.web_budget.model_cached',return_value=self.result()):
            result=collect_question_sets(self.state)
        self.assertEqual(read.invoke.call_count,1);search.invoke.assert_not_called()
        self.assertEqual(result['web']['acquisition']['pending_links'],1)

    def test_answerless_candidates_are_completed_before_more_search(self):
        item={**self.item,'answer':'','answer_evidence':''}
        self.state['web']['discovered_links']=self.links()
        with tool('retrieval_tools.search_public_questions',side_effect=AssertionError('Answer first')),\
             tool('retrieval_tools.read_public_question_page',return_value={'page':self.page,'cache_hit':False}),\
             patch('courseagent.web_budget.model_cached',return_value=self.result([item])):
            result=collect_question_sets(self.state)
        self.assertEqual(result['web']['acquisition']['candidate_gaps'],{'3':0})
        self.assertEqual(result['document']['questions'][0]['answer'],'')

    def test_evidence_rejection_rechecks_same_page_before_search(self):
        self.state['web']['discovered_links']=self.links()
        bad={**self.item,'stem_evidence':'不存在的原文证据'}
        with tool('retrieval_tools.search_public_questions',side_effect=AssertionError('Repair extraction first')),\
             tool('retrieval_tools.read_public_question_page',return_value={'page':self.page,'cache_hit':False}) as read,\
             patch('courseagent.web_budget.model_cached',side_effect=[self.result([bad]),self.result()]) as model:
            result=collect_question_sets(self.state)
        self.assertEqual(model.call_count,2);self.assertEqual(read.invoke.call_count,1)
        self.assertIn('rejected_candidates',model.call_args.args[4])
        self.assertTrue(any(e['status']=='extraction_recheck' for e in result['web']['events']))

    def test_type_inventory_mismatch_returns_to_same_source(self):
        self.state['web']['pages']=[self.page]
        with patch('courseagent.web_budget.model_cached',side_effect=[self.result([]),self.result()]) as model:
            result=extract_candidates(self.state)
        self.assertEqual(model.call_count,2);self.assertEqual(len(result['document']['questions']),1)

    def test_transport_failure_pauses_without_next_source_or_search(self):
        self.state['web']['discovered_links']=self.links()+[{'url':'https://other.example.org/next','title':'排序题集'}]
        with tool('retrieval_tools.search_public_questions',side_effect=AssertionError('Pause extraction')),\
             tool('retrieval_tools.read_public_question_page',return_value={'page':self.page,'cache_hit':False}) as read,\
             patch('courseagent.web_budget.model_cached',side_effect=TimeoutError('transport')) as model:
            result=collect_question_sets(self.state)
        self.assertEqual(model.call_count,2);self.assertEqual(read.invoke.call_count,1)
        self.assertEqual(result['web']['adaptation_failure']['stage'],'extract')
        self.assertEqual(result['web']['extraction_pending_pages'],[{'url':self.url}])

    def test_late_sections_and_separate_answer_key_reach_model_intact(self):
        text='排序课程正文。'*4000+'\n'+self.page['text']
        self.state['web']['pages']=[{**self.page,'text':text}]
        with patch('courseagent.web_budget.model_cached',return_value=self.result()) as model:
            extract_candidates(self.state)
        self.assertEqual(model.call_args.args[4]['pages'][0]['text'],text)

    def test_default_graph_does_not_invoke_researcher(self):
        from courseagent.workflow import build_graph
        self.state['request']['deep_research']=True
        with patch('courseagent.web_questions.plan_search',return_value={'web':self.state['web']}),\
             patch('courseagent.question_research.research_sources',side_effect=AssertionError('Disabled')),\
             patch('courseagent.ordinary_web_search.collect_question_sets',return_value={}) as collect,\
             patch('courseagent.web_questions.extract_candidates',return_value={}),\
             patch('courseagent.web_replenishment.check_gaps',return_value={'web':{'next_step':'done'}}):
            build_graph(_ordinary_branch=True).invoke(self.state)
        collect.assert_called_once()

    def test_queries_are_short_type_specific_and_do_not_invent_batch_tokens(self):
        from courseagent.ordinary_search_plan import question_set_queries
        spec={'topics':['排序'],'counts':{'1':10,'3':10}}
        first=question_set_queries(spec)
        self.assertEqual([r['type'] for r in first[:2]],['1','3'])
        next_rows=question_set_queries(spec,{'3':2},[r['query'] for r in first],round_no=1)
        self.assertEqual(next_rows[0]['type'],'3')
        self.assertFalse({r['query'] for r in first}&{r['query'] for r in next_rows})
        self.assertTrue(all(len(r['query'])<40 and '第' not in r['query'] for r in first+next_rows))

    def test_all_search_entries_unavailable_stop_inner_replenishment(self):
        from courseagent.web_replenishment import check_gaps
        with tool('retrieval_tools.search_public_questions',side_effect=ValueError('搜索入口返回验证码')),\
             tool('retrieval_tools.read_public_question_page',side_effect=AssertionError('No source')):
            result=collect_question_sets(self.state)
        state={**self.state,**result}
        checked=check_gaps(state)
        self.assertEqual(checked['web']['next_step'],'done')
        self.assertIn('搜索入口',checked['web']['fill_report']['reason'])

    def test_ambiguous_answerless_question_does_not_hide_real_gap(self):
        from courseagent.web_questions import normalize_candidate
        from courseagent.ordinary_verification import solution_basis
        from courseagent.ordinary_web_search import candidate_gaps
        q=normalize_candidate({**self.item,'answer':'','answer_evidence':''},self.page)
        q['ordinary_answer_completion']={'status':'uncertain','basis':solution_basis(q)}
        self.state['document']['questions']=[q];self.state['web']['candidate_ids']=[q['id']]
        self.assertEqual(candidate_gaps(self.state),{'3':1})

    def test_mobile_search_adapter_decodes_original_url_and_excludes_portals(self):
        import tempfile
        from pathlib import Path
        from courseagent.web_questions import search
        html='<div class="res-list"><a class="alink" href="https://m.so.com/jump?u=https%3A%2F%2Fexample.org%2Fsort">排序判断题习题答案</a></div>'
        def fetch(url):
            if 'm.so.com' in url:return html,url
            return '<html>没有搜索结果</html>',url
        with tempfile.TemporaryDirectory() as folder,patch('courseagent.web_questions.CACHE',Path(folder)),\
             patch('courseagent.search_provider.configured',return_value=False),patch('courseagent.web_questions.fetch',side_effect=fetch):
            items,_=search('排序 判断题')
        self.assertEqual(items[0]['url'],'https://example.org/sort')
        self.assertEqual(items[0]['engine'],'360_mobile')

    def test_unsupported_boolean_cannot_reject_explicit_supported_request(self):
        from courseagent.workflow import parse_request
        state={**self.state,'request':{'use_model':True,'prompt':'排序10道单选题10道判断题4道编程题'}}
        with patch('courseagent.workflow.ask_role',return_value={'counts':{'1':10,'3':10},'topics':['排序'],'unsupported':True}):
            spec=parse_request(state)['spec']
        self.assertEqual(spec['programming_count'],4)



class CandidateAdmissionTests(unittest.TestCase):
    def question(self):
        from courseagent.web_questions import normalize_candidate
        page={'url':'https://example.org/q','title':'排序习题','retrieved_at':'fixture',
              'text':'希尔排序是一种不稳定的排序算法。\n答案：正确'}
        item={'type':3,'stem':'希尔排序是一种不稳定的排序算法。','answer':'正确',
              'stem_evidence':'希尔排序是一种不稳定的排序算法。','answer_evidence':'答案：正确'}
        q=normalize_candidate(item,page);q.update(selected=True,web_interpretation={'version':1,'method':'model','source_complete':True})
        return q

    def test_agreeing_answers_do_not_count_as_verified_before_content_review(self):
        from courseagent.ordinary_verification import verify_document,current
        from courseagent.verification_state import summary
        q=self.question();doc={'questions':[q]};roles=[]
        def ask(role,prompt,data):
            roles.append(role)
            if role=='ordinary_solver':return {'answers':[{'id':q['id'],'answer':'正确','reason':'希尔排序的性质'}]}
            self.assertEqual(summary(doc)['verified'],0)
            return {'checks':[{'id':q['id'],'verdict':'uncertain','reason':'保留题面疑点，不凭答案一致放行'}]}
        verify_document(doc,ask=ask)
        self.assertEqual(roles,['ordinary_solver','validator'])
        self.assertEqual(current(q)['verdict'],'uncertain')
        self.assertEqual(summary(doc)['verified'],0)

    def test_content_transport_retry_reuses_blind_solution(self):
        from courseagent.ordinary_verification import verify_document,current
        q=self.question();doc={'questions':[q]};roles=[]
        def first(role,prompt,data):
            if role=='ordinary_solver':return {'answers':[{'id':q['id'],'answer':'正确','reason':'希尔排序不稳定'}]}
            raise TimeoutError('transport')
        verify_document(doc,ask=first)
        self.assertEqual(current(q)['failure']['code'],'transport')
        def resumed(role,prompt,data):
            roles.append(role)
            return {'checks':[{'id':q['id'],'verdict':'pass','reason':'原文完整且答案成立'}]}
        verify_document(doc,ask=resumed)
        self.assertEqual(roles,['validator']);self.assertEqual(current(q)['verdict'],'pass')

    def test_parallel_pipeline_preserves_content_admission_on_merge(self):
        from courseagent.candidate_pipeline import CandidatePipeline
        from courseagent.ordinary_verification import verify_document,current
        from courseagent.verification_state import summary
        q=self.question();doc={'questions':[q]}
        def ask(role,prompt,data):
            if role=='ordinary_solver':return {'answers':[{'id':q['id'],'answer':'正确','reason':'希尔排序不稳定'}]}
            return {'checks':[{'id':q['id'],'verdict':'pass','reason':'原文完整且答案成立'}]}
        verifier=SimpleNamespace(invoke=lambda args:{'document':verify_document(args['document'],ask=ask)})
        pipeline=CandidatePipeline(ordinary=verifier)
        try:
            pipeline.offer('ordinary',doc);pipeline.drain()
            merged=pipeline.merge(doc)
            self.assertEqual(current(merged['questions'][0])['verdict'],'pass')
            self.assertEqual(summary(merged)['verified'],1)
            self.assertEqual(pipeline.offer('ordinary',merged),0)
            edited=copy.deepcopy(doc);edited['questions'][0]['stem']+=' 修改条件'
            self.assertIsNone(current(pipeline.merge(edited)['questions'][0]))
        finally:pipeline.close()

    def test_changed_content_policy_rechecks_without_repeating_blind_solve(self):
        from courseagent.ordinary_verification import verify_document,current,CONTENT_POLICY_VERSION
        q=self.question();doc={'questions':[q]}
        def ask(role,prompt,data):
            if role=='ordinary_solver':return {'answers':[{'id':q['id'],'answer':'正确','reason':'希尔排序不稳定'}]}
            return {'checks':[{'id':q['id'],'verdict':'pass','reason':'课程标准定义成立'}]}
        verify_document(doc,ask=ask)
        q['ordinary_content_check']['policy_version']=CONTENT_POLICY_VERSION-1
        self.assertIsNone(current(q))
        roles=[]
        def recheck(role,prompt,data):
            roles.append(role)
            self.assertIn('标准算法语义',prompt)
            return ask(role,prompt,data)
        verify_document(doc,ask=recheck)
        self.assertEqual(roles,['validator'])
        self.assertEqual(current(q)['verdict'],'pass')

    def test_final_review_keeps_cross_question_scope_after_admission(self):
        from courseagent.ordinary_verification import verify_document
        from courseagent.autonomous_agent import check_document
        q=self.question();doc={'name':'fixture','questions':[q], 'plan':{'spec':{'counts':{'3':1},'topics':['排序'],'programming_count':0}}}
        def ask(role,prompt,data):
            if role=='ordinary_solver':return {'answers':[{'id':q['id'],'answer':'正确','reason':'希尔排序不稳定'}]}
            return {'checks':[{'id':q['id'],'verdict':'pass','reason':'原文完整且答案成立'}]}
        verify_document(doc,ask=ask)
        with patch('courseagent.model_client.model_status',return_value={'model':'fixture'}),patch('courseagent.web_questions.cached',return_value=({'issues':[]},False)) as cache:
            report=check_document(doc)
        self.assertEqual(report['individual_content_review'],'completed_before_admission')
        self.assertIn('跨题关系',cache.call_args.args[1])

    def test_final_model_review_waits_for_candidate_admission(self):
        from courseagent.ordinary_verification import verify_document
        from courseagent.autonomous_agent import check_document
        for checked in (False,True):
            q=self.question();doc={'name':'fixture','questions':[q], 'plan':{'spec':{'counts':{'3':1},'topics':['排序'],'programming_count':0}}}
            def ask(role,prompt,data):
                if role=='ordinary_solver':return {'answers':[{'id':q['id'],'answer':'正确','reason':'希尔排序不稳定'}]}
                return {'checks':[{'id':q['id'],'verdict':'uncertain','reason':'候选尚有具体疑点'}]}
            if checked:verify_document(doc,ask=ask)
            with patch('courseagent.web_questions.cached',side_effect=AssertionError('先处理单题，不重复整卷审查')):
                report=check_document(doc)
            self.assertTrue(report['blocking']);self.assertTrue(report['model_deferred'])
            self.assertTrue(any(i['kind']=='ordinary_answer_uncertain' for i in report['issues']))


if __name__=='__main__':unittest.main()
