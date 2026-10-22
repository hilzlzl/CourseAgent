"""Normalize course language into a shared retrieval plan.

The planner and the source adapters used to communicate through a flat list of
strings.  That loses the distinction between a chapter (``图``), an algorithm
family (``DFS/BFS``), and supporting structures (``队列``/``邻接表``).  This
module keeps that distinction in a small, inspectable data object.  It is a
retrieval aid only; candidate eligibility is still decided from the actual
question statement and its evidence.
"""
CONCEPTS = {
    'graph': {
        'name': '图',
        'aliases': ('图', '图论', '邻接表', '邻接矩阵'),
        'algorithm_families': (),
        'structures': ('图', '邻接表', '邻接矩阵'),
        'bank_tags': ('graph',),
        'search_terms': ('图',),
    },
    'graph_traversal': {
        'name': '图遍历',
        'aliases': ('图遍历', '图的遍历', '深度优先搜索', '广度优先搜索',
                    '图的深度优先搜索', '图的广度优先搜索', 'DFS', 'BFS',
                    '深搜', '广搜', '连通分量'),
        'algorithm_families': ('DFS', 'BFS'),
        'structures': ('图', '邻接表', '邻接矩阵', '访问标记', '队列', '栈'),
        'bank_tags': ('graph',),
        'search_terms': ('图遍历', 'DFS', 'BFS', '连通分量'),
    },
    'graph_shortest_path': {
        'name': '图上的最短路径',
        'aliases': ('最短路径', '最短路', 'Dijkstra', '迪杰斯特拉', 'Floyd',
                    '弗洛伊德', 'Bellman-Ford'),
        'algorithm_families': ('Dijkstra', 'Floyd', 'Bellman-Ford'),
        'structures': ('图', '邻接表', '邻接矩阵', '优先队列'),
        'bank_tags': ('graph',),
        'search_terms': ('最短路径', 'Dijkstra', '图'),
    },
    'graph_topological': {
        'name': '有向图拓扑排序',
        'aliases': ('拓扑排序', '拓扑序列', '有向无环图', 'DAG'),
        'algorithm_families': ('拓扑排序',),
        'structures': ('有向图', '入度', '队列'),
        'bank_tags': ('graph',),
        'search_terms': ('拓扑排序', '有向图', '图'),
    },
    'binary_tree_traversal': {
        'name': '二叉树遍历',
        'aliases': ('二叉树遍历', '先序遍历', '前序遍历', '中序遍历', '后序遍历',
                    '层序遍历', '树的遍历'),
        'algorithm_families': ('先序遍历', '中序遍历', '后序遍历', '层序遍历'),
        'structures': ('二叉树', '栈', '队列', '递归'),
        'bank_tags': ('binary-tree', 'tree'),
        'search_terms': ('二叉树', '树的遍历'),
    },
    'binary_tree': {
        'name': '二叉树',
        'aliases': ('二叉树', '完全二叉树', '满二叉树', '二叉树结点'),
        'algorithm_families': (),
        'structures': ('二叉树', '递归'),
        'bank_tags': ('binary-tree', 'tree'),
        'search_terms': ('二叉树',),
    },
    'sorting': {
        'name': '排序算法',
        'aliases': ('排序', '排序算法', '插入排序', '选择排序', '冒泡排序', '快速排序',
                    '归并排序', '堆排序', '希尔排序'),
        'algorithm_families': ('插入排序', '选择排序', '冒泡排序', '快速排序', '归并排序'),
        'structures': ('数组',),
        'bank_tags': ('sorting',),
        'search_terms': ('排序算法', '排序'),
    },
    'searching': {
        'name': '查找算法',
        'aliases': ('查找', '查找算法', '顺序查找', '折半查找', '二分查找', '二分搜索',
                    '二叉排序树', '二叉搜索树', '哈希查找', '散列查找'),
        'algorithm_families': ('顺序查找', '二分查找', '哈希查找', '二叉排序树'),
        'structures': ('有序数组', '哈希表', '二叉搜索树'),
        'bank_tags': ('binary-search', 'hash-table', 'binary-search-tree'),
        'search_terms': ('查找算法', '二分查找', '哈希查找', '二叉排序树'),
    },
    'stack': {
        'name': '栈',
        'aliases': ('栈', '入栈', '出栈', '栈顶'),
        'algorithm_families': (),
        'structures': ('栈',),
        'bank_tags': ('stack',),
        'search_terms': ('栈',),
    },
    'queue': {
        'name': '队列',
        'aliases': ('队列', '循环队列', '入队', '出队', '队头', '队尾'),
        'algorithm_families': (),
        'structures': ('队列',),
        'bank_tags': ('queue',),
        'search_terms': ('队列',),
    },
    'linked_list': {
        'name': '链表',
        'aliases': ('链表', '单链表', '双向链表', '循环链表', '链式存储'),
        'algorithm_families': (),
        'structures': ('链表', '指针'),
        'bank_tags': ('linked-list',),
        'search_terms': ('链表',),
    },
}


def _text(spec):
    plan = spec.get('teaching_plan') or {}
    values = list(spec.get('topics') or [])
    for goal in plan.get('goals') or []:
        values += [goal.get('name', '')]
        values += list(goal.get('keywords') or [])
    values += [spec.get('request_text', '')]
    return ' '.join(str(v) for v in values if v).casefold()


def _matched(text):
    """Recognize concepts inside one scope without promoting supporting goals."""
    text = text.casefold()
    chosen = []
    for ident, concept in CONCEPTS.items():
        if any(alias.casefold() in text for alias in concept['aliases']):
            chosen.append((ident, concept))

    # A concrete algorithm carries more useful retrieval intent than its
    # chapter alias.  Keep the broad chapter only when no more specific
    # concept in the same bank was recognized (DFS/BFS should root queries at
    # 图遍历, not at the bare word 图).
    generic = {'graph', 'binary_tree'}
    if len(chosen) > 1:
        specific_tags = {tag for ident, concept in chosen if ident not in generic
                         for tag in concept['bank_tags']}
        chosen = [(ident, concept) for ident, concept in chosen
                  if ident not in generic or not set(concept['bank_tags']) & specific_tags]
    matched_aliases = {ident: [a.casefold() for a in concept['aliases']
                               if a.casefold() in text]
                       for ident, concept in chosen}
    chosen = [(ident, concept) for ident, concept in chosen
              if not any(other != ident and len(alias) < len(longer)
                         and alias in longer
                         for alias in matched_aliases[ident]
                         for other in matched_aliases
                         for longer in matched_aliases[other])]

    return chosen


def build_concept_plan(spec):
    """Teacher topics own retrieval; goals provide inspectable supporting context."""
    topics = [t.strip() for t in spec.get('topics', []) if isinstance(t, str) and t.strip()]
    primary_text = ' '.join(topics) or spec.get('request_text', '')
    chosen = _matched(primary_text)
    # Truly broad labels carry no chapter choice. In that case the existing
    # semantic goals may refine them; explicit recognized topics always win.
    if not chosen and topics and all(t in ('数据结构','搜索','算法','课程') for t in topics):
        primary_text = _text(spec)
        chosen = _matched(primary_text)
    text = primary_text.casefold()
    chosen.sort(key=lambda item: min(text.index(a.casefold()) for a in item[1]['aliases'] if a.casefold() in text))
    primary_ids = {ident for ident, _ in chosen}
    supporting = [(ident, concept) for ident, concept in _matched(_text(spec)) if ident not in primary_ids]
    def entry(ident, concept):
        return {'id': ident, 'name': concept['name'],
                'algorithm_families': list(concept['algorithm_families']),
                'structures': list(concept['structures']), 'aliases': list(concept['aliases'])}
    tags, terms = [], []
    for ident, concept in chosen:
        tags.extend(tag for tag in concept['bank_tags'] if tag not in tags)
        terms.extend(term for term in concept['search_terms'] if term not in terms)
    terms.extend(t for t in topics if t not in terms)
    return {'concepts': [entry(i, c) for i, c in chosen],
            'supporting_concepts': [entry(i, c) for i, c in supporting],
            'primary_topics': topics, 'bank_tags': tags, 'search_terms': terms[:16],
            'version': 2,
            'note': '用户主题决定检索范围；教学目标的辅助结构只作上下文，不能扩大题库标签。'}


def retrieval_concept_plan(spec):
    # Rebuild historical plans too: a continuation must not reuse a v1 plan
    # whose first concept was taken from an incidental lecture keyword.
    return build_concept_plan(spec)


def concept_matches(text, concept_plan):
    """Return concept ids with an explicit alias in candidate text."""
    text = str(text or '').casefold()
    return [c['id'] for c in concept_plan.get('concepts', [])
            if any(a.casefold() in text for a in c.get('aliases', []))]
