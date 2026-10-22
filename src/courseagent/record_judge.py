"""Declarative multi-field sorting oracle. Only string/int columns and sort keys.
No expressions, imports or source code are accepted or executed.
"""
import random,re
from functools import cmp_to_key
FORMAT='record_sort_v1'

def contract(c):
 if not isinstance(c,dict) or c.get('format')!=FORMAT:raise ValueError('记录排序契约格式不正确')
 fields=c.get('fields');order=c.get('order');limit=c.get('max_records',100)
 if not isinstance(fields,list) or not 1<=len(fields)<=8:raise ValueError('字段数量不正确')
 if type(limit) is not int or not 2<=limit<=1000:raise ValueError('记录规模不正确')
 names=set()
 for f in fields:
  if not isinstance(f,dict) or not re.fullmatch(r'[\w]{1,16}',f.get('name','')) or f['name'] in names or f.get('type') not in ('int','string'):raise ValueError('记录字段不正确')
  names.add(f['name'])
  if f['type']=='int' and (type(f.get('min')) is not int or type(f.get('max')) is not int or not -(2**31)<=f['min']<f['max']<2**31):raise ValueError('记录整数范围不正确')
 if not isinstance(order,list) or not order or len(order)>len(fields):raise ValueError('排序优先级不正确')
 seen=set()
 for key in order:
  if not isinstance(key,dict) or type(key.get('field')) is not int or not 0<=key['field']<len(fields) or key['field'] in seen or key.get('direction') not in ('asc','desc'):raise ValueError('排序键不正确')
  seen.add(key['field'])
 return c

def statement(c):
 contract(c)
 fields=c['fields'];labels='、'.join(f['name'] for f in fields)
 keys='，再'.join('按'+fields[k['field']]['name']+('升序' if k['direction']=='asc' else '降序') for k in c['order'])
 rules='；'.join(f['name']+('仅由ASCII英文字母组成（区分大小写，按ASCII字典序）' if f['type']=='string' else f"为{f['min']}至{f['max']}的整数") for f in fields)
 return f"给定n条记录，每条依次包含：{labels}。{keys}。所有排序键相同时保留原输入顺序。\n\n输入格式：\n第一行整数n；随后n行，每行{len(fields)}个空格分隔字段，顺序为{labels}。\n\n输出格式：\n按排序结果输出n行，每行按原字段顺序用单个空格分隔，不输出列表括号、逗号或引号。\n\n数据范围与约束：\n1 <= n <= {c.get('max_records',100)}；{rules}。"

def parse(text,c):
 contract(c);lines=text.strip().splitlines()
 if not lines or not re.fullmatch(r'\d+',lines[0].strip()):raise ValueError('记录输入第一行必须是n')
 n=int(lines[0]);fields=c['fields']
 if not 1<=n<=c.get('max_records',100) or len(lines)!=n+1:raise ValueError('记录数量与n不一致')
 rows=[]
 for line in lines[1:]:
  tokens=line.split()
  if len(tokens)!=len(fields):raise ValueError('记录字段数量不一致')
  values=[]
  for token,f in zip(tokens,fields):
   if f['type']=='string':
    if not re.fullmatch(r'[A-Za-z]{1,32}',token):raise ValueError('记录字符串必须是ASCII字母')
    value=token
   else:
    if not re.fullmatch(r'-?\d+',token):raise ValueError('记录整数格式不正确')
    value=int(token)
    if not f['min']<=value<=f['max']:raise ValueError('记录整数超出约束')
   values.append(value)
  rows.append(values)
 return rows

def expected_output(text,c):
 rows=parse(text,c)
 def compare(a,b):
  for k in c['order']:
   i=k['field'];sign=1 if k['direction']=='asc' else -1
   if a[i]!=b[i]:return sign*((a[i]>b[i])-(a[i]<b[i]))
  return 0
 rows=sorted(rows,key=cmp_to_key(compare))
 return '\n'.join(' '.join(map(str,row)) for row in rows)+'\n'

def apply_contract(q,c):
 import copy
 contract(c);q['judge_contract']=copy.deepcopy(c);q['description']=statement(c)
 r=random.Random(67);fields=c['fields'];limit=c.get('max_records',100)
 def row(index):return [('Ab' if index%3==0 else 'a' if index%3==1 else 'Z') if f['type']=='string' else f['min']+(index*7+j)%min(11,f['max']-f['min']+1) for j,f in enumerate(fields)]
 fixtures=[([row(0)],'单条记录'),([row(i) for i in (4,2,3,1)],'普通排序与不同主键'),([row(i) for i in (3,0,6)],'主键相同，核对次级键'),
           ([row(1),row(1),row(2)],'重复记录'),([row(i) for i in range(8)],'多级排序'),
           ([[('A' if i%2 else 'z') if f['type']=='string' else (f['min'] if i%2 else f['max']) for f in fields] for i in range(2)],'大小写及整数边界'),
           ([row(i) for i in range(limit)],'最大记录数量')]
 cases=[];seen=set()
 for rows,purpose in fixtures:
  r.shuffle(rows);text=str(len(rows))+'\n'+'\n'.join(' '.join(map(str,row)) for row in rows)+'\n'
  if text in seen:continue
  seen.add(text);cases.append({'input':text,'output':expected_output(text,c),'purpose':purpose,'output_basis':'本地声明式多字段排序算法重新计算',
   'verification_method':FORMAT,'verified':False,'visibility':'public' if len(cases)<2 else 'hidden','excel_selected':len(cases)<4})
 q['test_cases']=cases;q['public_examples']=[{'input':x['input'],'output':x['output']} for x in cases if x['visibility']=='public']
 q['reference_code']='';q['explanation']='';q['approved']=False;q.pop('approval_snapshot',None)
 q['languages']=[{**l,'starter_code':''} for l in q['languages']]
 return q

def validate_contract(q):
 c=contract(q['judge_contract'])
 if q['description']!=statement(c):raise ValueError('题面偏离记录排序契约')
 for case in q.get('test_cases',[])+q.get('public_examples',[]):
  if case.get('output','').strip()!=expected_output(case.get('input',''),c).strip():raise ValueError('记录排序预期输出错误')
