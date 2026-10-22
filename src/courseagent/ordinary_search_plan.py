"""Type-aware query allocation using model-planned terms and bounded fallbacks."""
import re
from courseagent.questions import TYPE_NAMES


def validate_intents(value):
    if not isinstance(value, list):
        return []
    result = []
    for row in value[:12]:
        if not isinstance(row, dict):
            continue
        kind, query = str(row.get('type', '')), row.get('query')
        if (kind not in ('1', '2', '3', '4', '5') or not isinstance(query, str)
                or not 2 <= len(query.strip()) <= 180 or re.search(r'[\r\n\x00]', query)):
            continue
        result.append({'type': kind, 'query': query.strip()})
    return result


def compact_query(spec, query, kind=None, round_no=0):
    """Keep one focus per query, including decisions made by the researcher."""
    from courseagent.web_questions import search_topic
    root=search_topic(spec)
    if kind is None:
        labels={'1':r'单选|单项选择|选择题','2':r'多选|多项选择','3':r'判断','4':r'填空','5':r'简答|应用题|算法设计'}
        kind=next((t for t in ('2','1','3','4','5') if re.search(labels[t],query)),None)
    if kind and (len(query)>36 or len(query.split())>5):
        words=[t for t in spec.get('topics',[]) if t in query and t not in root]
        words += [w for g in spec.get('teaching_plan',{}).get('goals',[]) for w in g.get('keywords',[])
                  if isinstance(w,str) and 2<=len(w)<=12 and w in query and w not in root]
        words=list(dict.fromkeys(words))
        focus=words[round_no%len(words)] if words else ''
        sites=re.findall(r'(?<![-\w])site:\S+',query)
        label='算法设计题' if kind=='5' and spec.get('short_answer_kind')=='algorithm_design' else TYPE_NAMES[int(kind)]
        return ' '.join(w for w in (root,focus,label,'习题',*sites[:1]) if w)
    return query.strip()


def plan_queries(spec, counts=None, previous=(), suggestions=(), round_no=0):
    from courseagent.web_questions import search_topic
    topic = search_topic(spec)
    counts = spec['counts'] if counts is None else counts
    kinds = [str(t) for t, n in counts.items() if n and int(t) in TYPE_NAMES]
    if not kinds:
        return []
    goals = spec.get('teaching_plan', {}).get('goals', [])
    intents = validate_intents(spec.get('teaching_plan', {}).get('search_intents', []))
    seen, rows = set(previous), []

    def add(query, kind, origin):
        if not isinstance(query, str) or not query.strip() or len(query) > 200:
            return False
        query = query.strip()
        original = query
        # A search intent is not an AND-list of every curriculum keyword.
        # Keep one model-chosen subtopic; later rounds can explore the others.
        if kind and (len(query) > 36 or len(query.split()) > 5):
            label = ('算法设计题' if spec.get('short_answer_kind') == 'algorithm_design'
                     else '应用题') if kind == '5' else TYPE_NAMES[int(kind)]
            terms = [w for goal in goals for w in goal.get('keywords', [])
                     if isinstance(w, str) and 2 <= len(w) <= 12 and w in query
                     and w not in spec.get('topics', [])]
            focus = terms[round_no % len(terms)] if terms else ''
            query = ' '.join(w for w in (topic, focus, label, '习题') if w)
        if topic and topic.casefold() not in query.casefold() and not any(t.casefold() in query.casefold() for t in spec.get('topics', [])):
            query = topic + ' ' + query
        if '数据结构' in original and '数据结构' not in query:
            query = '数据结构 ' + query
        if query in seen:
            return False
        seen.add(query)
        row={'query': query, 'type': kind, 'origin': origin}
        if query != original:row['original_query']=original
        rows.append(row)
        return True

    # Reserve one actual query per requested type BEFORE broad content queries
    # or supervisor suggestions consume the bounded first batch.
    for index, kind in enumerate(kinds):
        label = ('算法设计题' if spec.get('short_answer_kind') == 'algorithm_design'
                 else '应用题') if kind == '5' else TYPE_NAMES[int(kind)]
        suggested = [q for q in suggestions if isinstance(q, str) and label in q]
        planned = [r['query'] if label in r['query'] else r['query']+' '+label
                   for r in intents if r['type'] == kind]
        if any(add(q, kind, 'supervisor') for q in suggested):
            continue
        if any(add(q, kind, 'model') for q in planned):
            continue
        keywords = goals[(index + round_no) % len(goals)].get('keywords', [])[:2] if goals else []
        words = ' '.join(w for w in keywords if w not in spec.get('topics', []))
        suffix = ('习题 解析', '典型练习', '课程复习题')[round_no % 3]
        query = f'{topic} {words} {label} {suffix}'.replace('  ', ' ')
        if not add(query, kind, 'goal_fallback'):
            add(query + f' 第{round_no + 1}批', kind, 'goal_fallback')
    for query in suggestions:
        if len(rows) >= 5:
            break
        add(query, None, 'supervisor')
    for goal in goals:
        if len(rows) >= 5:
            break
        words = ' '.join(goal.get('keywords', [])[:2])
        add(f'{topic} {words} 课程 习题 解析', None, 'teaching_goal')
    if len(rows) < 5:
        add(f'{topic} 课程 习题 site:edu.cn', None, 'course_breadth')
    return rows[:5]


def question_set_queries(spec, counts=None, previous=(), suggestions=(), round_no=0):
    """Short chapter-level queries first; expand one focus only after a gap."""
    from courseagent.web_questions import search_topic
    from os.path import commonprefix
    topic=search_topic(spec).replace('排序算法','排序')
    topics=[t.strip() for t in spec.get('topics',[]) if isinstance(t,str) and t.strip()]
    # A normalized concept can describe only one part of the teacher's scope.
    # Use the common chapter root where possible; keep distinct topics in
    # separate queries rather than turning them into an AND-list.
    root=commonprefix(topics).rstrip('的、及与和 ') if topics else ''
    if len(root)<2 and len(topics)>2:
        prefixes={commonprefix([a,b]).rstrip('的、及与和 ') for i,a in enumerate(topics) for b in topics[i+1:]}
        shared=[p for p in prefixes if len(p)>=2 and sum(t.startswith(p) for t in topics)>len(topics)//2]
        root=max(shared,key=lambda p:(sum(t.startswith(p) for t in topics),len(p)),default='')
    if len(root)>=2:
        topic=('数据结构 ' if topic.startswith('数据结构 ') else '')+root
    counts={str(t):n for t,n in (spec['counts'] if counts is None else counts).items()}
    kinds=sorted((t for t,n in counts.items() if n), key=lambda t:-counts[t])
    seen=set(previous);rows=[]
    def add(query, kind=None, origin='question_set', original=None):
        if query and query not in seen:
            seen.add(query);row={'query':query,'type':kind,'origin':origin}
            if original and original!=query:row['original_query']=original
            rows.append(row)
            return True
        return False
    intents=validate_intents(spec.get('teaching_plan',{}).get('search_intents',[]))
    def planned(kind):
        label='选择题' if kind=='1' else TYPE_NAMES[int(kind)]
        options=[q for q in suggestions if isinstance(q,str) and
                 (label in q or TYPE_NAMES[int(kind)] in q)]
        for query in options:
            if 2<=len(query)<=100 and not re.search(r'[\r\n\x00]',query):
                if add(query.strip(),kind,'supervisor'):return True
        # Preserve the model's choice of focus, but execute one focus at a
        # time. Keywords from IO instructions are not curriculum topics.
        for row in intents:
            if row['type']!=kind:continue
            original=row['query']
            matched=[t for t in topics if t in original]
            chapter=max(matched,key=len) if matched else topic
            focuses=[w for g in spec.get('teaching_plan',{}).get('goals',[]) for w in g.get('keywords',[])
                     if isinstance(w,str) and 2<=len(w)<=12 and w in original and w not in chapter]
            if not focuses:
                focuses=[w for w in re.split(r'[\s，、；,;]+',original) if 2<=len(w)<=12
                         and w not in chapter and w not in ('数据结构','题库','习题','试题','答案','解析','标准输入','标准输出')
                         and not re.search(r'单选|选择题|判断题|填空题|简答题|多选|site:',w)]
            for focus in list(dict.fromkeys(focuses)) or ['']:
                query=' '.join(w for w in (chapter,focus,label,'习题 答案') if w)
                if add(query,kind,'model',original):return True
        return False
    for kind in kinds:
        label='选择题' if kind=='1' else TYPE_NAMES[int(kind)]
        if planned(kind):continue
        for suffix in ('答案',):
            query=f'{topic} {label} {suffix}'
            if query not in seen:
                add(query,kind);break
        else:
            for focus in topics:
                if focus in topic:continue
                if add(f'{focus} {label} 习题 答案',kind,'teacher_topic'):break
            else:
                for suffix in ('习题 site:cnblogs.com','习题 site:blog.csdn.net','试题 site:edu.cn'):
                    if add(f'{topic} {label} {suffix}',kind):break
    if round_no:
        for focus in topics:
            if focus in topic:continue
            for kind in kinds:
                if len(rows)>=3:break
                add(f'{focus} {TYPE_NAMES[int(kind)]} 习题 答案',kind,'teacher_topic')
        keywords=list(dict.fromkeys(w for g in spec.get('teaching_plan',{}).get('goals',[]) for w in g.get('keywords',[]) if isinstance(w,str) and 2<=len(w)<=12 and w not in topic
                                   and w not in ('标准输入','标准输出','输入格式','输出格式')))
        for word in keywords:
            for kind in kinds:
                if len(rows)>=3:break
                add(f'{topic} {word} {TYPE_NAMES[int(kind)]} 习题 答案',kind)
    if len(rows)<3:
        for suffix in ('习题 答案 site:cnblogs.com','章节习题及答案','习题 site:edu.cn'):
            add(f'{topic} {suffix}')
            if len(rows)>=3:break
    return rows[:max(3,len(kinds))]
