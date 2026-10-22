"""Translate existing course goals into discovery terms, never question eligibility."""


def distinct_topics(topics):
    from courseagent.selection_policy import normalized_topic
    result=[];seen=set()
    for topic in topics:
        key=normalized_topic(topic)
        if key not in seen:result.append(topic);seen.add(key)
    return result


def retrieval_topics(spec):
    from courseagent.algorithm_sources import TAGS
    if not spec.get('teaching_plan', {}).get('concept_plan'):
        topics = spec.get('topics', [])
        supported = [t for t in topics if t in TAGS]
        if supported and not any(t in ('查找','查找算法') for t in supported):
            return distinct_topics(t for t in topics if t not in ('数据结构','搜索','算法','课程'))
        if topics and all(t in ('数据结构','搜索','算法','课程') for t in topics):
            words = [k for g in spec.get('teaching_plan', {}).get('goals', []) for k in g.get('keywords', []) if k in TAGS]
            if words:
                return list(dict.fromkeys(words))[:8]
    plan = retrieval_plan(spec)
    return distinct_topics(plan.get('search_terms', []) or spec.get('topics', []))[:16]


def retrieval_plan(spec):
    """Reconcile saved plans with authoritative teacher topics on continuation."""
    from courseagent.course_concepts import retrieval_concept_plan
    return retrieval_concept_plan(spec)


def bank_query_schedule(topics, batch=0, suggested=()):
    from courseagent.source_policy import bank_queries
    # Rotate both focus and wording, with a finite frontier. A caller filters
    # task-wide history before taking the next bounded batch.
    queries=[]
    for offset in range(max(1,len(topics))):
        focus=topics[offset:]+topics[:offset]
        for style in range(3):
            queries.extend(bank_queries(focus,(batch+style)%3,suggested if not queries else ()))
    return list(dict.fromkeys(queries))
