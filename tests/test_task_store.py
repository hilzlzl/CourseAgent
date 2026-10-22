import json
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from courseagent.task_store import TaskStore

class StoreTests(unittest.TestCase):
    def test_enqueue_reservation_and_claim_are_atomic_across_connections(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=TaskStore(root)
            store.enqueue({'id':'a','status':'queued'},{'request':{'prompt':'x'}})
            with self.assertRaises(ValueError):TaskStore(root).enqueue({'id':'b','status':'queued'},{})
            with ThreadPoolExecutor(max_workers=2) as pool:
                claims=list(pool.map(lambda owner:TaskStore(root).claim(owner),['one','two']))
            self.assertEqual(sum(c is not None for c in claims),1)
            owner='one' if claims[0] else 'two'
            with self.assertRaises(RuntimeError):store.save({'id':'a','status':'ready'},owner='wrong')
            self.assertTrue(store.heartbeat('a',owner));self.assertFalse(store.heartbeat('a','wrong'))
            store.save({'id':'a','status':'ready'});store.finish('a',owner)
            store.enqueue({'id':'b','status':'queued'},{})
    def test_expired_lease_recovers_compute_but_never_replays_uncertain_write(self):
        with tempfile.TemporaryDirectory() as folder:
            store=TaskStore(folder)
            store.enqueue({'id':'a','status':'queued'},{'request':{}});store.claim('old',lease_seconds=-1)
            self.assertEqual(store.recover_expired(),['a']);self.assertEqual(store.get('a')['status'],'queued')
            store.claim('new',lease_seconds=-1);store.save({'id':'a','status':'running','delivery_intent':True})
            self.assertEqual(store.recover_expired(),[])
            self.assertEqual(store.get('a')['status'],'needs_attention');self.assertIsNone(store.claim('third'))
    def test_event_cursor_replays_only_new_summaries_without_question_content(self):
        with tempfile.TemporaryDirectory() as folder:
            store=TaskStore(folder)
            store.save({'id':'a','status':'running','result':{'reference_code':'PRIVATE'},'activity':'reading'})
            first=store.events()[0];store.save({'id':'a','status':'ready'})
            events=store.events(after=first['seq'])
            self.assertEqual(len(events),1);self.assertEqual(events[0]['summary']['status'],'ready')
            self.assertNotIn('PRIVATE',json.dumps(store.events()))
    def test_recovery_preserves_elapsed_even_before_first_model_call(self):
        from datetime import datetime,timezone,timedelta
        from unittest.mock import patch
        from courseagent.agent_worker import run_once
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=TaskStore(root)
            started=(datetime.now(timezone.utc)-timedelta(seconds=90)).isoformat()
            store.enqueue({'id':'a','status':'running','run_started_at':started,
                           'elapsed_before_run':40,'elapsed_seconds':40,'model_calls':0},{})
            store.claim('old',lease_seconds=-1)
            with patch('courseagent.agent_jobs.run_job') as run:
                self.assertTrue(run_once(root))
                submission=run.call_args.args[3]
                self.assertGreaterEqual(submission['previous_elapsed'],130)
                self.assertEqual(submission['previous_calls'],0)

class WorkerTests(unittest.TestCase):
    def test_submission_waits_for_worker_and_then_exports_without_review_write(self):
        from courseagent.agent_jobs import start,read
        from courseagent.agent_worker import run_once
        from courseagent.autonomous_agent import build_agent
        from tests.test_autonomous_agent import document
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            def graph(**kw):return build_agent(lambda d,r,s:d,lambda d:{'blocking':False,'issues':[]},**kw)
            job=start(root,document(),{'prompt':'队列作业'},[],{},execute=False)
            self.assertEqual(read(root,job['id'])['status'],'queued')
            self.assertTrue(run_once(root,graph_factory=graph))
            result=read(root,job['id']);self.assertEqual(result['status'],'ready')
            self.assertFalse(result['published']);self.assertFalse((root/'data/review.json').exists())
            self.assertTrue((root/'outputs/agent-tasks'/job['id']/'assignment.xlsx').exists())
            self.assertFalse(run_once(root,graph_factory=graph))
    def test_sqlite_langgraph_resume_does_not_repeat_completed_node(self):
        from langgraph.graph import StateGraph,START,END
        from langgraph.checkpoint.sqlite import SqliteSaver
        from typing import TypedDict
        class State(TypedDict):value:int
        calls=[];fail=[True]
        def first(s):calls.append('first');return {'value':s['value']+1}
        def second(s):
            if fail[0]:raise RuntimeError('interrupted')
            calls.append('second');return {'value':s['value']+1}
        def make(saver):
            g=StateGraph(State);g.add_node('first',first);g.add_node('second',second)
            g.add_edge(START,'first');g.add_edge('first','second');g.add_edge('second',END)
            return g.compile(checkpointer=saver)
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'checkpoints.sqlite');config={'configurable':{'thread_id':'task'}}
            with SqliteSaver.from_conn_string(path) as saver:
                with self.assertRaises(RuntimeError):make(saver).invoke({'value':0},config)
            fail[0]=False
            with SqliteSaver.from_conn_string(path) as saver:
                graph=make(saver);self.assertEqual(graph.get_state(config).next,('second',))
                self.assertEqual(graph.invoke(None,config)['value'],2)
        self.assertEqual(calls,['first','second'])
