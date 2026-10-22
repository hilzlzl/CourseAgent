"""Persistent LangGraph human review; no external platform actions."""
import copy
import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command, interrupt
from courseagent.questions import validate, review_content


def fingerprint(document):
    content = {'name': document['name'], 'questions': [
        {'id': q['id'], 'content': review_content(q)} for q in document['questions'] if q.get('selected')
    ]}
    from courseagent.programming_questions import review_content as programming_content
    programming = [{'id':q['id'], 'content':programming_content(q)} for q in document.get('programming_questions',[]) if q.get('selected')]
    if programming:content['programming_questions']=programming
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def teacher_review(state):
    approved = interrupt({'kind': 'teacher_review', 'message': '请核对已选题目并保存，再恢复审核流程。'})
    validate(approved, True)
    return {'result': approved, 'review_receipt': {'version': approved['version'],
            'sha256': fingerprint(approved), 'confirmed_at': datetime.now(timezone.utc).isoformat()}}


@contextmanager
def session(path):
    from courseagent.workflow import build_graph
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), check_same_thread=False)
    try:
        connection.execute('CREATE TABLE IF NOT EXISTS review_tasks (id TEXT PRIMARY KEY, created_at TEXT)')
        if 'saved_name' not in [r[1] for r in connection.execute('PRAGMA table_info(review_tasks)')]:
            connection.execute('ALTER TABLE review_tasks ADD COLUMN saved_name TEXT')
            connection.commit()
        graph = build_graph(checkpointer=SqliteSaver(connection), human_review=True)
        yield connection, graph
    finally:
        connection.close()


def config(task_id):
    if not isinstance(task_id, str) or len(task_id) != 32 or any(c not in '0123456789abcdef' for c in task_id):
        raise ValueError('审核任务编号不正确')
    return {'configurable': {'thread_id': task_id}, 'recursion_limit': 64}


def require_task(connection, task_id):
    if not connection.execute('SELECT 1 FROM review_tasks WHERE id=?', (task_id,)).fetchone():
        raise ValueError('审核任务不存在')


from courseagent.observability import traced

@traced("review_task_creation")
def create(path, document, request, sources, progress=None):
    task_id = uuid.uuid4().hex
    with session(path) as (connection, graph):
        if progress:
            for update in graph.stream({'document': document, 'request': request, 'sources': sources}, config(task_id), stream_mode='updates'):
                for node in update: progress(node)
        else:
            graph.invoke({'document': document, 'request': request, 'sources': sources}, config(task_id))
        result = copy.deepcopy(graph.get_state(config(task_id)).values['result'])
        result['review_task_id'] = task_id
        graph.update_state(config(task_id), {'result': result})
        connection.execute('INSERT INTO review_tasks (id, created_at) VALUES (?,?)', (task_id, datetime.now(timezone.utc).isoformat()))
        connection.commit()
        return result


def record_saved(path, document):
    task_id = document.get('review_task_id')
    if not task_id:
        return
    with session(path) as (connection, graph):
        require_task(connection, task_id)
        # Re-open review after each save, including edits to a previously approved exam.
        graph.update_state(config(task_id), {'result': copy.deepcopy(document), 'review_receipt': None}, as_node='assemble_draft')
        graph.invoke(None, config(task_id))


@traced("teacher_review_resume")
def resume(path, document):
    task_id = document.get('review_task_id')
    with session(path) as (connection, graph):
        require_task(connection, task_id)
        snapshot = graph.get_state(config(task_id))
        if snapshot.values.get('result') != document:
            raise ValueError('审核任务与已保存进度不一致，请先保存当前任务')
        validate(document, True)
        if snapshot.next:
            graph.invoke(Command(resume=copy.deepcopy(document)), config(task_id))
        return describe(graph.get_state(config(task_id)), task_id)


def describe(snapshot, task_id):
    doc = snapshot.values['result']
    return {'id': task_id, 'name': doc['name'], 'version': doc.get('version'),
            'request': (doc.get('plan') or {}).get('request') or snapshot.values.get('request',{}).get('prompt',''),
            'question_count': sum(bool(q.get('selected')) for q in doc['questions'] + doc.get('programming_questions', [])),
            'status': 'awaiting_review' if snapshot.next else 'reviewed',
            'receipt': snapshot.values.get('review_receipt')}


def list_tasks(path):
    with session(path) as (connection, graph):
        return [{**describe(graph.get_state(config(row[0])), row[0]), 'created_at': row[1], 'saved_name': row[2]} for row in
                connection.execute('SELECT id, created_at, saved_name FROM review_tasks ORDER BY created_at DESC')]


def restore(path, task_id, current_version):
    with session(path) as (connection, graph):
        require_task(connection, task_id)
        doc = copy.deepcopy(graph.get_state(config(task_id)).values['result'])
        doc['version'] = current_version
        return doc


def require_reviewed(path, document):
    if not document.get('review_task_id'):
        return  # Legacy manually reviewed exams remain supported.
    with session(path) as (connection, graph):
        task_id = document['review_task_id']
        require_task(connection, task_id)
        snapshot = graph.get_state(config(task_id))
        receipt = snapshot.values.get('review_receipt')
        validate(document, True)
        if snapshot.next or not receipt or receipt['version'] != document['version'] or receipt['sha256'] != fingerprint(document):
            raise ValueError('请先完成审核并恢复流程；保存修改后需再次确认审核')
        return {'task_id': task_id, **receipt}


def save_scheme(path, document, name):
    if not isinstance(name,str) or not name.strip() or len(name)>60:
        raise ValueError('方案名称需为1–60个字符')
    task_id=uuid.uuid4().hex
    doc=copy.deepcopy(document);doc['review_task_id']=task_id
    with session(path) as (connection,graph):
        graph.update_state(config(task_id),{'document':doc,'request':{'prompt':(doc.get('plan') or {}).get('request','')},'result':doc},as_node='assemble_draft')
        graph.invoke(None,config(task_id))
        connection.execute('INSERT INTO review_tasks (id,created_at,saved_name) VALUES (?,?,?)',(task_id,datetime.now(timezone.utc).isoformat(),name.strip()))
        connection.commit()
        return {'id':task_id,'saved_name':name.strip()}
