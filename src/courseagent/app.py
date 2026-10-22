"""Local teaching-source search, LangGraph planning, review, and Excel export."""
from courseagent.paths import ROOT as WORKSPACE_ROOT, WEB
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from xml.etree import ElementTree as ET
from threading import RLock
from datetime import datetime
import argparse
import base64
import copy
import json
import os
import re
import hashlib

from courseagent.questions import export_xlsx, validate, validate_question, normalize_approvals, review_content, NS
from courseagent.documents import FILES, scan_sources, extract_word_questions, source_id

ROOT = WORKSPACE_ROOT
STATE = ROOT/'data/review.json'
SOURCES = ROOT/'data/sources.json'
LOCK = RLock()

def checkpoint_path():
    return STATE.with_name(STATE.stem + '-workflow.sqlite')


class ConflictError(ValueError):
    pass


def load_state():
    if not STATE.exists() and STATE == ROOT/'data/review.json':
        from courseagent.workspace_setup import initialize_workspace
        initialize_workspace(ROOT)
    return json.loads(STATE.read_text(encoding='utf-8'))


def save_state(document, expected_version=None):
    with LOCK:
        current = load_state()
        if expected_version is not None and expected_version != current.get('version', 0):
            raise ConflictError('其他页面已保存新的进度，请刷新后再操作。当前内容未覆盖服务器数据。')
        if not isinstance(document, dict) or not isinstance(document.get('questions'), list):
            raise ValueError('审核内容格式不正确')
        if len(document['questions']) > 2000 or any(not isinstance(q, dict) or not isinstance(q.get('id'), str) for q in document['questions']):
            raise ValueError('题库格式不正确或超过 2000 道题')
        if len({q['id'] for q in document['questions']}) != len(document['questions']):
            raise ValueError('题目编号不能重复')
        from courseagent.knowledge_tags import annotate
        document = normalize_approvals(annotate(document))
        from courseagent.workflow import refresh_plan
        document = refresh_plan(document)
        document['version'] = current.get('version', 0)+1
        temporary = STATE.with_suffix('.tmp')
        temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf-8')
        from courseagent.review_workflow import record_saved
        record_saved(checkpoint_path(), document)
        temporary.replace(STATE)
        return document


def source_summaries(sources):
    return [{k: s.get(k) for k in ('id', 'name', 'kind', 'pages', 'warning','material_role','answer_hint')} for s in sources]


def refresh_sources(document):
    sources, errors = scan_sources()
    SOURCES.write_text(json.dumps({'sources': sources, 'errors': errors}, ensure_ascii=False, indent=2), encoding='utf-8')
    existing = {(q.get('source'), q['type'], q.get('source_number')) for q in document['questions']}
    for source in sources:
        if source['kind'] != 'docx':
            continue
        for q in extract_word_questions(source):
            key = (q['source'], q['type'], q['source_number'])
            if key not in existing:
                document['questions'].append(q)
                existing.add(key)
    for q in document['questions']:
        if q.get('origin') != 'supplement' and not q.get('source_refs'):
            match = next((s for s in sources if s['name'] == q.get('source')), None)
            if match:
                q['source_refs'] = [{'document_id': match['id'], 'question_number': q.get('source_number')}]
                q['approved'] = False  # A change to provenance requires review.
    from courseagent.answer_documents import attach_answers
    return attach_answers(document, sources), sources, errors


class Handler(BaseHTTPRequestHandler):
    def reply(self, body, content_type='application/json; charset=utf-8', status=200, filename=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        if filename:
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def json_reply(self, value, status=200):
        self.reply(json.dumps(value, ensure_ascii=False).encode(), status=status)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/':
            self.reply((WEB/'index.html').read_bytes(), 'text/html; charset=utf-8')
        elif path == '/app.js':
            self.reply((WEB/'app.js').read_bytes(), 'text/javascript; charset=utf-8')
        elif path == '/programming_review.js':
            self.reply((WEB/'programming_review.js').read_bytes(), 'text/javascript; charset=utf-8')
        elif path == '/agent_ui.js':
            self.reply((WEB/'agent_ui.js').read_bytes(), 'text/javascript; charset=utf-8')
        elif path == '/api/import-jobs':
            from courseagent.import_jobs import list_jobs
            self.json_reply({'jobs': list_jobs(ROOT)})
        elif path == '/api/agent-tasks':
            from courseagent.agent_jobs import list_tasks
            self.json_reply({'tasks':list_tasks(ROOT)})
        elif re.fullmatch(r'/api/agent-tasks/[0-9a-f]{32}/files/(assignment\.xlsx|assignment\.json|judge-tests\.zip)', path):
            identity,filename=path.split('/')[3],path.rsplit('/',1)[1]
            file=ROOT/'outputs/agent-tasks'/identity/filename
            if not file.exists():self.json_reply({'error':'任务文件尚未生成'},404)
            else:
                mime='application/zip' if filename.endswith('.zip') else 'application/json' if filename.endswith('.json') else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                self.reply(file.read_bytes(),mime,filename=filename)
        elif re.fullmatch(r'/api/agent-tasks/[0-9a-f]{32}', path):
            from courseagent.agent_jobs import read
            try:self.json_reply(read(ROOT,path.rsplit('/',1)[1]))
            except ValueError as error:self.json_reply({'error':str(error)},404)
        elif re.fullmatch(r'/api/web-jobs/[0-9a-f]{32}', path):
            from courseagent.web_jobs import get
            try:
                self.json_reply(get(ROOT, path.rsplit('/',1)[1]))
            except ValueError as error:
                self.json_reply({'error':str(error)},404)
        elif path.startswith('/api/replacement-jobs/'):
            from courseagent.replacement_jobs import get
            try:self.json_reply(get(ROOT,path.rsplit('/',1)[1]))
            except ValueError as error:self.json_reply({'error':str(error)},404)
        elif path == '/api/retrieval-status':
            from courseagent.retrieval_runtime import status
            from courseagent.source_adapters import manifest
            self.json_reply({**status(),'sources':manifest()})
        elif path == '/api/observability':
            from courseagent.observability import status
            self.json_reply(status())
        elif path == '/api/workflow':
            from courseagent.workflow import graph_description
            self.json_reply(graph_description())
        elif path == '/api/review-tasks':
            from courseagent.review_workflow import list_tasks
            with LOCK:
                self.json_reply({'tasks': list_tasks(checkpoint_path())})
        elif path == '/api/model-status':
            from courseagent.model_client import model_status
            self.json_reply(model_status())
        elif path == '/api/review':
            from courseagent.knowledge_tags import annotate
            self.json_reply(annotate(load_state()))
        elif path == '/api/sources':
            data = json.loads(SOURCES.read_text()) if SOURCES.exists() else {'sources': [], 'errors': []}
            self.json_reply({'sources': source_summaries(data['sources']), 'errors': data['errors']})
        elif re.fullmatch(r'/source/[0-9a-f]{16}', path):
            sid = path.rsplit('/', 1)[1]
            file = next((p for p in FILES.iterdir() if source_id(p) == sid), None)
            if file is None:
                self.json_reply({'error': '原文件不存在'}, 404)
            else:
                mime = 'application/pdf' if file.suffix == '.pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                self.reply(file.read_bytes(), mime)
        else:
            self.json_reply({'error': '页面不存在'}, 404)

    def do_POST(self):
        # This local service does not accept writes from unrelated browser pages.
        origin = self.headers.get('Origin')
        host = self.headers.get('Host')
        if origin and origin != f'http://{host}':
            self.json_reply({'error': '不接受其他网页发起的修改'}, 403)
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 25_000_000:
                raise ValueError('请求大小不正确（最多 25 MB）')
            payload = json.loads(self.rfile.read(size))
            with LOCK:
                if self.path == '/api/agent-start':
                    from courseagent.agent_jobs import start
                    document=copy.deepcopy(load_state())
                    if payload.get('name'):document['name']=payload['name']
                    sources=json.loads(SOURCES.read_text())['sources'] if SOURCES.exists() else []
                    self.json_reply(start(ROOT,document,{'prompt':payload.get('prompt','')},sources,
                        {'classroom_url':payload.get('classroom_url',''),'course':payload.get('course','')},
                        execute=payload.get('execute',False) is True),202)
                elif re.fullmatch(r'/api/agent-tasks/[0-9a-f]{32}/recheck',self.path):
                    from courseagent.agent_jobs import recheck_delivery
                    self.json_reply(recheck_delivery(ROOT,self.path.split('/')[3]),202)
                elif re.fullmatch(r'/api/agent-tasks/[0-9a-f]{32}/resume',self.path):
                    from courseagent.agent_jobs import resume
                    self.json_reply(resume(ROOT,self.path.split('/')[3]),202)
                elif re.fullmatch(r'/api/agent-tasks/[0-9a-f]{32}/stop',self.path):
                    from courseagent.agent_jobs import stop
                    self.json_reply(stop(ROOT,self.path.split('/')[3]),202)
                elif self.path == '/api/save':
                    self.json_reply(save_state(payload, payload.get('version', 0)))
                elif self.path == '/api/annotate-knowledge':
                    from courseagent.knowledge_tags import annotate
                    if payload.get('version',0) != load_state().get('version',0):
                        raise ConflictError('审核进度已经变化，请刷新后再识别知识点')
                    self.json_reply(annotate(payload))
                elif self.path == '/api/save-scheme':
                    from courseagent.review_workflow import save_scheme
                    document = load_state()
                    if payload.get('version') != document.get('version'):
                        raise ConflictError('审核进度已经变化，请刷新后再保存方案')
                    self.json_reply(save_scheme(checkpoint_path(), document, payload.get('name')))
                elif self.path == '/api/validate':
                    errors = []
                    for q in payload.get('questions', []):
                        if q.get('selected'):
                            try:
                                validate_question(q)
                            except ValueError as error:
                                errors.append({'id': q['id'], 'error': str(error)})
                    from courseagent.programming_questions import validate_programming
                    for q in payload.get('programming_questions', []):
                        if q.get('selected'):
                            try:validate_programming(q, False)
                            except ValueError as error:errors.append({'id':q.get('id',''), 'error':str(error)})
                    self.json_reply({'errors': errors})
                elif self.path == '/api/programming-tree-contract':
                    from courseagent.tree_judge import apply_contract
                    from courseagent.programming_questions import validate_programming
                    question=copy.deepcopy(payload.get('question'))
                    if not isinstance(question,dict):raise ValueError('请提供编程题')
                    question=apply_contract(question,payload.get('task'))
                    validate_programming(question,False)
                    self.json_reply(question)
                elif self.path == '/api/export-programming-tests':
                    if payload.get('version',0)!=load_state().get('version',0):raise ConflictError('审核进度已经变化，请先刷新页面。')
                    from courseagent.programming_questions import export_test_bundle
                    content=export_test_bundle(payload)
                    self.reply(content,'application/zip',filename='programming-judge-bundle.zip')
                elif self.path == '/api/export':
                    if payload.get('version', 0) != load_state().get('version', 0):
                        raise ConflictError('审核进度已经变化，请先刷新页面。')
                    content = export_xlsx(payload)
                    (ROOT/'outputs/已审核-在线考试.xlsx').write_bytes(content)
                    selected = validate(payload, True)
                    manifest = {'name': payload['name'], 'sha256': hashlib.sha256(content).hexdigest(),
                                'question_count': len(selected), 'total_score': sum(q['score'] for q in selected),
                                'type_counts': {str(t): sum(q.get('type') == t for q in selected) for t in range(1, 6)},
                                'programming_count': sum(bool(q.get('selected')) for q in payload.get('programming_questions', [])),
                                'review_version': payload['version'], 'requires_platform_verification': True}
                    (ROOT/'outputs/import-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
                    self.reply(content, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', filename='educoder-exam.xlsx')
                elif self.path == '/api/start-import':
                    from courseagent.import_jobs import start_import
                    document = load_state()
                    if payload.get('version') != document.get('version'):
                        raise ConflictError('审核进度已经变化，请刷新并核对后再导入')
                    from courseagent.review_workflow import require_reviewed
                    require_reviewed(checkpoint_path(), document)
                    self.json_reply(start_import(ROOT, document, payload.get('classroom_url', ''), payload.get('course', '')), 202)
                elif self.path in ('/api/resume-review', '/api/complete-review', '/api/restore-review'):
                    from courseagent.review_workflow import resume, restore
                    document = load_state()
                    if payload.get('version') != document.get('version'):
                        raise ConflictError('审核进度已经变化，请刷新后再操作')
                    if self.path in ('/api/resume-review', '/api/complete-review'):
                        validate(document, True)
                        self.json_reply(resume(checkpoint_path(), document) if document.get('review_task_id') else {'status':'reviewed'})
                    else:
                        from courseagent.knowledge_tags import annotate
                        self.json_reply(annotate(restore(checkpoint_path(), payload.get('task_id'), document['version'])))
                elif self.path == '/api/exam-quality':
                    from courseagent.exam_quality import check_exam
                    document=payload['document']
                    if document.get('version')!=load_state().get('version'):raise ConflictError('审核进度已经变化，请刷新后检查')
                    self.json_reply(check_exam(document,bool(payload.get('use_model'))))
                elif self.path == '/api/search-replacement':
                    from courseagent.replacement_jobs import start
                    document=payload['document']
                    if document.get('version')!=load_state().get('version'):raise ConflictError('审核进度已经变化，请刷新后换题')
                    sources=json.loads(SOURCES.read_text())['sources'] if SOURCES.exists() else []
                    self.json_reply(start(ROOT,document,payload['question_id'],payload['reason'],sources),202)
                elif self.path in ('/api/alternatives', '/api/replace-question'):
                    from courseagent.replacements import alternatives, replace_question
                    document = payload['document']
                    if document.get('version') != load_state().get('version'):
                        raise ConflictError('审核进度已经变化，请刷新后再换题')
                    if self.path == '/api/alternatives':
                        self.json_reply({'questions': alternatives(document, payload['question_id'],payload.get('reason',''))})
                    else:
                        self.json_reply(replace_question(document, payload['question_id'], payload['replacement_id']))
                elif self.path == '/api/web-plan':
                    from courseagent.web_jobs import start
                    document = payload['document']
                    if document.get('version',0) != load_state().get('version',0):
                        raise ConflictError('审核进度已经变化，请刷新后再搜题')
                    sources = json.loads(SOURCES.read_text())['sources'] if SOURCES.exists() else []
                    request = {**payload['request'], 'source_mode':'web'}
                    self.json_reply(start(ROOT,checkpoint_path(),document,request,sources),202)
                elif self.path == '/api/plan':
                    from courseagent.review_workflow import create
                    document = payload['document']
                    if document.get('version', 0) != load_state().get('version', 0):
                        raise ConflictError('审核进度已经变化，请刷新后再组卷。')
                    sources = json.loads(SOURCES.read_text())['sources'] if SOURCES.exists() else []
                    from courseagent.answer_documents import attach_answers
                    document = attach_answers(document, sources)
                    from courseagent.knowledge_tags import annotate
                    document = annotate(document)
                    result = create(checkpoint_path(), document, payload['request'], sources)
                    # Preview only: generating a draft never overwrites the saved exam.
                    self.json_reply(result)
                elif self.path == '/api/search':
                    query = payload.get('query', '').strip()
                    if not query:
                        raise ValueError('请输入检索词')
                    terms = [s for s in re.split(r'[，,、\s]+', query) if s]
                    data = json.loads(SOURCES.read_text())
                    matches = []
                    for source in data['sources']:
                        for chunk in source['chunks']:
                            if all(term.lower() in chunk['text'].lower() for term in terms):
                                matches.append({'document_id': source['id'], 'name': source['name'], **chunk})
                    self.json_reply({'total': len(matches), 'matches': matches[:40], 'engine': '文件文字检索'})
                elif self.path == '/api/import-documents':
                    name = payload.get('name', '')
                    if Path(name).name != name or '/' in name or '\\' in name or name.startswith('.') or Path(name).suffix.lower() not in ('.docx', '.pdf'):
                        raise ValueError('请上传 .docx 或 .pdf 文件')
                    content = base64.b64decode(payload['content'], validate=True)
                    if len(content) > 16_000_000:
                        raise ValueError('单个文件最多 16 MB')
                    FILES.mkdir(parents=True, exist_ok=True)
                    target = FILES/name
                    if target.exists():
                        raise ValueError('同名文件已经存在，请先换一个文件名，避免覆盖原资料')
                    target.write_bytes(content)
                    try:
                        from courseagent.documents import read_source
                        read_source(target)
                    except Exception:
                        target.unlink()
                        raise ValueError('文件无法解析，请检查格式；扫描 PDF 暂不支持 OCR')
                    doc, sources, errors = refresh_sources(load_state())
                    result = save_state(doc)
                    self.json_reply({'document': result, 'sources': source_summaries(sources), 'errors': errors})
                else:
                    self.json_reply({'error': '接口不存在'}, 404)
        except ConflictError as error:
            self.json_reply({'error': str(error)}, 409)
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            self.json_reply({'error': str(error)}, 400)
        except ImportError:
            self.json_reply({'error': '运行环境缺少依赖，请按项目说明安装 requirements.txt。'}, 503)
        except Exception as error:
            print(f'操作失败：{type(error).__name__}: {error}', flush=True)
            self.json_reply({'error': '操作未完成，原审核进度已保留。请查看服务日志。'}, 500)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--review-file', type=Path, help='独立验收审核文件，不覆盖教师进度')
    args = parser.parse_args()
    if args.review_file:
        STATE = args.review_file.resolve()
        if not STATE.exists():
            parser.error('独立审核文件不存在')
    print(f'教师审核页面：http://127.0.0.1:{args.port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
