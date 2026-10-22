import copy,json,unittest
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as E
from courseagent.programming_questions import export_programming_xlsx,review_content,validate_programming
from courseagent.questions import NS

class ProgrammingTests(unittest.TestCase):
 def sample(self):return {'title':'统计列表正数个数','description':'输入n及n个整数，输出正数个数。n为1至100。','score':10,'difficulty':1,'time_limit_seconds':3,'languages':[{'language':'Python','starter_code':'# 完成程序\n'}],'test_cases':[{'input':'4\n-1 0 2 3\n','output':'2\n','purpose':'混合正负与零','output_basis':'2和3为正数，共2个','verified':True},{'input':'1\n0\n','output':'0\n','purpose':'零不是正数','output_basis':'唯一元素为0，正数个数为0','verified':True}],'reference_code':'n=int(input())\na=list(map(int,input().split()))\nprint(sum(x>0 for x in a))\n','selected':True,'approved':False}
 def test_unreviewed_or_changed_code_blocked(self):
  q=self.sample()
  with self.assertRaises(ValueError):validate_programming(q)
  q['approved']=True;q['approval_snapshot']=copy.deepcopy(review_content(q));validate_programming(q);q['test_cases'][0]['output']='99'
  with self.assertRaises(ValueError):validate_programming(q)
 def test_template_exact_mapping_and_examples_removed(self):
  q=self.sample();before=copy.deepcopy(q)
  with ZipFile(BytesIO(export_programming_xlsx([q],approved_only=False))) as z:
   sheet=E.fromstring(z.read('xl/worksheets/sheet2.xml'));cells={c.get('r'):''.join(c.itertext()) for c in sheet.iter(f'{{{NS}}}c')};self.assertEqual(cells['G2'],'Python');self.assertEqual(cells['P2'],q['test_cases'][0]['input']);self.assertEqual(cells['Q2'],'2\n');self.assertEqual(cells['Y2'],q['reference_code'])
   for n in (1,3):self.assertEqual(len(E.fromstring(z.read(f'xl/worksheets/sheet{n}.xml')).find(f'{{{NS}}}sheetData')),1)
  self.assertEqual(q,before)
 def test_mixed_workbook_keeps_ordinary_questions(self):
  d=json.loads((Path(__file__).resolve().parents[1]/'examples/offline-fixture.json').read_text())
  with ZipFile(BytesIO(export_programming_xlsx([self.sample()],d,approved_only=False))) as z:
   self.assertGreater(len(E.fromstring(z.read('xl/worksheets/sheet1.xml')).find(f'{{{NS}}}sheetData')),1)
 def test_missing_outputs_and_invalid_limits(self):
  for k,v in [('test_cases',[{'input':'1','output':''}]),('time_limit_seconds',0),('score',float('nan')),('languages',[])]:
   q=self.sample();q[k]=v
   with self.assertRaises(ValueError):validate_programming(q,False)

 def test_optional_code_and_public_samples_export_without_judging_metadata(self):
  q=self.sample();q.pop('reference_code');q['public_examples']=[{'input':'1\n5\n','output':'1\n'}]
  q['approved']=True;q['approval_snapshot']=review_content(q)
  validate_programming(q)
  with ZipFile(BytesIO(export_programming_xlsx([q]))) as z:
   sheet=E.fromstring(z.read('xl/worksheets/sheet2.xml'));cells={c.get('r'):''.join(c.itertext()) for c in sheet.iter(f'{{{NS}}}c')}
   self.assertEqual(cells['Y2'],'');self.assertIn('公开样例 1',cells['B2'])
   self.assertNotIn('混合正负与零',cells['B2']);self.assertNotIn('共2个',cells['B2'])
   self.assertEqual(cells['P2'],q['test_cases'][0]['input'])

 def test_unconfirmed_case_and_conflicting_inputs_block_export(self):
  q=self.approved();q['test_cases'][0]['verified']=False;q['approval_snapshot']=review_content(q)
  with self.assertRaisesRegex(ValueError,'评测用例1'):validate_programming(q)
  q=self.sample();q['test_cases'][1]['input']=q['test_cases'][0]['input']
  with self.assertRaisesRegex(ValueError,'重复或对应输出冲突'):validate_programming(q,False)

 def test_output_basis_and_public_sample_edits_revoke_approval(self):
  from courseagent.questions import normalize_approvals
  for mutate in (lambda q:q['test_cases'][0].update(output_basis='修改依据'),lambda q:q.update(public_examples=[{'input':'1','output':'1'}])):
   q=self.approved();mutate(q);d={'questions':[],'programming_questions':[q]}
   normalize_approvals(d);self.assertFalse(q['approved'])


 def approved(self):
  q=self.sample();q.update(id='programming-test',source='教师录入',source_refs=[])
  q['approved']=True;q['approval_snapshot']=review_content(q)
  return q

 def test_mixed_export_requires_both_approvals_and_programming_only_supported(self):
  from courseagent.questions import export_xlsx,validate,review_content as ordinary_content
  d=json.loads((Path(__file__).resolve().parents[1]/'examples/offline-fixture.json').read_text())
  for ordinary in d['questions']:
   ordinary['approved']=True;ordinary['approval_snapshot']=ordinary_content(ordinary)
  d['programming_questions']=[self.approved()]
  self.assertEqual(len(validate(d,True)),len(d['questions'])+1)
  d['questions'][0]['approved']=False
  with self.assertRaises(ValueError):export_xlsx(d)
  d['questions'][0]['approved']=True
  with ZipFile(BytesIO(export_xlsx(d))) as z:
   self.assertEqual(len(E.fromstring(z.read('xl/worksheets/sheet2.xml')).find(f'{{{NS}}}sheetData')),2)
  d['programming_questions'][0]['reference_code']+='\n# 修改'
  with self.assertRaises(ValueError):export_xlsx(d)
  q=self.approved()
  with ZipFile(BytesIO(export_xlsx({'name':'只有编程题','questions':[],'programming_questions':[q]}))) as z:
   self.assertEqual(len(E.fromstring(z.read('xl/worksheets/sheet1.xml')).find(f'{{{NS}}}sheetData')),1)

 def test_nested_changes_and_provenance_invalidate_approval_and_receipt(self):
  from courseagent.questions import normalize_approvals
  from courseagent.review_workflow import fingerprint
  for mutate in (lambda q:q['test_cases'][0].update(output='99'), lambda q:q['languages'][0].update(starter_code='print(1)'),lambda q:q.update(source='新来源')):
   d={'name':'审核','questions':[],'programming_questions':[self.approved()]}
   before=fingerprint(d);mutate(d['programming_questions'][0]);self.assertNotEqual(before,fingerprint(d))
   normalize_approvals(d);self.assertFalse(d['programming_questions'][0]['approved'])

 def test_invalid_excel_cells_rejected_before_approval(self):
  for change in ({'reference_code':'\x00'}, {'description':'a'*32768}, {'source_refs':'invalid'}, {'reference_code':'print('}):
   q=self.sample();q.update(change)
   with self.assertRaises(ValueError):validate_programming(q,False)

 def test_duplicate_ids_rejected_and_drafts_can_be_saved(self):
  from courseagent.questions import normalize_approvals
  q=self.approved();d={'name':'审核','questions':[{'id':q['id']}],'programming_questions':[q]}
  with self.assertRaises(ValueError):normalize_approvals(d)
  d={'name':'审核','questions':[],'programming_questions':[{'id':'blank','title':'','approved':False}]}
  self.assertEqual(normalize_approvals(d),d)

 def test_programming_import_freezes_full_case_snapshot(self):
  import tempfile
  from courseagent.import_jobs import start_import
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);q=self.approved()
   d={'name':'编程导入测试','version':1,'questions':[],'programming_questions':[q]}
   job=start_import(root,d,'https://www.educoder.net/classrooms/x/exercise','课程',runner=lambda *a:None)
   expected=json.loads((root/'outputs/import-jobs'/job['id']/'expected.json').read_text())
   self.assertEqual(expected['questions'],[])
   self.assertEqual(expected['programming_questions'][0]['test_cases'],q['test_cases'])
   self.assertEqual(job['question_count'],1);self.assertFalse(job['published'])

 def test_programming_only_quality_report_is_invalidated_by_nested_edit(self):
  from courseagent.exam_quality import basis,check_exam
  d={'name':'编程题','questions':[],'programming_questions':[self.approved()]}
  result=check_exam(d);self.assertEqual(result['selected_count'],1);self.assertIn('未执行代码',result['note'])
  before=basis(d);d['programming_questions'][0]['test_cases'][0]['output']='99'
  self.assertNotEqual(before,basis(d))

if __name__=='__main__':unittest.main()
