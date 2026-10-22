"""SQLite task queue, durable receipts and replayable progress events.

No keys or teacher review state are stored here. Each process uses short-lived
connections; claiming work and reserving the one active task are transactional.
"""
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

class TaskStore:
    def __init__(self,root):
        self.path=Path(root)/'data/agent-tasks.sqlite'
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
            CREATE TABLE IF NOT EXISTS tasks(
              id TEXT PRIMARY KEY, record TEXT NOT NULL, submission TEXT,
              queue_state TEXT NOT NULL DEFAULT 'done', owner TEXT,
              lease_until REAL NOT NULL DEFAULT 0, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS events(
              seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
              created REAL NOT NULL, summary TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS task_events ON events(task_id,seq);
            ''')
    def connect(self):
        db=sqlite3.connect(self.path,timeout=15)
        return db
    def _write(self,db,job):
        data=json.dumps(job,ensure_ascii=False)
        db.execute('INSERT INTO tasks(id,record,updated) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET record=excluded.record,updated=excluded.updated',(job['id'],data,time.time()))
        # Progress event contains UI metadata, never full questions/private solutions.
        summary={k:job.get(k) for k in ('status','phase','activity','model_calls','run_model_calls','live_selection','branches','verification_progress','message')}
        db.execute('INSERT INTO events(task_id,created,summary) VALUES(?,?,?)',(job['id'],time.time(),json.dumps(summary,ensure_ascii=False)))
    def save(self,job,owner=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if owner:
                row=db.execute('SELECT owner,queue_state,lease_until FROM tasks WHERE id=?',(job['id'],)).fetchone()
                if not row or row[0]!=owner or row[1]!='running' or row[2]<time.time():
                    raise RuntimeError('Worker lease lost; stale worker cannot update or deliver this task')
            self._write(db,job)
    def get(self,identity):
        with self.connect() as db:row=db.execute('SELECT record FROM tasks WHERE id=?',(identity,)).fetchone()
        return json.loads(row[0]) if row else None
    def queued_for_recovery(self,identity):
        with self.connect() as db:
            row=db.execute('SELECT queue_state FROM tasks WHERE id=?',(identity,)).fetchone()
        return bool(row and row[0] in ('queued','running'))
    def active_ids(self):
        with self.connect() as db:
            return [r[0] for r in db.execute("SELECT id FROM tasks WHERE queue_state IN ('queued','running') OR json_extract(record,'$.status')='importing'")]
    def ids(self):
        with self.connect() as db:return [r[0] for r in db.execute('SELECT id FROM tasks ORDER BY updated DESC')]
    def enqueue(self,job,submission):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for ident,state,record in db.execute('SELECT id,queue_state,record FROM tasks'):
                if state in ('queued','running') or json.loads(record).get('status')=='importing':
                    raise ValueError('已有自主任务正在执行或等待 Worker')
            self._write(db,job)
            db.execute("UPDATE tasks SET submission=?,queue_state='queued',owner=NULL,lease_until=0 WHERE id=?",(json.dumps(submission,ensure_ascii=False),job['id']))
    def claim(self,owner,lease_seconds=120):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT id,record,submission FROM tasks WHERE queue_state='queued' ORDER BY updated LIMIT 1").fetchone()
            if not row:return None
            db.execute("UPDATE tasks SET queue_state='running',owner=?,lease_until=? WHERE id=?",(owner,time.time()+lease_seconds,row[0]))
            return {'id':row[0],'job':json.loads(row[1]),'submission':json.loads(row[2])}
    def heartbeat(self,identity,owner,lease_seconds=120):
        with self.connect() as db:
            cur=db.execute("UPDATE tasks SET lease_until=? WHERE id=? AND owner=? AND queue_state='running'",(time.time()+lease_seconds,identity,owner))
            return cur.rowcount==1
    def finish(self,identity,owner):
        with self.connect() as db:
            db.execute("UPDATE tasks SET queue_state='done',lease_until=0 WHERE id=? AND owner=?",(identity,owner))
    def recover_expired(self):
        recovered=[]
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for ident,record,submission in db.execute("SELECT id,record,submission FROM tasks WHERE queue_state='running' AND lease_until<?",(time.time(),)).fetchall():
                job=json.loads(record)
                # Running records contain the last persisted counters, not the
                # UI's computed elapsed value. Preserve that run on recovery.
                if job.get('run_started_at'):
                    try:
                        runtime=max(0,int((datetime.now(timezone.utc)-datetime.fromisoformat(job['run_started_at'])).total_seconds()))
                        job['elapsed_seconds']=max(job.get('elapsed_seconds',0),job.get('elapsed_before_run',0)+runtime)
                    except (TypeError,ValueError):
                        pass
                # Never replay an uncertain external write after process failure.
                if job.get('delivery_intent') or job.get('import_id'):
                    job.update(status='needs_attention',message='交付期间 Worker 中断；保留导入记录，需核对平台状态后恢复，未重复写入')
                    state='done'
                else:
                    job.update(status='queued',phase='Worker 中断，等待从检查点恢复',owner_pid=None)
                    state='queued';recovered.append(ident)
                self._write(db,job)
                db.execute('UPDATE tasks SET queue_state=?,owner=NULL,lease_until=0 WHERE id=?',(state,ident))
        return recovered
    def events(self,identity=None,after=0,limit=100):
        with self.connect() as db:
            sql='SELECT seq,task_id,created,summary FROM events WHERE seq>?';args=[after]
            if identity:sql+=' AND task_id=?';args.append(identity)
            sql+=' ORDER BY seq LIMIT ?';args.append(min(limit,500))
            rows=db.execute(sql,args).fetchall()
        return [{'seq':r[0],'task_id':r[1],'created':r[2],'summary':json.loads(r[3])} for r in rows]


from functools import lru_cache
@lru_cache(maxsize=64)
def _store_at(root):return TaskStore(root)
def store_for(root):return _store_at(str(Path(root).absolute()))
