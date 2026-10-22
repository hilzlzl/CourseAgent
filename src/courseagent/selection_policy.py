"""Soft diversity preferences; eligibility and execution checks stay authoritative."""
import hashlib
import json
import re
import sqlite3
from collections import Counter
from urllib.parse import urlsplit


def canonical_source(url):
    p=urlsplit(url);host=(p.hostname or '').lower().removeprefix('www.')
    if host in ('leetcode.cn','leetcode.com'):
        m=re.match(r'/problems/([^/]+)',p.path)
        if m:return 'leetcode:'+m[1]
    if host in ('nowcoder.com','ac.nowcoder.com'):
        m=re.match(r'/(acm/problem/\d+|practice/[A-Za-z0-9]+)',p.path)
        if m:return 'nowcoder:'+m[1]
    return host+p.path.rstrip('/')


def coding(q):return bool(q.get('description') is not None and q.get('title'))


def identity_keys(q):
    keys=['id:'+str(q.get('base_question_id') or q.get('id',''))]
    if coding(q):
        text=re.sub(r'\s+','',q.get('description','')).casefold()
        keys += ['url:'+canonical_source(r['url']) for r in q.get('source_refs',[]) if r.get('url')]
    else:
        from courseagent.web_questions import semantic_question_key
        text=semantic_question_key(q)
    if text:keys.append('text:'+hashlib.sha256(text.encode()).hexdigest())
    return [k for k in dict.fromkeys(keys) if k!='id:']


def scope(target):
    # A deployment serves its logged-in teacher; separate classroom/course histories.
    return json.dumps([target.get('classroom_url','').rstrip('/'),target.get('course','').strip()],ensure_ascii=False)


def usage_snapshot(root,target,exclude_id=None,limit=30,*,execute=True,local_group='local_assignments'):
    path=root/'data/agent-tasks.sqlite';counts=Counter();tasks=[]
    if not path.exists():return {'counts':{},'task_ids':[]}
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        for ident,record in db.execute('SELECT id,record FROM tasks ORDER BY updated DESC'):
            if ident==exclude_id:continue
            job=json.loads(record)
            if job.get('status') not in ('ready','completed') or scope(job.get('target',{}))!=scope(target):continue
            if job.get('purpose') in ('development_test','format_validation_only'):continue
            # Local assignments have a separate history and never deplete the
            # real classroom's bank. Named experiments can isolate their group.
            if (job.get('execute') is True) != execute:continue
            if not execute and job.get('local_history_group','local_assignments') != local_group:continue
            doc=job.get('result',{})
            questions=[q for q in doc.get('questions',[])+doc.get('programming_questions',[]) if q.get('selected')]
            if not questions:continue
            counts.update({k for q in questions for k in identity_keys(q)})
            tasks.append(ident)
            if len(tasks)>=limit:break
    return {'counts':dict(counts),'task_ids':tasks}


def recent_count(q,context):
    return max((context.get('history',{}).get('counts',{}).get(k,0) for k in identity_keys(q)),default=0)


def stable_tie(q,context):
    seed=context.get('seed')
    if not seed:return ''
    return hashlib.sha256((seed+'|'+(q.get('url') or str(q.get('id','')))).encode()).hexdigest()


ALIASES={'二分查找':('二分查找','折半查找','binary-search'),
         '哈希查找':('哈希查找','散列查找','哈希表','散列表','hash-table'),
         '二叉排序树':('二叉排序树','二叉搜索树','binary-search-tree'),
         '深度优先搜索':('深度优先搜索','深度优先遍历','DFS','depth-first-search'),
         '广度优先搜索':('广度优先搜索','广度优先遍历','BFS','breadth-first-search'),
         '栈':('栈','stack'),'队列':('队列','queue'),'链表':('链表','linked-list'),
         '排序算法':('排序算法','排序','sorting'),'二叉树':('二叉树','binary-tree'),'图':('图','graph')}


def normalized_topic(word):
    word=re.sub(r'(?:的)?(?:基础操作|基本操作|典型应用|相关题目|基础知识|相关知识)$','',word)
    for key,values in ALIASES.items():
        if word.casefold() in [v.casefold() for v in values]:return key
    return word


def topic_hits(q,topics):
    # Discovery metadata ranks unread links; admitted question coverage uses actual text/labels.
    text=' '.join([q.get('title',''),q.get('stem',''),q.get('knowledge','')]+q.get('discovery_topics',[])).casefold()
    hits=[]
    for topic in dict.fromkeys(normalized_topic(t) for t in topics):
        words=ALIASES.get(topic,(topic,))
        if any(w.casefold() in text for w in words):hits.append(topic)
    return hits


def task_family(q):
    title=re.sub(r'\s*(?:[IVX]+|[ⅠⅡⅢⅣⅤ]+|\d+)\s*$','',q.get('title','')).strip()
    # Source titles often share a noun phrase while varying the queried value.
    title=re.sub(r'^(?:搜索|寻找|查找|求出|计算)','',title)
    title=re.split(r'中的|的最|的第',title)[0]
    explicit=q.get('course_fit',{}).get('task_family')
    if len(title)<5 and isinstance(explicit,str) and explicit.strip():return explicit.strip()
    return title or re.sub(r'\d+(?:\.\d+)?','#',q.get('stem',''))


def link_priority(link,chosen,context,topics,difficulty=0,read_counts=None,*,fallback=False):
    usage=context.get('history',{}).get('counts',{}).get('url:'+canonical_source(link['url']),0)
    topics=list(dict.fromkeys(normalized_topic(t) for t in topics))
    covered=Counter(t for q in chosen for t in topic_hits(q,topics))
    hits=topic_hits(link,topics)
    load=min((covered[t] for t in hits),default=max(covered.values(),default=0)+1)
    families={task_family(q) for q in chosen}
    def provider(url):return canonical_source(url).split(':')[0] if ':' in canonical_source(url) else urlsplit(url).hostname
    source_load=sum(any(provider(r.get('url',''))==provider(link['url']) for r in q.get('source_refs',[])) for q in chosen)
    desired={1:'EASY',2:'MEDIUM',3:'HARD'}.get(difficulty)
    raw=link.get('source_difficulty')
    mismatch=int(isinstance(raw,str) and bool(desired) and raw.upper()!=desired)
    read_load=(read_counts or {}).get(provider(link['url']),0)
    if fallback:
        # History is scoped to successful assignments, not a fit certificate.
        # Read known sources first; admission and execution gates still apply.
        return (int(usage==0),load,int(task_family(link) in families),mismatch,
                usage,read_load,source_load,stable_tie(link,context))
    return (load,int(task_family(link) in families),usage,mismatch,read_load,source_load,stable_tie(link,context))


def selection_report(document,context):
    qs=[q for q in document.get('questions',[])+document.get('programming_questions',[]) if q.get('selected')]
    programs=[q for q in qs if coding(q)];families=Counter(task_family(q) for q in programs)
    reused=[q['id'] for q in qs if recent_count(q,context)]
    return {'selected_count':len(qs),'recent_reused_ids':reused,'recent_reused_count':len(reused),
            'history_task_count':len(context.get('history',{}).get('task_ids',[])),
            'programming_families':[{'family':key,'count':n} for key,n in families.items()],
            'note':'优先考点互补与近期少用题；来源不足时允许复用，不降低正确性要求。'}
