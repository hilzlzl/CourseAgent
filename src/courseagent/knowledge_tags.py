"""Local, evidence-bearing knowledge suggestions. No model calls, no selection filters."""
import copy
import hashlib
import json
import re

DEFAULT_CATALOG = [
 {'group':'栈','name':'栈的基本操作','aliases':['栈顶','入栈','出栈','进栈','退栈']},
 {'group':'栈','name':'出入栈序列','aliases':['出栈次序','入栈序列','出栈序列','输出序列','操作序列']},
 {'group':'栈','name':'栈的应用','aliases':['表达式','括号','回文','递归']},
 {'group':'队列','name':'队列的基本操作','aliases':['队列','队头','队尾','入队','出队']},
 {'group':'队列','name':'循环队列','aliases':['循环队列','环形队列']},
 {'group':'线性表','name':'顺序存储','aliases':['顺序表','顺序存储']},
 {'group':'线性表','name':'链式存储','aliases':['链表','链式存储','链式栈','链队列']},
 {'group':'通用','name':'复杂度分析','aliases':['时间复杂度','空间复杂度','复杂度']},
]


def catalog_id(item):
 return hashlib.sha256((item['group']+'\n'+item['name']).encode()).hexdigest()[:16]


def validate_catalog(catalog):
 if not isinstance(catalog,list) or len(catalog)>100:raise ValueError('知识点表最多100条')
 result=[]
 for item in catalog:
  if not isinstance(item,dict):raise ValueError('知识点格式不正确')
  group,name,aliases=item.get('group'),item.get('name'),item.get('aliases')
  if any(not isinstance(s,str) or not s.strip() or len(s)>80 for s in [group,name]):raise ValueError('分组和知识点名称需为1–80个字符')
  if not isinstance(aliases,list) or len(aliases)>30 or any(not isinstance(a,str) or not a.strip() or len(a)>80 for a in aliases):raise ValueError('每个知识点最多30个非空关键词，每词最多80字符')
  entry={'group':group.strip(),'name':name.strip(),'aliases':list(dict.fromkeys(a.strip() for a in aliases))}
  entry['id']=catalog_id(entry);result.append(entry)
 if len({i['id'] for i in result})!=len(result):raise ValueError('同一分组的知识点名称不能重复')
 return result


def annotate(document):
 result=copy.deepcopy(document)
 catalog=validate_catalog(result.get('knowledge_catalog',DEFAULT_CATALOG));result['knowledge_catalog']=catalog
 for q in result['questions']:
  data={'stem':q.get('stem',''),'knowledge':q.get('knowledge',''),'catalog':catalog}
  basis=hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
  old=q.get('knowledge_tags',{})
  confirmed=old.get('confirmed_ids',[]) if old.get('basis')==basis else []
  reviewed=old.get('reviewed') is True and old.get('basis')==basis
  if not isinstance(confirmed,list) or any(not isinstance(i,str) or i not in {c['id'] for c in catalog} for i in confirmed):raise ValueError('教师确认的知识点不在当前知识点表中')
  suggestions=[]
  for c in catalog:
   evidence=[]
   for field,label in [('stem','题干'),('knowledge','原有知识点')]:
    text=q.get(field,'') or ''
    for alias in c['aliases']:
     match=re.search(re.escape(alias),text,re.IGNORECASE)
     if match:evidence.append({'field':field,'label':label,'keyword':alias,'excerpt':text[max(0,match.start()-12):match.end()+12]})
   if evidence:suggestions.append({'id':c['id'],'name':c['name'],'group':c['group'],'evidence':evidence})
  q['knowledge_tags']={'basis':basis,'suggestions':suggestions,'confirmed_ids':list(dict.fromkeys(confirmed)), 'reviewed':reviewed,'method':'local_rules'}
 return result


def coverage(document):
 catalog=document.get('knowledge_catalog',[]);selected=[q for q in document['questions'] if q.get('selected')]
 return [{'id':c['id'],'name':c['name'],'group':c['group'],
          'suggested':sum(any(a['id']==c['id'] for a in q.get('knowledge_tags',{}).get('suggestions',[])) for q in selected),
          'confirmed':sum(q.get('knowledge_tags',{}).get('reviewed') is True and c['id'] in q.get('knowledge_tags',{}).get('confirmed_ids',[]) for q in selected)} for c in catalog]
