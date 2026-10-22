"""Content-free trace index; JSON artifacts remain available for inspection."""
import json
import sqlite3
from pathlib import Path
from functools import lru_cache

class TraceStore:
    def __init__(self,folder):
        self.path=Path(folder)/'index.sqlite'
        with sqlite3.connect(self.path,timeout=15) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS traces(id TEXT PRIMARY KEY,parent_id TEXT,record TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS trace_parent ON traces(parent_id)')
    def save(self,record):
        with sqlite3.connect(self.path,timeout=15) as db:
            db.execute('INSERT INTO traces VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET record=excluded.record,parent_id=excluded.parent_id',
                       (record['id'],record.get('parent_id'),json.dumps(record,ensure_ascii=False)))
    def records(self):
        with sqlite3.connect(self.path,timeout=15) as db:return [json.loads(row[0]) for row in db.execute('SELECT record FROM traces')]

@lru_cache(maxsize=64)
def store_at(folder):return TraceStore(folder)
