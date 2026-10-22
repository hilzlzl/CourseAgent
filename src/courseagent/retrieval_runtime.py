"""Integration boundaries for the autonomous Agent's persistent candidate memory."""
from courseagent.paths import ROOT as WORKSPACE_ROOT
import copy,json,os,threading
from pathlib import Path
from courseagent.hybrid_retrieval import HybridIndex,question_text,content_fingerprint,ALIASES
from courseagent.source_adapters import provider_for
ROOT=WORKSPACE_ROOT
INDEX_PATH=ROOT/'data/retrieval.sqlite'
INDEXES={};LOCK=threading.RLock()

def get_index():
    path=Path(os.environ.get('EDUCODER_RETRIEVAL_DB',str(INDEX_PATH)))
    with LOCK:
        if str(path) not in INDEXES:
            from courseagent.semantic_embeddings import LocalEmbeddings
            INDEXES[str(path)]=HybridIndex(path,LocalEmbeddings())
        return INDEXES[str(path)]

def question_record(q,kind):
    refs=q.get('source_refs',[])
    url=next((r.get('url') for r in refs if r.get('url')),None)
    if not url:return None
    provider=provider_for(url)
    return {'id':kind+':'+q['id'],'origin_id':q['id'],'kind':kind,'provider':provider,
            'title':q.get('title') or q.get('stem','')[:100], 'text':question_text(q),
            'source_id':url,'fingerprint':content_fingerprint(q),'payload':copy.deepcopy(q)}

def remember_document(document):
    rows=[]
    for field,kind in [('questions','ordinary'),('programming_questions','programming')]:
        for q in document.get(field,[]):
            if not q.get('origin','').startswith('web') or q.get('approved'):continue
            record=question_record(q,kind)
            if record:rows.append(record)
    return get_index().upsert(rows)

def remember_sources(sources):
    rows=[]
    for source in sources:
        for index,chunk in enumerate(source.get('chunks',[])):
            text=chunk.get('text','')
            if not text.strip():continue
            payload={'name':source['name'],'document_id':source['id'],**copy.deepcopy(chunk)}
            rows.append({'id':'material:'+source['id']+':'+str(chunk.get('page',chunk.get('paragraph',index))),
                         'origin_id':source['id'],'kind':'material','provider':'course_material' if source.get('kind')=='pdf' else 'local_document',
                         'title':source['name'],'text':text,'source_id':source['id'],'payload':payload})
    index=get_index();index.upsert(rows)
    # Uploaded material may be rescanned/edited: remove disappeared chunks from current sources.
    live={r['id'] for r in rows}
    with index.connect() as db:
        for source in sources:
            for r in db.execute('SELECT id FROM records WHERE kind="material" AND source_id=?',(source['id'],)).fetchall():
                if r['id'] not in live:db.execute('DELETE FROM records WHERE id=?',(r['id'],))
    return len(rows)

def scope_match(topics,text):
    if not topics:return True
    text=text.casefold()
    return any(word.casefold() in text for topic in topics for word in [topic,*ALIASES.get(topic,[])])

def reusable(q,kind,avoid_ids):
    if q['id'] in avoid_ids or (q.get('base_question_id') or q['id']) in avoid_ids:return False
    if kind=='ordinary':
        from courseagent.ordinary_verification import current
        evidence=current(q)
        if evidence and evidence.get('verdict') in ('conflict','uncertain'):return False
        from courseagent.questions import validate_question
        try:validate_question(q)
        except ValueError:return False
    else:
        from courseagent.programming_questions import validate_programming
        from courseagent.programming_verification import current_report
        evidence=current_report(q)
        if evidence and not evidence.get('passed'):return False
        try:validate_programming(q,False)
        except ValueError:return False
    return True

def reuse_candidates(document,spec,request,kind):
    topics=spec.get('topics',[]);query=' '.join(topics) or request.get('prompt','')
    from courseagent.retrieval_tools import search_indexed_questions
    result=search_indexed_questions.invoke({'query':query,'kinds':[kind],'exclude_ids':request.get('avoid_ids',[]),'limit':100})
    field='questions' if kind=='ordinary' else 'programming_questions'
    bank={q['id']:q for q in document.get(field,[])};hits=[];seen=set();conflicts=[]
    answer_groups={}
    for item in result['items']:
        q=item['payload']
        answer_key=json.dumps({k:q.get(k) for k in ('answer','blanks','reference_answer')},ensure_ascii=False,sort_keys=True)
        if kind=='ordinary':answer_groups.setdefault(item['fingerprint'],set()).add(answer_key)
    conflicting={key for key,values in answer_groups.items() if len(values)>1}
    for item in result['items']:
        if item['fingerprint'] in conflicting:continue
        q=copy.deepcopy(item['payload'])
        if not scope_match(topics,question_text(q)) or not reusable(q,kind,request.get('avoid_ids',[])):continue
        if item['fingerprint'] in seen:continue
        if q['id'] in bank:
            # Retrieval cannot overwrite current preview edits or confirm teacher review.
            existing=bank[q['id']]
            if existing.get('approved'):continue
            keys=('stem','options','answer','blanks','reference_answer') if kind=='ordinary' else ('description','public_examples','test_cases')
            if any(existing.get(k)!=q.get(k) for k in keys):
                conflicts.append(q['id']);continue
            q=existing
        else:
            q['selected']=False;q['approved']=False;q.pop('approval_snapshot',None)
            document.setdefault(field,[]).append(q);bank[q['id']]=q
        q['retrieval_evidence']=item['retrieval']
        q['retrieval_evidence']['source_provider']=item['provider']
        q['retrieval_evidence']['reused']=True
        hits.append(q);seen.add(item['fingerprint'])
    return hits,{**result['diagnostics'],'reused_count':len(hits),'preview_conflicts':conflicts,'conflicting_answer_groups':len(conflicting)}

def retrieve_materials(sources,spec):
    remember_sources(sources)
    selected=spec.get('source_ids')
    allowed=[s['id'] for s in sources if selected is None or s['id'] in selected]
    if not allowed:return []
    query=' '.join(spec.get('topics',[]))
    if not query:return []
    allowed_rows=get_index().rows(kinds=['material'],source_ids=allowed)
    ids=[]
    for row in allowed_rows:
        p=json.loads(row['payload']);page=p.get('page')
        if page and ((spec.get('page_start') and page<int(spec['page_start'])) or (spec.get('page_end') and page>int(spec['page_end']))):continue
        ids.append(row['id'])
    items=get_index().search(query,kinds=['material'],source_ids=allowed,record_ids=ids,limit=40)['items']
    result=[]
    for item in items:
        p=item['payload'];page=p.get('page')
        if page and ((spec.get('page_start') and page<int(spec['page_start'])) or (spec.get('page_end') and page>int(spec['page_end']))):continue
        result.append({**p,'text':p['text'][:1800],'retrieval_evidence':item['retrieval']})
        if len(result)>=8:break
    return result


def status():
    index=get_index()
    return {**index.stats(),'embedding':index.embeddings.status() if index.embeddings else {'enabled':False}}
