import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from courseagent.autonomous_agent import build_agent,validate_machine_delivery,fingerprint
from courseagent.import_jobs import start_import
from courseagent.model_client import model_budget,chat_json

FIXTURE=json.loads((Path(__file__).resolve().parents[1]/'examples/offline-fixture.json').read_text())

def document():
 d=copy.deepcopy(FIXTURE)
 for q in d['questions']:q['approved']=False;q.pop('approval_snapshot',None)
 d['plan']={'spec':{'counts':{str(t):sum(q['type']==t and q.get('selected') for q in d['questions']) for t in range(1,6)},'programming_count':0},'diagnostics':{}}
 d['version']=1
 return d

class AgentTests(unittest.TestCase):
 def state(self):return {'document':document(),'request':{'prompt':'测试作业'},'sources':[],'rounds':0,'events':[]}
 def test_complete_delivers_without_teacher_confirmation(self):
  graph=build_agent(planner=lambda d,r,s:d,checker=lambda d:{'blocking':False,'issues':[]})
  out=graph.invoke(self.state());self.assertEqual(out['action'],'deliver')
  self.assertTrue(validate_machine_delivery(out['document']))
  self.assertFalse(any(q['approved'] for q in out['document']['questions']))
  out['document']['questions'][0]['stem']+='改动'
  with self.assertRaisesRegex(ValueError,'变化'):validate_machine_delivery(out['document'])
 def test_bad_question_automatically_replaced_good_questions_locked(self):
  calls=[];bad=self.state()['document']['questions'][0]['id']
  def planner(d,r,s):
   calls.append(copy.deepcopy(r));return d
  def checker(d):
   return {'blocking':len(calls)==1,'issues':[{'kind':'answer','question_ids':[bad],'message':'答案矛盾'}] if len(calls)==1 else []}
  out=build_agent(planner,checker,lambda *a:{'action':'search','reason':'更换错误题目'}).invoke(self.state())
  self.assertEqual(out['rounds'],2);self.assertEqual(out['events'][0]['action'],'replace')
  self.assertIn(bad,calls[1]['avoid_ids']);self.assertNotIn(bad,calls[1]['locked_ids'])
 def test_count_shortage_self_loops_and_stops_at_budget(self):
  calls=[]
  graph=build_agent(lambda d,r,s:(calls.append(r) or d),lambda d:{'blocking':True,'issues':[{'kind':'count','question_ids':[],'message':'缺1道题'}]},lambda *a:{'action':'search','reason':'换搜索词补齐'},max_decisions=2)
  out=graph.invoke(self.state());self.assertEqual(out['rounds'],3);self.assertEqual(out['action'],'stop');self.assertNotIn('delivery',out)
 def test_invalid_tool_action_never_delivers(self):
  with self.assertRaisesRegex(ValueError,'无效动作'):
   build_agent(lambda d,r,s:d,lambda d:{'blocking':True,'issues':[]},lambda *a:{'action':'publish','reason':'发布'}).invoke(self.state())
 def test_unavailable_oracle_stops_without_fake_approval(self):
  out=build_agent(lambda d,r,s:d,lambda d:{'blocking':True,'issues':[{'kind':'judge_capability','question_ids':['q'],'message':'无可信算法'}]}).invoke(self.state())
  self.assertEqual(out['action'],'stop');self.assertEqual(out['rounds'],1)
 def test_coding_capability_gap_does_not_stop_ordinary_quota_replenishment(self):
  state=self.state();state['document']['programming_questions']=[{'id':'coding-kept','selected':True}]
  calls=[]
  def planner(d,r,s):calls.append(copy.deepcopy(r));return d
  def checker(d):
   issues=[{'kind':'judge_capability','question_ids':['coding-kept'],'message':'无可信评测'}]
   if len(calls)==1:issues.append({'kind':'count','question_ids':[],'message':'判断题缺2道'})
   return {'blocking':True,'issues':issues}
  decisions=[]
  def decide(prompt,data):decisions.append(data);return {'action':'search','reason':'更换查询补齐判断题'}
  out=build_agent(planner,checker,decide).invoke(state)
  self.assertEqual(len(decisions),1);self.assertEqual(len(calls),2)
  self.assertEqual(out['events'][0]['action'],'search');self.assertEqual(out['action'],'stop')
  self.assertTrue(out['document']['programming_questions'][0]['selected'])
  self.assertNotIn('coding-kept',out.get('avoid_ids',[]));self.assertNotIn('delivery',out)
 def test_shortage_can_continue_past_three_batches(self):
  calls=[];decisions=[]
  def planner(d,r,s):calls.append(r);return d
  def checker(d):return {'blocking':len(calls)<5,'issues':[{'kind':'count','question_ids':[],'message':'缺1道判断题'}] if len(calls)<5 else []}
  def decide(p,d):decisions.append(d);return {'action':'search','reason':'换新来源','search_queries':['不同来源 新的知识素材']}
  out=build_agent(planner,checker,decide).invoke(self.state())
  self.assertEqual(out['rounds'],5);self.assertEqual(out['action'],'deliver')
  self.assertEqual(len(decisions),4);self.assertTrue(decisions[-1]['recent_attempts'])
  self.assertEqual(calls[-1]['agent_queries'],['不同来源 新的知识素材'])
 def test_dispatch_inspects_real_material_state_without_missing_context(self):
  state=self.state();state['document']['web_search']={'candidate_ids':[],'knowledge_sources':[]}
  checks=[]
  def checker(d):
   checks.append(1);return {'blocking':len(checks)==1,'issues':[{'kind':'count','question_ids':[],'message':'缺题'}] if len(checks)==1 else []}
  out=build_agent(lambda d,r,s:d,checker,lambda p,d:{'action':'search','reason':'素材不足继续搜索'}).invoke(state)
  self.assertEqual(out['action'],'deliver');self.assertEqual(out['rounds'],2)
 def test_global_budget_stops_even_when_cached_composition_returns(self):
  with model_budget(1) as budget:
   budget['calls']=1
   with patch('courseagent.model_client.chat_json') as model:
    out=build_agent(lambda d,r,s:d,lambda d:{'blocking':True,'issues':[{'kind':'count','question_ids':[],'message':'缺1道'}]}).invoke(self.state())
  model.assert_not_called();self.assertEqual(out['action'],'stop');self.assertIn('预算',out['reason'])
 def test_adapt_decision_reaches_existing_material_only_composition(self):
  calls=[]
  def planner(d,r,s):calls.append(copy.deepcopy(r));return d
  def checker(d):return {'blocking':len(calls)==1,'issues':[{'kind':'count','question_ids':[],'message':'缺判断题'}] if len(calls)==1 else []}
  state=self.state();state['request']['allow_adaptation']=True;state['document']['web_search']={'candidate_ids':[],'knowledge_sources':[]}
  with patch('courseagent.question_adaptation.has_unused_sources',return_value=True):
   out=build_agent(planner,checker,lambda *a:{'action':'adapt','reason':'先用现有知识素材改编'}).invoke(state)
  self.assertEqual(out['events'][0]['action'],'adapt');self.assertTrue(calls[1]['adaptation_only'])
 def test_repeated_unsuccessful_fix_switches_to_replacement_instead_of_stopping(self):
  state=self.state();qid=state['document']['questions'][0]['id'];checks=[]
  def checker(d):
   checks.append(1);return {'blocking':len(checks)<4,'issues':[{'kind':'answer','question_ids':[qid],'message':'答案仍不正确'}] if len(checks)<4 else []}
  with patch('courseagent.model_client.chat_json',return_value={'patches':[{'id':qid,'changes':{'explanation':'重新核对'},'reason':'尝试修复'}]}):
   out=build_agent(lambda d,r,s:d,checker,lambda *a:{'action':'fix','reason':'修复答案'}).invoke(state)
  self.assertEqual([e['action'] for e in out['events'][:3]],['fix','fix','replace'])
  self.assertEqual(out['action'],'deliver')
 def test_autonomous_checks_do_not_require_teacher_difficulty_but_keep_case_basis_checks(self):
  from courseagent.exam_quality import check_exam
  from tests.test_programming_questions import ProgrammingTests
  d=document();q=ProgrammingTests().sample();q.update(id='coding',difficulty=0)
  for c in q['test_cases']:c['verified']=False
  d['programming_questions']=[q];d['plan']['spec']['programming_count']=1
  report=check_exam(d,require_teacher_metadata=False)
  self.assertFalse(any(i['kind'] in ('format','conditions') for i in report['issues']))
  q['test_cases'][0]['output_basis']=''
  report=check_exam(d,require_teacher_metadata=False)
  self.assertTrue(any(i['kind']=='conditions' for i in report['issues']))
 def test_machine_import_independent_of_teacher_flags(self):
  out=build_agent(lambda d,r,s:d,lambda d:{'blocking':False,'issues':[]}).invoke(self.state())
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);job=start_import(root,out['document'],'https://www.educoder.net/classrooms/x/exercise','测试课程',runner=lambda *a:None,machine_checked=True)
   manifest=json.loads((root/'outputs/import-jobs'/job['id']/'manifest.json').read_text())
   self.assertEqual(manifest['validation_mode'],'agent');self.assertFalse(job['published'])
   with self.assertRaises(ValueError):start_import(root,document(),'https://www.educoder.net/classrooms/x/exercise','测试课程',runner=lambda *a:None,machine_checked=True)
 def test_budget_shared_across_model_calls(self):
  with patch('courseagent.model_client.configuration',return_value={'backend':'direct'}),patch('courseagent.model_client._chat_json',return_value={}):
   with model_budget(2) as b:
    chat_json('a',{});chat_json('b',{})
    with self.assertRaisesRegex(ValueError,'预算'):chat_json('c',{})
    self.assertEqual(b['calls'],2)
 def test_local_fix_rechecks_without_search_or_teacher(self):
  count=[];checks=[];state=self.state();qid=state['document']['questions'][0]['id']
  def check(d):
   checks.append(1)
   return {'blocking':len(checks)==1,'issues':[{'kind':'answer','question_ids':[qid],'message':'修正答案'}] if len(checks)==1 else []}
  patch_answer={'patches':[{'id':qid,'changes':{'explanation':'已重新核对选项'},'reason':'纠正解析'}]}
  with patch('courseagent.model_client.chat_json',return_value=patch_answer):
   out=build_agent(lambda d,r,s:(count.append(1) or d),check,lambda *a:{'action':'fix','reason':'修复局部问题'}).invoke(state)
  self.assertEqual(len(count),1);self.assertEqual(len(checks),2);self.assertEqual(out['repair_attempts'],1)
  self.assertEqual(out['document']['questions'][0]['explanation'],'已重新核对选项')
  self.assertFalse(out['document']['questions'][0]['approved'])

 def test_issue_verdict_retries_wrong_question_index(self):
  from courseagent.autonomous_agent import check_document
  d=document();qid=d['questions'][0]['id']
  replies=[{'issues':[{'kind':'answer','severity':'blocking','question_ids':[qid],'evidence':d['questions'][0]['stem'],'message':'具体答案错误'}]},
           {'confirmed_indices':[5]}, {'confirmed_issue_ids':['issue-0'],'reason':'已确认具体错误'}]
  def uncached(kind,key,fn,**kwargs):return fn(),False
  with patch('courseagent.web_questions.cached',side_effect=uncached),patch('courseagent.model_client.model_status',return_value={'model':'test'}),patch('courseagent.model_client.chat_json',side_effect=replies) as model:
   report=check_document(d)
  self.assertEqual(model.call_count,3);self.assertTrue(report['model_used']);self.assertNotIn('model_error',report)
  self.assertTrue(any(i.get('kind')=='answer' and i.get('severity')=='blocking' for i in report['issues']))
  self.assertTrue(report['blocking']);self.assertEqual(report['delivery_policy'],'unpublished_draft')

if __name__=='__main__':unittest.main()
