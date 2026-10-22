"""Immutable reviewed snapshots and background imports into unpublished exams."""
import hashlib
import copy
import json
import os
import re
import shutil
import subprocess
import threading
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
from courseagent.paths import BROWSER
from courseagent.questions import export_xlsx, validate

LOCK=threading.RLock()
ACTIVE={'queued','running'}


def now():
    return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()


def write_json(path,data):
    # Different question workers may checkpoint concurrently. A shared .tmp
    # lets one writer rename the other writer's file and crash its checkpoint.
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def windows_path(path):
    text=str(Path(path).resolve())
    match=re.fullmatch(r'/mnt/([a-zA-Z])/(.*)',text)
    if not match:raise ValueError('Windows 浏览器需要项目位于 Windows 磁盘目录')
    return match[1].upper()+':\\'+match[2].replace('/','\\')


def runtime_command(root):
    # Use the user's installed runtime; Windows Node in WSL is explicit opt-in.
    node=os.environ.get('EDUCODER_BROWSER_NODE') or shutil.which('node')
    if not node:raise ValueError('没有找到 Node.js 浏览器运行环境，请按 README 安装')
    is_windows=str(node).lower().endswith('.exe')
    module=os.environ.get('EDUCODER_PLAYWRIGHT_MODULE','playwright')
    path=windows_path if is_windows else str
    if is_windows and module.startswith('/mnt/'):module=windows_path(module)
    return [str(node),path(BROWSER/'educoder_import.cjs')],is_windows,module


def job_folder(root):
    folder=root/'outputs/import-jobs';folder.mkdir(parents=True,exist_ok=True);return folder


def before_creation(folder,job):
    """Only explicit pre-submit evidence permits starting creation again."""
    if job.get('draft_url') or job.get('reconcile_url') or job.get('verify_only'):
        return False
    stage_path=folder/'platform-job.json'
    try:
        if stage_path.exists():
            stage=json.loads(stage_path.read_text(encoding='utf-8'))
            return stage.get('status')=='preparing' and not stage.get('draft_url') and not stage.get('detail_url')
        # Older adapters did not checkpoint entry to the creation form. This
        # exact locator is awaited only before 下一步; do not infer safety from
        # arbitrary browser timeouts or missing records.
        error=json.loads((folder/'operation-error.json').read_text(encoding='utf-8'))
        message=error.get('message','')
        return (error.get('url')==job.get('classroom_url')
                and 'locator.waitFor: Timeout' in message
                and "getByPlaceholder('请输入试卷名称', { exact: true })" in message)
    except (OSError,ValueError,TypeError):
        return False


def public_job(folder):
    data=json.loads((folder/'status.json').read_text(encoding='utf-8'))
    if data.get('started_at'):
        try:
            started=datetime.fromisoformat(data['started_at'])
            ended=datetime.fromisoformat(data['finished_at']) if data.get('finished_at') else datetime.now(started.tzinfo)
            data['elapsed_seconds']=max(0,int((ended-started).total_seconds()))
        except (ValueError,TypeError):pass
    progress=folder/'coding-progress.json'
    if progress.exists():
        try:data['coding_progress']=json.loads(progress.read_text(encoding='utf-8'))
        except (ValueError,OSError):pass
    stage=folder/'platform-job.json'
    if stage.exists():
        try:
            platform=json.loads(stage.read_text(encoding='utf-8'))
            data['platform_stage']=platform.get('status')
            data['draft_url']=platform.get('detail_url') or platform.get('draft_url')
        except (ValueError,OSError):pass
    if data.get('status')=='needs_attention' and before_creation(folder,data):
        data.update(retry_safe=True,message='未能进入头歌“创建新试卷”表单，尚未创建或上传题目；可重试导入，已完成的搜题与核验会保留。')
    elif data.get('status')=='needs_attention' and not data.get('platform_stage'):
        log=folder/'browser.log'
        if log.exists():
            tail=log.read_text(encoding='utf-8',errors='replace')[-8000:]
            if '创建新试卷' in tail and ('Timeout' in tail or '尚未创建' in tail):
                data['message']='未能打开头歌“创建新试卷”界面，任务停在创建前，尚未导入题目。'
    if data.get("reconcile_url") and data.get("status") in ACTIVE:
        data["platform_stage"]="checking_existing"
        data.pop("draft_url",None)
    return data


def list_jobs(root):
    with LOCK:
        return [public_job(p.parent) for p in sorted(job_folder(root).glob('*/status.json'),key=lambda p:p.stat().st_mtime,reverse=True)]


def retryable_configuration_error(folder):
    try:
        error=json.loads((folder/'operation-error.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):return False
    if error.get('retryable') is False:return False
    message=error.get('message','')
    if re.search(r'不一致|不完整|多余|无法唯一定位|不支持|缺少',message):return False
    return bool(re.search(r'Timeout|超时|Target.*closed|browser.*closed|net::ERR_|ECONNRESET|connection.*closed',message,re.I))


def delivery_snapshot_path(folder):
    """Keep the original frozen snapshot and a verified in-place I/O migration."""
    receipt_path=folder/'stdio-migration.json'
    if not receipt_path.exists():return folder/'expected.json'
    receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
    path=folder/'expected-stdio.json'
    if (receipt.get('status')!='verified'
        or receipt.get('original_sha256')!=hashlib.sha256((folder/'expected.json').read_bytes()).hexdigest()
        or not path.exists()
        or receipt.get('snapshot_sha256')!=hashlib.sha256(path.read_bytes()).hexdigest()):
        raise ValueError('已有草稿的输入输出迁移尚未核对完成，请先恢复迁移；没有重新上传')
    return path


def same_reviewed_snapshot(folder,document):
    """Presentation fixes must not turn a retained draft into a new upload."""
    paths={folder/'expected.json',delivery_snapshot_path(folder)}
    try:
        snapshots=[json.loads(path.read_text(encoding='utf-8')) for path in paths]
    except (OSError,ValueError):return False
    def content(q):
        return {k:v for k,v in q.items() if k not in ('platform_description','platform_options')}
    exact=any(snapshot.get('name')==document.get('name') and snapshot.get('version')==document.get('version')
            and [content(q) for q in snapshot.get('questions',[])]==
                [content(q) for q in sorted(document['questions'],key=lambda q:q['type']) if q.get('selected')]
            and [content(q) for q in snapshot.get('programming_questions',[])]==
                [content(q) for q in document.get('programming_questions',[]) if q.get('selected')] for snapshot in snapshots)
    if exact:return True
    if len(paths)==1:return False
    # Re-executing a migrated question refreshes private evidence timestamps.
    # Compare all delivered content, while leaving that evidence out of identity.
    from courseagent.questions import review_content as ordinary_content
    from courseagent.programming_questions import review_content as coding_content
    def delivery(q,coding=False):
        value=(coding_content if coding else ordinary_content)(q)
        value.update(id=q['id'],selected=q.get('selected'))
        if coding:
            value['test_cases']=[{k:c.get(k,'hidden' if k=='visibility' else None) for k in ('input','output','visibility','excel_selected')} for c in q['test_cases']]
            value['source_metadata']=q.get('source_metadata');value['source_protocol']=q.get('source_protocol')
        return value
    snapshot=next(s for p,s in zip(paths,snapshots) if p.name=='expected-stdio.json')
    return (snapshot.get('name')==document.get('name') and snapshot.get('version')==document.get('version')
            and [delivery(q) for q in snapshot['questions']]==[delivery(q) for q in sorted(document['questions'],key=lambda q:q['type']) if q.get('selected')]
            and [delivery(q,True) for q in snapshot.get('programming_questions',[])]==[delivery(q,True) for q in document.get('programming_questions',[]) if q.get('selected')])


def start_import(root,document,url,course,runner=None,machine_checked=False):
    for q in document.get('programming_questions',[]):
        if q.get('selected') and any(l['language'] not in ('C语言','C','C++','Python','Java') for l in q.get('languages',[])):
            raise ValueError('头歌在线考试自动导入目前支持C、C++、Python和Java')
    parsed=urlparse(url)
    if parsed.scheme!='https' or parsed.netloc!='www.educoder.net' or not re.fullmatch(r'/classrooms/[A-Za-z0-9_-]+/exercise/?',parsed.path) or parsed.query or parsed.fragment:
        raise ValueError('请填写头歌课堂在线考试列表页网址')
    url=url.rstrip('/')
    if not isinstance(course,str) or not course.strip() or len(course)>100:
        raise ValueError('请填写平台中准确的所属课程名称')
    course=course.strip()
    if machine_checked:
        from courseagent.autonomous_agent import validate_machine_delivery
        selected=validate_machine_delivery(document)
    else:
        selected=validate(document,True)
    content=export_xlsx(document,approved_only=not machine_checked)
    digest=hashlib.sha256(content).hexdigest()
    identity=hashlib.sha256((url+'\n'+course+'\n'+document['name']+'\n'+digest).encode()).hexdigest()[:24]
    with LOCK:
        jobs=list_jobs(root)
        existing=next((j for j in jobs if j['id']==identity),None)
        if not existing:
            existing=next((j for j in jobs if j.get('classroom_url')==url and j.get('course')==course
                           and same_reviewed_snapshot(job_folder(root)/j['id'],document)),None)
            if existing:identity=existing['id']
        if existing:
            folder=job_folder(root)/identity
            if (existing['status']=='needs_attention' and existing.get('retry_safe') is True
                and not existing.get('draft_url')
                and (not (folder/'platform-job.json').exists() or before_creation(folder,existing))):
                if any(j['status'] in ACTIVE for j in jobs):raise ValueError('已有导入任务正在运行，请等待完成后再开始')
                history=existing.get('attempt_history',[])+[{'status':existing['status'],'message':existing.get('message'),'finished_at':existing.get('finished_at')}]
                job={k:v for k,v in existing.items() if k not in ('message','finished_at','started_at')}
                job.update(status='queued',retry_safe=False,attempt=existing.get('attempt',1)+1,attempt_history=history)
                write_json(folder/'status.json',job)
                receipt={**copy.deepcopy(job),'restarted':True}
                threading.Thread(target=runner or run_import,args=(root,folder),daemon=True).start()
                return receipt
            platform_path=folder/'platform-job.json'
            stage=json.loads(platform_path.read_text()) if platform_path.exists() else {}
            if existing['status']=='needs_attention' and stage.get('status')=='imported':
                if any(j['status'] in ACTIVE for j in jobs):raise ValueError('已有导入任务正在运行，请等待完成后再开始')
                job={**existing,'status':'queued','verify_only':True,'message':'题目已上传，正在重新核对并保存；不会再次上传。'}
                write_json(folder/'status.json',job)
                receipt={**copy.deepcopy(job),'verifying':True}
                threading.Thread(target=runner or run_import,args=(root,folder),daemon=True).start()
                return receipt
            if existing['status'] in ACTIVE:
                message='相同内容的本地导入任务正在执行，已显示该任务进度；尚不代表平台已创建试卷。'
            elif existing['status']=='completed':
                if any(j['status'] in ACTIVE for j in jobs):raise ValueError('已有导入任务正在运行，请等待完成后再开始')
                job={**existing,'status':'queued','reconcile_url':existing.get('draft_url'),'message':'正在核对头歌上的历史试卷；已删除则自动重建，仍存在则核对后复用。'}
                if not job['reconcile_url']:raise ValueError('历史交付缺少试卷链接，无法确认平台结果')
                write_json(folder/'status.json',job)
                receipt={**copy.deepcopy(job),'reconciling':True}
                threading.Thread(target=runner or run_import,args=(root,folder),daemon=True).start()
                return receipt
            else:
                message='相同内容的历史导入未完成，平台结果尚不确定；已显示原任务和失败原因，没有再次上传。'
            return {**existing,'reused':True,'reuse_message':message}
        if any(j['status'] in ACTIVE for j in jobs):raise ValueError('已有导入任务正在运行，请等待完成后再开始')
        # Restarting a server cannot safely assume a browser job was stopped.
        folder=job_folder(root)/identity;folder.mkdir()
        manifest={'name':document['name'],'sha256':digest,'question_count':len(selected),'total_score':sum(q['score'] for q in selected),'review_version':document['version'],'review_task_id':document.get('review_task_id'), 'validation_mode':'agent' if machine_checked else 'teacher'}
        (folder/'reviewed.xlsx').write_bytes(content)
        write_json(folder/'manifest.json',manifest)
        snapshot={'name':document['name'],'version':document['version'],'questions':sorted([q for q in document['questions'] if q.get('selected')],key=lambda q:q['type']),
                  'programming_questions':[q for q in document.get('programming_questions',[]) if q.get('selected')]}
        # Freeze both reviewed content and its exact platform presentation.
        # Old snapshots remain untouched when resuming an existing draft.
        from courseagent.platform_format import option_texts
        from courseagent.programming_questions import platform_description
        snapshot=copy.deepcopy(snapshot)
        for q in snapshot['questions']:
            if q['type'] in (1,2):q['platform_options']=option_texts(q['options'])
        for q in snapshot['programming_questions']:q['platform_description']=platform_description(q)
        write_json(folder/'expected.json',snapshot)
        job={'id':identity,'status':'queued','created_at':now(),'name':document['name'],'question_count':len(selected),'total_score':manifest['total_score'],'classroom_url':url,'course':course,'review_version':document['version'],'published':False}
        write_json(folder/'status.json',job)
        target=runner or run_import
        receipt=copy.deepcopy(job)
        threading.Thread(target=target,args=(root,folder),daemon=True).start()
        return receipt


def run_import(root,folder):
    status_path=folder/'status.json'
    with LOCK:
        job=public_job(folder);job.update(status='running',started_at=now(),verified=False);write_json(status_path,job)
    retry_safe=not (folder/'platform-job.json').exists() and not job.get('draft_url')
    try:
        command,is_windows,module=runtime_command(root)
        path=windows_path if is_windows else str
        snapshot_path=delivery_snapshot_path(folder)
        migrated=snapshot_path.name!='expected.json'
        command+=['--url',job['classroom_url'],'--channel','chrome','--execute','--wait-login','--course',job['course'],
                  '--file',path(folder/'reviewed.xlsx'),'--manifest',path(folder/'manifest.json'),'--expected',path(snapshot_path),
                  '--job',path(folder/'platform-job.json'),'--output',path(folder),'--playwright-module',module]
        if job.get('verify_only') or migrated:command+=['--verify-only']
        if job.get('reconcile_url') and not migrated:command+=['--reconcile-url',job['reconcile_url']]
        env={k:v for k,v in os.environ.items() if not k.startswith('EDUCODER_MODEL_')}
        snapshot=json.loads(snapshot_path.read_text(encoding='utf-8'))
        case_total=sum(len(q.get('test_cases',[])) for q in snapshot.get('programming_questions',[]))
        browser_timeout=max(600,min(1800,300+12*case_total))
        # A saved Excel upload is a recovery boundary: retry only configuration
        # of that same draft, never creation/upload. Browser exits close context.
        for attempt in range(2):
            (folder/'operation-error.json').unlink(missing_ok=True)
            with (folder/'browser.log').open('w' if attempt==0 else 'a',encoding='utf-8') as log:
                retry_safe=False
                job.update(retry_safe=False,browser_launch_attempted_at=now());write_json(status_path,job)
                process=subprocess.Popen(command,cwd=root,stdout=log,stderr=log,env=env)
                try:code=process.wait(timeout=browser_timeout)
                except subprocess.TimeoutExpired:
                    process.kill();process.wait();raise ValueError('导入超时，已保留原草稿；恢复时只补齐并核对该草稿，不会重新上传')
            stage=json.loads((folder/'platform-job.json').read_text(encoding='utf-8')) if (folder/'platform-job.json').exists() else {}
            if code and attempt==0 and stage.get('status')=='imported' and stage.get('draft_url') and retryable_configuration_error(folder):
                job.update(message='配置中断，正在恢复已有草稿并重新核对用例；不会重复上传',configuration_retry=1)
                write_json(status_path,job)
                if '--verify-only' not in command:command+=['--verify-only']
                continue
            break
        platform=json.loads((folder/'platform-job.json').read_text(encoding='utf-8')) if (folder/'platform-job.json').exists() else {}
        if code or platform.get('status')!='saved':
            diagnostic=folder/'operation-error.json'
            detail=''
            if diagnostic.exists():
                try:detail=json.loads(diagnostic.read_text()).get('message','')[:300]
                except (ValueError,OSError):pass
            raise ValueError('平台导入或回读未完成：'+(detail or '请查看本任务 browser.log 和头歌草稿')+'；已保留当前草稿，没有再次上传')
        verified=folder/'import-verification.json'
        if not verified.exists():raise ValueError('试卷已保存，但未找到逐题核对结果，请人工核对')
        result=json.loads(verified.read_text(encoding='utf-8'))
        if result['question_count']!=job['question_count'] or result['total_score']!=job['total_score']:
            raise ValueError('保存结果与审核快照不一致，请人工核对')
        by_id={q.get('id'):q for q in result.get('questions',[])}
        for q in snapshot.get('programming_questions',[]):
            actual=by_id.get(q['id'],{})
            cases=q.get('test_cases',[])
            expected_counts={'case_count':len(cases),
                'public_count':sum(c.get('visibility')=='public' for c in cases),
                'hidden_count':sum(c.get('visibility','hidden')=='hidden' for c in cases)}
            if actual.get('verified') is not True or any(actual.get(k)!=v for k,v in expected_counts.items()):
                raise ValueError('编程题公开/隐藏用例平台回读不完整：'+q['title'])
            if q.get('io_contract') and actual.get('initial_code_verified') is not True:
                raise ValueError('编程题初始代码平台回读不完整：'+q['title'])
        job.update(status='completed',draft_url=platform['detail_url'],verified=True,message='已保存未发布试卷，逐题回读核对通过')
        job.pop('reconcile_url',None)
        job.pop('verify_only',None)
    except Exception as error:
        # A draft may already exist even when the browser failed while
        # configuring or reading back programming questions. Make that state
        # explicit: local hidden cases are not platform delivery evidence.
        platform_stage = None
        try:
            platform_stage = json.loads((folder/'platform-job.json').read_text(encoding='utf-8')).get('status')
        except (OSError, ValueError, TypeError):
            pass
        if before_creation(folder,job):
            message='未能进入头歌“创建新试卷”表单，尚未创建或上传题目；可重试导入，已完成的搜题与核验会保留。'
            retry_safe=True
        elif platform_stage == 'imported':
            try:
                coding_progress=json.loads((folder/'coding-progress.json').read_text(encoding='utf-8'))
            except (OSError,ValueError):coding_progress={}
            coding_done=(coding_progress.get('stage')=='coding_verified' and
                         coding_progress.get('completed')==coding_progress.get('total') and
                         bool(coding_progress.get('total')))
            message = (('头歌草稿已创建，编程题用例已配置并回读；其余题目或整卷保存尚未核对通过。' if coding_done else
                       f'题目已上传到头歌草稿；编程题配置与回读已完成 {coding_progress.get("completed",0)}/{coding_progress.get("total",0)} 道，整卷尚未核对完成。')+
                       '继续时核对当前草稿，不会重复创建。具体原因：'+str(error)[:300])
            retry_safe = False
        else:
            message = str(error) if isinstance(error,ValueError) else '浏览器任务异常，请查看任务记录并人工核对平台'
        job.update(status='needs_attention',retry_safe=retry_safe,message=message)
    with LOCK:
        job['finished_at']=now();write_json(status_path,job)
