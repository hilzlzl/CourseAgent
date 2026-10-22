import copy
import unittest
from unittest.mock import patch

from courseagent.stdio_contract import make_contract,serialize_input,serialize_output
from courseagent.programming_statement import prepare_statement,needs_statement,render,payload,validate_wording


def fixture(params=None,output='ListNode',source=None):
    metadata={'name':'solve','params':[{'name':n,'type':t} for n,t in (params or [('head','ListNode'),('n','integer')])],
              'return':{'type':output}}
    source=source or '给定链表，删除倒数第 n 个结点，返回头结点。\n\n示例 1：\n输入：head=[1],n=1\n输出：[]\n\n提示：\n链表中结点的数目为 sz\n1 <= sz <= 30\n1 <= n <= sz'
    return {'title':'测试任务','source_description':source,'source_metadata':{'provider':'leetcode'},
            'io_contract':make_contract(metadata,source),'description':'旧题面','languages':[{'language':'C','starter_code':''}],
            'public_examples':[{'input':'1\n1\n1\n','output':'0\n\n'}],
            'test_cases':[{'input':'2\n1 2\n1\n','output':'1\n1\n','visibility':'hidden'}]}


def wording(q):
    c=q['io_contract'];ms=[c] if c['kind']=='function' else [c['constructor']]+c['methods']
    return {'task':'读取链表及删除位置 n，删除倒数第 n 个结点，输出删除后链表的结点值。',
            'methods':[{'params':[{'name':p['name'],'label':'待处理链表' if p['type']=='ListNode' else '参数 '+p['name'],
                                   'empty':'unspecified','empty_evidence':''} for p in m['params']],
                        'result':'处理后链表'} for m in ms]}


class StatementTests(unittest.TestCase):
    def setUp(self):
        self.cache_values={}
    def cache(self,kind,key,compute,ttl=None,validate=None):
        k=(kind,key);hit=k in self.cache_values
        result=copy.deepcopy(self.cache_values[k]) if hit else compute()
        if validate:validate(result)
        self.cache_values[k]=copy.deepcopy(result)
        return result,hit
    def test_rewrite_preserves_codec_cases_constraints_and_invalidates_evidence(self):
        q=fixture();before=copy.deepcopy(q);calls=[]
        q['platform_description']='stale rendered prose'
        q['execution_verification']={'passed':True,'basis':'stale'}
        def ask(role,prompt,data):
            calls.append(role)
            return wording(q) if role=='author' else {'passed':True,'issues':[]}
        self.assertTrue(prepare_statement(q,ask,self.cache))
        for field in ('io_contract','test_cases','public_examples','source_description','languages'):
            self.assertEqual(q[field],before[field])
        self.assertIn('输入结点个数',q['description']);self.assertIn('参数 n',q['description'])
        self.assertNotIn('个数 n',q['description']);self.assertNotIn('头结点',q['description'])
        self.assertNotIn('仅在原题',q['description']);self.assertNotIn('计算结果',q['description'])
        self.assertIn('1 <= n <= sz',q['description']);self.assertNotIn('execution_verification',q)
        self.assertNotIn('platform_description',q)
        self.assertTrue(q['description_includes_examples']);self.assertEqual(q['description_format'],'markdown')
        self.assertFalse(prepare_statement(q,ask,self.cache));self.assertEqual(calls,['author','validator'])
        q['description']+='manual edit';self.assertTrue(needs_statement(q))
    def test_failure_is_atomic_and_local_correction_does_not_search(self):
        q=fixture();original=copy.deepcopy(q);calls=[]
        def reject(role,prompt,data):
            calls.append(role)
            return wording(q) if role=='author' else {'passed':False,'issues':['遗漏了一个原题限制']}
        with self.assertRaisesRegex(ValueError,'保留来源'):
            prepare_statement(q,reject,self.cache)
        self.assertEqual({k:v for k,v in q.items() if k not in ('verification_state','statement_adaptation_retry')},original)
        self.assertEqual(calls,['author','validator','author'])
        self.assertEqual(q['statement_adaptation_retry']['revision'],1)
        # An explicit continuation revises the last failed draft rather than
        # becoming permanently stuck behind the same rejected cached wording.
        def resume(role,prompt,data):
            if role=='author':
                self.assertEqual(data['revision'],1)
                self.assertEqual(data['correction'],['遗漏了一个原题限制'])
                result=wording(q);result['task']+='补齐原题限制。';return result
            return {'passed':True,'issues':[]}
        self.assertTrue(prepare_statement(q,resume,self.cache))
        self.assertNotIn('statement_adaptation_retry',q)

    def test_audited_prose_transfer_preserves_mapping_but_manual_edits_invalidate_it(self):
        from courseagent.teaching_plan import alignment_basis,goal_evidence
        goals=[{'id':'g','name':'链表操作','keywords':['链表']}]
        q=fixture();q['description']=q['source_description']
        q['course_fit']={'fit':True,'alignment_basis':alignment_basis(q,goals),'goal_alignment':[
            {'goal_id':'g','relation':'direct','evidence':'删除倒数第 n 个结点','assessment_action':'删除链表结点'}]}
        def ask(role,prompt,data):return wording(q) if role=='author' else {'passed':True,'issues':[]}
        prepare_statement(q,ask,self.cache)
        mapping=goal_evidence(q,goals)[0]
        self.assertEqual(mapping['kind'],'direct')
        self.assertEqual(mapping['evidence_origin'],'audited_source_statement')
        q['description']='新的链表任务，考点已改变。'
        self.assertEqual(goal_evidence(q,goals)[0]['kind'],'keyword')
    def test_one_local_semantic_correction_can_pass(self):
        q=fixture();calls=[]
        def ask(role,prompt,data):
            calls.append(role)
            if role=='author':
                result=wording(q)
                if 'correction' in data:result['task']+='不得修改保留结点的值。'
                return result
            return {'passed':len(calls)==4,'issues':[] if len(calls)==4 else ['遗漏操作限制']}
        prepare_statement(q,ask,self.cache)
        self.assertEqual(calls,['author','validator','author','validator'])
        self.assertIn('不得修改',q['description'])
    def test_missing_parameters_or_unsupported_empty_claim_are_rejected(self):
        q=fixture();w=wording(q);w['methods'][0]['params'].pop()
        with self.assertRaisesRegex(ValueError,'全部输入参数'):validate_wording(w,payload(q))
        w=wording(q);w['methods'][0]['params'][0].update(empty='allowed',empty_evidence='题目一定允许空链表')
        with self.assertRaisesRegex(ValueError,'原题依据'):validate_wording(w,payload(q))
    def test_scalar_names_and_empty_sample_lines_are_preserved_in_display(self):
        q=fixture();w=wording(q);w['methods'][0]['params'][1]['label']='倒数位置'
        text=render(payload(q),w)
        self.assertIn('倒数位置 n：',text)
        self.assertIn('```text\n0\n\n```',text)
    def test_teacher_answers_approved_and_standard_io_sources_are_untouched(self):
        for field,value in [('answer_provenance',{'kind':'teacher'}),('approved',True),('io_contract',None)]:
            q=fixture();q[field]=value;original=copy.deepcopy(q)
            self.assertFalse(prepare_statement(q,lambda *args:self.fail('must not call model'),self.cache));self.assertEqual(q,original)
    def test_varied_encodings_are_rendered_without_changing_any_sample_bytes(self):
        fixtures=[([('nums','integer[]'),('len','integer')],'boolean','数组',[[1,2],3],True),
                  ([('grid','integer[][]')],'integer[][]','矩阵',[[[1,2],[3,4]]],[[3,4],[1,2]]),
                  ([('rows','integer[][]')],'integer[]','邻接表',[[[],[1,2]]],[1]),
                  ([('s','string'),('words','string[]')],'string','字符串',[' a ',['','two words']],'true'),
                  ([('root','TreeNode')],'TreeNode','二叉树',[[1,None,2]],[2,None,1])]
        for params,out,source,values,result in fixtures:
            q=fixture(params,out,source);c=q['io_contract']
            q['public_examples']=[{'input':serialize_input(c,values),'output':serialize_output(c,result)}]
            original=copy.deepcopy(q['public_examples']);text=render(payload(q),wording(q))
            self.assertEqual(q['public_examples'],original)
            for e in original:
                self.assertIn(e['input'].rstrip('\n'),text);self.assertIn(e['output'].rstrip('\n'),text)
            if params[0][0]=='nums':
                self.assertNotIn('个数 len',text);self.assertIn('参数 len',text);self.assertIn('1 或 0',text)
    def test_operations_preserve_command_names_and_void_output_policy(self):
        q=fixture();q['io_contract']=make_contract({'classname':'Stack','constructor':{'params':[]},'methods':[
            {'name':'push','params':[{'name':'x','type':'integer'}],'return':{'type':'void'}},
            {'name':'pop','params':[],'return':{'type':'integer'}}]})
        text=render(payload(q),wording(q))
        for expected in ('第一个操作必须为 Stack','push：','pop：','无返回值的操作不输出'):
            self.assertIn(expected,text)
        output=text.split('### 输出格式')[1].split('### 数据范围')[0]
        self.assertNotIn('push：',output)
    def test_tree_codec_distinguishes_null_tokens_and_respects_empty_boundary(self):
        q=fixture([('root','TreeNode')],'boolean',
                  '判断是否为二叉搜索树。\n\n提示：\n树中节点数目范围为 [1, 10000]')
        w=wording(q)
        w['methods'][0]['params'][0].update(empty='forbidden',empty_evidence='[1, 10000]')
        validate_wording(w,payload(q))
        text=render(payload(q),w)
        self.assertIn('# 也计入编码项总数',text)
        self.assertNotIn('空树',text)
        self.assertIn('不改变合法输入的范围',text)
        q['source_description']='判断是否为二叉搜索树。\n\n提示：\n树中节点数目范围为 [0, 10000]'
        w['methods'][0]['params'][0].update(empty='allowed',empty_evidence='[0, 10000]')
        validate_wording(w,payload(q))
        self.assertIn('空树的编码项总数为 0',render(payload(q),w))
    def test_empty_nested_output_description_matches_the_actual_serializer(self):
        q=fixture([('root','TreeNode')],'integer[][]','按二叉树层序遍历返回各层结点值，可返回空数组。')
        self.assertEqual(q['io_contract']['output']['kind'],'array')
        encoded=serialize_output(q['io_contract'],[])
        self.assertEqual(encoded,'0\n')
        q['public_examples']=[{'input':'0\n\n','output':encoded}]
        text=render(payload(q),wording(q));output=text.split('### 输出格式')[1].split('### 样例输入')[0]
        self.assertIn('只输出一行 0',output)
        self.assertNotIn('第二行留空',output)
    def test_indented_constraints_from_task_1129_are_preserved_and_stale_proof_expires(self):
        q=fixture([('numCourses','integer'),('prerequisites','integer[][]')],'integer[]',
                  '输出合法的课程学习顺序。\n\n 示例 1：\n输入：numCourses = 1, prerequisites = []\n输出：[0]\n\n 提示：  \n\n'
                  '` 1 <= numCourses <= 2000 `\n\n` prerequisites[i].length == 2 `')
        q['public_examples']=[{'input':'1\n0\n','output':'1\n0\n'}]
        w=wording(q)
        prepare_statement(q,lambda role,*args:w if role=='author' else {'passed':True,'issues':[]},self.cache)
        self.assertIn('### 数据范围',q['description'])
        self.assertIn('` 1 <= numCourses <= 2000 `',q['description'])
        self.assertIn('` prerequisites[i].length == 2 `',q['description'])
        self.assertFalse(needs_statement(q))
        from courseagent.programming_statement import digest
        # A legacy receipt may match its own text while the renderer omitted
        # the indented range section. It must be audited again under the fix.
        q['description']=q['description'].split('### 数据范围')[0]
        q['statement_adaptation']['description_digest']=digest(q['description'])
        self.assertTrue(needs_statement(q))
    def test_validated_hidden_inputs_can_be_replayed_but_old_report_not_rebased(self):
        q=fixture();old={'passed':True,'basis':'old','case_basis':'cases','method':'source','source_evidence':{'ok':True},'assessment':{'obligations':[{'id':'boundary'}]}}
        with patch('courseagent.programming_verification.current_report',return_value=old):
            prepare_statement(q,lambda role,*args:wording(q) if role=='author' else {'passed':True,'issues':[]},self.cache)
        self.assertNotIn('execution_verification',q)
        self.assertEqual(q['io_migration']['input_provenance'],'previously_source_validated_inputs_only')


if __name__=='__main__':unittest.main()
