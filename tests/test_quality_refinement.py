import copy
import json
import random
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from courseagent.stdio_contract import make_contract, serialize_input, serialize_output, parse_input, runtime_source
from courseagent.programming_output_policy import apply_output_policy, apply_input_policy, structural_issue, ORDER_RULE
from courseagent.programming_oracles import check_case
from courseagent.programming_source_recovery import recovery_key, retry_count
from tests.test_programming_statement import fixture, wording


def question(slug, params, output, values, result):
    metadata = {'name':'solve', 'params':[{'name':n,'type':t} for n,t in params], 'return':{'type':output}}
    contract = make_contract(metadata)
    case = {'input':serialize_input(contract, values), 'output':serialize_output(contract, result)}
    return {'id':slug, 'title':slug, 'io_contract':contract, 'source_metadata':{'provider':'leetcode'},
            'source_refs':[{'url':'https://leetcode.cn/problems/'+slug+'/'}],
            'source_description':'读取输入并完成给定的计算任务。', 'description':'旧描述',
            'public_examples':[case], 'test_cases':[{**case,'verified':True}]}


class OutputPolicyTests(unittest.TestCase):
    def test_reordered_indices_become_identical_and_old_evidence_is_invalidated(self):
        q = question('two-sum', [('nums','integer[]'),('target','integer')], 'integer[]', [[2,7],9], [1,0])
        q['execution_verification'] = {'passed':True}
        inputs = q['test_cases'][0]['input']
        self.assertTrue(apply_output_policy(q))
        self.assertEqual(q['test_cases'][0]['output'], '2\n0 1\n')
        self.assertEqual(q['public_examples'][0]['output'], '2\n0 1\n')
        self.assertEqual(q['test_cases'][0]['input'], inputs)
        self.assertNotIn('execution_verification',q)
        self.assertFalse(q['test_cases'][0]['verified'])
        self.assertFalse(apply_output_policy(q))

    def test_paths_sort_only_outer_results_and_preserve_duplicate_characters(self):
        q = question('path-sum-ii',[('root','TreeNode'),('target','integer')], 'integer[][]', [[1],1], [[2,9,1],[2,3,7]])
        apply_output_policy(q)
        self.assertEqual(q['public_examples'][0]['output'],'2\n3\n2 3 7\n3\n2 9 1\n')
        q = question('find-common-characters',[('words','string[]')], 'string[]', [['bella','label','roller']], ['l','e','l'])
        apply_output_policy(q)
        self.assertEqual(q['public_examples'][0]['output'],'3\ne\nl\nl\n')

    def test_failure_is_atomic_and_teacher_or_approved_snapshots_are_untouched(self):
        q = question('two-sum',[('nums','integer[]')], 'integer[]', [[2,7]], [1,0])
        q['test_cases'][0]['output'] += 'bad\n'
        before = copy.deepcopy(q)
        with self.assertRaises(ValueError):apply_output_policy(q)
        self.assertEqual(q,before)
        for extra in ({'approved':True},{'answer_provenance':{'kind':'teacher'}},{'origin':'web_programming_adapted'}):
            q.update(extra);before=copy.deepcopy(q)
            self.assertFalse(apply_output_policy(q));self.assertEqual(q,before)

    def test_structural_questions_are_replaced_before_any_source_request(self):
        from courseagent.programming_sourcing import executable_source_gate
        for slug in ('delete-node-in-a-bst','construct-binary-tree-from-preorder-and-postorder-traversal'):
            q={'title':slug,'source_refs':[{'url':'https://leetcode.com/problems/'+slug+'/description/'}]}
            report={'events':[]}
            with patch('courseagent.source_references.discover_reference') as discover:
                self.assertFalse(executable_source_gate(q, report));discover.assert_not_called()
            self.assertEqual(report['events'][0]['stage'],'output_contract')
        self.assertFalse(structural_issue({'title':'允许任意操作','source_refs':[]}))

    def test_driver_runtime_and_student_statement_use_same_order(self):
        from courseagent.programming_statement import prepare_statement
        q=question('two-sum',[('nums','integer[]'),('target','integer')], 'integer[]', [[2,7],9], [1,0])
        q['languages']=[{'language':'C','starter_code':''}]
        def ask(role,prompt,data):
            if role=='author':
                value=wording(q);value['task']='找出和为目标值的两个不同数组元素，输出其下标。';return value
            return {'passed':True,'issues':[]}
        def cache(kind,key,compute,**kwargs):return compute(),False
        prepare_statement(q,ask,cache)
        self.assertIn(ORDER_RULE,q['description'])
        namespace={};exec(runtime_source(),namespace)
        self.assertEqual(namespace['serialize_output'](q['io_contract'],[1,0]),'2\n0 1\n')
        self.assertIn('0 1',q['description'])

    def test_arbitrary_order_cannot_override_local_rule_even_if_model_passes(self):
        from courseagent.programming_statement import output_conflicts
        q=question('two-sum',[('nums','integer[]')], 'integer[]', [[2,7]], [1,0]);apply_output_policy(q)
        self.assertTrue(output_conflicts(q['io_contract'],{'task':'允许以任意顺序输出下标。'}))
        self.assertTrue(output_conflicts(q['io_contract'],{'task':'可以按任何顺序返回答案。'}))


class InputLayoutTests(unittest.TestCase):
    def test_sudoku_round_trip_preserves_all_cells_and_rejects_wrong_sizes(self):
        board=[list('53..7....')]+[list('.........') for _ in range(8)]
        q=question('valid-sudoku',[('board','character[][]')], 'boolean', [board], True)
        original=q['public_examples'][0]['input'];self.assertGreater(len(original.splitlines()),9)
        self.assertTrue(apply_input_policy(q));self.assertFalse(apply_input_policy(q))
        text=q['public_examples'][0]['input'];self.assertEqual(len(text.splitlines()),9)
        self.assertEqual(parse_input(q['io_contract'],text),[board])
        namespace={};exec(runtime_source(),namespace)
        self.assertEqual(namespace['parse_input'](q['io_contract'],text),[board])
        for bad in (text[:-2],text+'.........\n',text.replace('53..7....','5 3..7....')):
            with self.assertRaises(ValueError):parse_input(q['io_contract'],bad)


class IndependentCheckTests(unittest.TestCase):
    def test_binary_boundaries_duplicates_and_missing_targets(self):
        rng=random.Random(42)
        for _ in range(80):
            data=sorted(rng.randrange(-10,11) for _ in range(rng.randrange(1,35)))
            target=rng.randrange(-12,13)
            positions=[i for i,v in enumerate(data) if v==target]
            q=question('find-first-and-last-position-of-element-in-sorted-array', [('nums','integer[]'),('target','integer')],
                'integer[]',[data,target], [positions[0],positions[-1]] if positions else [-1,-1])
            case=q['public_examples'][0]
            self.assertEqual(check_case(q,case['input'],case['output'])['status'],'passed')
            self.assertEqual(check_case(q,case['input'],'2\n-9 -9\n')['status'],'mismatch')

    def test_tree_queue_encoding_with_internal_nulls_and_empty_root(self):
        for tree,rows in [([],[]),([1,None,2,3],[[1],[2],[3]]),([1,2,3,None,4],[[1],[2,3],[4]])]:
            q=question('binary-tree-level-order-traversal',[('root','TreeNode')], 'integer[][]',[tree],rows)
            case=q['public_examples'][0]
            self.assertEqual(check_case(q,case['input'],case['output'])['status'],'passed')
            self.assertEqual(check_case(q,case['input'],'1\n1\n-999\n')['status'],'mismatch')

    def test_wrong_sort_is_detected_and_unknown_task_remains_unassessed(self):
        q=question('sort-an-array',[('nums','integer[]')], 'integer[]',[[3,-2,3]],[-2,3,3])
        case=q['public_examples'][0]
        self.assertEqual(check_case(q,case['input'],case['output'])['status'],'passed')
        self.assertEqual(check_case(q,case['input'],'3\n3 3 -2\n')['status'],'mismatch')
        for field,value in [('answer_provenance',{'kind':'teacher'}),('origin','web_programming_adapted')]:
            adapted={**q,field:value}
            self.assertEqual(check_case(adapted,case['input'],'3\n3 3 -2\n')['status'],'unassessed')
        q['source_refs']=[];self.assertEqual(check_case(q,case['input'],case['output'])['status'],'unassessed')

    def test_wrong_reference_stops_after_counterexample_without_repeated_design(self):
        from courseagent.code_sandbox import available, execute
        from courseagent.programming_verification import build_verification_graph
        if not available():self.skipTest('隔离环境不可用')
        q=question('sort-an-array',[('nums','integer[]')], 'integer[]',[[1,2]],[1,2])
        q['source_protocol']='standard_io'
        q['source_refs'][0]['answer_status']='source_explicit'
        q['source_metadata']['interface']={'name':'sortArray','params':[{'name':'nums','type':'integer[]'}], 'return':{'type':'integer[]'}}
        q['source_reference']={'code':'class Solution:\n def sortArray(self, nums):\n  return nums',
            'language':'Python','url':'https://leetcode.cn/problems/sort-an-array/solutions/wrong/',
            'status':'public_editorial'}
        calls=[]
        def ask(role,prompt,data):
            calls.append(role)
            self.assertEqual(role,'test_designer')
            cases=[{'input':f'2\n{i} 0\n','purpose':'逆序','category':'adversarial','obligation_ids':['o']} for i in range(2,8)]
            return {'generator_code':'print('+repr(json.dumps({'cases':cases}))+')',
                'input_validator_code':'print("VALID")',
                'obligations':[{'id':'o','description':'检查逆序','category':'adversarial'},
                    {'id':'normal','description':'普通排序','category':'normal'},
                    {'id':'boundary','description':'最短序列','category':'boundary'}]}
        with tempfile.TemporaryDirectory() as tmp,patch('courseagent.programming_verification.ROOT',Path(tmp)):
            state=build_verification_graph(ask=ask,execute=execute,require_source=True).invoke({'question':q})
        self.assertFalse(state['result']['passed'])
        self.assertEqual(state['result']['failure']['code'],'independent_output')
        self.assertEqual(calls,['test_designer'])
        self.assertIn('counterexample',state['failures'][0])


class RecoveryBudgetTests(unittest.TestCase):
    def test_large_retained_inputs_have_a_small_exact_validator_and_a_bounded_generator(self):
        from courseagent.source_verification import retained_input_design
        from courseagent.code_sandbox import available,execute
        if not available():self.skipTest('隔离环境不可用')
        rng=random.Random(42)
        q=question('sort-an-array',[('nums','integer[]')],'integer[]',[[1,2]],[1,2])
        q['test_cases']=[{'input':serialize_input(q['io_contract'],[[rng.randrange(1000000) for _ in range(800)]]),
            'visibility':'hidden','purpose':'已验证排序输入','category':'normal'} for _ in range(12)]
        q['io_migration']={'input_provenance':'previously_source_validated_inputs_only',
            'assessment':{'obligations':[{'id':'a'}]}}
        retained=retained_input_design(q)
        self.assertIsNotNone(retained)
        validator=retained['designer']['input_validator_code']
        self.assertLess(len(validator),15000)
        self.assertLessEqual(len(retained['designer']['generator_code']),50000)
        self.assertEqual(execute(validator,q['test_cases'][0]['input'])['output'].strip(),'VALID')
        self.assertEqual(execute(validator,'2\n1 3\n')['output'].strip(),'INVALID')
        # Oversized packages yield to normal input design instead of generating
        # the identical oversized program on all three local retries.
        q['test_cases'] *= 3
        # Make the additional inputs distinct so compression cannot erase growth.
        for i,case in enumerate(q['test_cases']):
            q['test_cases'][i]={**case,'input':serialize_input(q['io_contract'],[[rng.randrange(1000000) for _ in range(800)]])}
        self.assertIsNone(retained_input_design(q))

    def run_failures(self, sequence):
        from courseagent.programming_sourcing import build_sourcing_graph
        calls=[]
        def collect(state):
            doc=copy.deepcopy(state['document']);report=doc.setdefault('programming_search',{})
            item=sequence[min(len(calls),len(sequence)-1)];calls.append(item)
            if item:
                key=recovery_key({'id':item},'course_fit')
                report['source_failure']={'code':'transport','stage':'course_fit','recovery_key':key}
                candidates=[]
            else:
                report.pop('source_failure',None);candidates=[{'id':'done'}]
            return {'document':doc,'programming_candidates':candidates,'programming_batches':1}
        state={'document':{},'request':{'source_mode':'web'},'spec':{'programming_count':1}}
        with patch('courseagent.programming_sourcing.source_programming_round',side_effect=collect):
            result=build_sourcing_graph().invoke(state)
        return calls,result

    def test_distinct_candidates_recover_without_stealing_each_others_retries(self):
        calls,state=self.run_failures(['a','a','b','b',None])
        self.assertEqual(len(calls),5)
        self.assertEqual(sorted(state['document']['programming_search']['source_retry_counts'].values()),[2,2])
        self.assertFalse(state['document']['programming_search'].get('source_failure'))

    def test_same_failure_stops_after_two_retries_and_preserves_stage(self):
        calls,state=self.run_failures(['a'])
        self.assertEqual(len(calls),3)
        self.assertEqual(retry_count(state['document']['programming_search']),2)
        self.assertEqual(state['document']['programming_search']['source_failure']['stage'],'course_fit')


class LocalHistoryTests(unittest.TestCase):
    def test_new_task_refreshes_history_instead_of_reusing_previous_documents_seed(self):
        from courseagent.agent_jobs import start,stop
        from tests.test_autonomous_agent import document
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);doc=document()
            doc['selection_policy']={'version':2,'history_mode':'local','history_group':'local_assignments',
                'seed':'previous-task','history':{'counts':{},'task_ids':[]}}
            snapshot={'counts':{'id:recent':1},'task_ids':['recent-task']}
            with patch('courseagent.selection_policy.usage_snapshot',return_value=snapshot) as history:
                job=start(root,doc,{'prompt':'栈作业'},[],{},execute=False)
            try:
                history.assert_called_once()
                with sqlite3.connect(root/'data/agent-tasks.sqlite') as db:
                    submission=json.loads(db.execute('select submission from tasks where id=?',(job['id'],)).fetchone()[0])
                policy=submission['request']['selection_policy']
                self.assertEqual(policy['seed'],job['id'])
                self.assertEqual(policy['history']['task_ids'],['recent-task'])
            finally:stop(root,job['id'])

    def test_local_groups_do_not_affect_production_or_each_other(self):
        from courseagent.selection_policy import usage_snapshot
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'data').mkdir()
            with sqlite3.connect(root/'data/agent-tasks.sqlite') as db:
                db.execute('create table tasks(id text,record text,updated real)')
                for i,(execute,group) in enumerate([(True,'g'),(False,'g'),(False,'other')]):
                    job={'execute':execute,'local_history_group':group,'status':'ready','target':{},
                        'result':{'questions':[{'id':str(i),'stem':'题目'+str(i),'type':3,'selected':True}]}}
                    db.execute('insert into tasks values(?,?,?)',(str(i),json.dumps(job),i))
            self.assertEqual(usage_snapshot(root,{})['task_ids'],['0'])
            self.assertEqual(usage_snapshot(root,{},execute=False,local_group='g')['task_ids'],['1'])


if __name__ == '__main__':
    unittest.main()
