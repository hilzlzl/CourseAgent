"""Optional batched adaptation, with independent checking and explicit derived provenance."""
import copy
import hashlib
import json
import re
from courseagent.questions import validate_question, review_content

PROMPT='''根据教师要求，将给定网络原题改编成指定题型。严格遵循assignments中的base_id与target_type分配，不改变任务题型，不用同一原题替代多个任务。条件、数字和遍历序列必须来自该base_id的原题，不准借用别的original或reserved_questions中的条件。将填空题改为应用题时，保留条件，删除空格，明确要求计算和推导过程。只使用提供的base_id，不凭空引入新知识或新数据，不改变课程范围，不把改编当网络原题。优先使用已有题型不足时的缺口；应用题需要说明/推导/计算过程，不能只改标签或留一个空；算法设计题需要设计完整算法。先分配来源：为每种缺口分配不同且未保留的原题，再逐题改编，所有题型合计每个原题最多一个改编版本。多出的判断题也能改成说明理由的应用题，填空题可以改成计算推导应用题，但要明确要求解题过程。避开reserved_ids中已可用所需题型的原题。同一份作业不同题目不能互相泄露答案。返回questions数组，每项base_id,type,stem,options,answer,blanks,reference_answer,explanation,change_reason。单选只有一个正确选项，判断答案为正确/错误，填空有____及对应标准答案；参考答案与解析可以推导但要完整自洽。应用题的reference_answer必须逐步写出推导过程，不能只写最终结果，不能把过程只放explanation。不要推测缺失图示。概念解释必须准确，尤其“树的度”为结点度的最大值，度为2的普通树也允许度为1的结点，不可误写成所有结点都恰有两个或零个孩子，也不可等同于严格二叉树。最多15题，不足则如实返回更少。'''
ADAPTATION_POLICY_VERSION = 'adaptation-v13'

CHECK='''独立检查每道改编题与原题的课程范围、条件、选项、答案和推导，不以原题答案绝对正确为前提。同时检查当前改编题与reserved_questions或其他改编题之间是否直接泄露答案，直接泄露则fail。检查是否只修改type字段而没有把题干改成相应作答形式、引用缺失图示、混淆判断/填空/应用题、答案不唯一或计算错误。允许将未入选的单选原题改写成完整的判断陈述，或把原题结论改成填空；不要求增加新条件、数据、难度或分析过程。合法题型转换本身不是拒收理由。仅当原题或等价题已在reserved_questions中，才按实际重复或题间答案泄露判断。应用题需实际要求分析过程；算法设计题需设计算法。返回checks数组，每项id,verdict（pass/fail/uncertain）,reason。只有能明确检查正确且范围一致才pass；特别核对定义：树的度是结点度的最大值；度为2的普通树可以有度为1的结点，不等于严格二叉树。若答案声称每个结点必须有两个或零个孩子，则fail。不要修改或补题。'''

PROMPT += '\n题型编号必须明确遵守：1单选、2多选、3判断、4填空、5简答/应用。target_type=4必须在stem中出现____且blanks为对应答案数组，answer和reference_answer为空；不准改为说明理由/简答/判断。示例：知识原文“外部排序需访问外存”，填空stem“外部排序通常需要访问____。”、blanks=[“外存”]。target_type=3只要求判断正误，理由写在explanation，不要求学生额外书写理由。\noriginals中basis=web_knowledge的内容是知识原文，不是现成题目。允许以其事实、完整条件和结论出指定题型的新题。答案必须被该段证据支持，不补充未经证实的事实或数值；与reserved_questions重复或直接泄露答案的考点不要使用。出题依据必须体现于change_reason。依据知识出题也必须逐题完成独立复核。填空题的题干或已给解释不能直接包含所问答案，不能先说属于平方阶再让学生填平方；不要在题干写‘根据给定知识’但不提供实际必要条件。'

def local_application(parent):
    """Exact integer derivations for two unambiguous complete-binary-tree questions."""
    stem=re.sub(r'\s+','',parent['stem'])
    # Count must describe the whole tree, never the population of one layer.
    count=re.search(r'(?:有|具有|含有)(\d+)个结点的完全二叉树',stem)
    if not count:
        count=re.search(r'完全二叉树(?:中|共|一共)?(?:有|具有|含有)(\d+)个结点',stem)
    if not count or '完全二叉树' not in stem:return None
    n=int(count[1])
    if not 1<=n<=1000000:return None
    layer=re.search(r'第(\d+)层',stem)
    if '叶' in stem:
        value=(n+1)//2
        question=re.sub(r'_{3,}','多少',parent['stem']).rstrip('。')+'？请写出推导过程。'
        answer=f'叶子结点数为{value}。完全二叉树按层序从1开始编号，编号为i的结点有左孩子的条件是2i≤n。因此编号1到⌊n/2⌋的结点是非叶子，其余结点为叶子。代入n={n}，非叶子结点有{n//2}个，叶子结点数为{n}-{n//2}={value}。'
    elif layer and '根结点在第1层' in stem:
        k=int(layer[1])
        # The first layer mentioned is the root definition; use the requested last layer.
        layers=re.findall(r'第(\d+)层',stem);k=int(layers[-1])
        if not 1<=k<=30:return None
        capacity=2**(k-1);before=capacity-1;value=max(0,min(capacity,n-before))
        question=re.sub(r'_{3,}','多少',parent['stem']).rstrip('。')+'？请写出推导过程。'
        answer=f'第{k}层有{value}个结点。完全二叉树按层序从左到右依次填充，前{k-1}层最多容纳2^{k-1}-1={before}个结点，第{k}层最多容纳2^({k}-1)={capacity}个结点。剩余结点数为max(0,{n}-{before})={max(0,n-before)}，其中至多{capacity}个放在第{k}层，其余放入更深层。因此第{k}层结点数为min({capacity},max(0,{n}-{before}))={value}。'
    else:return None
    return {'base_id':parent['id'],'type':5,'stem':question,'options':[],'answer':'','blanks':[],'reference_answer':answer,'explanation':'使用完全二叉树层序编号性质进行本地整数计算。','change_reason':'保留原题数字及知识点，将填空改为要求解释推导过程的应用题。','local_derivation':True}

def adaptation_sources(state):
    """Reserve the actual assembled originals/variants, not raw counts by type."""
    from courseagent.workflow import retrieve, pick_candidates
    valid = retrieve(state)['candidates']
    picked, _ = pick_candidates(state, valid)
    reserved = {q.get('base_question_id') or q['id'] for q in picked}
    wanted = state['spec']['counts']
    missing = {t: max(0, n-sum(q['type'] == int(t) for q in picked)) for t,n in wanted.items()}
    tried = {(a['base_id'], a['target_type']) for a in state['web'].get('adaptation_attempts', [])
             if a.get('status')!='deferred' and (a.get('status')!='rejected'
                 or a.get('policy_version')==ADAPTATION_POLICY_VERSION)}
    base = [q for q in valid if q.get('origin') == 'web'] + state['web'].get('knowledge_sources', [])
    return valid, picked, reserved, {t:n for t,n in missing.items() if n}, base, tried


def has_unused_sources(state):
    _, _, reserved, missing, base, tried = adaptation_sources(state)
    return any((q.get('base_question_id') or q['id']) not in reserved and (q['id'],int(t)) not in tried for t in missing for q in base)


def candidate_from_item(item, parent, typ, local=False):
    if not isinstance(item, dict) or item.get('base_id') != parent['id'] or item.get('type') != typ:
        raise ValueError('改编未遵循固定来源与题型分配')
    stem=item.get('stem','')
    if not isinstance(stem,str) or len(stem.strip())<8: raise ValueError('改编题干不完整')
    if typ==5 and (re.search(r'_{3,}',stem) or not re.search(r'说明|解释|分析|证明|推导|计算|求出|设计|算法|过程',stem)):
        raise ValueError('应用题必须实际要求解答过程，不能只重标填空题')
    condition_stem=re.sub(r'[（(]\s*\d+\s*[）)]','',stem)
    original_text=parent['stem']+' '+' '.join(parent.get('options',[]))
    number_evidence=original_text
    if typ==3:
        # A fill answer becomes a claim in a judgment statement. Its result is
        # not a new input condition; the independent checker still verifies it.
        number_evidence+=' '+parent.get('answer','')+' '+' '.join(parent.get('blanks',[]))+' '+parent.get('reference_answer','')
    if any(value not in re.findall(r'\d+',number_evidence) for value in re.findall(r'\d+',condition_stem)):
        raise ValueError('改编引入了原题没有的数字条件')
    if any(value not in original_text for value in re.findall(r'[A-Z]{3,}',stem)):
        raise ValueError('改编引入了原题没有的遍历序列')
    item=copy.deepcopy(item)
    if typ==3:
        from courseagent.web_questions import judgment_value
        item['answer']=judgment_value(item.get('answer')) or item.get('answer','')
    if typ==4:
        stem=re.sub(r'_{1,}', '____', stem)
        item['stem']=stem
    if typ==4 and parent.get('origin')=='web_knowledge':
        from courseagent.web_questions import norm
        if any(isinstance(v,str) and len(norm(v))>=2 and norm(v) in norm(stem) for v in item.get('blanks',[])):
            raise ValueError('题干直接给出了待填的答案，请移除泄露答案的表述')
    content={k:item.get(k,[] if k in ('options','blanks') else '') for k in ('stem','options','answer','blanks','reference_answer','explanation')}
    q={'id':'adapt-'+hashlib.sha256(json.dumps({'base':parent['id'],'type':typ,**content},ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:24],
       'type':typ,**content,'source':parent.get('source','网络来源'),'origin':'web_adapted','base_question_id':parent.get('base_question_id') or parent['id'],
       'adaptation_basis':'web_knowledge' if parent.get('origin')=='web_knowledge' else 'web_question',
       'rubric':'','knowledge':parent.get('knowledge',''),'score':10 if typ==5 else 2,'estimated_minutes':15 if typ==5 else 2,
       'teacher_difficulty':0,'selected':False,'approved':False,
       'selection_reason':('依据网页知识内容出题：' if parent.get('origin')=='web_knowledge' else '根据网络原题改编：')+str(item.get('change_reason',''))[:600],
       'warning':'改编题：答案由本地整数计算规则推导，仍需教师独立审核。' if local else '依据网页知识内容出题：答案由模型推导，经过复核仍需教师独立审核。' if parent.get('origin')=='web_knowledge' else '模型改编题，答案为推导结果；经过模型复核仍需教师独立审核。',
       'source_refs':[{**r,'method':'web_knowledge_drafted' if parent.get('origin')=='web_knowledge' else 'web_adapted','answer_status':'rule_derived' if local else 'model_derived',
           'original_question':{'id':parent['id'],**review_content(parent)},'adaptation_reason':str(item.get('change_reason',''))[:800]} for r in parent.get('source_refs',[])]}
    validate_question(q)
    if typ==5 and len(q['reference_answer'].strip())<25: raise ValueError('应用题参考答案缺少推导或说明过程')
    if '度为2的树' in q['reference_answer'] and re.search(r'恰好有两个或零个|每个结点.{0,10}两个或零个',q['reference_answer']):
        raise ValueError('改编答案混淆树的最大度与严格二叉树定义')
    if not q['source_refs']: raise ValueError('原题缺少可追溯来源')
    if local: q['local_derivation']=True
    return q


def adapt_questions(state):
    if state['request'].get('source_mode')!='web' or not state['request'].get('allow_adaptation'): return {}
    if state.get('web',{}).get('adaptation_failure',{}).get('stage') in ('extract','answers','research'):return {}
    from courseagent.model_client import model_status
    from courseagent.web_budget import LIMITS, model_cached
    from courseagent.knowledge_tags import annotate
    web=copy.deepcopy(state['web']);doc=copy.deepcopy(state['document'])
    web.pop('adaptation_failure',None)
    web.pop('resume_adaptation',None)
    # Reuse actual eligible material before another network round. Assignment
    # size does not determine whether that material can fill the current gap.
    if web.get('adaptation_rounds',0)>=LIMITS['adaptation_rounds']: return {}
    valid, picked, reserved, missing, base, tried=adaptation_sources(state)
    if not missing or not base: return {'web':web}
    normalized={q['id']:q for q in valid}
    doc['questions']=[copy.deepcopy(normalized.get(q['id'],q)) for q in doc['questions']]
    available=[q for q in base if (q.get('base_question_id') or q['id']) not in reserved]
    allow_local=state['spec'].get('short_answer_kind')!='algorithm_design'
    assignments=[]
    # Reserve capacity for every missing type before a second source goes to
    # the first type. Small mixed batches isolate provider failures.
    turns=[]
    for index in range(max(missing.values(),default=0)):
        turns.extend((t,1) for t,n in sorted(missing.items()) if n>index)
    for t,n in turns:
        available.sort(key=lambda q:(0 if t=='5' and allow_local and local_application(q) else 1,
            (0 if q['type']==4 else 1 if q['type'] in (1,5) else 2) if t=='5' else q['type'] not in (1,2,4),q['id']))
        suitable=[q for q in available if (q['id'],int(t)) not in tried]
        deferred={a['base_id'] for a in web.get('adaptation_attempts',[])
                  if a.get('status')=='deferred' and a['target_type']==int(t)}
        suitable.sort(key=lambda q:q['id'] not in deferred)
        from courseagent.teaching_plan import goal_matches, pattern
        goals=state['spec'].get('teaching_plan',{}).get('goals',[])
        chosen_sources=list(picked)
        for previous in assignments:
            chosen_sources.extend(q for q in base if q['id']==previous['base_id'])
        for _ in range(min(n,4-len(assignments))):
            if not suitable: break
            if goals:
                covered={g['id']:sum(g['id'] in goal_matches(q,goals) for q in chosen_sources) for g in goals}
                used_patterns={pattern(q) for q in chosen_sources}
                suitable.sort(key=lambda q:(pattern(q) in used_patterns,
                    -sum(covered[g['id']]==0 for g in goals if g['id'] in goal_matches(q,goals))))
            parent=suitable.pop(0)
            assignments.append({'base_id':parent['id'],'target_type':int(t)})
            chosen_sources.append(parent)
            available.remove(parent)
        if len(assignments)>=4: break
    if not assignments: return {'web':web}
    web['adaptation_rounds']=web.get('adaptation_rounds',0)+1
    by_id={q['id']:q for q in base};existing={q['id']:q for q in doc['questions']}
    attempts=[];local_items=[];pending=[];generated={};reasons={};operational={}
    for a in assignments:
        from courseagent.verification_state import digest
        parent_basis=digest(review_content(by_id[a['base_id']]))
        saved=next((r.get('candidate') for r in reversed(web.get('adaptation_attempts',[]))
                    if r.get('status')=='deferred' and r['base_id']==a['base_id']
                    and r['target_type']==a['target_type'] and r.get('parent_basis')==parent_basis),None)
        record={**a,'round':web['adaptation_rounds'],'status':'pending','parent_basis':parent_basis,
                'policy_version':ADAPTATION_POLICY_VERSION}
        web.setdefault('adaptation_attempts',[]).append(record);attempts.append(record)
        if saved:
            validate_question(saved)
            generated[a['base_id']]=copy.deepcopy(saved)
            continue
        item=local_application(by_id[a['base_id']]) if a['target_type']==5 and allow_local and by_id[a['base_id']].get('origin')!='web_knowledge' else None
        if item: local_items.append(item)
        else: pending.append(a)
    model=model_status()['model']
    def call(kind,prompt,data):
        from courseagent.verification_state import failure_info
        key=json.dumps({'version':ADAPTATION_POLICY_VERSION,'model':model,'prompt':prompt,'data':data},ensure_ascii=False,sort_keys=True)
        for attempt in range(2):
            try:return model_cached(web,kind,key,prompt,data)
            except (ValueError,RuntimeError,TimeoutError,ConnectionError) as error:
                if attempt or failure_info(error)['code'] not in ('transport','format','output_limit'):raise
                web.setdefault('events',[]).append({'status':'adaptation_request_retry','stage':kind,
                    'reason':'接口响应暂未完成，重试当前请求，不重新搜索或丢弃素材。',
                    'failure':failure_info(error)})
    def payload(tasks):
        # The model sees only the assigned sources, eliminating unrelated IDs/data.
        return {'type_schema':{'1':'单选','2':'多选','3':'判断','4':'填空，stem含____，blanks数组，禁止写简答或判断','5':'简答/应用'},'assignments':tasks,'spec':state['spec'],'request':state['request'].get('prompt',''),
                'replacement_context':state['request'].get('replacement_context'),
                'reserved_questions':[review_content(q) for q in picked],
                'originals':[{'id':by_id[a['base_id']]['id'],'basis':by_id[a['base_id']].get('origin'),**review_content(by_id[a['base_id']])} for a in tasks]}
    def receive(answer,tasks):
        items=answer.get('questions',[]) if isinstance(answer,dict) else None
        if not isinstance(items,list): items=[]
        for a in tasks:
            key=a['base_id'];matches=[i for i in items if isinstance(i,dict) and i.get('base_id')==key and i.get('type')==a['target_type']]
            try:
                if len(matches)!=1: raise ValueError('未返回指定来源和题型的唯一改编结果')
                if a['target_type']==5 and state['spec'].get('short_answer_kind')=='algorithm_design' and not re.search(r'算法|伪代码|编写|实现',str(matches[0].get('stem',''))):
                    raise ValueError('算法设计要求不能用计算或概念解释题代替')
                generated[key]=candidate_from_item(matches[0],by_id[key],a['target_type'])
            except (ValueError,TypeError,AttributeError) as e: reasons[key]=str(e)[:300]
    for item in local_items:
        try: generated[item['base_id']]=candidate_from_item(item,by_id[item['base_id']],5,local=True)
        except (ValueError,TypeError,AttributeError) as e: reasons[item['base_id']]=str(e)[:300]
    if pending:
        try:
            receive(call('adapt',PROMPT,payload(pending)),pending)
            repair=[a for a in pending if a['base_id'] not in generated]
            # One format/condition correction per assignment; content-check failures
            # are never repeatedly sent back to the same original in later rounds.
            from courseagent.web_budget import call_limit
            if repair and web.get('model_calls',0)<call_limit(web)-1:
                data={**payload(repair),'correction_reasons':{a['base_id']:reasons.get(a['base_id'],'缺少结果') for a in repair}}
                receive(call('adapt-repair',PROMPT+'上次输出未通过格式或条件检查，请按correction_reasons纠正。仅返回assignments中的任务。',data),repair)
        except (ValueError,RuntimeError,TimeoutError,ConnectionError) as e:
            for a in pending:
                if a['base_id'] not in generated:
                    reasons[a['base_id']]=str(e)[:300];operational[a['base_id']]=e
    model_generated=[q for q in generated.values() if not q.get('local_derivation')]
    verdicts={}
    if model_generated:
        try:
            checked=call('adapt-check',CHECK,{'spec':state['spec'],
                'reserved_questions':[review_content(q) for q in picked]+[review_content(q) for q in generated.values() if q.get('local_derivation')],
                'questions':[{'id':q['id'],'original':review_content(by_id[next(k for k,v in generated.items() if v['id']==q['id'])]),'adapted':review_content(q)} for q in model_generated]})
            for c in checked.get('checks',[]):
                if isinstance(c,dict) and isinstance(c.get('id'),str): verdicts.setdefault(c['id'],[]).append(c)
        except (ValueError,RuntimeError,TimeoutError,ConnectionError) as e:
            for key,q in generated.items():
                if not q.get('local_derivation'):
                    reasons[key]='复核未完成：'+str(e)[:200];operational[key]=e
    for record in attempts:
        key=record['base_id'];q=generated.get(key)
        entries=verdicts.get(q['id'],[]) if q else []
        if q and q.get('local_derivation'):
            entries=[{'verdict':'pass','reason':'按完全二叉树层序编号性质进行本地整数计算，仍需教师核对适用条件。'}]
        if q and len(entries)==1 and entries[0].get('verdict')=='pass':
            if q['id'] not in existing:
                q['source_refs'][0]['adaptation_check']={'verdict':'pass','reason':str(entries[0].get('reason',''))[:1000]}
                doc['questions'].append(q);existing[q['id']]=q
            web.setdefault('candidate_ids',[]).append(q['id'])
            record.update(status='accepted',question_id=q['id'])
        elif key in operational:
            from courseagent.verification_state import failure_info
            failure=failure_info(operational[key])
            record.update(status='deferred',reason=reasons[key],failure=failure)
            if q:record['candidate']=copy.deepcopy(q)
            web['adaptation_failure']={'code':failure['code'],'action':'pause','retryable':failure['retryable']}
            web.setdefault('events',[]).append({'status':'adaptation_deferred','base_id':key,
                'reason':'模型请求未完成；保留来源与已生成内容，未判定题目不合格。','failure':failure})
        else:
            reason=reasons.get(key) or (str(entries[0].get('reason','复核未明确通过')) if len(entries)==1 else '复核结论缺失或重复')
            record.update(status='rejected',reason=reason)
            web.setdefault('events',[]).append({'status':'adaptation_rejected','base_id':key,'title':by_id[key]['stem'][:100],'reason':reason,'round':web['adaptation_rounds']})
    web['candidate_ids']=list(dict.fromkeys(web.get('candidate_ids',[])))
    web['adaptation_count']=sum(q.get('origin')=='web_adapted' and q['id'] in web['candidate_ids'] for q in doc['questions'])
    web['candidate_count']=len(web['candidate_ids'])
    if state['request'].get('reuse_retrieval'):
        try:
            from courseagent.retrieval_runtime import remember_document
            remember_document(doc)
        except (OSError,RuntimeError,ValueError) as error:web.setdefault('events',[]).append({'status':'index_failed','reason':type(error).__name__})
    return {'web':web,'document':annotate(doc),'trace':state['trace']+[f"第{web['adaptation_rounds']}轮按缺口改编：通过{sum(a['status']=='accepted' for a in attempts)}道，内容未通过{sum(a['status']=='rejected' for a in attempts)}道，请求未完成{sum(a['status']=='deferred' for a in attempts)}道；请求失败保留阶段成果，不触发换题搜索。"]}
