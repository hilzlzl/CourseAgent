"""Regressions from the real tree task that was manually continued twice."""
import copy
import unittest
import tempfile
import json
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch, Mock

from courseagent.autonomous_agent import build_agent, statement_repairs, validate_machine_delivery, fingerprint, VALIDATION_VERSION
from courseagent.programming_statement import prepare_statement, validate_wording, payload
from tests.test_programming_statement import fixture, wording
from tests import test_programming_statement as fixtures
from tests.test_autonomous_agent import document


class StatementRecoveryTests(unittest.TestCase):
    def test_output_order_repair_passes_reference_to_author_and_auditor(self):
        from courseagent.programming_statement import needs_statement
        q=fixture([('root','TreeNode')],'integer[][]','找出所有根到叶的合格路径，可以任意顺序返回。')
        q['source_reference']={'code':'visit(node.left)\nvisit(node.right)','language':'Python','url':'https://example.org/solution'}
        q['statement_repair_request']={'attempt':2,'issues':[{'message':'补充路径间输出顺序'}]}
        before=copy.deepcopy(q);cache=fixtures.StatementTests();cache.setUp();roles=[]
        def ask(role,prompt,data):
            roles.append(role)
            self.assertEqual(data['reference_output_context']['code'],q['source_reference']['code'])
            if role=='validator':
                self.assertIn('按对应叶结点从左到右排列',data['adapted_statement'])
                return {'passed':True,'issues':[]}
            self.assertIn('排列规则',prompt)
            w=wording(q);w['task']='找出所有根到叶的合格路径，路径按对应叶结点从左到右排列。';return w
        prepare_statement(q,ask,cache.cache)
        self.assertEqual(roles,['author','validator']);self.assertFalse(needs_statement(q))
        for field in ('source_reference','test_cases','public_examples','io_contract'):
            self.assertEqual(q[field],before[field])
        self.assertNotIn('visit(node.left)',q['description'])
        q['source_reference']['code']='visit(node.right)\nvisit(node.left)'
        self.assertTrue(needs_statement(q))

    def test_concurrent_json_checkpoints_do_not_rename_each_others_temp_file(self):
        from courseagent.import_jobs import write_json
        barrier=threading.Barrier(2);replace=Path.replace
        def simultaneous(path,target):
            barrier.wait(timeout=5)
            return replace(path,target)
        with tempfile.TemporaryDirectory() as folder,patch.object(Path,'replace',simultaneous):
            target=Path(folder)/'checkpoint.json'
            with ThreadPoolExecutor(max_workers=2) as pool:
                calls=[pool.submit(write_json,target,{'writer':i}) for i in range(2)]
                for call in calls:call.result()
            self.assertIn(json.loads(target.read_text())['writer'],[0,1])
            self.assertEqual(list(Path(folder).glob('*.tmp')),[])

    def tree(self):
        from tests.test_programming_questions import ProgrammingTests
        base=ProgrammingTests().sample()
        q=fixture([('root','TreeNode')],'TreeNode',
                  '翻转二叉树，输出结果。\n\n提示：\n树的结点数在 [0, 100] 内。')
        q={**base,**q}
        q.update(id='tree-kept',selected=True,approved=False)
        q['public_examples']=[{'input':'3\n1 # 2\n','output':'2\n1 2\n'}]
        q['test_cases']=[{'input':'3\n1 2 3\n','output':'3\n1 3 2\n',
                         'visibility':'hidden','purpose':'左右子树互换','output_basis':'翻转后左为3右为2'}]
        return q

    def issue(self,qid='tree-kept'):
        return {'kind':'conditions','severity':'blocking','question_ids':[qid],
                'message':'层序编码缺少非空父结点展开规则和末尾空标记删除规则',
                'evidence':'#表示空结点'}

    def state(self):
        d=document();d['programming_questions']=[self.tree()]
        return {'document':d,'request':{'prompt':'二叉树'},'sources':[], 'rounds':0,'events':[]}

    def test_misnested_empty_fields_get_local_format_retry_without_search(self):
        q=self.tree();calls=[];cache=fixtures.StatementTests();cache.setUp()
        def ask(role,prompt,data):
            calls.append((role,data))
            if role=='validator':return {'passed':True,'issues':[]}
            w=wording(q);group=w['methods'][0];param=group['params'][0]
            if len(calls)==1:
                param.pop('empty');param.pop('empty_evidence')
                group.update(empty='allowed',empty_evidence='[0, 100]')
            else:param.update(empty='allowed',empty_evidence='[0, 100]')
            return w
        prepare_statement(q,ask=ask,cache=cache.cache)
        self.assertEqual([role for role,_ in calls],['author','author','validator'])
        self.assertIn('format_correction',calls[1][1])
        self.assertIn('空树的编码项总数为 0',q['description'])

    def test_nested_fields_cannot_be_omitted_even_if_method_has_empty_claim(self):
        q=self.tree();w=wording(q)
        w['methods'][0]['params'][0].pop('empty')
        with self.assertRaisesRegex(ValueError,'每个params'):validate_wording(w,payload(q))
        w=wording(q);w['methods'][0]['empty']='allowed'
        with self.assertRaisesRegex(ValueError,'不能放在methods'):validate_wording(w,payload(q))

    def test_local_repair_keeps_id_source_and_cases_and_runs_verification(self):
        state=self.state();before=copy.deepcopy(state['document']['programming_questions'][0]);calls=[];checks=[]
        def checker(doc):
            checks.append(1)
            return {'blocking':len(checks)==1,'issues':[self.issue()] if len(checks)==1 else []}
        def verify(arg):
            q=arg['document']['programming_questions'][0]
            self.assertIn('statement_repair_request',q)
            self.assertEqual(q['id'],before['id']);self.assertEqual(q['test_cases'],before['test_cases'])
            q.pop('statement_repair_request');q['description']='修复后的完整题意及树编码规则'
            return {'document':arg['document']}
        with patch('courseagent.verification_tools.verify_programming_answers',Mock(invoke=Mock(side_effect=verify))) as tool, \
             patch('courseagent.verification_tools.verify_ordinary_answers',Mock(invoke=Mock(side_effect=lambda a:{'document':a['document']}))):
            out=build_agent(planner=lambda d,r,s:(calls.append(1) or d),checker=checker).invoke(state)
        self.assertEqual(len(calls),1);tool.invoke.assert_called_once()
        self.assertEqual(out['events'][0]['action'],'repair_statements')
        q=out['document']['programming_questions'][0]
        for key in ['id','source_description','io_contract','test_cases']:self.assertEqual(q[key],before[key])
        self.assertTrue(q['selected']);self.assertNotIn(q['id'],out.get('avoid_ids',[]))

    def test_shared_codec_loop_guard_survives_continuation_and_new_question_id(self):
        state=self.state();state['resume']=True;state['statement_repair_counts']={'tree_codec':2}
        state['document']['programming_questions'][0]['id']='new-tree'
        out=build_agent(planner=lambda *a:self.fail('must not search'),
            checker=lambda d:{'blocking':True,'issues':[self.issue('new-tree')]}).invoke(state)
        self.assertEqual(out['action'],'stop');self.assertIn('共用编码规则',out['reason'])
        self.assertTrue(out['document']['programming_questions'][0]['selected'])

    def test_duplicate_topic_and_trusted_material_are_not_wording_repairs(self):
        d=self.state()['document']
        for change in [{'kind':'repetition'},{'kind':'topic'},{'replacement_required':True}]:
            self.assertEqual(statement_repairs(d,[{**self.issue(),**change}]),{})
        d['programming_questions'][0]['answer_provenance']={'kind':'teacher_material'}
        self.assertEqual(statement_repairs(d,[self.issue()]),{})

    def test_pending_repair_cannot_use_an_old_whole_exam_delivery_receipt(self):
        d=self.state()['document'];q=d['programming_questions'][0]
        q['statement_repair_request']={'issues':[self.issue()],'attempt':1}
        d['agent_validation']={'version':VALIDATION_VERSION,'passed':True,'basis':fingerprint(d)}
        with self.assertRaisesRegex(ValueError,'局部修复尚未完成'):validate_machine_delivery(d)


if __name__=='__main__':unittest.main()
