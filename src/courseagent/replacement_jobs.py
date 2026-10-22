"""Background replacement search; results are candidate previews, never saved review writes."""
import copy,json,threading,uuid
from datetime import datetime,timezone
LOCK=threading.RLock()
ACTIVE=set()

def start(root,document,question_id,reason,sources):
 from courseagent.replacements import REASONS
 if reason not in REASONS:raise ValueError('请选择换题原因')
 if not any(q['id']==question_id and q.get('selected') for q in document['questions']):raise ValueError('只能为已选题找备选')
 with LOCK:
  if ACTIVE:raise ValueError('已有换题搜索进行中，请等待完成')
  ident=uuid.uuid4().hex;ACTIVE.add(ident)
 folder=root/'outputs/replacement-search';folder.mkdir(parents=True,exist_ok=True);path=folder/(ident+'.json')
 job={'id':ident,'status':'running','question_id':question_id,'review_version':document.get('version'),'created_at':datetime.now(timezone.utc).isoformat()}
 def write():
  with LOCK:
   tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(job,ensure_ascii=False),encoding='utf-8');tmp.replace(path)
 write()
 def run():
  try:
   from courseagent.replacements import search_replacements
   result=search_replacements(copy.deepcopy(document),question_id,reason,copy.deepcopy(sources))
   with LOCK:job.update(status='completed',result=result)
  except Exception as e:
   with LOCK:job.update(status='failed',error=str(e)[:500])
  finally:
   write()
   with LOCK:ACTIVE.discard(ident)
 threading.Thread(target=run,daemon=True).start()
 with LOCK:return copy.deepcopy(job)

def get(root,ident):
 if len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):raise ValueError('换题任务编号不正确')
 with LOCK:
  path=root/'outputs/replacement-search'/(ident+'.json')
  if not path.exists():raise ValueError('换题任务不存在')
  job=json.loads(path.read_text())
  if job['status']=='running' and ident not in ACTIVE:job.update(status='failed',error='服务重启中断换题搜索，原作业保持不变')
  return job
