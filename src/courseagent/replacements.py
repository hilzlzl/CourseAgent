"""Review-time alternatives, constrained by the original plan and current selection."""
import copy
from courseagent.workflow import retrieve, refresh_plan


def alternatives(document,question_id,reason=''):
    original=next((q for q in document['questions'] if q['id']==question_id),None)
    if original is None or not original.get('selected'):
        raise ValueError('只能为当前已选题目查找备选题')
    spec=copy.deepcopy(document.get('plan',{}).get('spec') or {'topics':[],'difficulty':3,'source_ids':None,'page_start':None,'page_end':None})
    # Existing semantic recommendations define the eligible pool when present.
    eligible=document.get('plan',{}).get('eligible_ids')
    pool=retrieve({'document':document,'spec':spec,'request':{'use_model':eligible is not None,'source_mode':'web' if document.get('plan',{}).get('engine','').endswith('网络搜题与原文证据核对') else 'local'},'web':document.get('web_search',{}),'trace':[]})['candidates']
    roots={q.get('base_question_id') or q['id'] for q in document['questions'] if q.get('selected')}
    if document.get('web_search') and not document.get('plan',{}).get('engine','').endswith('网络搜题与原文证据核对'):
        extra=retrieve({'document':document,'spec':spec,'request':{'source_mode':'web'},'web':document['web_search'],'trace':[]})['candidates']
        pool=list({q['id']:q for q in pool+extra}.values())
    selected_stems={''.join(q['stem'].split()) for q in document['questions'] if q.get('selected')}
    result=[q for q in pool if q['type']==original['type'] and not q.get('selected') and (q.get('base_question_id') or q['id']) not in roots and ''.join(q['stem'].split()) not in selected_stems and (eligible is None or q['id'] in eligible)]
    from courseagent.teaching_plan import goal_matches,pattern
    goals=spec.get('teaching_plan',{}).get('goals',[])
    others=[q for q in document['questions'] if q.get('selected') and q['id']!=question_id]
    covered={g['id'] for q in others for g in goals if g['id'] in goal_matches(q,goals)}
    result.sort(key=lambda q:(q.get('score')!=original.get('score'),not q.get('approved'),q.get('source_number') or 100000,q['id']))
    if reason=='repetition':result.sort(key=lambda q:(pattern(q)==pattern(original),-sum(g not in covered for g in goal_matches(q,goals))))
    return result


def replace_question(document,old_id,new_id):
    candidate=next((q for q in alternatives(document,old_id) if q['id']==new_id),None)
    if candidate is None:raise ValueError('备选题已不符合条件，请重新查看备选题')
    result=copy.deepcopy(document)
    for q in result['questions']:
        if q['id']==old_id:q['selected']=False
        if q['id']==new_id:
            q['selected']=True;q['approved']=False;q.pop('approval_snapshot',None)
            q['selection_reason']='教师手动替换；符合当前题型、资料与知识范围，请重新审核答案和分值。'
    if result.get('plan'):
        plan=result['plan'];selected=[q for q in result['questions'] if q.get('selected')]
        refresh_plan(result)
        plan['trace']=plan.get('trace',[])+['教师替换了一道题，替换题等待重新审核。']
    return result


REASONS={'repetition':'重复考点，优先不同考点与不同解题方式','topic':'超出教学范围，严格贴合原作业知识范围','answer':'答案有疑问，优先答案证据完整且条件明确的题','conditions':'条件不完整，优先不依赖缺失图片或省略条件的题'}


def search_replacements(document,question_id,reason,sources):
    if reason not in REASONS:raise ValueError('请选择有效换题原因')
    original=next((q for q in document['questions'] if q['id']==question_id and q.get('selected')),None)
    if original is None:raise ValueError('只能为已选题查找新备选')
    p=document.get('plan',{});spec=p.get('spec',{})
    if not p.get('request') or not spec.get('counts'):raise ValueError('请先组卷，再按原因搜索备选题')
    work=copy.deepcopy(document)
    for q in work['questions']:
        if q['id']==question_id:q['selected']=False
    # A local-file plan can start a web candidate pool without changing the saved exam.
    work.setdefault('web_search',{'candidate_ids':[],'pages':[],'attempted_urls':[]})
    request={'prompt':p['request'],'topics':'、'.join(spec.get('topics',[])),'counts':spec['counts'],
             'source_mode':'web','continue_web':True,'use_model':False,'allow_adaptation':True,
             'locked_ids':[q['id'] for q in work['questions'] if q.get('selected')],
             'avoid_ids':[original.get('base_question_id') or original['id']],
             'replacement_context':{'old_question':original['stem'],'reason':REASONS[reason]},
             'source_ids':spec.get('source_ids'),'page_start':spec.get('page_start'),'page_end':spec.get('page_end'),
             'teaching_goals':[{'name':g['name'],'keywords':g['keywords']} for g in spec.get('teaching_plan',{}).get('goals',[])] or None}
    # Local locked questions are valid but must be explicitly included in the web pool.
    work['web_search']['candidate_ids']=list(dict.fromkeys(work['web_search'].get('candidate_ids',[])+request['locked_ids']))
    from courseagent.workflow import plan
    draft=plan(work,request,sources)
    result=copy.deepcopy(document);existing={q['id'] for q in result['questions']}
    for q in draft['questions']:
        if q['id'] not in existing:
            q=copy.deepcopy(q);q['selected']=False;q['approved']=False;q.pop('approval_snapshot',None);result['questions'].append(q)
    result['web_search']=draft['web_search']
    result['plan']['eligible_ids']=list(dict.fromkeys((p.get('eligible_ids') or [])+draft['plan']['eligible_ids']))
    pool=alternatives(result,question_id,reason)
    return {'document':result,'questions':pool[:10],'reason':REASONS[reason],
            'note':'找到备选，请查看后决定是否替换。' if pool else '本批未找到符合条件的备选，原题与审核进度保持不变。'}
