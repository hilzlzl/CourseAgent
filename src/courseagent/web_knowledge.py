"""Verbatim web facts are drafting material, not source-original questions."""
import hashlib
import re
from courseagent.web_questions import norm


def extract_seeds(items, pages, spec, web):
    if not isinstance(items,list):return
    existing={q['id']:q for q in web.get('knowledge_sources',[])}
    for item in items[:16]:
        try:
            if not isinstance(item,dict):raise ValueError('知识素材格式错误')
            index=item.get('page_index');evidence=item.get('evidence');knowledge=item.get('knowledge','')
            if type(index)!=int or not 0<=index<len(pages):raise ValueError('知识素材来源页编号错误')
            page=pages[index]
            if not isinstance(evidence,str) or not 30<=len(norm(evidence))<=1800 or norm(evidence) not in norm(page['text']):raise ValueError('知识素材证据无法逐字定位或长度不合适')
            if re.search(r'_{2,}|[（(]\s*[）)]|(?:^|\s)[A-D][.．、）)]|[？?]',evidence):
                raise ValueError('知识素材仍是未解答的题目或选项，不能当作已证实事实')
            if not isinstance(knowledge,str):raise ValueError('知识素材标签格式错误')
            words=spec.get('topics',[])+[w for g in spec.get('teaching_plan',{}).get('goals',[]) for w in g['keywords']]
            if words and not any(w in evidence for w in words):raise ValueError('知识素材缺少课程范围线索')
            ident='fact-'+hashlib.sha256(norm(evidence).encode()).hexdigest()[:24]
            existing.setdefault(ident,{'id':ident,'origin':'web_knowledge','type':5,
                'stem':evidence,'reference_answer':evidence,'answer':'','options':[],'blanks':[],
                'knowledge':knowledge[:160],'source':page['title'],'explanation':'','rubric':'','score':0,
                'source_refs':[{'url':page['url'],'title':page['title'],'retrieved_at':page['retrieved_at'],
                    'stem_evidence':evidence,'answer_evidence':evidence,'answer_status':'knowledge_evidence','method':'web_knowledge'}]})
        except (ValueError,KeyError,TypeError) as e:
            web.setdefault('events',[]).append({'status':'knowledge_rejected','reason':str(e)[:250]})
    web['knowledge_sources']=list(existing.values())
