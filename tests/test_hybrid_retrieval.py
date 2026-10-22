import copy,json,math,tempfile,unittest
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from courseagent.hybrid_retrieval import HybridIndex,content_fingerprint,question_text
from courseagent.retrieval_runtime import remember_document,reuse_candidates,retrieve_materials
from courseagent.web_questions import plan_search,search_read,normalize_candidate

VECTOR_BACKEND = bool(importlib.util.find_spec('faiss') and importlib.util.find_spec('numpy'))

class Embeddings:
    model_id='fixture-semantic-v1'
    def __init__(self):self.calls=[]
    def embed(self,texts):
        self.calls.append(list(texts))
        return [[1.,0.,0.] if any(w in t for w in ('fifo','排队','队列')) else [0.,1.,0.] if '栈' in t else [0.,0.,1.] for t in texts]

class IndexTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.index=HybridIndex(Path(self.folder.name)/'index.sqlite')
    def record(self,id,text,kind='ordinary',provider='web',source='public'):
        return {'id':id,'origin_id':id,'kind':kind,'provider':provider,'title':id,'text':text,'source_id':source,'payload':{}}
    def test_chinese_bm25_and_aliases(self):
        self.index.upsert([self.record('stack','后进先出的线性结构'),self.record('queue','先进先出的数据结构')])
        r=self.index.search('栈',semantic=False)
        self.assertEqual(r['items'][0]['id'],'stack');self.assertEqual(r['diagnostics']['model_calls'],0)
    def test_metadata_filters_apply_before_search(self):
        self.index.upsert([self.record('a','栈',source='allowed'),self.record('b','栈',source='outside'),self.record('p','栈','programming')])
        r=self.index.search('栈',kinds=['ordinary'],source_ids=['allowed'])
        self.assertEqual([i['id'] for i in r['items']],['a']);self.assertEqual(r['diagnostics']['eligible_records'],1)
        self.assertEqual(self.index.search('栈',source_ids=[])['items'],[])
    def test_avoid_ids_filtered_before_search(self):
        self.index.upsert([self.record('a','栈'),self.record('b','栈')])
        self.assertEqual([i['id'] for i in self.index.search('栈',exclude_ids=['a'])['items']],['b'])
    def test_numeric_conditions_are_not_deduplicated(self):
        a={'type':3,'stem':'二叉树有10个叶子结点。','options':[]};b={**a,'stem':'二叉树有100个叶子结点。'}
        self.assertNotEqual(content_fingerprint(a),content_fingerprint(b))
        self.assertEqual(content_fingerprint(a),content_fingerprint({**a,'answer':'错误'}))
    def test_changed_text_invalidates_persisted_vector(self):
        self.index.embeddings=Embeddings();self.index.upsert([self.record('a','队列')]);self.index.prepare_vectors()
        self.assertEqual(self.index.stats()['vectors'],1)
        self.index.upsert([self.record('a','栈')]);self.assertEqual(self.index.stats()['vectors'],0)
        self.index.prepare_vectors();self.assertEqual(self.index.stats()['vectors'],1)
    @unittest.skipUnless(VECTOR_BACKEND, 'optional vector backend: install faiss-cpu')
    def test_vector_only_paraphrase_is_retrieved_and_fused(self):
        self.index.embeddings=Embeddings();self.index.upsert([self.record('a','队列'),self.record('b','栈')])
        r=self.index.search('fifo')
        self.assertEqual(r['diagnostics']['vector_state'],'ready');self.assertEqual(r['items'][0]['id'],'a')
        self.assertEqual(r['items'][0]['retrieval']['bm25_score'],0)
        self.assertEqual(r['items'][0]['retrieval']['ranks']['vector'],1)
    @unittest.skipUnless(VECTOR_BACKEND, 'optional vector backend: install faiss-cpu')
    def test_vectors_reused_without_reencoding_documents(self):
        e=Embeddings();self.index.embeddings=e;self.index.upsert([self.record('a','队列')])
        self.index.prepare_vectors();calls=len(e.calls);self.index.search('排队');self.index.search('fifo')
        self.assertEqual(len(e.calls),calls+2)
    def test_unavailable_vector_backend_is_explicit_bm25_fallback(self):
        class Broken(Embeddings):
            def embed(self,texts):raise RuntimeError('fixture unavailable')
        self.index.embeddings=Broken();self.index.upsert([self.record('a','栈')])
        r=self.index.search('栈');self.assertEqual(r['items'][0]['id'],'a')
        self.assertEqual(r['diagnostics']['vector_state'],'unavailable');self.assertIn('fixture unavailable',r['diagnostics']['vector_error'])
    @unittest.skipUnless(VECTOR_BACKEND, 'optional vector backend: install faiss-cpu')
    def test_near_duplicate_is_a_hint_not_a_deletion(self):
        self.index.embeddings=Embeddings();self.index.upsert([self.record('a','栈中有10个元素'),self.record('b','栈中有100个元素')])
        r=self.index.search('栈');self.assertEqual(len(r['items']),2)
        self.assertEqual(r['items'][0]['retrieval']['near_duplicates'][0]['cosine'],1)
    def test_concurrent_source_branches_do_not_lose_writes(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs=[pool.submit(self.index.upsert,[self.record(str(n),'栈') for n in range(i*20,(i+1)*20)]) for i in range(2)]
            self.assertEqual(sum(j.result() for j in jobs),40)
        self.assertEqual(self.index.stats()['counts']['ordinary'],40)
    def test_answers_and_private_code_are_not_embedding_input(self):
        q={'stem':'栈是什么？','answer':'PRIVATE_ANSWER','reference_code':'SECRET_CODE','reference_answer':'PRIVATE_EXPLANATION','options':['a','b']}
        text=question_text(q)
        self.assertNotIn('PRIVATE',text);self.assertNotIn('SECRET_CODE',text)

class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.index=HybridIndex(Path(self.folder.name)/'index.sqlite')
        mock=patch('courseagent.retrieval_runtime.get_index',return_value=self.index);mock.start();self.addCleanup(mock.stop)
        self.page={'url':'https://example.org/stack','title':'栈习题','retrieved_at':'2026-10-14',
                   'text':'栈是一种什么样的数据结构？\nA. 先进先出\nB. 后进先出\n答案：B。'}
        self.q=normalize_candidate({'type':1,'stem':'栈是一种什么样的数据结构？','options':['先进先出','后进先出'],
                                  'answer':'B','stem_evidence':'栈是一种什么样的数据结构？\nA. 先进先出\nB. 后进先出','answer_evidence':'答案：B。'},self.page)
        remember_document({'questions':[self.q]})
    def spec(self):return {'topics':['栈'],'counts':{'1':1},'source_ids':None,'locked_ids':[]}
    def state(self):
        return {'request':{'prompt':'栈 1道单选题','source_mode':'web','reuse_retrieval':True},'document':{'questions':[]},'sources':[],
                'spec':self.spec(),'trace':[]}
    def test_cache_does_not_set_teacher_approval_or_overwrite_current_edit(self):
        edited=copy.deepcopy(self.q);edited['answer']='A';before=copy.deepcopy(edited)
        doc={'questions':[edited]};hits,diagnostics=reuse_candidates(doc,self.spec(),{},'ordinary')
        self.assertEqual(hits,[]);self.assertEqual(doc['questions'][0],before)
        self.assertEqual(diagnostics['preview_conflicts'],[edited['id']])
    def test_conflicting_cached_answers_force_new_sourcing(self):
        another=copy.deepcopy(self.q);another['id']='conflicting';another['answer']='A'
        remember_document({'questions':[another]})
        hits,diagnostics=reuse_candidates({'questions':[]},self.spec(),{},'ordinary')
        self.assertEqual(hits,[]);self.assertEqual(diagnostics['conflicting_answer_groups'],1)
    def test_reuse_keeps_source_evidence_and_requires_later_quality_verification(self):
        hits,diag=reuse_candidates({'questions':[]},self.spec(),{},'ordinary')
        self.assertEqual(len(hits),1);self.assertFalse(hits[0]['approved']);self.assertFalse(hits[0]['selected'])
        self.assertEqual(hits[0]['source_refs'][0]['url'],self.page['url']);self.assertEqual(diag['reused_count'],1)
        self.assertNotIn('ordinary_blind_check',hits[0])
    def test_complete_cached_candidates_skip_repeated_network_extraction(self):
        s=self.state()
        with patch('courseagent.model_client.model_status',return_value={'configured':True}):s.update(plan_search(s))
        with patch('courseagent.retrieval_tools.search_public_questions') as search:
            result=search_read(s)
            search.invoke.assert_not_called()
        self.assertEqual(result['web']['events'][0]['status'],'indexed_candidates_ready')
        self.assertEqual(len(s['document']['questions']),1)
    def test_shortage_still_searches_the_web(self):
        s=self.state();s['spec']['counts']={'1':2}
        with patch('courseagent.model_client.model_status',return_value={'configured':True}):s.update(plan_search(s))
        with patch('courseagent.retrieval_tools.search_public_questions') as search,patch('courseagent.web_questions.known_source_links',return_value=[]):
            search.invoke.return_value={'items':[],'cache_hit':False}
            result=search_read(s)
        self.assertGreater(search.invoke.call_count,0);self.assertFalse(any(e['status']=='indexed_candidates_ready' for e in result['web']['events']))
    def test_base_ids_in_avoid_list_are_not_reused(self):
        q=copy.deepcopy(self.q);q['id']='child';q['base_question_id']='parent';remember_document({'questions':[q]})
        hits,_=reuse_candidates({'questions':[]},self.spec(),{'avoid_ids':['parent',self.q['id']]},'ordinary')
        self.assertEqual(hits,[])
    def test_cached_programming_rerank_cannot_discard_candidates(self):
        from courseagent.programming_sourcing import rerank_cached_programming
        questions=[{'id':'tree','title':'树','description':'使用队列遍历树'},
                   {'id':'queue','title':'队列','description':'实现先进先出操作'}]
        report={'model_calls':0,'cache_hits':0,'events':[]}
        with patch('courseagent.web_questions.cached',side_effect=lambda k,key,fn,**kw:(kw['validate'](fn()),False)),patch('courseagent.agent_roles.ask_role',return_value={}),patch('courseagent.programming_sourcing.ask_role',return_value={'ranked_ids':['queue','tree'],'reasons':{'queue':'主考点符合'}}):
            ranked=rerank_cached_programming(copy.deepcopy(questions),{'topics':['队列']},{'prompt':'队列1道编程题'},set(),report)
        self.assertEqual([q['id'] for q in ranked],['queue','tree']);self.assertEqual(report['model_calls'],1)
        with patch('courseagent.web_questions.cached',side_effect=lambda k,key,fn,**kw:(kw['validate'](fn()),False)),patch('courseagent.programming_sourcing.ask_role',return_value={'ranked_ids':['queue'],'reasons':{}}):
            fallback=rerank_cached_programming(copy.deepcopy(questions),{'topics':['队列']},{'prompt':'队列'},set(),report)
        self.assertEqual(len(fallback),2);self.assertEqual(report['events'][-1]['status'],'indexed_ranking_fallback')

    def test_pdf_page_scope_is_prefiltered_even_with_many_similar_pages(self):
        sources=[{'id':'ppt','name':'Slides.pdf','kind':'pdf','chunks':[{'page':i,'text':'栈课程范围 '+str(i)} for i in range(1,90)]},
                 {'id':'other','name':'Other.pdf','kind':'pdf','chunks':[{'page':89,'text':'栈 outside'}]}]
        hits=retrieve_materials(sources,{'topics':['栈'],'source_ids':['ppt'],'page_start':89,'page_end':89})
        self.assertEqual(len(hits),1);self.assertEqual(hits[0]['page'],89);self.assertEqual(hits[0]['document_id'],'ppt')
    def test_rescan_removes_old_uploaded_chunks(self):
        sources=[{'id':'ppt','name':'Slides.pdf','kind':'pdf','chunks':[{'page':1,'text':'栈 page1'},{'page':2,'text':'栈 page2'}]}]
        retrieve_materials(sources,{'topics':['栈']});sources[0]['chunks']=sources[0]['chunks'][:1]
        hits=retrieve_materials(sources,{'topics':['栈']})
        self.assertEqual(len(hits),1)

if __name__=='__main__':unittest.main()
