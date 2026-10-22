import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tests import test_programming_questions as programming_tests
from tests.test_autonomous_agent import document
from courseagent.programming_judge import apply_contract,validate_autonomous_cases
from courseagent.programming_verification import verify_document
from courseagent.autonomous_agent import check_document,validate_machine_delivery,fingerprint,build_agent,VALIDATION_VERSION


class DeliveryGuards(unittest.TestCase):
    def coding(self):
        q=programming_tests.ProgrammingTests().sample();q['id']='guard-coding'
        apply_contract(q,'binary_search_unique')
        from courseagent.programming_verification import basis,case_basis,VERSION
        q['execution_verification']={'passed':True,'status':'verified','method':VERSION,'basis':basis(q),'case_basis':case_basis(q),'mutation_testing':{'passed':True,'eligible_count':2}}
        return q

    def test_public_examples_cannot_be_counted_as_hidden_even_with_correct_outputs(self):
        q=self.coding()
        validate_autonomous_cases(q)
        q['public_examples']=[{'input':c['input'],'output':c['output']} for c in q['test_cases']]
        with self.assertRaisesRegex(ValueError,'隐藏评测'):validate_autonomous_cases(q)

    def test_missing_hidden_cases_block_both_supervisor_and_import_boundary(self):
        d=document();q=self.coding();q['test_cases']=[c for c in q['test_cases'] if c['visibility']=='public']
        d['programming_questions']=[q];d['plan']['spec']['programming_count']=1
        with tempfile.TemporaryDirectory() as tmp,patch('courseagent.web_questions.CACHE',Path(tmp)),patch('courseagent.agent_roles.ask_role',return_value={'issues':[]}):
            r=check_document(d)
        self.assertTrue(r['blocking'])
        self.assertTrue(any('隐藏评测' in i['message'] and i['severity']=='blocking' for i in r['issues']))
        d['agent_validation']={'version':VALIDATION_VERSION,'passed':True,'basis':fingerprint(d)}
        with self.assertRaisesRegex(ValueError,'隐藏评测'):validate_machine_delivery(d)

    def test_builtin_public_only_questions_are_not_skipped_by_verifier(self):
        q=self.coding();q['test_cases']=[c for c in q['test_cases'] if c['visibility']=='public']
        with patch('courseagent.programming_verification.available',return_value=False):
            result=verify_document({'programming_questions':[q]})
        self.assertEqual(result['programming_questions'][0]['execution_verification']['status'],'sandbox_unavailable')

    def test_contract_output_error_is_not_silently_accepted(self):
        q=self.coding();q['test_cases'][-1]['output']='999999\n'
        with self.assertRaises(ValueError):validate_autonomous_cases(q)

    def test_old_quality_receipt_cannot_authorize_new_import(self):
        d=document();d['agent_validation']={'passed':True,'basis':fingerprint(d)}
        with self.assertRaisesRegex(ValueError,'规则已升级'):validate_machine_delivery(d)

    def test_reviewed_ordinary_questions_do_not_suppress_programming_scope_issues(self):
        d=document();q=self.coding();d['programming_questions']=[q]
        for item in d['questions']:item['web_interpretation']={'in_scope':True}
        d['plan'].update(complete=True);d['plan']['spec']['programming_count']=1
        issue={'kind':'topic','severity':'blocking','question_ids':[q['id']],
               'evidence':q['title'],'message':'编程题主考点超出明确指定范围'}
        prompts=[]
        def model(role,prompt,data):
            prompts.append(prompt)
            if 'confirmed_issue_ids' in prompt:return {'confirmed_issue_ids':['issue-0'],'reason':'确认为范围外'}
            return {'issues':[issue]}
        with tempfile.TemporaryDirectory() as tmp,patch('courseagent.web_questions.CACHE',Path(tmp)),\
             patch('courseagent.workflow.refresh_plan'),patch('courseagent.exam_quality.check_exam',return_value={'issues':[]}),\
             patch('courseagent.ordinary_verification.current',return_value={'verdict':'pass'}),\
             patch('courseagent.agent_roles.ask_role',side_effect=model):
            report=check_document(d)
        self.assertIn('编程题仍须独立检查',prompts[0])
        self.assertTrue(any(i['kind']=='topic' and i['severity']=='blocking' for i in report['issues']))

    def test_hidden_case_failure_replaces_only_bad_question_then_delivers(self):
        d=document();bad=self.coding()
        bad['test_cases']=[c for c in bad['test_cases'] if c['visibility']=='public']
        d['programming_questions']=[bad];d['plan']['spec']['programming_count']=1
        original=copy.deepcopy(d['questions']);requests=[];delivered=[]
        def planner(doc,request,sources):
            requests.append(copy.deepcopy(request))
            if len(requests)>1:
                good=self.coding();good['id']='replacement-coding'
                doc['programming_questions'].append(good)
            return doc
        def delivery(doc):
            validate_machine_delivery(doc);delivered.append(copy.deepcopy(doc))
            return {'status':'ready'}
        with tempfile.TemporaryDirectory() as tmp,patch('courseagent.web_questions.CACHE',Path(tmp)),patch('courseagent.agent_roles.ask_role',return_value={'issues':[]}):
            out=build_agent(planner,check_document,lambda *a:{'action':'replace','reason':'缺少独立隐藏输入，替换'},delivery).invoke(
                {'document':d,'request':{'prompt':'课程练习'},'sources':[],'rounds':0,'events':[]})
        self.assertEqual(out['action'],'deliver');self.assertEqual(len(delivered),1)
        self.assertEqual(out['document']['questions'],original)
        self.assertFalse(out['document']['programming_questions'][0]['selected'])
        self.assertTrue(out['document']['programming_questions'][1]['selected'])
        self.assertIn(bad['id'],requests[1]['avoid_ids'])

    def test_excel_knowledge_limit_does_not_modify_original_metadata(self):
        from courseagent.questions import excel_values
        from courseagent.programming_questions import excel_values as coding_values
        d=document();q=d['questions'][0];q['knowledge']='数据结构'*30
        original=copy.deepcopy(q)
        self.assertEqual(len(excel_values(q)['T']),50);self.assertEqual(q,original)
        q=self.coding();q['knowledge']='算法'*40
        original=copy.deepcopy(q)
        self.assertEqual(len(coding_values({**q,'test_cases':q['test_cases'][:4]})['C']),50)
        self.assertEqual(q,original)


if __name__=='__main__':unittest.main()
