"""Content-free local traces and optional explicit LangSmith SDK transport."""
from courseagent.paths import ROOT as WORKSPACE_ROOT
import copy,json,os,threading,time,uuid,sqlite3,queue
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime,timezone
from functools import wraps,lru_cache
from pathlib import Path
ROOT=WORKSPACE_ROOT
CONFIG=ROOT/'langsmith-config.local.json'
TRACE_DIR=ROOT/'outputs/traces'
PARENT=ContextVar('educoder_trace_parent',default=None)
LOCK=threading.RLock()
TRANSPORT_ERROR=None
UPLOADS=queue.Queue(maxsize=1000)
UPLOAD_THREAD=None
UPLOAD_LOCK=threading.Lock()


def _upload_loop():
 while True:
  operation,record=UPLOADS.get()
  try:
   if TRANSPORT_ERROR:continue
   client=_client()
   if client is None:continue
   if operation=='start':
    client.create_run(name=record['name'],run_type=record['kind'],inputs=record['metrics'],
      id=record['id'],parent_run_id=record['parent_id'],project_name=configuration()['project'])
   else:
    client.update_run(record['id'],end_time=datetime.fromisoformat(record['ended_at']),
      outputs={'status':record['status'],'elapsed_ms':record['elapsed_ms'],**record['metrics']},
      error=record['error_type'] if record['status']=='failed' else None)
  except Exception:
   global_error('LangSmith上传失败；组卷继续，追踪保留在本地')
  finally:UPLOADS.task_done()


def global_error(message):
 global TRANSPORT_ERROR
 TRANSPORT_ERROR=message


def _enqueue(operation,record):
 """Remote telemetry must never sit on the Agent execution path."""
 global UPLOAD_THREAD
 try:
  if os.environ.get('EDUCODER_TRACE_MODE') in ('offline_tests','fixture_infrastructure'):return
  if TRANSPORT_ERROR or not configuration()['enabled']:return
  with UPLOAD_LOCK:
   if UPLOAD_THREAD is None or not UPLOAD_THREAD.is_alive():
    UPLOAD_THREAD=threading.Thread(target=_upload_loop,daemon=True,name='langsmith-uploader');UPLOAD_THREAD.start()
  UPLOADS.put_nowait((operation,copy.deepcopy(record)))
 except queue.Full:global_error('LangSmith上传队列已满；组卷继续，完整追踪保留在本地')
 except Exception:global_error('LangSmith配置无法读取；组卷继续，追踪保留在本地')


def configuration():
 c=json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
 return {'enabled':c.get('enabled') is True,'api_key':os.environ.get('EDUCODER_LANGSMITH_API_KEY',c.get('api_key','')),
         'endpoint':c.get('endpoint','https://api.smith.langchain.com'),'project':c.get('project','educoder-exam')}


def status():
 try:
  c=configuration()
  import importlib.util
  installed=bool(importlib.util.find_spec('langsmith'))
  return {'enabled':c['enabled'],'configured':bool(c['api_key']),'sdk_installed':installed,
          'project':c['project'],'content_uploaded':False,'transport_error':TRANSPORT_ERROR,
          'mode':'仅上传节点名称、耗时、数量和模型用量，不上传题目、资料或密钥'}
 except (ValueError,OSError):return {'enabled':False,'configured':False,'error':'追踪配置无法读取；不影响组卷'}


def _client():
 global TRANSPORT_ERROR
 if os.environ.get('EDUCODER_TRACE_MODE') in ('offline_tests','fixture_infrastructure'):return None
 try:
  c=configuration()
  if not c['enabled'] or not c['api_key'] or TRANSPORT_ERROR:return None
  from urllib.parse import urlparse
  u=urlparse(c['endpoint'])
  if u.scheme!='https' or u.username or u.password:raise ValueError('endpoint')
  return _configured_client(c['endpoint'],c['api_key'])
 except Exception:
  TRANSPORT_ERROR='LangSmith连接或配置失败；本次服务保留本地追踪，重启后可重试'
  return None


@lru_cache(maxsize=2)
def _configured_client(endpoint,api_key):
 from langsmith import Client
 return Client(api_url=endpoint,api_key=api_key,auto_batch_tracing=False,
               timeout_ms=1500,omit_traced_runtime_info=True)


def _save(record):
 try:
  with LOCK:
   TRACE_DIR.mkdir(parents=True,exist_ok=True)
   p=TRACE_DIR/(record['id']+'.json');tmp=p.with_suffix('.tmp')
   tmp.write_text(json.dumps(record,ensure_ascii=False,indent=2));tmp.replace(p)
   from courseagent.trace_store import store_at
   store_at(str(TRACE_DIR.absolute())).save(record)
 except (OSError,sqlite3.Error):pass


@contextmanager
def span(name,kind='chain',metrics=None):
 global TRANSPORT_ERROR
 ident=str(uuid.uuid4());parent=PARENT.get();token=PARENT.set(ident);started=time.monotonic()
 record={'id':ident,'parent_id':parent,'name':name,'kind':kind,'started_at':datetime.now(timezone.utc).isoformat(),
         'status':'running','mode':os.environ.get('EDUCODER_TRACE_MODE','runtime'),'metrics':copy.deepcopy(metrics or {})}
 _save(record);_enqueue('start',record)
 try:
  yield record['metrics']
 except BaseException as e:
  record.update(status='paused' if type(e).__name__=='GraphInterrupt' else 'failed',error_type=type(e).__name__);raise
 finally:
  record.setdefault('error_type',None)
  if record['status']=='running':record['status']='completed'
  record['ended_at']=datetime.now(timezone.utc).isoformat()
  record['elapsed_ms']=round((time.monotonic()-started)*1000);_save(record)
  _enqueue('finish',record)
  PARENT.reset(token)


def traced(name):
 def decorate(fn):
  @wraps(fn)
  def run(*args,**kwargs):
   with span(name) as m:
    result=fn(*args,**kwargs)
    if isinstance(result,dict):
     document=result.get('result',result)
     if isinstance(document.get('questions'),list):m['selected_count']=sum(bool(q.get('selected')) for q in document['questions'])
     if isinstance(result.get('candidates'),list):m['candidate_count']=len(result['candidates'])
     web=result.get('web',{})
     for k in ('model_calls','search_rounds','adaptation_rounds'):
      if isinstance(web.get(k),(int,float)):m[k]=web[k]
    return result
  return run
 return decorate
