import json,tempfile,time,unittest,copy
from pathlib import Path
from unittest.mock import patch
from courseagent.autonomous_agent import build_agent
from courseagent.agent_jobs import start,read
from tests.test_autonomous_agent import document

class JobsTests(unittest.TestCase):
 def test_start_does_not_revalidate_every_historical_document(self):
  from courseagent.agent_jobs import stop
  with tempfile.TemporaryDirectory() as tmp,patch('courseagent.agent_jobs.list_tasks',side_effect=AssertionError('历史全量扫描')):
   root=Path(tmp);j=start(root,document(),{'prompt':'栈作业'},[],{},execute=False)
   self.assertEqual(j['status'],'queued');stop(root,j['id'])

 def test_unchanged_finished_summary_does_not_repeat_verification(self):
  from courseagent.agent_jobs import folder,write_json,_list_tasks
  from courseagent.task_store import store_for
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);identity='d'*32;p=folder(root)/identity;p.mkdir()
   job={'id':identity,'status':'ready','created_at':'2026-10-18T00:00:00+00:00',
        'result':{'questions':[],'programming_questions':[{'id':'p','selected':True}]}}
   store_for(root).save(job);write_json(p/'task.json',job)
   with patch('courseagent.verification_state.summary',return_value={'total':1}) as summary, \
        patch('courseagent.programming_judge.delivery_report',return_value={'passed':True}) as verify:
    first=_list_tasks(root);second=_list_tasks(root)
    self.assertEqual(first,second);self.assertEqual(summary.call_count,1);self.assertEqual(verify.call_count,1)
    job['result']['programming_questions']=[];store_for(root).save(job);write_json(p/'task.json',job)
    self.assertNotIn('programming_verification_summary',_list_tasks(root)[0])
    self.assertEqual(summary.call_count,2)
 def test_dead_durable_worker_waits_for_auto_recovery_without_manual_resume(self):
  from datetime import datetime,timezone
  from courseagent.task_store import store_for
  from courseagent.agent_jobs import folder,write_json
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);identity='e'*32;p=folder(root)/identity;p.mkdir()
   job={'id':identity,'status':'running','owner_pid':99999999,
        'created_at':datetime.now(timezone.utc).isoformat(),'result':{'questions':[{'id':'kept'}]}}
   store=store_for(root);store.enqueue(job,{});store.claim('dead')
   write_json(p/'task.json',job)
   observed=read(root,identity)
   self.assertEqual(observed['status'],'queued');self.assertFalse(observed['can_resume'])
   self.assertIn('自动',observed['phase'])
   self.assertEqual(store.get(identity)['status'],'running')
 def test_resumed_elapsed_excludes_time_awaiting_manual_continuation(self):
  from datetime import datetime,timezone,timedelta
  import os
  from courseagent.agent_jobs import folder,write_json
  from courseagent.task_store import store_for
  now=datetime.now(timezone.utc)
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);identity='f'*32;p=folder(root)/identity;p.mkdir()
   job={'id':identity,'status':'running','owner_pid':os.getppid(),
        'created_at':(now-timedelta(days=1)).isoformat(),
        'run_started_at':(now-timedelta(seconds=30)).isoformat(),
        'elapsed_before_run':120,'elapsed_seconds':120}
   store_for(root).save(job);write_json(p/'task.json',job)
   observed=read(root,identity)
   self.assertGreaterEqual(observed['elapsed_seconds'],150)
   self.assertLess(observed['elapsed_seconds'],155)
   self.assertLess(observed['run_elapsed_seconds'],35)
   self.assertEqual(store_for(root).get(identity)['elapsed_seconds'],120)

 def test_stop_queued_task_preserves_result_and_revokes_delivery_lease(self):
  from courseagent.task_store import store_for
  from courseagent.agent_jobs import stop,write_json,folder
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);identity='a'*32;p=folder(root)/identity;p.mkdir()
   job={'id':identity,'status':'queued','created_at':'2026-10-14T00:00:00+00:00','request':'测试','published':False}
   store=store_for(root);store.enqueue(job,{'request':{'prompt':'测试'}})
   write_json(p/'task.json',job);write_json(p/'partial-state.json',{'document':{'questions':[{'id':'retained'}]}})
   result=stop(root,identity)
   self.assertEqual(result['status'],'stopped');self.assertEqual(result['result']['questions'][0]['id'],'retained')
   self.assertIsNone(store.claim('worker'))
   self.assertTrue((p/'stop-requested').exists())
   self.assertEqual(stop(root,identity)['status'],'stopped')

 def test_stop_refuses_uncertain_platform_write(self):
  from courseagent.task_store import store_for
  from courseagent.agent_jobs import stop,write_json,folder
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);identity='b'*32;p=folder(root)/identity;p.mkdir()
   job={'id':identity,'status':'running','created_at':'2026-10-14T00:00:00+00:00','request':'测试','delivery_intent':True}
   store=store_for(root);store.enqueue(job,{});write_json(p/'task.json',job)
   with self.assertRaises(ValueError):stop(root,identity)
   self.assertFalse((p/'stop-requested').exists())

 def test_cancel_escapes_broad_retry_handlers_before_model_call(self):
  from courseagent.task_cancellation import TaskStopped
  from courseagent.model_client import model_budget,request_limits
  with model_budget() as budget:
   budget['stop_requested']=lambda:True
   with self.assertRaises(TaskStopped):request_limits(60)

 def test_overlapping_progress_requests_share_one_history_scan(self):
  from concurrent.futures import ThreadPoolExecutor
  import threading
  from courseagent import agent_jobs
  entered=threading.Event();release=threading.Event()
  def slow(root):entered.set();release.wait(2);return [{'id':'fixture','status':'running'}]
  with tempfile.TemporaryDirectory() as tmp,patch('courseagent.agent_jobs._list_tasks',side_effect=slow) as scan:
   with ThreadPoolExecutor(max_workers=3) as pool:
    futures=[pool.submit(agent_jobs.list_tasks,Path(tmp)) for _ in range(3)]
    self.assertTrue(entered.wait(1));release.set()
    results=[f.result() for f in futures]
   scan.assert_called_once()
   results[0][0]['status']='changed'
   self.assertEqual(agent_jobs.list_tasks(Path(tmp))[0]['status'],'running')

 def test_workflow_emits_candidate_counts_before_final_result(self):
  from courseagent.model_client import model_budget
  from courseagent.workflow import plan
  snapshots=[]
  with model_budget() as budget:
   budget['on_candidates']=lambda s:snapshots.append(copy.deepcopy(s))
   result=plan(document(),{'prompt':'2道单选题 1道多选题 1道判断题 1道填空题','source_mode':'local'},[])
  self.assertGreaterEqual(len(snapshots),2)
  self.assertEqual(snapshots[-1]['type_counts'],result['plan']['type_counts'])
  self.assertTrue(all('type_counts' in s for s in snapshots))
 def test_background_delivery_persists_without_mutating_review(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);doc=document();original=copy.deepcopy(doc)
   def graph(**kw):return build_agent(lambda d,r,s:d,lambda d:{'blocking':False,'issues':[]},**kw)
   j=start(root,doc,{'prompt':'测试要求'},[],{},execute=False,graph_factory=graph)
   for _ in range(1000):
    result=read(root,j['id'])
    if result['status']!='running':break
    time.sleep(.02)
   self.assertEqual(result['status'],'ready');self.assertEqual(doc,original)
   p=root/'outputs/agent-tasks'/j['id'];self.assertTrue((p/'state.json').exists());self.assertTrue((p/'assignment.xlsx').exists())
   self.assertFalse(result['published']);self.assertFalse(any(q['approved'] for q in result['result']['questions']))
 def test_programming_delivery_not_silently_truncated(self):
  from courseagent.tree_judge import apply_contract
  from tests.test_programming_questions import ProgrammingTests
  d=document();q=ProgrammingTests().sample();q["id"]="coding";apply_contract(q,'max_depth');q['selected']=True;d['programming_questions']=[q];d['plan']['spec']['programming_count']=1
  from courseagent.programming_verification import basis,case_basis,VERSION
  q['execution_verification']={'passed':True,'status':'verified','method':VERSION,'basis':basis(q),'case_basis':case_basis(q),'case_count':8,'mutation_testing':{'passed':True,'eligible_count':2}}
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   def graph(**kw):return build_agent(lambda d,r,s:d,lambda d:{'blocking':False,'issues':[]},**kw)
   with patch('courseagent.agent_jobs.start_import',return_value={'id':'mixed-job'}) as imported, patch('courseagent.agent_jobs.public_job',return_value={'status':'running'}):
    j=start(root,d,{'prompt':'测试要求'},[],{'classroom_url':'https://www.educoder.net/classrooms/x/exercise','course':'测试课程'},graph_factory=graph)
    for _ in range(1000):
     result=read(root,j['id'])
     if result['status']!='running':break
     time.sleep(.02)
    self.assertEqual(result['status'],'importing');imported.assert_called_once()
    self.assertEqual(result['import_id'],'mixed-job')
    self.assertEqual(result['result']['agent_validation']['programming_verification'][0]['case_count'],8)
    self.assertTrue((root/'outputs/agent-tasks'/j['id']/'judge-tests.zip').exists())

if __name__=='__main__':unittest.main()
