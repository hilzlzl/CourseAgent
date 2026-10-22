import copy
import json
import tempfile
import threading
import time
import unittest
from contextvars import copy_context
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from tests.test_autonomous_agent import document
from courseagent.model_client import TASK_BUDGET,model_budget,model_phase,chat_json,BudgetExhausted
from courseagent.agent_jobs import start,resume,read,write_json
from courseagent.autonomous_agent import build_agent

class ParallelResumeTests(unittest.TestCase):
 def test_sources_overlap_share_budget_and_merge_without_overwriting(self):
  from courseagent.workflow import parallel_sources
  barrier=threading.Barrier(2);seen=[];d=document()
  state={'document':copy.deepcopy(d),'request':{},'sources':[],
         'spec':{'counts':{'1':1},'programming_count':1},'trace':[]}
  class OrdinaryGraph:
   def stream(self,s,*args,**kwargs):
    seen.append(TASK_BUDGET.get());barrier.wait(timeout=3)
    s['document']['normal_marker']=True;s['document']['questions'][0]['stem']='ordinary branch'
    yield {'node':{'document':s['document'],'candidates':s['document']['questions']}}
  def coding(s):
   seen.append(TASK_BUDGET.get());barrier.wait(timeout=3)
   s['document']['normal_marker']=False
   s['document']['programming_questions']=[{'id':'coding','selected':True}]
   return {'document':s['document'],'programming_candidates':s['document']['programming_questions']}
  with model_budget() as b,patch('courseagent.workflow.build_graph',return_value=OrdinaryGraph()),patch('courseagent.programming_sourcing.source_programming_round',side_effect=coding),patch('courseagent.programming_sourcing.programming_next_step',return_value='done'):
   out=parallel_sources(state)
   self.assertTrue(all(x is b for x in seen))
  self.assertEqual(len(seen),2);self.assertTrue(out['document']['normal_marker'])
  self.assertEqual(out['document']['questions'][0]['stem'],'ordinary branch')
  self.assertEqual(out['document']['programming_questions'][0]['id'],'coding')
  self.assertEqual(state['document'],d)

 def test_ordinary_snapshot_preserves_pending_coding_branch(self):
  from courseagent.agent_jobs import merge_source_progress
  from tests.test_programming_questions import ProgrammingTests
  d=document();q=ProgrammingTests().sample();q['id']='kept';q['selected']=True
  d['programming_questions']=[q];spec=copy.deepcopy(d['plan']['spec']);spec['programming_count']=2;spec.setdefault('topics',[])
  state={'document':d,'spec':spec,'request':{'source_mode':'local'},'sources':[],'trace':[]}
  partial=merge_source_progress(state,{'ordinary':state})
  self.assertEqual(partial['plan']['programming_count']['selected'],1)
  self.assertTrue(partial['programming_questions'][0]['selected'])
  self.assertTrue(d['programming_questions'][0]['selected'])
  # A real removal is reflected; progress is not a cosmetic maximum.
  removed=copy.deepcopy(state);removed['document']['programming_questions'][0]['selected']=False
  partial=merge_source_progress(removed,{'ordinary':removed})
  self.assertEqual(partial['plan']['programming_count']['selected'],0)

 def test_delivery_recheck_retains_task_and_import_identity(self):
  from courseagent.agent_jobs import recheck_delivery
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);identity='c'*32;p=root/'outputs/agent-tasks'/identity;p.mkdir(parents=True)
   job={'id':identity,'status':'completed','created_at':'2026-10-13T00:00:00+00:00','import_id':'same-import',
        'result':document(),'target':{'classroom_url':'https://www.educoder.net/classrooms/x/exercise','course':'课程'},'execute':True}
   write_json(p/'task.json',job)
   with patch('courseagent.agent_jobs.public_job',return_value={'status':'completed','draft_url':'https://www.educoder.net/classrooms/x/exercise/123/detail'}),patch('courseagent.agent_jobs.start_import',return_value={'id':'same-import','status':'queued','message':'checking existing'}) as imported:
    receipt=recheck_delivery(root,identity)
   self.assertEqual(receipt,{'id':identity,'status':'importing','import_id':'same-import'})
   self.assertEqual(imported.call_args.args[1],job['result'])
   self.assertTrue(imported.call_args.kwargs['machine_checked'])
   saved=json.loads((p/'task.json').read_text());self.assertNotIn('draft_url',saved)
   self.assertEqual(saved['status'],'importing')

 def test_coding_candidates_emit_before_batch_completion(self):
  from courseagent.programming_sourcing import emit_programming_progress
  states=[];d=document();state={'spec':{'programming_count':4},'trace':[]}
  candidate={'id':'accepted','selected':False}
  with model_budget() as b:
   b['on_source_checkpoint']=lambda branch,s:states.append((branch,s))
   emit_programming_progress(state,d,[candidate],{'pages':2,'search_rounds':1})
  self.assertEqual(states[0][0],'programming')
  self.assertEqual(states[0][1]['programming_candidates'],[candidate])
  self.assertEqual(states[0][1]['document']['programming_search']['missing'],3)
  self.assertNotIn('programming_search',d)

 def test_course_topic_alias_matches_search_problem(self):
  from courseagent.programming_sourcing import topic_matches
  self.assertTrue(topic_matches(['查找算法'],'给定有序数组，实现二分查找'))
  self.assertTrue(topic_matches(['查找算法'],'Binary Search'))
  self.assertFalse(topic_matches(['查找算法'],'翻转二叉树'))
  from courseagent.algorithm_sources import TAGS
  self.assertEqual(TAGS['查找算法'],'binary-search')

 def test_atomic_call_limit_and_reserved_checks(self):
  def call():
   try:chat_json('test',{});return True
   except BudgetExhausted:return False
  with model_budget(25) as b,patch('courseagent.model_client.configuration',return_value={'backend':'direct'}),patch('courseagent.model_client._chat_json',return_value={}):
   with model_phase('sourcing'),ThreadPoolExecutor(max_workers=8) as pool:
    results=list(pool.map(lambda context:context.run(call),[copy_context() for _ in range(30)]))
   self.assertEqual(sum(results),20);self.assertEqual(b['calls'],20)
   chat_json('remaining verification',{});self.assertEqual(b['calls'],21)

 def test_continue_same_identity_without_recomposition_or_teacher_changes(self):
  d=document();original=copy.deepcopy(d)
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   def stopped(**kw):return build_agent(lambda *a:copy.deepcopy(d),lambda d:{'blocking':True,'issues':[{'kind':'model_unavailable','message':'temporary','question_ids':[]}]},**kw)
   j=start(root,d,{'prompt':'测试任务'},[],{},execute=False,graph_factory=stopped)
   for _ in range(1000):
    job=read(root,j['id'])
    if job['status']!='running':break
    time.sleep(.02)
   self.assertTrue(job['can_resume'])
   task_folder=root/'outputs/agent-tasks'/j['id']
   partial=json.loads((task_folder/'state.json').read_text())
   partial['document']['questions'][0]['explanation']='newer persisted partial'
   partial['document']['questions'][0]['ordinary_blind_check']={'method':'blind_solve_incomplete'}
   from courseagent.ordinary_verification import basis
   partial['document']['questions'][1]['ordinary_blind_check']={'method':'blind_solve_then_compare','verdict':'pass','basis':basis(partial['document']['questions'][1])}
   write_json(task_folder/'partial-state.json',partial)
   def continued(**kw):
    def must_not_compose(*a):raise AssertionError('resume recomposed completed work')
    return build_agent(must_not_compose,lambda d:{'blocking':False,'issues':[]},**kw)
   receipt=resume(root,j['id'],graph_factory=continued)
   self.assertEqual(receipt['id'],j['id'])
   for _ in range(1000):
    job=read(root,j['id'])
    if job['status']!='running':break
    time.sleep(.02)
   self.assertEqual(job['status'],'ready');self.assertEqual(job['resume_count'],1)
   self.assertEqual(job['result']['questions'][0]['explanation'],'newer persisted partial')
   self.assertNotIn('ordinary_blind_check',job['result']['questions'][0])
   self.assertEqual(job['result']['questions'][1]['ordinary_blind_check']['verdict'],'pass')
   self.assertEqual(job['budget']['max_calls'],100);self.assertEqual(d,original)
   self.assertEqual(len(list((root/'outputs/agent-tasks').iterdir())),1)
   with self.assertRaises(ValueError):resume(root,j['id'])

if __name__=='__main__':unittest.main()
