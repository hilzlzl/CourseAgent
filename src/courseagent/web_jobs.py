"""Background sourcing jobs; previews never overwrite the teacher's saved review."""
import copy
import json
import threading
import uuid
from pathlib import Path
from datetime import datetime,timezone

LOCK=threading.RLock()
ACTIVE=False
PHASES={'plan_teaching_goals':'规划教学目标与知识点分配','parse_requirements':'理解作业要求','annotate_knowledge':'读取参考范围','plan_web_search':'准备搜索','search_and_read':'搜索并读取网页（首轮最多6页）','extract_web_questions':'提取题目并检查原文证据','adapt_question_types':'只补剩余缺口，换来源改编与复核','check_web_gaps':'检查剩余题数与补题预算','replenish_missing_types':'更换查询继续搜题（预算内）','retrieve_candidates':'检查题型和答案完整性','rank_candidates':'整理候选题','assemble_draft':'准备审核预览','teacher_review':'等待教师审核'}
PHASES['source_programming_questions']='多轮搜集编程题、核对评测契约，缺题自动继续补搜'
PHASES['complete_missing_answers']='自动解答无答案原题，随后独立核验'
PHASES.update(researcher='针对剩余缺口规划来源研究',researcher_tools='搜索并读取新的题目来源',
              compress_research='交接题目原文和来源记录')

def start(root,checkpoint,document,request,sources):
    global ACTIVE
    with LOCK:
        if ACTIVE: raise ValueError('已有网络搜题任务进行中，请等待完成')
        ACTIVE=True
    job_id=uuid.uuid4().hex;folder=root/'outputs/web-search';folder.mkdir(parents=True,exist_ok=True)
    job={'id':job_id,'status':'running','phase':'准备搜索','created_at':datetime.now(timezone.utc).isoformat(),'request':request.get('prompt',''),'review_version':document.get('version')}
    path=folder/(job_id+'.json')
    def write():
        with LOCK:
            tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(job,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)
    write()
    def run():
        global ACTIVE
        try:
            from courseagent.review_workflow import create
            def progress(node):
                job['phase']=PHASES.get(node,node);write()
            result=create(checkpoint,copy.deepcopy(document),copy.deepcopy(request),copy.deepcopy(sources),progress=progress)
            job.update(status='completed',phase='搜题完成，等待核对',result=result)
        except Exception as e:
            job.update(status='failed',phase='搜题未完成',error=str(e)[:500])
        finally:
            write()
            with LOCK: ACTIVE=False
    threading.Thread(target=run,daemon=True).start()
    return {k:v for k,v in job.items() if k!='result'}

def get(root,job_id):
    if len(job_id)!=32 or any(c not in '0123456789abcdef' for c in job_id): raise ValueError('搜题任务编号错误')
    with LOCK:
        path=root/'outputs/web-search'/(job_id+'.json')
        if not path.exists(): raise ValueError('搜题任务不存在')
        job=json.loads(path.read_text(encoding='utf-8'))
    if job['status']=='running' and not ACTIVE:
        job.update(status='failed',error='服务重启中断了搜题，已有审核进度保留，可重新搜题并复用缓存')
    return job
