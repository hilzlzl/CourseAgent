import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from courseagent.workflow import plan,parse_request
from courseagent.programming_sourcing import candidate_from, source_programming
from courseagent.programming_questions import review_content
from courseagent.questions import validate,export_xlsx


class ProgrammingSourcingTests(unittest.TestCase):
 def setUp(self):
  native=patch('courseagent.algorithm_sources.search_questions',return_value=([],False));native.start();self.addCleanup(native.stop)
  self.page={'url':'https://example.org/stack','title':'栈编程练习','retrieved_at':'2026-10-13','text':'栈的括号匹配编程练习：输入一行括号字符串，输出括号是否匹配，需要处理空串与非法字符。参考算法使用栈维护未配对的左括号。'}
  self.item={'page_index':0,'title':'栈的括号匹配','description':'使用栈检查括号字符串是否匹配。','input_format':'一行仅含左右圆括号的字符串。','output_format':'匹配输出YES，否则输出NO。','constraints':'字符串长度为0至100，空串合法。','knowledge':'栈','starter_code':'','test_cases':[{'input':'()\n','output':'YES\n'},{'input':'\n','output':'YES\n'}],'reference_code':'s=input()\na=[]\nok=True\nfor c in s:\n if c=="(":a.append(c)\n elif a:a.pop()\n else:ok=False;break\nprint("YES" if ok and not a else "NO")\n','explanation':'栈记录尚未匹配的左括号。','evidence':self.page['text']}
  self.doc={'name':'编程题测试','version':0,'questions':[]}
 def state(self):
  return {'request':{'prompt':'Python 栈 1 道编程题','source_mode':'web','allow_adaptation':True},'spec':{'programming_count':1,'topics':['栈'],'counts':{}},'document':copy.deepcopy(self.doc),'trace':[]}
 def test_web_extraction_does_not_deliver_model_generated_scaffolds(self):
  q=candidate_from({**self.item,'starter_code':'print("generated scaffold")'},[self.page],'Python',True)
  self.assertEqual(q['languages'],[{'language':'Python','starter_code':''}])
 def test_knowledge_tag_list_is_normalized_without_weakening_contract(self):
  q=candidate_from({**self.item,'knowledge':['栈','括号匹配','栈']},[self.page],'Python',True)
  self.assertEqual(q['knowledge'],'栈、括号匹配')
  with self.assertRaises(ValueError):
   candidate_from({**self.item,'knowledge':[{'name':'栈'}]},[self.page],'Python',True)
 def test_unconverted_function_interfaces_cannot_leak_into_standard_io_delivery(self):
  page={**self.page,'source_metadata':{'provider':'acwing','interface_kind':'function'}}
  with self.assertRaisesRegex(ValueError,'结构化标准输入输出转换'):
   candidate_from(self.item,[page],'C',True)
 def test_bank_search_redirect_checked_against_final_destination(self):
  from courseagent.source_policy import search_redirect, source_tier
  self.assertTrue(search_redirect('https://www.sogou.com/link?url=bank-result'))
  self.assertEqual(source_tier('https://leetcode.cn/problems/valid-parentheses/', programming=True),0)
  self.assertEqual(source_tier('https://blog.example/a', programming=True),2)
 def response(self,prompt,data):
  if '独立核对' in prompt:return {'checks':[{'id':q['id'],'ok':True,'reason':'文本契约一致'} for q in data['questions']]}
  return {'questions':[self.item]}
 def test_original_professional_problem_skips_redundant_model_review(self):
  page={**self.page,'url':'https://ac.nowcoder.com/acm/problem/16422',
        'source_metadata':{'provider':'nowcoder','interface_kind':'standard_io'}}
  item={**self.item,'description':page['text'],
        'public_examples':[{'input':'()\n','output':'YES\n'}],
        'test_cases':[{'input':'()\n','output':'YES\n','visibility':'public'}]}
  item.pop('reference_code')
  page['text']+='\n'+item['input_format']+'\n'+item['output_format']+'\n'+item['constraints']+'\n()\nYES\n'
  prompts=[]
  def respond(prompt,data):
   prompts.append(prompt)
   if '独立核对' in prompt:raise AssertionError('Do not rejudge an original bank problem')
   return {'questions':[item]}
  s=self.state();s['request']['fresh_questions']=True
  with tempfile.TemporaryDirectory() as folder,patch('courseagent.web_questions.CACHE',Path(folder)),\
       patch('courseagent.web_questions.search',return_value=([{'url':page['url']}],False)),\
       patch('courseagent.web_questions.read_page',return_value=(page,False)),\
       patch('courseagent.nowcoder_sources.read_question',return_value=(page,False)),\
       patch('courseagent.programming_sourcing.executable_source_gate',return_value=True) as gate,\
       patch('courseagent.model_client.model_status',return_value={'configured':True,'model':'mock'}),\
       patch('courseagent.model_client.chat_json',side_effect=respond):
   result=source_programming(s)
  self.assertEqual(len(result['programming_candidates']),1)
  gate.assert_called_once()
  self.assertEqual(len(prompts),1)
  self.assertIn('仅复制原题公开样例',prompts[0])
  self.assertNotIn('建议6至10组评测',prompts[0])
  self.assertTrue(any(e['status']=='published_source_reused' for e in result['document']['programming_search']['events']))
 def test_cached_blog_cannot_skip_professional_search(self):
  s=self.state();s['request'].update(reuse_retrieval=True,agent_round=5)
  s['document']['programming_questions']=[candidate_from(self.item,[self.page],'Python',True)]
  with patch('courseagent.retrieval_runtime.reuse_candidates',return_value=(None,{})),patch('courseagent.retrieval_runtime.remember_document',return_value=1),patch('courseagent.web_questions.search',return_value=([{'url':self.page['url']}],False)) as search,patch('courseagent.web_questions.read_page') as read,patch('courseagent.model_client.model_status',return_value={'configured':True}):
   result=source_programming(s)
  self.assertEqual(result['programming_candidates'],[])
  self.assertEqual(search.call_count,3)
  self.assertTrue(all('site:' in call.args[0] for call in search.call_args_list))
  read.assert_not_called()
  self.assertEqual(result['document']['programming_search']['events'][0]['deferred_cached_supplements'],1)
  self.assertEqual(len(result['document']['programming_questions']),1)
 def test_programming_extraction_receives_only_programming_scope(self):
  from courseagent import web_questions
  captured=[]
  def respond(prompt,data):
   if '独立核对' not in prompt:captured.append(data['request'])
   return self.response(prompt,data)
  s=self.state();s['request']['prompt']='栈 2道单选题 2道判断题 1道编程题'
  with tempfile.TemporaryDirectory() as directory,patch.object(web_questions,'CACHE',Path(directory)),patch('courseagent.web_questions.search',return_value=([{'url':self.page['url']}],False)),patch('courseagent.web_questions.read_page',return_value=(self.page,False)),patch('courseagent.model_client.model_status',return_value={'configured':True,'model':'mock'}),patch('courseagent.model_client.chat_json',side_effect=respond):
   result=source_programming(s)
  self.assertEqual(len(result['programming_candidates']),1)
  self.assertEqual(captured[0]['programming_count'],1)
  self.assertNotIn('单选',str(captured[0]));self.assertNotIn('判断',str(captured[0]))
 def test_later_agent_round_keeps_native_question_bank_entry(self):
  s=self.state();s['request'].update(continue_web=True,agent_round=4,programming_batch=0)
  s['document']['programming_search']={'attempted_urls':[]}
  with patch('courseagent.algorithm_sources.search_questions',return_value=([],False)) as native,patch('courseagent.web_questions.search',return_value=([],False)),patch('courseagent.model_client.model_status',return_value={'configured':True}):
   source_programming(s)
  native.assert_called_once()

 def test_continuation_queries_change_between_batches(self):
  s=self.state();s['request']['continue_web']=True;s['document']['programming_search']={'attempted_urls':[]}
  with patch('courseagent.web_questions.search',return_value=([],False)),patch('courseagent.model_client.model_status',return_value={'configured':True}):
   a=source_programming(s)['document']['programming_search']['queries']
   s['request']['programming_batch']=1
   b=source_programming(s)['document']['programming_search']['queries']
  self.assertNotEqual(a,b)
 def test_supervisor_queries_reach_programming_search_and_are_not_repeated(self):
  s=self.state();s['request'].update(continue_web=True,agent_queries=['栈 括号匹配 输入输出 例题','栈 表达式求值 编程题'])
  s['document']['programming_search']={'attempted_urls':[],'queries':['栈 括号匹配 输入输出 例题']}
  with patch('courseagent.web_questions.search',return_value=([],False)) as search,patch('courseagent.model_client.model_status',return_value={'configured':True}):
   result=source_programming(s)
  queries=result['document']['programming_search']['queries']
  self.assertTrue(any('site:nowcoder.com/acm/problem/' in q for q in queries))
  self.assertNotIn('栈 括号匹配 输入输出 例题',queries);self.assertLessEqual(search.call_count,3)
 def test_count_parsing_and_local_programming_only_graph(self):
  q=candidate_from(self.item,[self.page],'Python',True)

  for c in q['test_cases']:c.update(purpose='边界检查',output_basis='教师逐步核对',verified=True)
  q['difficulty']=1;q['approved']=True;q['selected']=True;q['approval_snapshot']=review_content(q)
  doc={**self.doc,'programming_questions':[q]};before=copy.deepcopy(doc)
  result=plan(doc,{'prompt':'Python 栈 1 道编程题','source_mode':'local'},[])
  self.assertEqual(doc,before);self.assertTrue(result['plan']['complete']);self.assertEqual(len(validate(result,True)),1)
  self.assertEqual(result['plan']['programming_count']['selected'],1);export_xlsx(result)
 def test_optional_reference_and_model_confirmation_never_trusted(self):
  item=copy.deepcopy(self.item);item.pop('reference_code')
  for c in item['test_cases']:c.update(purpose='合法边界',output_basis='模型推导',verified=True)
  q=candidate_from(item,[self.page],'Python',True)
  self.assertEqual(q['reference_code'],'');self.assertTrue(all(c['verified'] is False for c in q['test_cases']))
  self.assertTrue(all(c['verified'] is True for c in item['test_cases']))


 def test_graph_automatically_replenishes_after_first_empty_batch(self):
  from courseagent import web_questions
  page={**self.page,'text':'二叉树的编程练习包括遍历和深度计算，可以通过递归或队列完成。二叉树每个节点有最多两个孩子。'}
  extraction_calls=0
  def respond(prompt,data):
   nonlocal extraction_calls
   if '独立核对' in prompt:return self.response(prompt,data)
   extraction_calls+=1
   if extraction_calls<=3:return {'questions':[]}
   return {'questions':[{**self.item,'title':name,'description':'根据输入的二叉树计算'+name+'，仅输出结果。','knowledge':'二叉树','evidence':page['text'],'judge_contract':{'format':'binary_tree_level_tokens_v1','task':task}} for name,task in [('二叉树最大深度','max_depth'),('二叉树最小深度','min_depth'),('翻转二叉树','invert')]]}
  with tempfile.TemporaryDirectory() as directory,patch.object(web_questions,'CACHE',Path(directory)),patch('courseagent.web_questions.search',side_effect=[([{'url':f'https://example.org/tree-{i}'}],False) for i in range(6)]) as search,patch('courseagent.web_questions.read_page',side_effect=[({**page,'url':f'https://example.org/tree-{i}'},False) for i in range(6)]),patch('courseagent.model_client.model_status',return_value={'configured':True,'model':'mock'}),patch('courseagent.model_client.chat_json',side_effect=respond):
   result=plan(self.doc,{'prompt':'给数据结构课程布置一次关于二叉树的作业，包含 3道编程题','source_mode':'web','allow_adaptation':True},[])
  self.assertTrue(result['plan']['complete']);self.assertEqual(search.call_count,4)
  self.assertEqual(result['programming_search']['automatic_batches'],2)
  self.assertEqual(result['programming_search']['model_calls'],6)  # Includes candidate-comparison role.
  self.assertEqual(sum(q['selected'] for q in result['programming_questions']),3)
  self.assertTrue(all(q['test_cases']==self.item['test_cases'] or len(q['test_cases'])==len(self.item['test_cases']) for q in result['programming_questions']))
  self.assertTrue(all('judge_contract' not in q for q in result['programming_questions']))

 def test_indexed_evidence_is_literal_and_bad_index_rejected(self):
  item={**self.item,'evidence':'模型改写了摘录','evidence_index':0}
  q=candidate_from(item,[self.page],'Python',True)
  self.assertEqual(q['source_refs'][0]['stem_evidence'],self.page['text'])
  with self.assertRaises(ValueError):candidate_from({**item,'evidence_index':99},[self.page],'Python',True)
  q=candidate_from({**item,'evidence_index':[0]},[self.page],'Python',True)
  self.assertEqual(q['source_refs'][0]['stem_evidence'],self.page['text'])


 def test_mixed_counts_dont_turn_programming_into_short_answer(self):
  result=parse_request({'request':{'prompt':'循环 2 道单选题、1 道编程题、2 道应用题'}})['spec']
  self.assertEqual(result['counts'],{'1':2,'5':2});self.assertEqual(result['programming_count'],1)
 def test_missing_programming_blocks_formal_export(self):
  result=plan(self.doc,{'prompt':'栈 1 道编程题','source_mode':'local'},[])
  self.assertFalse(result['plan']['complete'])
  with self.assertRaises(ValueError):export_xlsx(result)
 def test_web_tool_extraction_and_independent_review(self):
  from courseagent import web_questions
  with tempfile.TemporaryDirectory() as directory,patch.object(web_questions,'CACHE',Path(directory)),patch('courseagent.web_questions.search',return_value=([{'url':self.page['url']}],False)),patch('courseagent.web_questions.read_page',return_value=(self.page,False)),patch('courseagent.model_client.model_status',return_value={'configured':True,'model':'mock'}),patch('courseagent.model_client.chat_json',side_effect=self.response) as model:
   s=self.state();before=copy.deepcopy(s);result=source_programming(s)
   self.assertEqual(s,before);self.assertEqual(model.call_count,2);self.assertEqual(result['document']['programming_search']['missing'],0)
   q=result['programming_candidates'][0];self.assertFalse(q['approved']);self.assertEqual(q['difficulty'],0);self.assertEqual(q['source_refs'][0]['answer_status'],'model_derived')
   second=source_programming(s);self.assertEqual(model.call_count,2);self.assertEqual(second['document']['programming_search']['model_calls'],0)
 def test_programming_only_web_graph_builds_a_reviewable_draft(self):
  from courseagent import web_questions
  with tempfile.TemporaryDirectory() as directory,patch.object(web_questions,'CACHE',Path(directory)),patch('courseagent.web_questions.search',return_value=([{'url':self.page['url']}],False)),patch('courseagent.web_questions.read_page',return_value=(self.page,False)),patch('courseagent.model_client.model_status',return_value={'configured':True,'model':'mock'}),patch('courseagent.model_client.chat_json',side_effect=self.response):
   result=plan(self.doc,self.state()['request'],[])
  self.assertTrue(result['plan']['complete']);self.assertEqual(len(result['programming_questions']),1)
  self.assertTrue(result['programming_questions'][0]['selected']);self.assertIn('已凑齐1道题',result['plan']['trace'][-1])
  with self.assertRaises(ValueError):export_xlsx(result)
 def test_search_retries_after_failed_review_then_fills_gap(self):
  from courseagent import web_questions
  pages=[self.page,{**self.page,'url':'https://example.org/second'}];reviews=0
  def respond(prompt,data):
   nonlocal reviews
   if '独立核对' in prompt:
    reviews+=1
    return {'checks':[{'id':q['id'],'ok':reviews>1} for q in data['questions']]}
   return {'questions':[self.item]}
  with tempfile.TemporaryDirectory() as directory,patch.object(web_questions,'CACHE',Path(directory)),patch('courseagent.web_questions.search',side_effect=[([{'url':p['url']}],False) for p in pages]) as search,patch('courseagent.web_questions.read_page',side_effect=[(p,False) for p in pages]),patch('courseagent.model_client.model_status',return_value={'configured':True,'model':'mock'}),patch('courseagent.model_client.chat_json',side_effect=respond):
   result=source_programming(self.state());self.assertEqual(search.call_count,2);self.assertEqual(result['document']['programming_search']['missing'],0)
 def test_rejected_source_continues_search_and_never_selects_unverified_code(self):
  from courseagent import web_questions
  pages=[{**self.page,'url':f'https://example.org/{i}'} for i in range(3)]
  rejected=self.response
  def respond(prompt,data):
   if '独立核对' in prompt:return {'checks':[{'id':q['id'],'ok':False} for q in data['questions']]}
   return rejected(prompt,data)
  with tempfile.TemporaryDirectory() as directory,patch.object(web_questions,'CACHE',Path(directory)),patch('courseagent.web_questions.search',side_effect=[([{'url':p['url']}],False) for p in pages]) as search,patch('courseagent.web_questions.read_page',side_effect=[(p,False) for p in pages]),patch('courseagent.model_client.model_status',return_value={'configured':True,'model':'mock'}),patch('courseagent.model_client.chat_json',side_effect=respond):
   result=source_programming(self.state());self.assertEqual(search.call_count,3);self.assertEqual(result['programming_candidates'],[])
   report=result['document']['programming_search'];self.assertEqual(report['missing'],1);self.assertEqual(report['model_calls'],6);self.assertFalse(report['code_executed'])
 def test_evidence_and_missing_contract_rejected(self):
  for change in ({'evidence':'模型编造的引文根本不在网页上且长度足够验证'}, {'constraints':''}, {'test_cases':[{'input':'()','output':''}]}):
   with self.assertRaises(ValueError):candidate_from({**self.item,**change},[self.page],'Python',True)
  with self.assertRaises(ValueError):candidate_from(self.item,[self.page],'Python',False)
 def test_valid_programming_after_four_invalid_items_is_not_discarded(self):
  from courseagent import web_questions
  def respond(prompt,data):
   if '独立核对' in prompt:return self.response(prompt,data)
   return {'questions':[{**self.item,'title':'普通概念题','input_format':''} for _ in range(4)]+[self.item]}
  with tempfile.TemporaryDirectory() as directory,patch.object(web_questions,'CACHE',Path(directory)),patch('courseagent.web_questions.search',return_value=([{'url':self.page['url']}],False)),patch('courseagent.web_questions.read_page',return_value=(self.page,False)),patch('courseagent.model_client.model_status',return_value={'configured':True,'model':'mock'}),patch('courseagent.model_client.chat_json',side_effect=respond):
   result=source_programming(self.state())
   self.assertEqual(result['document']['programming_search']['missing'],0)
   self.assertEqual(result['programming_candidates'][0]['title'],self.item['title'])
   self.assertEqual(len([e for e in result['document']['programming_search']['events'] if e['status']=='candidate_rejected']),4)
 def test_mixed_assignment_verification_only_receives_programming_scope(self):
  from courseagent import web_questions
  seen=[]
  def respond(prompt,data):
   if '独立核对' in prompt:seen.append(data)
   return self.response(prompt,data)
  s=self.state();s['request']['prompt']='给数据结构课程布置一次作业，包含 2 道单选题和2道判断题和 1 道编程题。要求内容栈和队列'
  with tempfile.TemporaryDirectory() as directory,patch.object(web_questions,'CACHE',Path(directory)),patch('courseagent.web_questions.search',return_value=([{'url':self.page['url']}],False)),patch('courseagent.web_questions.read_page',return_value=(self.page,False)),patch('courseagent.model_client.model_status',return_value={'configured':True,'model':'mock'}),patch('courseagent.model_client.chat_json',side_effect=respond):
   result=source_programming(s)
  self.assertEqual(result['document']['programming_search']['missing'],0)
  self.assertEqual(seen[0]['request']['scope'],'仅审核编程题候选，不核对普通题题量')
 def test_locked_teacher_programming_is_kept_without_new_model_calls(self):
  q=candidate_from(self.item,[self.page],'Python',True);q['difficulty']=1;q['approved']=True;q['selected']=True;q['approval_snapshot']=review_content(q)
  s=self.state();s['request']['continue_web']=True;s['document']['programming_questions']=[q]
  with patch('courseagent.model_client.chat_json') as model:
   result=source_programming(s);model.assert_not_called()
  self.assertEqual(result['programming_candidates'],[q]);self.assertTrue(result['programming_candidates'][0]['approved'])

if __name__=='__main__':unittest.main()

class AllowedLanguagesTests(unittest.TestCase):
    def test_default_languages_and_explicit_restrictions(self):
        from courseagent.programming_sourcing import allowed_languages
        self.assertEqual(allowed_languages({'prompt':'二叉树编程题'}),['C','C++','Python','Java'])
        self.assertEqual(allowed_languages({'prompt':'请用C++完成'}),['C++'])
        self.assertEqual(allowed_languages({'prompt':'C语言或Java'}),['Java','C'])
        self.assertEqual(allowed_languages({'prompt':'Python编程作业'}),['Python'])
