"""Persist autonomous task progress separately from teacher review state."""
import copy
import json
import threading
import uuid
import os
import time
from pathlib import Path
from datetime import datetime, timezone
from courseagent.import_jobs import write_json, start_import, public_job
from courseagent.autonomous_agent import build_agent, validate_machine_delivery
LOCK=threading.RLock()
ACTIVE=set()
BUDGETS={}
LIST_LOCK=threading.RLock()
LIST_CACHE={}
TASK_SUMMARY_CACHE={}
from contextvars import ContextVar
from courseagent.task_cancellation import TaskStopped
WORKER_OWNER=ContextVar("worker_lease_owner",default=None)

def persist(root,path,job):
    from courseagent.task_store import TaskStore,store_for
    store_for(root).save(job,owner=WORKER_OWNER.get())
    write_json(path,job)
    LIST_CACHE.pop(str(Path(root).absolute()),None)

PHASES={'compose':'自主检索、改编与补齐','inspect':'自动检查整卷与评测用例','decide':'根据检查结果决定下一步','repair':'保留合格题，替换问题题','deliver':'导出并提交未发布试卷'}
PHASES['begin']='准备本次执行与防循环保护'
PHASES['fix']='自动修正答案或必要条件，然后独立复核'
PHASES['repair_statements']='保留原题，局部修复编程题说明并重新验证'
PHASES['verify_coding']='编程题评测输入设计与程序运行核验'
PHASES['retained_candidates']='题目已齐，保留已有结果'
PHASES['source_batch_done']='本批候选已汇总'
PHASES['collect_candidates']='从未尝试的原题继续补齐编程题'
PHASES['verify_candidates']='执行编程题验证，保留通过题并补失败题'
PHASES['retain_requirements']='需求未变，复用规划并只补缺额'
PHASES['verify_answers']='检查资料题的提取匹配；核验无可信答案的题目'
PHASES['retry_verification']='保留题目与完成步骤，继续局部验证'
PHASES['recover_sources']='恢复普通题失败步骤，保留已完成成果'
PHASES['recover_programming']='自动恢复编程题来源步骤，保留已完成成果'
from courseagent.web_jobs import PHASES as SOURCING_PHASES
PHASES.update({k:v for k,v in SOURCING_PHASES.items() if k not in PHASES})

def folder(root):
    p=root/'outputs/agent-tasks';p.mkdir(parents=True,exist_ok=True);return p

def read(root,identity,_store=None):
    if len(identity)!=32 or any(c not in '0123456789abcdef' for c in identity):raise ValueError('任务编号不正确')
    with LOCK:
        p=folder(root)/identity/'task.json'
        if not p.exists():raise ValueError('任务不存在')
        from courseagent.task_store import TaskStore,store_for
        store=_store or store_for(root)
        stored=store.get(identity)
        job=stored or json.loads(p.read_text())
        if stored is None:store.save(job)
        end=datetime.now(timezone.utc) if job.get('status')=='running' else datetime.fromtimestamp(p.stat().st_mtime,timezone.utc)
        if job.get('status')=='running':
            job['run_elapsed_seconds']=max(0,int((end-datetime.fromisoformat(job.get('run_started_at',job['created_at']))).total_seconds()))
            job['elapsed_seconds']=job.get('elapsed_before_run',job.get('elapsed_seconds',0))+job['run_elapsed_seconds']
        else:
            job.setdefault('elapsed_seconds',max(0,int((end-datetime.fromisoformat(job.get('run_started_at',job['created_at']))).total_seconds())))
        job['files']=[name for name in ('assignment.xlsx','assignment.json','judge-tests.zip') if (p.parent/name).exists()]
        if identity in BUDGETS:job['run_model_calls']=BUDGETS[identity]['calls']
        owner=job.get('owner_pid')
        owner_alive=False
        if owner and owner!=os.getpid():
            try:os.kill(owner,0);owner_alive=True
            except (OSError,ValueError):pass
        if job['status']=='running' and identity not in ACTIVE and not owner_alive:
            if store.queued_for_recovery(identity) and not job.get('delivery_intent') and not job.get('import_id'):
                job.update(status='queued',phase='执行进程中断，等待自动恢复检查点',
                           message='已保留完成步骤，Worker 将自动接续，无需再次开始。')
            else:
                job.update(status='interrupted',message='服务重启中断任务；已保留最近结果，不会重新提交平台')
        persisted_status=job['status']
        if job.get('import_id'):
            platform=public_job(root/'outputs/import-jobs'/job['import_id'])
            job['platform']=platform
            if platform['status']=='completed':job.update(status='completed',draft_url=platform['draft_url'],message='未发布试卷已保存，平台题目与用例配置回读一致')
            elif platform['status']=='needs_attention':job.update(status='needs_attention',message=platform['message'])
        if job.get('import_id') and job['status']!=persisted_status:
            store.save(job)
            write_json(p,job)
        partial=p.parent/'partial-state.json'
        checkpoint=p.parent/'state.json'
        if job['status'] in ('interrupted','needs_attention','stopped') and partial.exists() and (not checkpoint.exists() or partial.stat().st_mtime_ns>=checkpoint.stat().st_mtime_ns):
            job['result']=json.loads(partial.read_text())['document']
        job['can_resume']=job['status'] in ('needs_attention','interrupted') and bool(job.get('result')) and not job.get('import_id') and not job.get('delivery_intent')
        return job

def list_tasks(root):
    # SSE and polling can arrive together. A list rebuild reads every task's
    # saved document; serialize and coalesce those reads instead of saturating
    # FastAPI's shared thread pool with duplicate full-history scans.
    key=str(Path(root).absolute())
    with LIST_LOCK:
        cached=LIST_CACHE.get(key)
        if cached and time.monotonic()-cached[0]<2:return copy.deepcopy(cached[1])
        tasks=_list_tasks(root)
        LIST_CACHE[key]=(time.monotonic(),tasks)
        return copy.deepcopy(tasks)


def _list_tasks(root):
    from courseagent.task_store import store_for
    store=store_for(root)
    tasks=[]
    for p in sorted(folder(root).glob('*/task.json'),key=lambda p:p.stat().st_mtime,reverse=True):
        cache_key=str(p.absolute());signature=p.stat().st_mtime_ns
        cached=TASK_SUMMARY_CACHE.get(cache_key)
        if cached and cached[0]==signature:
            tasks.append(copy.deepcopy(cached[1]));continue
        job=read(root,p.parent.name,_store=store)
        document=job.pop('result',None)
        job['has_result']=document is not None
        if document:
            job['replacement_history']=document.get('replacement_history',[])
            job['selection_diversity']=document.get('selection_diversity',{})
            job['teaching_coverage']=document.get('plan',{}).get('teaching_coverage',{})
            from courseagent.verification_state import summary
            job['verification_progress']=summary(document)
            advisories=document.get('agent_validation',{}).get('advisories',[])
            job['draft_warnings']=list(dict.fromkeys(job.get('draft_warnings',[])+[i['message'] for i in advisories if i.get('message')]))
            plan=document.get('plan',{})
            job['selection_summary']={'complete':plan.get('complete'), 'warnings':plan.get('warnings',[]),
                                      'type_counts':plan.get('type_counts',{}),'programming_count':plan.get('programming_count')}
            from courseagent.programming_judge import delivery_report
            coding=[q for q in document.get('programming_questions',[]) if q.get('selected')]
            reports=[]
            for q in coding:
                try:reports.append(delivery_report(q))
                except ValueError:reports.append({'passed':False})
            if coding:
                job['programming_verification_summary']={'total':len(coding),'checked':sum(r.get('passed') is True for r in reports),
                    'case_count':sum(len(q.get('test_cases',[])) for q in coding)}
        elif job.get('live_selection'):
            job['selection_summary']=job['live_selection']
        job.pop('report',None)
        if job['status'] in ('ready','completed','stopped','needs_attention') and (not job.get('import_id') or job['status']=='completed'):
            TASK_SUMMARY_CACHE[cache_key]=(signature,copy.deepcopy(job))
        tasks.append(job)
    return tasks

def merge_source_progress(current,branches,baseline=None):
    """A missing branch snapshot means pending, never an empty result."""
    from courseagent.workflow import assemble,retrieve
    a=copy.deepcopy(branches.get('ordinary',current))
    b=branches.get('programming',{})
    if not b and baseline:
        for key in ('programming_questions','programming_search'):
            if key in baseline:a['document'][key]=copy.deepcopy(baseline[key])
    if 'web' not in a:a['web']=copy.deepcopy(a['document'].get('web_search',{}))
    if 'candidates' not in a:a.update(retrieve(a))
    # The ordinary branch's empty/default candidate field owns no programming
    # progress. Until that branch reports, retain the document's selected pool.
    a['programming_candidates']=copy.deepcopy(
        [q for q in a['document'].get('programming_questions',[]) if q.get('selected')])
    if b:
        for key in ('programming_questions','programming_search'):
            if key in b['document']:a['document'][key]=copy.deepcopy(b['document'][key])
        a['programming_candidates']=copy.deepcopy(b.get('programming_candidates',
            [q for q in b['document'].get('programming_questions',[]) if q.get('selected')]))
    return assemble(a)['result']


def start(root,document,request,sources,target,execute=True,graph_factory=None,_resume_id=None,_resume_state=None):
    if not isinstance(request.get('prompt'),str) or not request['prompt'].strip():raise ValueError('请填写作业要求')
    if execute:
        from urllib.parse import urlparse
        import re
        u=urlparse(target.get('classroom_url',''))
        if u.scheme!='https' or u.netloc!='www.educoder.net' or not re.fullmatch(r'/classrooms/[A-Za-z0-9_-]+/exercise/?',u.path) or u.query or u.fragment:raise ValueError('请填写正确的在线考试列表页网址')
        if not target.get('course','').strip():raise ValueError('请填写平台所属课程名称')
    with LOCK:
        from courseagent.task_store import store_for
        if ACTIVE or any(read(root,i)['status'] in ('queued','running','importing')
                         for i in store_for(root).active_ids()):raise ValueError('已有自主任务正在执行')
        identity=_resume_id or uuid.uuid4().hex;ACTIVE.add(identity)
    request=copy.deepcopy(request)
    if not request.get('selection_policy'):
        from courseagent.selection_policy import usage_snapshot
        restored=(_resume_state or {}).get('request',{}).get('selection_policy')
        if not restored and _resume_id:
            restored = document.get('selection_policy')
        if restored:
            request['selection_policy']=copy.deepcopy(restored)
        else:
            try:history=usage_snapshot(Path(root),target,exclude_id=identity,execute=execute,
                local_group=request.get('local_history_group','local_assignments'))
            except (OSError,ValueError,__import__('sqlite3').Error):history={'counts':{},'task_ids':[],'unavailable':True}
            request['selection_policy']={'version':2,'seed':identity,'history':history,
                'history_mode':'production' if execute else 'local',
                'history_group':request.get('local_history_group','local_assignments') if not execute else None}
    p=folder(root)/identity;p.mkdir(exist_ok=bool(_resume_id))
    job={'id':identity,'status':'running','phase':'准备自主任务','created_at':datetime.now(timezone.utc).isoformat(),
         'request':request['prompt'],'published':False,'execute':execute,'events':[],'target':target,'owner_pid':os.getpid(),
         'purpose':request.get('purpose','assignment')}
    if not execute:job['local_history_group']=request.get('local_history_group','local_assignments')
    previous_calls=0
    previous_elapsed=0
    if _resume_id:
        previous=json.loads((p/'task.json').read_text())
        previous_calls=previous.get('model_calls',0)
        previous_elapsed=previous.get('elapsed_seconds',0)
        job={**previous,**job,'created_at':previous['created_at'],'events':_resume_state.get('events',[]),
             'resume_count':previous.get('resume_count',0)+1,'result':copy.deepcopy(document)}
        for key in ('finished_at','message','delivery','import_id','report','draft_url','failure','draft_warnings'):job.pop(key,None)
    from courseagent.verification_state import task_budget
    limits=task_budget(request)
    job.update(run_model_calls=0,elapsed_before_run=previous_elapsed,elapsed_seconds=previous_elapsed,
               budget={**limits,'reserved_check_calls':min(20,limits['max_calls']//5)},run_started_at=datetime.now(timezone.utc).isoformat())
    if graph_factory:persist(root,p/'task.json',job)
    submission={'document':document,'request':request,'sources':sources,'target':target,'execute':execute,
                'resume_state':_resume_state,'previous_calls':previous_calls,'previous_elapsed':previous_elapsed}
    receipt=copy.deepcopy(job)
    if graph_factory:
        threading.Thread(target=run_job,args=(root,identity,job,submission,graph_factory),daemon=True).start()
    else:
        from courseagent.task_store import TaskStore,store_for
        job.update(status='queued',phase='等待独立 Worker 接手',owner_pid=None)
        try:
            store_for(root).enqueue(job,submission)
            write_json(p/'task.json',job)
            LIST_CACHE.pop(str(Path(root).absolute()),None)
        except Exception as error:
            ACTIVE.discard(identity)
            # Preserve the actionable queue reason. The old generic message
            # made a second submission look frozen even when another task was
            # already occupying the single safe browser worker.
            safe_reason=str(error).strip()[:240] or '队列拒绝了本次任务'
            job.update(status='needs_attention',message='任务未进入执行队列：'+safe_reason)
            write_json(p/'task.json',job)
            raise
        ACTIVE.discard(identity)
        receipt=copy.deepcopy(job)
    return receipt


def run_job(root,identity,job,submission,graph_factory=None):
    document,request,sources,target=(submission[k] for k in ('document','request','sources','target'))
    execute=submission['execute'];_resume_state=submission.get('resume_state')
    previous_calls=submission.get('previous_calls',0);previous_elapsed=submission.get('previous_elapsed',0)
    p=folder(root)/identity
    worker_token=WORKER_OWNER.set(submission.get('worker_owner'))
    with LOCK:ACTIVE.add(identity)
    job.update(status='running',owner_pid=os.getpid(),phase='Worker 已接手',
               elapsed_before_run=previous_elapsed,elapsed_seconds=previous_elapsed,
               run_started_at=datetime.now(timezone.utc).isoformat())
    persist(root,p/'task.json',job)
    try:
        from courseagent.model_client import model_budget
        from courseagent.questions import export_xlsx
        def deliver(doc):
            from courseagent.task_cancellation import check_stopped
            check_stopped()
            validate_machine_delivery(doc)
            (p/'assignment.xlsx').write_bytes(export_xlsx(doc,False))
            write_json(p/'assignment.json',doc)
            has_coding=any(q.get('selected') for q in doc.get('programming_questions',[]))
            if has_coding:
                from courseagent.programming_questions import export_test_bundle
                (p/'judge-tests.zip').write_bytes(export_test_bundle(doc,False))
            unverified=[v for v in doc.get('agent_validation',{}).get('programming_verification',[]) if not v.get('passed')]
            warnings=[f'{len(unverified)}道编程题的用例预期输出尚未完成程序计算核验（不影响未发布草稿导入）。'] if unverified else []
            if not execute:return {'status':'ready','message':'自动组卷和校验完成（仅本地演示）'}
            job.update(delivery_intent=True,phase='准备写入未发布草稿')
            persist(root,p/'task.json',job)
            from courseagent.verification_tools import import_exam_draft
            imported=import_exam_draft.invoke({'root':str(root),'document':doc,'classroom_url':target['classroom_url'],'course':target['course']})['job']
            job.update(import_id=imported['id'])
            persist(root,p/'task.json',job)
            return {'status':'importing','import_id':imported['id'],'draft_warnings':warnings,'message':'题量与必填内容完整，正在导入并核对未发布试卷'}
        state={'document':copy.deepcopy(document),'request':copy.deepcopy(request),'sources':copy.deepcopy(sources),'rounds':0,'events':[]}
        if _resume_state:
            state=copy.deepcopy(_resume_state)
            state['request']['selection_policy']=copy.deepcopy(request['selection_policy'])
            state.pop('delivery',None)
            state['resume']=True
            state['verification_retries']={}
            state['source_retries']=0
            state['programming_source_retries']=0
            if state['document'].get('programming_search'):
                state['document']['programming_search']['producer_recovery_attempts']=0
            state['source_window_extensions']=0
            state['source_window_baseline']=sum(bool(q.get('selected')) for q in state['document'].get('questions',[]))
        with model_budget(job['budget']['max_calls'],job['budget']['max_seconds']) as budget:
            budget['stop_requested']=lambda:(p/'stop-requested').exists()
            budget['verification_checkpoint_dir']=p/'verification-cache'
            with LOCK:BUDGETS[identity]=budget
            # A model request has its own deadline, but webpage parsing,
            # compilation and result assembly can also occupy the run. Keep a
            # visible watchdog for the whole workflow so a quiet step cannot
            # look frozen and so the next cooperative checkpoint exits cleanly.
            watchdog_stop=threading.Event()
            watchdog_owner=WORKER_OWNER.get()
            def watchdog():
                token=WORKER_OWNER.set(watchdog_owner)
                try:
                    while not watchdog_stop.wait(15):
                        remaining=int(budget['deadline']-time.monotonic())
                        with LOCK:
                            if remaining<=0:
                                budget['deadline_exceeded']=True
                                job.update(activity='本轮时间预算已用完，正在保存检查点',budget_expired=True,
                                           last_progress_at=datetime.now(timezone.utc).isoformat())
                                persist(root,p/'task.json',job)
                                break
                            # Keep the UI alive during a long model/web/compiler
                            # step without claiming that a question completed.
                            if job.get('status')=='running':
                                job.update(activity='当前步骤仍在执行，剩余约 '+str(remaining)+' 秒',
                                           last_progress_at=datetime.now(timezone.utc).isoformat())
                                persist(root,p/'task.json',job)
                finally:
                    WORKER_OWNER.reset(token)
            watchdog_thread=threading.Thread(target=watchdog,name='agent-budget-watchdog',daemon=True)
            watchdog_thread.start()
            def model_progress(calls):
                job['model_calls']=previous_calls+calls
                job['run_model_calls']=calls
                job['activity']='模型正在处理当前要求或题目，请等待返回'
                with LOCK:persist(root,p/'task.json',job)
            budget['on_call']=model_progress
            def activity(message):
                job.update(activity=message,last_progress_at=datetime.now(timezone.utc).isoformat())
                with LOCK:persist(root,p/'task.json',job)
            budget['on_activity']=activity
            def candidates(summary):
                previous=job.get('live_selection') or {}
                job['live_selection']={**previous,'type_counts':copy.deepcopy(summary.get('type_counts',previous.get('type_counts',{}))),
                    'stage':'candidate','complete':summary.get('complete',False)}
                if 'programming_count' in summary:job['live_selection']['programming_count']=copy.deepcopy(summary['programming_count'])
                with LOCK:persist(root,p/'task.json',job)
            budget['on_candidates']=candidates
            partial_sources={}
            question_updates={}
            def question_checkpoint(kind,question):
                from courseagent.verification_state import merge_updates,summary
                from courseagent.workflow import refresh_plan
                with LOCK:
                    question_updates[(kind,question['id'])]=question
                    doc=merge_updates(job.get('result') or state['document'],question_updates)
                    refresh_plan(doc)
                    partial={**copy.deepcopy(state),'document':doc}
                    write_json(p/'partial-state.json',partial)
                    job.update(result=doc,verification_progress=summary(doc))
                    persist(root,p/'task.json',job)
            budget['on_question_checkpoint']=question_checkpoint
            def source_checkpoint(branch,current):
                from courseagent.workflow import assemble,retrieve
                with LOCK:
                    partial_sources[branch]=copy.deepcopy(current)
                    if branch=='programming':
                        report=current['document'].get('programming_search',{})
                        job['coding_search_progress']={k:report.get(k,0) for k in ('search_rounds','pages','read_attempts','candidate_count','missing')}
                    doc=merge_source_progress(current,partial_sources,state['document'] if state.get('rounds',0) else None)
                    from courseagent.verification_state import merge_updates
                    doc=merge_updates(doc,question_updates)
                    partial={**copy.deepcopy(state),'document':doc,'rounds':state.get('rounds',0)+1}
                    write_json(p/'partial-state.json',partial)
                    job['result']=doc
                    job['live_selection']=doc['plan']
                    persist(root,p/'task.json',job)
            budget['on_source_checkpoint']=source_checkpoint
            def progress(node):
                from courseagent.task_cancellation import check_stopped
                check_stopped()
                if node=='compose':
                    with LOCK:partial_sources.clear();job['branches']={}
                phase=PHASES.get(node,node)
                if ':' in node:
                    branch,node=node.split(':',1)
                    with LOCK:
                        job.setdefault('branches',{})[branch]=PHASES.get(node,node)
                        phase='；'.join(('普通题' if key=='ordinary' else '编程题')+'：'+value for key,value in job['branches'].items())
                job.update(phase=phase,activity='',model_calls=previous_calls+budget['calls'],last_progress_at=datetime.now(timezone.utc).isoformat())
                with LOCK:persist(root,p/'task.json',job)
            from contextlib import ExitStack
            with ExitStack() as stack:
                config={'recursion_limit':512,'configurable':{'thread_id':identity}}
                if graph_factory:
                    graph=graph_factory(delivery=deliver,progress=progress)
                    graph_input=state
                else:
                    from langgraph.checkpoint.sqlite import SqliteSaver
                    saver=stack.enter_context(SqliteSaver.from_conn_string(str(root/'data/agent-checkpoints.sqlite')))
                    graph=build_agent(delivery=deliver,progress=progress,checkpointer=saver)
                    saved=graph.get_state(config)
                    partial_path=p/'partial-state.json'
                    if _resume_state:
                        # Explicit continuation starts at the recovery router;
                        # do not replay an older failed compose checkpoint.
                        graph_input=state
                    elif saved.next and partial_path.exists():
                        partial=json.loads(partial_path.read_text())
                        # A source checkpoint owns newly discovered questions
                        # and its frontier, not just existing verification keys.
                        state={**copy.deepcopy(saved.values), **partial, 'resume':True}
                        state['rounds']=max(1,state.get('rounds',0))
                        graph_input=state
                    else:
                        graph_input=None if saved.next else state
                        if saved.next:state=copy.deepcopy(saved.values)
                for change in graph.stream(graph_input,config,stream_mode='updates'):
                    for node,delta in change.items():
                        state.update(delta)
                        if 'document' in delta:job['result']=copy.deepcopy(state['document'])
                        if node in ('compose','verify_coding','repair','fix'):
                            from courseagent.workflow import refresh_plan
                            candidates(refresh_plan(copy.deepcopy(state['document'])).get('plan',{}))
                        job.update(phase=PHASES.get(node,node),rounds=state.get('rounds',0),events=state.get('events',[]),model_calls=previous_calls+budget['calls'])
                        with LOCK:
                            write_json(p/'state.json',state)
                            (p/'partial-state.json').unlink(missing_ok=True)
                            persist(root,p/'task.json',job)
            job['result']=state['document']
            if state.get('delivery'):job.update(state['delivery'])
            else:job.update(status='needs_attention',message=state.get('reason','任务未完成'),report=state.get('report'))
    except TaskStopped:
        job.update(status='stopped',phase='已手动停止',activity='',message='已保留取得的题目；本任务不会继续自动导入。')
        partial=p/'partial-state.json'
        if partial.exists():job['result']=json.loads(partial.read_text())['document']
    except Exception as error:
        from courseagent.verification_state import failure_info
        job.update(status='needs_attention',message=job.get('phase','当前步骤')+'：'+str(error)[:400],
                   failure={**failure_info(error),'error_type':type(error).__name__,'phase':job.get('phase')})
        partial=p/'partial-state.json'
        if partial.exists():job['result']=json.loads(partial.read_text())['document']
        elif 'state' in locals():job.update(result=state['document'],report=state.get('report'))
    finally:
        if 'watchdog_stop' in locals():
            watchdog_stop.set()
            if 'watchdog_thread' in locals():watchdog_thread.join(timeout=2)
        with LOCK:
            job['elapsed_seconds']=previous_elapsed+int((datetime.now(timezone.utc)-datetime.fromisoformat(job['run_started_at'])).total_seconds())
            job['finished_at']=datetime.now(timezone.utc).isoformat()
            try:
                from courseagent.task_store import store_for
                latest=store_for(root).get(identity)
                if latest and latest.get('status')=='stopped':
                    job.update(latest)
                else:
                    persist(root,p/'task.json',job)
            finally:
                ACTIVE.discard(identity);BUDGETS.pop(identity,None)
                WORKER_OWNER.reset(worker_token)


def stop(root,identity):
    """Revoke queued/running work before delivery; keep partial artifacts."""
    from courseagent.task_store import store_for
    with LOCK:
        job=read(root,identity)
        store=store_for(root)
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT record,queue_state FROM tasks WHERE id=?',(identity,)).fetchone()
            if not row:raise ValueError('任务不存在')
            latest=json.loads(row[0])
            if latest.get('status')=='stopped':return job
            if latest.get('delivery_intent') or latest.get('import_id') or latest.get('status')=='importing':
                raise ValueError('任务已进入平台写入，不能直接中断；需保留草稿并完成状态核对。')
            if row[1] not in ('queued','running'):raise ValueError('当前任务已经结束，无需停止')
            p=folder(root)/identity
            (p/'stop-requested').touch()
            for filename in ('partial-state.json','state.json'):
                saved=p/filename
                if saved.exists():
                    latest['result']=json.loads(saved.read_text()).get('document',{})
                    break
            latest.update(status='stopped',phase='已手动停止',activity='',can_resume=False,
                          message='已保留取得的题目；本任务不会继续自动导入。',
                          finished_at=datetime.now(timezone.utc).isoformat())
            store._write(db,latest)
            # Lease revocation also prevents an older Worker from delivering
            # between the user's stop and its next cooperative checkpoint.
            db.execute("UPDATE tasks SET queue_state='done',owner=NULL,lease_until=0 WHERE id=?",(identity,))
        write_json(p/'task.json',latest)
        LIST_CACHE.pop(str(Path(root).absolute()),None)
        # The task's cooperative cancellation and revoked lease block delivery.
        # Keep the shared worker alive so it can service the next queued task.
        ACTIVE.discard(identity)
        return latest


def resume(root,identity,graph_factory=None):
    """Continue the same autonomous task; never read/overwrite teacher workbench."""
    with LOCK:
        job=read(root,identity)
        if not job.get('can_resume'):raise ValueError('当前任务不能继续，运行中或已交付的任务不会重复提交')
        path=folder(root)/identity/'state.json'
        partial=path.parent/'partial-state.json'
        if partial.exists() and (not path.exists() or partial.stat().st_mtime_ns>=path.stat().st_mtime_ns):path=partial
        state=json.loads(path.read_text()) if path.exists() else {}
        state.update(document=copy.deepcopy(job['result']),resume=True)
        request=state.get('request') or {'prompt':job['request']}
        state.update(request=request,sources=state.get('sources',[]))
        for q in state['document'].get('questions',[]):
            if q.get('ordinary_blind_check',{}).get('method')=='blind_solve_incomplete':q.pop('ordinary_blind_check',None)
        for q in state['document'].get('programming_questions',[]):
            if q.get('execution_verification',{}).get('status') in ('role_failed','sandbox_unavailable','execution_failed'):
                q['verification_retry_failures']=q['execution_verification'].get('failures',[])
                q.pop('execution_verification',None)
        return start(root,state['document'],request,state['sources'],job['target'],
                     execute=job['execute'],graph_factory=graph_factory,_resume_id=identity,_resume_state=state)


def recheck_delivery(root,identity):
    """Reconcile the actual platform exam before reusing a success record."""
    with LOCK:
        job=read(root,identity)
        if job['status'] in ('running','importing') or not job.get('import_id') or not job.get('result'):
            raise ValueError('当前任务没有可重新核对的交付，或仍在运行')
        if ACTIVE or any(t['status'] in ('running','importing') for t in list_tasks(root)):
            raise ValueError('已有任务正在运行，请等待完成后再核对')
        imported=start_import(root,job['result'],job['target']['classroom_url'],job['target']['course'],machine_checked=True)
        job.update(status='importing' if imported['status'] in ('queued','running') else imported['status'],
                   phase='核对平台当前试卷，缺失则恢复未发布草稿',message=imported.get('message','正在核对平台当前状态'))
        for key in ('draft_url','platform','can_resume'):job.pop(key,None)
        persist(root,folder(root)/identity/'task.json',job)
        return {'id':identity,'status':job['status'],'import_id':imported['id']}
