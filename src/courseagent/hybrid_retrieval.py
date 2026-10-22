"""SQLite provenance and vectors, Chinese BM25, FAISS cosine search, RRF fusion.

Embeddings only encode question/material text, never answers or private solutions.
Numeric differences survive normalization. Near matches are hints, not deletions.
"""
from collections import Counter
from contextlib import contextmanager
from datetime import datetime,timezone
import hashlib,json,math,re,sqlite3
from pathlib import Path
import struct
import threading

VERSION='hybrid-retrieval-v1'

ALIASES={'栈':['后进先出','LIFO','stack'],'队列':['先进先出','FIFO','queue'],
         '栈和队列':['栈','队列','后进先出','先进先出','stack','queue'],
         '排序算法':['排序','sort','sorting'],'查找算法':['查找','search','二分搜索'],
         '链表':['链式存储','linked list'],'二叉树':['二叉树','binary tree'],
         '排序':['sort','sorting'],'查找':['search','二分搜索'],'哈希':['hash','散列']}

def tokens(text):
    result=re.findall(r'[a-z0-9_]+',text.casefold())
    for part in re.findall(r'[\u4e00-\u9fff]+',text):
        result.extend(part[i:i+2] for i in range(len(part)-1))
        result.extend(part)  # Single-character concepts such as 栈/树/图 must remain searchable.
    return result

def normalize(text):return re.sub(r'\s+','',text).casefold()

def expanded_query(query):
    return query+' '+' '.join(a for word,aliases in ALIASES.items() if word in query for a in aliases)

def question_text(q):
    return '\n'.join(str(q.get(k,'') or '') for k in ('title','stem','description','knowledge'))+'\n'+'\n'.join(q.get('options',[]))

def content_fingerprint(q):
    # Type and choices matter; answers do not turn the same question into a new problem.
    fields={k:q.get(k) for k in ('type','stem','description','options')}
    return hashlib.sha256(normalize(json.dumps(fields,ensure_ascii=False,sort_keys=True)).encode()).hexdigest()

class HybridIndex:
    def __init__(self,path,embeddings=None):
        self.path=Path(path);self.embeddings=embeddings;self._lock=threading.RLock()
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS records (
             id TEXT PRIMARY KEY, origin_id TEXT NOT NULL, kind TEXT NOT NULL, provider TEXT NOT NULL,
             title TEXT NOT NULL, text TEXT NOT NULL, text_hash TEXT NOT NULL, fingerprint TEXT NOT NULL,
             source_id TEXT NOT NULL, payload TEXT NOT NULL, terms TEXT NOT NULL, length INTEGER NOT NULL,
             updated_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS records_kind ON records(kind,provider);
            CREATE INDEX IF NOT EXISTS records_source ON records(source_id);
            CREATE INDEX IF NOT EXISTS records_fingerprint ON records(fingerprint);
            CREATE TABLE IF NOT EXISTS vectors (
             record_id TEXT NOT NULL, model TEXT NOT NULL, text_hash TEXT NOT NULL, dim INTEGER NOT NULL,
             vector BLOB NOT NULL, PRIMARY KEY(record_id,model),
             FOREIGN KEY(record_id) REFERENCES records(id) ON DELETE CASCADE);
            ''')
            if db.execute('PRAGMA user_version').fetchone()[0]<2:
                for row in db.execute('SELECT id,text FROM records').fetchall():
                    terms=Counter(tokens(row['text']))
                    db.execute('UPDATE records SET terms=?,length=? WHERE id=?',
                               (json.dumps(terms,ensure_ascii=False),sum(terms.values()),row['id']))
                db.execute('PRAGMA user_version=2')
    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=30);db.row_factory=sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:yield db
        finally:db.close()
    def upsert(self,records):
        count=0
        with self._lock,self.connect() as db:
            for r in records:
                text=r['text'][:24000];counts=Counter(tokens(text));hash_=hashlib.sha256(text.encode()).hexdigest()
                values=(r['id'],r['origin_id'],r['kind'],r['provider'],r['title'],text,hash_,r.get('fingerprint',hash_),
                        r.get('source_id',''),json.dumps(r['payload'],ensure_ascii=False),json.dumps(counts,ensure_ascii=False),
                        sum(counts.values()),datetime.now(timezone.utc).isoformat())
                db.execute('''INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                origin_id=excluded.origin_id,kind=excluded.kind,provider=excluded.provider,title=excluded.title,
                text=excluded.text,text_hash=excluded.text_hash,fingerprint=excluded.fingerprint,source_id=excluded.source_id,
                payload=excluded.payload,terms=excluded.terms,length=excluded.length,updated_at=excluded.updated_at''',values)
                # A changed question must never reuse a vector of its old text.
                db.execute('DELETE FROM vectors WHERE record_id=? AND text_hash<>?',(r['id'],hash_));count+=1
        return count
    def rows(self,kinds=None,providers=None,source_ids=None,exclude_ids=(),record_ids=None):
        clauses=[];values=[]
        for field,items in [('kind',kinds),('provider',providers),('source_id',source_ids),('id',record_ids)]:
            if items is not None:
                if not items:return []
                clauses.append(field+' IN ('+','.join('?' for _ in items)+')');values.extend(items)
        if exclude_ids:
            clauses.append('origin_id NOT IN ('+','.join('?' for _ in exclude_ids)+')');values.extend(exclude_ids)
        query='SELECT * FROM records'+(' WHERE '+' AND '.join(clauses) if clauses else '')+' ORDER BY id'
        with self.connect() as db:return [dict(r) for r in db.execute(query,values)]
    def _vectors(self,records,max_new=None):
        if not self.embeddings:return {},'disabled'
        model=self.embeddings.model_id
        with self.connect() as db:
            # Filter by selected rows again: vectors from a different source/kind cannot leak through.
            wanted={r['id']:r for r in records}
            stored={r['record_id']:list(struct.unpack('<'+'f'*r['dim'],r['vector']))
                    for r in db.execute('SELECT * FROM vectors WHERE model=?',(model,))
                    if r['record_id'] in wanted and r['text_hash']==wanted[r['record_id']]['text_hash']}
        missing=[r for r in records if r['id'] not in stored]
        if max_new is not None:missing=missing[:max_new]
        for start in range(0,len(missing),32):
            batch=missing[start:start+32]
            vectors=self.embeddings.embed([r['text'] for r in batch])
            if len(vectors)!=len(batch):raise ValueError('Embedding batch length mismatch')
            with self.connect() as db:
                for r,v in zip(batch,vectors):
                    if not v or not all(math.isfinite(float(x)) for x in v):raise ValueError('Invalid vector')
                    norm_=math.sqrt(sum(x*x for x in v))
                    if norm_==0:raise ValueError('Zero vector')
                    v=[x/norm_ for x in v];stored[r['id']]=v
                    # Check content again so concurrent edits cannot write a stale vector.
                    db.execute('''INSERT INTO vectors(record_id,model,text_hash,dim,vector)
                    SELECT ?,?,?,?,? WHERE EXISTS(SELECT 1 FROM records WHERE id=? AND text_hash=?)
                    ON CONFLICT(record_id,model) DO UPDATE SET text_hash=excluded.text_hash,dim=excluded.dim,vector=excluded.vector''',
                    (r['id'],model,r['text_hash'],len(v),struct.pack('<'+'f'*len(v),*v),r['id'],r['text_hash']))
        return stored,'ready'
    def prepare_vectors(self):
        records=self.rows();vectors,state=self._vectors(records)
        return {'records':len(records),'vectors':len(vectors),'state':state}
    def search(self,query,*,kinds=None,providers=None,source_ids=None,exclude_ids=(),record_ids=None,limit=20,semantic=True):
        if not isinstance(query,str) or not query.strip():raise ValueError('Empty retrieval query')
        if not 1<=limit<=200:raise ValueError('Retrieval limit outside 1..200')
        records=self.rows(kinds,providers,source_ids,exclude_ids,record_ids)
        qterms=set(tokens(expanded_query(query)));n=len(records);lex={};terms={r['id']:json.loads(r['terms']) for r in records}
        df={w:sum(w in terms[r['id']] for r in records) for w in qterms}
        avg=sum(r['length'] for r in records)/n if n else 1
        for r in records:
            score=0
            for word in qterms:
                freq=terms[r['id']].get(word,0)
                if freq:
                    idf=math.log(1+(n-df[word]+.5)/(df[word]+.5))
                    weight=.2 if len(word)==1 and '\u4e00'<=word<='\u9fff' else 1.
                    score+=weight*idf*freq*2.2/(freq+1.2*(.25+.75*r['length']/max(avg,1)))
            if score>0:lex[r['id']]=score
        lexical=sorted(lex,key=lambda i:(-lex[i],i));dense=[];scores={};vector_state='disabled';vector_error=None;vectors={}
        if semantic and records and self.embeddings:
            try:
                # Prepared corpora have all vectors; incremental new items are capped per query.
                preferred=sorted(records,key=lambda r:(-lex.get(r['id'],0),r['id']))
                vectors,vector_state=self._vectors(preferred,max_new=64)
                import numpy as np
                import faiss
                ids=[r['id'] for r in records if r['id'] in vectors]
                q=np.asarray(self.embeddings.embed([query]),dtype='float32')
                if q.ndim!=2 or q.shape[0]!=1 or not np.isfinite(q).all():raise ValueError('Invalid query vector')
                qnorm=np.linalg.norm(q)
                if qnorm==0:raise ValueError('Zero query vector')
                q/=qnorm
                matrix=np.asarray([vectors[i] for i in ids],dtype='float32')
                if matrix.shape[1]!=q.shape[1]:raise ValueError('Embedding dimension mismatch')
                index=faiss.IndexFlatIP(matrix.shape[1]);index.add(matrix)
                ds,positions=index.search(q,min(len(ids),max(limit*3,30)))
                for score,pos in zip(ds[0],positions[0]):
                    if pos>=0 and float(score)>0:
                        ident=ids[int(pos)];dense.append(ident);scores[ident]=float(score)
                vector_state='ready' if len(ids)==n else 'partial'
            except (ImportError,RuntimeError,ValueError,IndexError) as exc:
                vector_state='unavailable';vector_error=str(exc)[:240]
        fused={};ranks={}
        for channel,ordered in [('bm25',lexical),('vector',dense)]:
            for rank,ident in enumerate(ordered,1):
                fused[ident]=fused.get(ident,0)+1/(60+rank);ranks.setdefault(ident,{})[channel]=rank
        by_id={r['id']:r for r in records};items=[]
        for ident in sorted(fused,key=lambda i:(-fused[i],i))[:limit]:
            r=by_id[ident]
            items.append({'id':ident,'origin_id':r['origin_id'],'kind':r['kind'],'provider':r['provider'],
                          'title':r['title'],'text':r['text'],'source_id':r['source_id'],'fingerprint':r['fingerprint'],
                          'payload':json.loads(r['payload']),
                          'retrieval':{'method':VERSION,'rrf_score':fused[ident],'ranks':ranks[ident],
                                       'bm25_score':lex.get(ident,0),'vector_score':scores.get(ident)}})
        # Similarity is only a duplicate-review clue: do not delete different conditions/answers.
        if vector_state in ('ready','partial') and vectors:
            eligible=[item for item in items if item['id'] in vectors]
            if eligible:
                matrix=np.asarray([vectors[item['id']] for item in eligible],dtype='float32')
                similarities=matrix@matrix.T
                for i,item in enumerate(eligible):
                    hints=[{'origin_id':other['origin_id'],'cosine':float(similarities[i,j])}
                           for j,other in enumerate(eligible) if i!=j and item['kind']==other['kind'] and similarities[i,j]>=.94]
                    if hints:item['retrieval']['near_duplicates']=hints[:5]
        return {'items':items,'diagnostics':{'method':VERSION,'eligible_records':n,'lexical_hits':len(lexical),
                'vector_hits':len(dense),'vector_state':vector_state,'vector_error':vector_error,
                'embedding_model':self.embeddings.model_id if self.embeddings else None,'model_calls':0}}
    def stats(self):
        with self.connect() as db:
            counts={r['kind']:r['n'] for r in db.execute('SELECT kind,count(*) n FROM records GROUP BY kind')}
            vectors=db.execute('SELECT count(*) FROM vectors').fetchone()[0]
        return {'version':VERSION,'counts':counts,'vectors':vectors}
