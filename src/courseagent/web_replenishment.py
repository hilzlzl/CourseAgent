"""Gap-aware LangGraph routing and bounded, non-repeating supplementary searches."""
import copy
from courseagent.web_budget import LIMITS,call_limit


def shortages(state):
    from courseagent.workflow import retrieve, pick_candidates
    picked, _ = pick_candidates(state, retrieve(state)['candidates'])
    return {t:max(0,n-sum(q['type']==int(t) for q in picked)) for t,n in state['spec']['counts'].items() if n}


def check_gaps(state):
    if state['request'].get('source_mode')!='web': return {}
    from courseagent.question_adaptation import has_unused_sources
    web=copy.deepcopy(state['web']);missing={t:n for t,n in shortages(state).items() if n}
    route='done';reason='已满足全部题型数量，等待教师审核。'
    if missing:
        from courseagent.model_client import TASK_BUDGET
        import time
        budget=TASK_BUDGET.get()
        if budget and time.monotonic()>=budget['deadline']:
            reason='任务运行时间预算已用完，保留已取得题目和具体缺口。'
        elif web.get('model_calls',0)>=call_limit(web):
            reason='已达到本轮模型调用预算；保留已通过题目和剩余缺口。'
        elif web.get('adaptation_failure'):
            reason='已有素材的模型请求未完成；保留来源及已生成改编，暂停本轮，不因接口问题重新搜题。'
        elif web.get('search_unavailable'):
            reason='本批搜索入口均未取得结果，暂停联网补搜；保留已有题目，避免换词重复访问不可用入口。'
        elif web.get('search_paths_exhausted') and not web.get('acquisition',{}).get('pending_links'):
            from courseagent.questions import TYPE_NAMES
            gaps='、'.join(TYPE_NAMES[int(t)]+'缺'+str(n)+'道' for t,n in missing.items())
            reason=('未能补齐：'+gaps+'。现有搜索词及可读来源已耗尽；已进行'
                    +str(len(web.get('query_replans',[])))+'次搜索方向自动重规划，保留已有题目和具体来源失败记录。')
        elif state['request'].get('adaptation_only'):
            reason='本次已有素材改编已结束；仍有缺口，返回Agent决定是否搜索新来源。'
        else:
            search_available=(web.get('replenishment_rounds',0)-web.get('window_start_rounds',0)<LIMITS['search_rounds']
                              and len(web.get('pages',[]))-web.get('window_start_pages',0)<LIMITS['pages']
                              and web.get('read_attempts',0)-web.get('window_start_reads',0)<LIMITS['read_attempts'])
            if (state['request'].get('allow_adaptation')
                  and web.get('adaptation_rounds',0)<LIMITS['adaptation_rounds']
                  and has_unused_sources(state)):
                route='adapt';reason='已有可用且未尝试的素材，先局部补齐缺少题型；仍有缺口再搜索。'
            elif search_available:
                route='search';reason='当前可用题不足，更换查询和网页继续搜题。'
            else:
                used = {'search_rounds':web.get('replenishment_rounds',0)-web.get('window_start_rounds',0),
                        'pages':len(web.get('pages',[]))-web.get('window_start_pages',0),
                        'read_attempts':web.get('read_attempts',0)-web.get('window_start_reads',0)}
                labels = {'search_rounds':'补搜轮数','pages':'正文页数','read_attempts':'来源读取次数'}
                hits = [labels[k]+' '+str(v)+'/'+str(LIMITS[k]) for k,v in used.items() if v>=LIMITS[k]]
                web['exhausted_counters'] = {k:{'used':v,'limit':LIMITS[k]} for k,v in used.items() if v>=LIMITS[k]}
                reason='本轮检索上限已达到：'+'、'.join(hits)+'；保留已通过题目和剩余缺口。'
    web['search_exhausted']=bool(missing and route=='done' and not web.get('adaptation_failure') and not state['request'].get('adaptation_only'))
    web['fill_report']={'missing':missing,'next':route,'reason':reason,'limits':{**LIMITS,'model_calls':call_limit(web)},
        'adaptation_rounds':web.get('adaptation_rounds',0),'search_rounds':web.get('replenishment_rounds',0),
        'exhausted_counters':web.get('exhausted_counters',{}),
        'failed_sources':sum(a.get('status')=='rejected' for a in web.get('adaptation_attempts',[]))}
    web['next_step']=route
    return {'web':web,'trace':state['trace']+[reason]}


def next_step(state):
    return state.get('web',{}).get('next_step','done') if state['request'].get('source_mode')=='web' else 'done'


def replenish(state):
    if state['request'].get('source_mode')!='web': return {}
    old=copy.deepcopy(state['web']);round_no=old.get('replenishment_rounds',0)+1
    if round_no-old.get('window_start_rounds',0)>LIMITS['search_rounds']: return {}
    from courseagent.web_questions import search_read,extract_candidates
    from courseagent.web_questions import search_topic
    topic=search_topic(state['spec']);missing={t:n for t,n in shortages(state).items() if n}
    if not missing:return {}
    # Missing types keep their own query slots on every round. Model-planned
    # terms, then uncovered goals and bounded fallback terms; never a fixed
    # generic list which forgets the actual gap.
    from courseagent.ordinary_search_plan import question_set_queries
    query_plan=question_set_queries(state['spec'],missing,old.get('searched_queries',[]),
                            state['request'].get('agent_queries',[]),round_no=round_no)
    queries=[r['query'] for r in query_plan]
    attempted=set(old.get('attempted_urls',[]))|{p['url'] for p in old.get('pages',[])}
    current=copy.deepcopy(state)
    # Checkpoints emitted during extraction must retain the previous pool too;
    # otherwise the UI and verifier temporarily see zero old selected questions.
    total_requested=sum(state['spec']['counts'].values())
    active_types=sum(n>0 for n in state['spec']['counts'].values())
    if total_requested>10:
        round_pages=min(10, max(4, active_types+(total_requested+5)//6))
        round_attempts=min(24, max(8, round_pages*3))
    else:
        round_pages=2;round_attempts=6
    current['web']={**old,'queries':queries,'query_plan':query_plan,'pages':copy.deepcopy(old.get('pages',[])),'events':copy.deepcopy(old.get('events',[])),'candidate_ids':list(old.get('candidate_ids',[])),
        'skip_urls':list(attempted),'max_pages':min(round_pages,LIMITS['pages']-len(old.get('pages',[]))+old.get('window_start_pages',0)),
        'max_attempts':min(round_attempts,LIMITS['read_attempts']-old.get('read_attempts',0)+old.get('window_start_reads',0))}
    current['request']={**current['request'],'web_urls':[]}
    from courseagent.ordinary_web_search import collect_question_sets
    current.update(collect_question_sets(current))
    new=current['web']
    new['candidate_ids']=list(dict.fromkeys(old.get('candidate_ids',[])+new.get('candidate_ids',[])))
    seeds={q['id']:q for q in old.get('knowledge_sources',[])}
    seeds.update({q['id']:q for q in new.get('knowledge_sources',[])})
    new['knowledge_sources']=list(seeds.values())
    new['queries']=list(dict.fromkeys(old.get('queries',[])+new.get('queries',[])))
    new['pages']=list({p['url']:p for p in old.get('pages',[])+new['pages']}.values())
    new['candidate_count']=len(new['candidate_ids'])
    new['attempted_urls']=list(dict.fromkeys(old.get('attempted_urls',[])+new.get('attempted_urls',[])))
    new['replenishment_rounds']=round_no
    return {'document':current['document'],'web':new,'trace':current['trace']+[f'第{round_no}轮补搜已完成，保留已有候选；下一步重新检查缺口。']}
