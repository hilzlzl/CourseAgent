"""Real-process infrastructure acceptance with deterministic fixtures, zero model calls/writes."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import urllib.request
ROOT=Path(__file__).resolve().parents[1]
API_CODE='''import sys
from pathlib import Path
from courseagent import app
import uvicorn
from courseagent.api_service import create_app
root=Path(sys.argv[1]);app.ROOT=root;app.STATE=root/'review.json';app.SOURCES=root/'sources.json'
uvicorn.run(create_app(root),host='127.0.0.1',port=int(sys.argv[2]),log_level='warning')
'''
WORKER_CODE='''import sys
from pathlib import Path
from courseagent.autonomous_agent import build_agent
from courseagent.agent_worker import run_once
def graph(**kw):return build_agent(lambda d,r,s:d,lambda d:{'blocking':False,'issues':[]},**kw)
assert run_once(Path(sys.argv[1]),graph_factory=graph)
'''

def run():
    from tests.test_autonomous_agent import document
    from courseagent.task_store import TaskStore
    environment={**os.environ,'EDUCODER_TRACE_MODE':'fixture_infrastructure'}
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def wait_api(url):
        for _ in range(100):
            try:return json.load(opener.open(url+'/api/health',timeout=1))
            except Exception:time.sleep(.1)
        raise RuntimeError('API startup failed')
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder);review=root/'review.json';review.write_text(json.dumps(document()))
        before=review.read_bytes()
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        base='http://127.0.0.1:'+str(port)
        def api():return subprocess.Popen([sys.executable,'-c',API_CODE,str(root),str(port)],cwd=ROOT,env=environment,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        service=api()
        try:
            health=wait_api(base)
            request=urllib.request.Request(base+'/api/agent-start',json.dumps({'prompt':'离线基础设施验收','execute':False}).encode(),{'Content-Type':'application/json'})
            job=json.load(opener.open(request,timeout=10));assert job['status']=='queued'
            service.terminate();service.wait(timeout=10)
            assert TaskStore(root).get(job['id'])['status']=='queued'
            worker=subprocess.run([sys.executable,'-c',WORKER_CODE,str(root)],cwd=ROOT,env=environment,capture_output=True,timeout=30)
            if worker.returncode:raise RuntimeError('fixture Worker failed: '+worker.stderr.decode()[-1000:])
            service=api();wait_api(base)
            result=json.load(opener.open(base+'/api/agent-tasks/'+job['id'],timeout=10))
            assert result['status']=='ready' and not result['published']
            assert (root/'outputs/agent-tasks'/job['id']/'assignment.xlsx').exists()
            events=TaskStore(root).events(identity=job['id']);cursor=events[-1]['seq']
            saved=TaskStore(root).get(job['id']);saved['activity']='offline replay probe';TaskStore(root).save(saved)
            req=urllib.request.Request(base+'/api/agent-events',headers={'Last-Event-ID':str(cursor)})
            with opener.open(req,timeout=10) as response:
                found=None
                for _ in range(20):
                    line=response.readline().decode()
                    if line.startswith('data: '):found=json.loads(line[6:]);break
                assert found and found['seq']>cursor
            assert review.read_bytes()==before
            return {'passed':True,'mode':'real_api_and_worker_processes_with_fixture_graph',
                    'queue_survives_api_restart':True,'worker_exports_preview':True,'sse_replays_cursor':True,
                    'review_unchanged':True,'model_calls':0,'platform_writes':0,
                    'limitations':['这是基础设施验收，使用固定题目和检查器，不是实际模型组卷或平台交付成功率。']}
        finally:
            if service.poll() is None:service.terminate();service.wait(timeout=10)

def main():
    from courseagent.workspace_setup import initialize_workspace
    initialize_workspace(ROOT)
    report=run();(ROOT/'outputs/infrastructure-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
