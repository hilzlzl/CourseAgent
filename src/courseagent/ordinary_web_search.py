"""Question-set discovery: consume retained sources before searching again.

Search routing is bounded and deterministic. Models interpret source content;
no native question-format recognizer decides whether a page contains questions.
"""
import copy
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from urllib.parse import urlparse


def candidate_gaps(state, include_answerless=True):
    from courseagent.workflow import retrieve, pick_candidates
    from courseagent.ordinary_answers import answerless_but_complete
    from courseagent.ordinary_verification import solution_basis
    from courseagent.web_questions import semantic_question_key
    candidates = retrieve(state)['candidates']
    picked, _ = pick_candidates(state, candidates)
    counts = Counter(q['type'] for q in picked)
    seen = {semantic_question_key(q) for q in picked}
    ids = set(state.get('web', {}).get('candidate_ids', []))
    avoided = set(state['request'].get('avoid_ids', []))
    if include_answerless:
        from courseagent.semantic_duplicates import groups
        components=groups(state['document']['questions'])
        counted=list(picked)
        for q in state['document']['questions']:
            if (q['id'] not in ids or (q.get('base_question_id') or q['id']) in avoided
                    or q.get('material_answer_expected') or not answerless_but_complete(q)):
                continue
            completion=q.get('ordinary_answer_completion',{})
            if completion.get('status')=='uncertain' and completion.get('basis')==solution_basis(q):
                continue
            key = semantic_question_key(q)
            if key in seen:
                continue
            if any(components.get(q['id'],q['id'])==components.get(other['id'],other['id']) for other in counted):continue
            seen.add(key)
            counted.append(q)
            counts[q['type']] += 1
    return {str(t): max(0, n - counts[int(t)]) for t, n in state['spec']['counts'].items() if n}


def collect_question_sets(state):
    from courseagent.retrieval_tools import search_public_questions, read_public_question_page
    from courseagent.source_policy import search_page, order_links
    from courseagent.web_questions import extract_candidates
    from courseagent.model_client import TASK_BUDGET
    from courseagent.task_cancellation import check_stopped
    from courseagent.model_client import BudgetExhausted
    from courseagent.source_inventory import reusable_types

    current = copy.deepcopy(state)
    web = current['web']
    web.setdefault('read_attempts', 0)
    web['search_strategy'] = 'question_sets_v1'
    web.pop('research', None)
    if web.get('resume_adaptation') or current['request'].get('adaptation_only'):
        return {}
    if web.get('resume_extraction_pages'):
        return extract_candidates(current)
    if not any(candidate_gaps(current).values()):
        return {'web': web, 'trace': current['trace'] + ['现有候选足够，先完成答案与检查，不新增搜索。']}
    starting_gaps=candidate_gaps(current)

    # A source whose output was capped is revisited from retained raw text,
    # before either reading a different source or issuing another query.
    from courseagent.web_questions import cached_page, recover_scope_rejections
    recover_scope_rejections(web)
    for page in list(web.get('pages', [])):
        assessment = web.get('source_assessments', {}).get(page['url'], {})
        needed={t for t,n in candidate_gaps(current).items() if n}
        if not reusable_types(assessment,needed):
            continue
        raw = cached_page(page)
        if raw:
            web['pages'] = [raw if p['url'] == page['url'] else p for p in web['pages']]
            current.update(extract_candidates(current)); web = current['web']
            if web.get('adaptation_failure') or not any(candidate_gaps(current).values()):
                return {k: current[k] for k in ('document', 'web', 'trace')}

    attempted = set(web.get('skip_urls', [])) | set(web.get('attempted_urls', []))
    attempted.update(p['url'] for p in web.get('pages', []))
    discoveries = {r['url']: r for r in web.get('discovered_links', [])}
    domain_failures = web.setdefault('domain_failures', {})
    reads = 0
    acquired = 0
    max_reads = web.get('max_attempts', 8)
    # Read one source and interpret it before consuming the next read slot.
    max_pages = web.get('max_pages', 3)

    def checkpoint():
        budget = TASK_BUDGET.get()
        if budget and budget.get('on_source_checkpoint'):
            preview = copy.deepcopy(current)
            preview.pop('candidates', None)
            preview['web']['pages'] = [{k:v for k,v in p.items() if k != 'text'} for p in web.get('pages', [])]
            budget['on_source_checkpoint']('ordinary', preview)

    def consume(source_limit=None):
        nonlocal reads, acquired, web
        start_acquired=acquired
        needed={t for t,n in candidate_gaps(current).items() if n}
        from courseagent.questions import TYPE_NAMES
        labels=[('选择' if t=='1' else TYPE_NAMES[int(t)].removesuffix('题')) for t in needed]
        rows=order_links(list(discoveries.values()))
        # A previous broad-query result is a lead, not proof that it contains
        # the remaining type. Give gap-specific discoveries first use.
        gaps=candidate_gaps(current)
        def priority(row):
            text=row.get('title','')+' '+row.get('query','')
            return -max((gaps.get(t,0) for t,label in zip(needed,labels) if label in text),default=0)
        rows.sort(key=priority)
        for row in rows:
            check_stopped()
            if reads >= max_reads or acquired >= max_pages or not any(candidate_gaps(current).values()):
                break
            if source_limit is not None and acquired-start_acquired>=source_limit:
                break
            url = row['url']; host = (urlparse(url).hostname or '').lower()
            if url in attempted or search_page(url) or domain_failures.get(host, 0) >= 2:
                continue
            attempted.add(url); reads += 1
            web.setdefault('attempted_urls', []).append(url)
            web['read_attempts'] = web.get('read_attempts', 0) + 1
            try:
                result = read_public_question_page.invoke({'url': url})
                page = result['page']; web['cache_hits'] += int(result.get('cache_hit', False))
                if search_page(page['url']):
                    raise ValueError('搜索入口不是题目原文')
                if page['url'] in {p['url'] for p in web.get('pages', [])}:
                    continue
                attempted.add(page['url'])
                acquired += 1
                web.setdefault('pages', []).append({**page, 'query': row.get('query', '')})
                web['extraction_pending_pages'] = [{'url':page['url']}]
                web['events'].append({'status':'read', 'url':page['url'],
                                      'reason':'先由模型理解本页题型、原题与答案，再决定是否读取下一来源'})
                checkpoint()
            except BudgetExhausted:
                raise
            except (ValueError, RuntimeError, OSError) as error:
                domain_failures[host] = domain_failures.get(host, 0) + 1
                web['events'].append({'status':'read_failed', 'url':url, 'reason':str(error)[:300]})
                checkpoint()
                continue
            # Extraction failure is not a source access failure. Preserve it and
            # pause without opening another page or increasing domain failures.
            current.update(extract_candidates(current)); web = current['web']
            while (not web.get('adaptation_failure') and reusable_types(
                   web.get('source_assessments',{}).get(page['url'],{}),
                   {t for t,n in candidate_gaps(current).items() if n})):
                web['pages'] = [page if p['url']==page['url'] else p for p in web['pages']]
                current.update(extract_candidates(current)); web = current['web']
            domain_failures.update(web.get('domain_failures', {}))
            if web.get('adaptation_failure'):
                break

    # Teacher URLs and unconsumed discoveries get first use. Do not silently
    # seed a fresh run with topic-specific pages from previous test runs.
    for url in current['request'].get('web_urls', []):
        discoveries[url] = {'url':url, 'title':'教师指定网页', 'query':'教师指定'}
    # Do not spend the entire read quota on old broad-query results. After two
    # unsuccessful sources, allow the next gap-specific query batch to run.
    consume(source_limit=2)
    if (not web.get('adaptation_failure') and any(candidate_gaps(current).values())
            and reads < max_reads and acquired < max_pages):
        previous = set(web.get('searched_queries', []))
        query_cap=max(3,sum(n>0 for n in candidate_gaps(current).values()))
        queries = [q for q in web.get('queries', []) if q not in previous][:query_cap]
        if previous and (not queries or web.get('discovery_stagnation',0)>=2):
            from courseagent.ordinary_search_recovery import recover_queries
            recovery=recover_queries(current,before_request=checkpoint)
            if web.get('adaptation_failure'):
                checkpoint()
                return {k:current[k] for k in ('document','web','trace')}
            if recovery:
                web['discovery_stagnation']=0
                web['query_plan']=recovery
                web['queries']=list(dict.fromkeys(web.get('queries',[])+[r['query'] for r in recovery]))
                queries=[r['query'] for r in recovery]
                checkpoint()
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix='question-set-search') as pool:
            pending = [(q, pool.submit(copy_context().run, search_public_questions.invoke, {'query':q})) for q in queries]
            groups = []
            failures = 0
            for query, future in pending:
                web.setdefault('searched_queries', []).append(query)
                try:
                    result = future.result(); web['cache_hits'] += int(result.get('cache_hit', False))
                    groups.append([{**r,'query':query} for r in result['items']])
                    web['events'].append({'status':'set_search', 'query':query, 'count':len(result['items'])})
                except BudgetExhausted:
                    raise
                except (ValueError, RuntimeError, OSError) as error:
                    failures += 1
                    web['events'].append({'status':'search_failed', 'query':query, 'reason':str(error)[:300]})
            for i in range(8):
                for group in groups:
                    if i < len(group):
                        row = group[i]; discoveries.setdefault(row['url'], row)
        web['search_unavailable']=bool(queries and failures==len(queries))
        web['search_paths_exhausted']=not bool(queries)
        web['discovered_links'] = list(discoveries.values())[-120:]
        checkpoint()
        consume()
    web['domain_failures'] = domain_failures
    web['discovered_links'] = list(discoveries.values())[-120:]
    pending_links = [r for r in discoveries.values() if r['url'] not in attempted
                     and not search_page(r['url']) and domain_failures.get((urlparse(r['url']).hostname or '').lower(),0)<2]
    web['acquisition'] = {'reads':reads, 'sources_interpreted':acquired,
                          'pending_links':len(pending_links), 'candidate_gaps':candidate_gaps(current)}
    if sum(candidate_gaps(current).values())<sum(starting_gaps.values()):
        web['discovery_stagnation']=0
    elif not web.get('adaptation_failure') and not web.get('search_unavailable'):
        web['discovery_stagnation']=web.get('discovery_stagnation',0)+1
    checkpoint()
    return {k:current[k] for k in ('document','web','trace')}
