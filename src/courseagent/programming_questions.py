"""Review and export ONLINE EXAM programming questions. Never execute source code."""
from courseagent.paths import ROOT as WORKSPACE_ROOT
import copy
import ast
import math
import re
import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from xml.etree import ElementTree as E
from courseagent.questions import NS,export_xlsx
FIELDS=('title','description','knowledge','score','difficulty','time_limit_seconds','languages','author_username','test_cases','explanation','reference_code','source','source_refs','public_examples','judge_contract','description_includes_examples','description_format')


def review_content(q):
 # Optional metadata must not invalidate unchanged approvals from older versions.
 content={k:q.get(k) for k in FIELDS if k not in ('description_includes_examples','description_format') or k in q}
 if 'io_contract' in q:content['io_contract']=q['io_contract']
 return copy.deepcopy(content)


def normalize_document(document):
 """Allow incomplete drafts, but require unique IDs and invalidate changed approvals."""
 items=document.get('programming_questions',[])
 if not isinstance(items,list) or len(items)>2000:raise ValueError('编程题题库格式不正确或超过2000道题')
 ids={q['id'] for q in document['questions']}
 for q in items:
  if not isinstance(q,dict) or not isinstance(q.get('id'),str) or not q['id'] or q['id'] in ids:
   raise ValueError('编程题编号缺失或与已有题目重复')
  ids.add(q['id'])
  if q.get('approved'):
   try:validate_programming(q,True)
   except ValueError:q['approved']=False;q.pop('approval_snapshot',None)
 return document


def validate_case_text(case):
 for field in ('input','output'):
  text=case.get(field,'')
  if not isinstance(text,str) or len(text)>32767 or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]',text):
   raise ValueError('评测用例文字超长或包含不支持的控制字符：'+field)


def validate_programming(q,approved_only=True):
 if not isinstance(q,dict):raise ValueError('编程题格式不正确')
 for k in ('title','description'):
  if not isinstance(q.get(k),str) or not q[k].strip():raise ValueError('编程题缺少 '+k)
 score=q.get('score')
 if isinstance(score,bool) or not isinstance(score,(int,float)) or not math.isfinite(score) or score<=0:raise ValueError('编程题分值必须为正数')
 if isinstance(q.get('difficulty'),bool) or q.get('difficulty') not in ((1,2,3) if approved_only else (0,1,2,3)):raise ValueError('编程题难度需由教师标注1、2或3')
 limit=q.get('time_limit_seconds')
 if isinstance(limit,bool) or not isinstance(limit,int) or limit<=0:raise ValueError('编程题运行时限必须为正整数秒')
 languages=q.get('languages')
 if not isinstance(languages,list) or not 1<=len(languages)<=4:raise ValueError('模板支持1至4组语言与初始代码')
 seen=set()
 for item in languages:
  if not isinstance(item,dict) or item.get('language') not in ('C语言','C','C++','Python','Java','JavaScript','Ruby'):raise ValueError('编程语言尚未适配')
  if item['language'] in seen:raise ValueError('编程语言不能重复')
  seen.add(item['language'])
  if not isinstance(item.get('starter_code'),str):raise ValueError('需要初始代码字段，可由教师明确留空')
 cases=q.get('test_cases')
 if not isinstance(cases,list) or not 1<=len(cases)<=1000:raise ValueError('请提供1至1000组评测用例')
 for c in cases:
  if not isinstance(c,dict) or not isinstance(c.get('input',''),str) or not isinstance(c.get('output'),str) or not c['output']:raise ValueError('测试用例输入必须是文字，输出不能为空')
 seen_inputs={}
 for i,c in enumerate(cases,1):
  for field in ('purpose','output_basis'):
   if field in c and not isinstance(c[field],str):raise ValueError('测试用例说明必须为文字')
  if 'verified' in c and type(c['verified']) is not bool:raise ValueError('用例确认状态必须为布尔值')
  if 'excel_selected' in c and type(c['excel_selected']) is not bool:raise ValueError('Excel用例选择必须为布尔值')
  if c.get('visibility','hidden') not in ('public','hidden'):raise ValueError('评测用例须选择公开自测或内部测试')
  key=c.get('input','')
  if key in seen_inputs:raise ValueError('测试用例输入重复或对应输出冲突，请合并用例')
  seen_inputs[key]=c['output']
  if approved_only and (c.get('verified') is not True or not c.get('purpose','').strip() or not c.get('output_basis','').strip()):
   raise ValueError(f'请核对评测用例{i}，填写测试目的、输出依据并确认预期输出')
 examples=q.get('public_examples',[])
 if 'description_includes_examples' in q and type(q['description_includes_examples']) is not bool:raise ValueError('原题样例标记必须为布尔值')
 if q.get('description_format','markdown') not in ('plain','markdown'):raise ValueError('题面格式必须为plain或markdown')
 if not isinstance(examples,list) or len(examples)>1000:raise ValueError('公开样例最多1000组')
 for c in examples:
  if not isinstance(c,dict) or not isinstance(c.get('input',''),str) or not isinstance(c.get('output'),str) or not c['output']:raise ValueError('公开样例输出不能为空')
 if q.get('io_contract'):
  from courseagent.stdio_contract import VERSION,parse_input,serialize_input
  if q['io_contract'].get('version')!=VERSION:raise ValueError('未知的编程题输入输出协议版本')
  for case in cases+examples:
   if serialize_input(q['io_contract'],parse_input(q['io_contract'],case.get('input','')))!=case.get('input',''):
    raise ValueError('编程题样例或评测输入未使用统一标准格式')
 from courseagent.programming_judge import validate_contract
 validate_contract(q)
 for k in ('knowledge','author_username','explanation','source','reference_code'):
  if k in q and not isinstance(q[k],str):raise ValueError('编程题文字字段格式不正确：'+k)
 if 'source_refs' in q and (not isinstance(q['source_refs'],list) or any(not isinstance(r,dict) or ('url' in r and not isinstance(r['url'],str)) for r in q['source_refs'])):
  raise ValueError('编程题出处格式不正确')
 # Validate every cell before accepting approval, not only at workbook generation.
 values=excel_values({**q,'test_cases':cases[:4]})
 for case in cases:validate_case_text(case)
 if any(isinstance(v,str) and re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]',v) for v in values.values()):
  raise ValueError('编程题文字包含Excel不支持的控制字符')
 if q.get('reference_code','').strip() and len(languages)==1 and languages[0]['language']=='Python':
  try:ast.parse(q['reference_code'])
  except (SyntaxError,ValueError,RecursionError):raise ValueError('Python参考代码语法检查未通过；未执行代码') from None
 if approved_only and (q.get('approved') is not True or q.get('approval_snapshot')!=review_content(q)):
  raise ValueError('编程题未审核，或审核后发生修改')
 return q


def student_description(q):
 """Public examples belong in the statement; judging metadata never does."""
 text=q['description']
 if q.get('description_includes_examples'):return text
 for i,c in enumerate(q.get('public_examples',[]),1):
  from courseagent.platform_format import code_block
  text+=f"\n\n公开样例 {i}\n\n输入：\n\n{code_block(c.get('input',''))}\n\n输出：\n\n{code_block(c['output'])}"
 return text


def platform_description(q):
 from courseagent.platform_format import markdown_literal,code_block,native_literal_delimiters,plain_sample_blocks
 native=any(r.get('method')=='native_structured_question' for r in q.get('source_refs',[]))
 if q.get('description_format')=='plain' or native and 'description_format' not in q:
  text=markdown_literal(q['description'])
  if not q.get('description_includes_examples'):
   for i,c in enumerate(q.get('public_examples',[]),1):
    text+=f"\n\n公开样例 {i}\n\n输入：\n\n{code_block(c.get('input',''))}\n\n输出：\n\n{code_block(c['output'])}"
  return plain_sample_blocks(text)
 text=student_description(q)
 return plain_sample_blocks(native_literal_delimiters(text) if native else text)


def excel_cases(q):
 cases=[c for c in q['test_cases'] if c.get('excel_selected',True)]
 if not 1<=len(cases)<=4:raise ValueError('现有Excel模板只有4组用例栏；请在题目审核中选择1至4组写入Excel，其余完整导出评测包后在平台补充，不会自动截断用例')
 return cases


def excel_values(q):
 if len(q['test_cases'])>4:raise ValueError('现有Excel模板只有4组用例栏；请完整导出评测包，并在平台补充用例及设置公开/内部可见性，不会截断用例')
 v={'A':q['title'],'B':platform_description(q),'C':q.get('knowledge','')[:50],'D':q['score'],'E':q['difficulty'],'F':q['time_limit_seconds'],
    'O':q.get('author_username',''),'X':q.get('explanation',''),'Y':q.get('reference_code','')}
 for i,item in enumerate(q['languages']):v[chr(71+i*2)]=item['language'];v[chr(72+i*2)]=item['starter_code']
 for i,item in enumerate(q['test_cases']):v[chr(80+i*2)]=item.get('input','');v[chr(81+i*2)]=item['output']
 if any(isinstance(x,str) and len(x)>32767 for x in v.values()):raise ValueError('编程题内容超过Excel单元格长度上限')
 return v


def export_programming_xlsx(programming,ordinary_document=None,approved_only=True,template=None):
 qs=[validate_programming(q,approved_only) for q in programming if q.get('selected')]
 # Platform requires 1/2/3; 0 means unlabelled locally, not a difficulty judgment.
 qs=[{**q,'difficulty':q['difficulty'] or 2,'test_cases':excel_cases(q)} for q in qs]
 if not qs:raise ValueError('请先选择编程题')
 template=template or WORKSPACE_ROOT/'data/template.xlsx'
 ordinary_present=bool(ordinary_document and any(q.get('selected') for q in ordinary_document['questions']))
 base=BytesIO(export_xlsx(ordinary_document,approved_only,template)) if ordinary_present else template
 out=BytesIO()
 with ZipFile(base) as source,ZipFile(out,'w',ZIP_DEFLATED) as target:
  for info in source.infolist():
   content=source.read(info.filename)
   if info.filename in ('xl/worksheets/sheet1.xml','xl/worksheets/sheet2.xml','xl/worksheets/sheet3.xml'):
    sheet=E.fromstring(content);rows=sheet.find(f'{{{NS}}}sheetData')
    if info.filename!='xl/worksheets/sheet1.xml' or not ordinary_present:
     for row in list(rows):
      if row.get('r')!='1':rows.remove(row)
     sheet.find(f'{{{NS}}}dimension').set('ref','A1:Y1')
    if info.filename=='xl/worksheets/sheet2.xml':
     for n,q in enumerate(qs,2):
      row=E.SubElement(rows,f'{{{NS}}}row',r=str(n))
      for col,value in excel_values(q).items():
       cell=E.SubElement(row,f'{{{NS}}}c',r=f'{col}{n}')
       if isinstance(value,(int,float)):E.SubElement(cell,f'{{{NS}}}v').text=str(value)
       else:
        cell.set('t','inlineStr');text=E.SubElement(E.SubElement(cell,f'{{{NS}}}is'),f'{{{NS}}}t');text.set('{http://www.w3.org/XML/1998/namespace}space','preserve');text.text=str(value)
     sheet.find(f'{{{NS}}}dimension').set('ref',f'A1:Y{len(qs)+1}')
    content=E.tostring(sheet,encoding='utf-8',xml_declaration=True)
   target.writestr(info,content)
 return out.getvalue()


def export_test_bundle(document,approved_only=True):
 """Full teacher-only judge files; this ZIP is not an Educoder import format."""
 selected=[q for q in document.get('programming_questions',[]) if q.get('selected')]
 if not selected:raise ValueError('请先选择编程题')
 manifest={'format':'educoder-teacher-judge-bundle-v1','platform_importable':False,'questions':[]}
 out=BytesIO()
 with ZipFile(out,'w',ZIP_DEFLATED) as z:
  for n,q in enumerate(selected,1):
   validate_programming(q,approved_only)
   entry={'title':q['title'],'description':student_description(q),'judge_contract':q.get('judge_contract'),'test_cases':[]}
   from courseagent.programming_judge import delivery_report
   entry['machine_verification']=delivery_report(q)
   for i,c in enumerate(q['test_cases'],1):
    base=f'question-{n:03d}/case-{i:04d}'
    z.writestr(base+'.in',c.get('input',''));z.writestr(base+'.out',c['output'])
    entry['test_cases'].append({**c,'input_file':base+'.in','output_file':base+'.out','visibility':c.get('visibility','hidden')})
   manifest['questions'].append(entry)
  if all(1<=sum(c.get('excel_selected',True) for c in q['test_cases'])<=4 for q in selected):
   z.writestr('programming-questions.xlsx',export_programming_xlsx(selected,approved_only=approved_only))
   manifest['excel_included']=True
  else:manifest['excel_included']=False
  z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
  z.writestr('教师使用说明.txt','这是教师评测资料包，不是头歌已验证的ZIP导入格式。\n包含全部公开自测和内部测试的输入、预期输出及说明；请勿整包提供给学生。\nExcel模板只能容纳4组输入输出且没有可见性栏；请在平台按manifest中的顺序与可见性补充/设置全部用例。\n此包不会发布试卷或操作平台。\n')
 return out.getvalue()
