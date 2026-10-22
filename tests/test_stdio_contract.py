import copy
import json
import unittest

from courseagent.stdio_contract import make_contract,parse_input,serialize_input,serialize_output,source_values,student_statement
from courseagent.leetcode_driver import python_driver
from courseagent.native_sandbox import execute


def function(params,output='integer'):
    return {'name':'solve','params':[{'name':name,'type':typ} for name,typ in params],
            'return':{'type':output}}


class ContractTests(unittest.TestCase):
    def test_cached_scaffolds_clear_without_repeating_algorithm_verification(self):
        from courseagent.native_questions import upgrade_native_question
        from courseagent.programming_verification import current_report,basis,case_basis,VERSION
        q={'io_contract':make_contract(function([('x','integer')])),
           'languages':[{'language':'C','starter_code':'old scaffold'}],
           'approved':True,'approval_snapshot':'old','test_cases':[]}
        q['execution_verification']={'passed':True,'method':VERSION,'basis':basis(q),'case_basis':case_basis(q),
                                    'mutation_testing':{'passed':True,'eligible_count':2},'template_io':{'passed':True}}
        self.assertTrue(upgrade_native_question(q))
        self.assertEqual(q['languages'],[{'language':'C','starter_code':''}])
        self.assertFalse(q['approved']);self.assertNotIn('approval_snapshot',q)
        self.assertIsNotNone(current_report(q));self.assertNotIn('template_io',q['execution_verification'])
        self.assertFalse(upgrade_native_question(q))
        q['test_cases']=[{'input':'2','output':'4'}]
        self.assertIsNone(current_report(q))

    def test_stale_algorithm_evidence_cannot_be_recertified_by_clearing_code(self):
        from courseagent.native_questions import upgrade_native_question
        from courseagent.programming_verification import current_report,basis,case_basis,VERSION
        q={'io_contract':make_contract(function([('x','integer')])),
           'languages':[{'language':'C','starter_code':'old scaffold'}],'description':'old'}
        q['execution_verification']={'passed':True,'method':VERSION,'basis':basis(q),'case_basis':case_basis(q),
                                    'mutation_testing':{'passed':True,'eligible_count':2}}
        q['description']='changed task'
        upgrade_native_question(q)
        self.assertIsNone(current_report(q))

    def test_array_and_boolean_use_one_unambiguous_format(self):
        contract=make_contract(function([('nums','integer[]'),('target','integer')],'boolean'))
        values=source_values('nums = [2,5,6,0,0,1,2], target = 0')
        text=serialize_input(contract,values)
        self.assertEqual(text,'7\n2 5 6 0 0 1 2\n0\n')
        self.assertEqual(parse_input(contract,text),values)
        self.assertEqual(serialize_output(contract,True),'1\n')
        for invalid in ['[2,5]\n0\n','nums = [2,5], target = 0','2\n2 5\n0\nextra\n','2\n2\n0\n']:
            with self.assertRaises(ValueError):parse_input(contract,invalid)

    def test_matrix_ragged_rows_empty_strings_and_trees_roundtrip(self):
        fixtures=[
            (function([('matrix','integer[][]')]),'二维矩阵',[[[1,2],[3,4]]]),
            (function([('rows','integer[][]')]),'邻接表',[[[],[1,2],[3]]]),
            (function([('s','string'),('words','string[]')]),'', [' a b ',['','two words','中文']]),
            (function([('head','ListNode'),('root','TreeNode')]),'',[[],[1,None,2,3]]),
        ]
        for metadata,statement,values in fixtures:
            with self.subTest(values=values):
                c=make_contract(metadata,statement);self.assertEqual(parse_input(c,serialize_input(c,values)),values)
        c=make_contract(fixtures[0][0],'矩阵')
        self.assertEqual(serialize_input(c,[[[1,2],[3,4]]]),'2 2\n1 2\n3 4\n')
        with self.assertRaises(ValueError):serialize_input(c,[[[1],[2,3]]])

    def test_class_queries_have_command_lines_and_only_query_outputs(self):
        meta={'classname':'Stack','constructor':{'params':[]},'methods':[
            {'name':'push','params':[{'name':'x','type':'integer'}],'return':{'type':'void'}},
            {'name':'pop','params':[],'return':{'type':'integer'}},
            {'name':'empty','params':[],'return':{'type':'boolean'}}]}
        c=make_contract(meta);values=[['Stack','push','pop','empty'],[[],[7],[],[]]]
        text=serialize_input(c,values)
        self.assertEqual(text,'4\nStack\npush\n7\npop\nempty\n')
        self.assertEqual(parse_input(c,text),values)
        self.assertEqual(serialize_output(c,[None,None,7,True],values),'7\n1\n')

    def test_statement_replaces_entire_source_example_section(self):
        c=make_contract(function([('nums','integer[]')],'boolean'))
        text=student_statement('编写一个函数，返回 true 或 false。\n\n示例 1：\n输入：nums = [1]\n输出：true\n\n提示：\n1 <= n <= 9',c,[{'input':'1\n1\n','output':'1\n'}])
        for unwanted in ('运行约定','JSON','nums =','编写一个函数','true','false'):
            self.assertNotIn(unwanted,text)
        self.assertIn('### 输入格式',text);self.assertIn('### 样例输入 1',text);self.assertIn('1 <= n <= 9',text)

    def test_migration_keeps_id_source_and_selection_but_invalidates_old_evidence(self):
        from courseagent.native_questions import upgrade_native_question
        q={'id':'old-id','selected':True,'approved':True,'description':'编写一个函数。\n\n示例 1：\n输入：nums=[1,2]\n输出：3\n\n运行约定：旧协议',
           'public_examples':[{'input':'nums=[1,2]','output':'3'}],
           'source_metadata':{'provider':'leetcode','interface':function([('nums','integer[]')])},
           'source_refs':[{'url':'https://leetcode.cn/problems/example/'}],
           'languages':[{'language':'C','starter_code':''},{'language':'Python','starter_code':'old'}],
           'execution_verification':{'passed':True},'test_cases':[]}
        original=copy.deepcopy(q);self.assertTrue(upgrade_native_question(q))
        self.assertEqual(q['id'],original['id']);self.assertEqual(q['source_refs'],original['source_refs']);self.assertTrue(q['selected'])
        self.assertFalse(q['approved']);self.assertNotIn('execution_verification',q)
        self.assertTrue(all(l['starter_code']=='' for l in q['languages']))
        self.assertEqual(q['public_examples'],[{'input':'2\n1 2\n','output':'3\n'}])
        self.assertEqual(q['source_public_examples'],original['public_examples'])
        self.assertFalse(upgrade_native_question(q))

    def test_teacher_answers_keep_their_existing_protocol_and_evidence(self):
        from courseagent.native_questions import upgrade_native_question
        from courseagent.programming_verification import current_report,basis,case_basis,VERSION
        q={'languages':[{'language':'C','starter_code':'teacher code'}],'answer_provenance':{'kind':'teacher'},'source_protocol':'function','source_metadata':{'provider':'leetcode','interface':function([('x','integer')])}}
        q['execution_verification']={'passed':True,'method':VERSION,'basis':basis(q),'case_basis':case_basis(q),
                                    'mutation_testing':{'passed':True,'eligible_count':2}}
        original=copy.deepcopy(q)
        self.assertFalse(upgrade_native_question(q));self.assertEqual(q,original)
        self.assertIsNotNone(current_report(q))

    def test_output_array_length_is_not_constrained_by_input_length(self):
        from courseagent.stdio_contract import format_sections
        contract=make_contract(function([('nums','integer[]')],'integer[]'))
        inputs,outputs=format_sections(contract)
        self.assertIn('下方数据范围',inputs);self.assertNotIn('下方数据范围',outputs)
        string_contract=make_contract(function([('s','string')],'string'))
        statement=student_statement('当 s 等于 "true" 时返回 "false"。',string_contract,[])
        self.assertIn('"true"',statement);self.assertIn('"false"',statement)


class ExecutableContractTests(unittest.TestCase):
    def test_reference_adapter_runs_original_function_and_class_algorithms(self):
        metadata=function([('nums','integer[]'),('target','integer')],'boolean')
        c=make_contract(metadata);a=python_driver(metadata,c)
        source='class Solution:\n def solve(self,nums,target):return target in nums'
        for values in ([[7,-1,4],4],[[],3]):
            result=execute('Python',a['prelude_code']+'\n'+source+'\n'+a['driver_code'],serialize_input(c,values))
            self.assertTrue(result['ok'],result.get('error'));self.assertEqual(result['output'],'1\n' if values[1] in values[0] else '0\n')

    def test_class_source_adapter_uses_standard_command_protocol(self):
        metadata={'classname':'Stack','constructor':{'params':[]},'methods':[
            {'name':'push','params':[{'name':'x','type':'integer'}],'return':{'type':'void'}},
            {'name':'pop','params':[],'return':{'type':'integer'}},
            {'name':'empty','params':[],'return':{'type':'boolean'}}]}
        contract=make_contract(metadata);values=[['Stack','push','push','pop','empty'],[[],[-2],[7],[],[]]]
        text=serialize_input(contract,values)
        adapter=python_driver(metadata,contract)
        source='class Stack:\n def __init__(self):self.a=[]\n def push(self,x):self.a.append(x)\n def pop(self):return self.a.pop()\n def empty(self):return not self.a'
        result=execute('Python',adapter['prelude_code']+'\n'+source+'\n'+adapter['driver_code'],text)
        self.assertTrue(result['ok'],result.get('error'));self.assertEqual(result['output'],'7\n0\n')


if __name__=='__main__':unittest.main()
