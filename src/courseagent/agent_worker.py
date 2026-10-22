"""Independent durable Agent Worker. API restarts do not interrupt this process."""
from courseagent.paths import ROOT as WORKSPACE_ROOT
import argparse
import os
import threading
import time
import uuid
from pathlib import Path
from courseagent.task_store import TaskStore,store_for

ROOT=WORKSPACE_ROOT


def run_once(root=ROOT,graph_factory=None):
    store=store_for(root);store.recover_expired()
    owner=str(os.getpid())+'-'+uuid.uuid4().hex
    claimed=store.claim(owner)
    if not claimed:return False
    stop=threading.Event()
    def heartbeat():
        while not stop.wait(10):
            if not store.heartbeat(claimed['id'],owner):break
    thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
    try:
        from courseagent.agent_jobs import run_job
        submission=claimed['submission'];job=claimed['job'];submission['worker_owner']=owner
        # A lease recovery continues from the LangGraph checkpoint, with totals preserved.
        submission['previous_calls']=max(submission.get('previous_calls',0),job.get('model_calls',0))
        submission['previous_elapsed']=max(submission.get('previous_elapsed',0),job.get('elapsed_seconds',0))
        from courseagent.observability import span
        with span('autonomous_task',metrics={'task_id':claimed['id']}) as metrics:
            run_job(Path(root),claimed['id'],job,submission,graph_factory=graph_factory)
            metrics['task_status']=job.get('status')
            metrics['task_complete']=job.get('status') in ('ready','completed')
    finally:
        stop.set();thread.join(timeout=2);store.finish(claimed['id'],owner)
    return True


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--once',action='store_true');args=parser.parse_args()
    print('Agent Worker ready (draft-only)',flush=True)
    while True:
        ran=run_once(args.root)
        if args.once:return
        if not ran:time.sleep(1)

if __name__=='__main__':main()
