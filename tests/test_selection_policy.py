import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from courseagent.selection_policy import identity_keys,usage_snapshot,task_family,link_priority,selection_report
from courseagent.workflow import pick_candidates
from courseagent.teaching_plan import coverage_report

class SelectionPolicyTests(unittest.TestCase):
    def q(self,identity,stem='下面说法正确的是',options=None):
        return {'id':identity,'type':1,'origin':'web','stem':stem,'options':options or ['甲','乙'],'selected':True}
    def test_different_option_tasks_survive_exact_dedup(self):
        a=self.q('a',options=['栈后进先出','栈先进先出']);b=self.q('b',options=['二分要求有序','顺序要求有序'])
        state={'spec':{'counts':{'1':2}},'request':{'use_model':True},'document':{'questions':[a,b]}}
        selected,missing=pick_candidates(state,[a,b]);self.assertEqual(len(selected),2);self.assertFalse(missing)
    def test_reordered_options_are_still_exact_duplicates(self):
        a=self.q('a');b=self.q('b',options=['乙','甲'])
        self.assertEqual(identity_keys(a)[1:],identity_keys(b)[1:])
    def test_same_source_with_changed_options_cannot_evade_dedup(self):
        a=self.q('a');b={**self.q('b',options=['丙','丁']),'base_question_id':'a'}
        selected,_=pick_candidates({'spec':{'counts':{'1':2}},'request':{},'document':{}},[a,b])
        self.assertEqual(len(selected),1)
    def test_recent_questions_lose_ties_but_remain_available(self):
        a=self.q('a','栈出栈操作');b=self.q('b','栈压栈操作')
        context={'seed':'fixed','history':{'counts':{identity_keys(a)[0]:2}}}
        state={'spec':{'counts':{'1':1}},'request':{'use_model':True,'selection_policy':context},'document':{}}
        selected,_=pick_candidates(state,[a,b]);self.assertEqual(selected[0]['id'],'b')
        selected,missing=pick_candidates(state,[a]);self.assertEqual(selected[0]['id'],'a');self.assertFalse(missing)
    def test_locked_selection_wins_over_history(self):
        a=self.q('a','栈出栈操作');b=self.q('b','队列入队操作')
        state={'spec':{'counts':{'1':1},'locked_ids':['a']},'request':{'selection_policy':{'seed':'x','history':{'counts':{identity_keys(a)[0]:5}}}},'document':{}}
        self.assertEqual(pick_candidates(state,[a,b])[0][0]['id'],'a')
    def test_seed_is_stable_under_input_permutation_and_varies_between_runs(self):
        qs=[self.q(str(i),'栈操作'+str(i)) for i in range(15)]
        def select(seed,pool):
            return [q['id'] for q in pick_candidates({'spec':{'counts':{'1':3}},'request':{'use_model':True,'selection_policy':{'seed':seed}},'document':{}},pool)[0]]
        self.assertEqual(select('a',qs),select('a',list(reversed(qs))))
        self.assertNotEqual(select('a',qs),select('b',qs))
    def test_usage_is_scoped_success_only_and_excludes_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'data').mkdir();db=sqlite3.connect(root/'data/agent-tasks.sqlite');db.execute('create table tasks(id text,record text,updated real)')
            target={'classroom_url':'https://example/classrooms/a','course':'数据结构'}
            base={'status':'completed','execute':True,'target':target,'result':{'questions':[self.q('a')]}}
            for i,changes in enumerate([{}, {'status':'needs_attention'}, {'execute':False},{'purpose':'development_test'},{'target':{**target,'course':'另一课程'}}]):
                db.execute('insert into tasks values(?,?,?)',(str(i),json.dumps({**base,**changes}),i))
            db.commit();db.close();value=usage_snapshot(root,target)
            self.assertEqual(value['task_ids'],['0']);self.assertEqual(value['counts']['id:a'],1)
            self.assertFalse(usage_snapshot(root,target,exclude_id='0')['counts'])
    def test_programming_canonical_identity_ignores_leetcode_domain(self):
        q={'id':'a','title':'题','description':'题意','source_refs':[{'url':'https://leetcode.cn/problems/two-sum/'}]}
        other={**q,'id':'b','source_refs':[{'url':'https://leetcode.com/problems/two-sum/description/'}]}
        self.assertIn('url:leetcode:two-sum',set(identity_keys(q))&set(identity_keys(other)))
    def test_programming_coverage_includes_aliases_and_excludes_answer_text(self):
        q={'id':'p','title':'验证二叉搜索树','description':'some text','knowledge':'二叉搜索树','selected':True}
        d={'questions':[],'programming_questions':[q],'plan':{'spec':{'teaching_plan':{'goals':[{'id':'g','name':'搜索树','keywords':['二叉排序树'],'suggested_count':1}]}}}}
        report=coverage_report(d);self.assertEqual(report['goals'][0]['matched_ids'],['p']);self.assertEqual(report['programming_count'],1)
        q.update(title='题目',knowledge='',explanation='二叉排序树');self.assertEqual(coverage_report(d)['unmatched_ids'],['p'])
    def test_related_rotated_array_tasks_share_family(self):
        titles=['搜索旋转排序数组','搜索旋转排序数组 II','寻找旋转排序数组中的最小值']
        self.assertEqual(len({task_family({'title':title}) for title in titles}),1)
    def test_discovery_prefers_uncovered_topics_and_unused_sources(self):
        stack={'title':'栈操作','knowledge':'栈'};a={'title':'栈操作2','url':'https://leetcode.cn/problems/stack/','discovery_topics':['stack']};b={'title':'队列操作','url':'https://leetcode.cn/problems/queue/','discovery_topics':['queue']}
        self.assertLess(link_priority(b,[stack],{},['栈','队列']),link_priority(a,[stack],{},['栈','队列']))
    def test_empty_programming_pool_does_not_create_variant_group(self):
        q={'title':'新任务','description':'题意','id':'p','selected':True}
        self.assertEqual(selection_report({'programming_questions':[q]},{} )['selected_count'],1)


class SourceReadRecoveryTests(unittest.TestCase):
    def test_source_trailing_space_slot_is_restored_without_inventing_a_gap(self):
        from courseagent.web_questions import normalize_candidate
        from courseagent.questions import validate_question
        stem='设循环队列的容量为70，front为20，rear为11，则队列中元素的个数为 。'
        answer='答案：61'
        page={'url':'https://example.org/exercise','title':'循环队列填空题',
              'text':stem+'\n'+answer,'retrieved_at':'2026-10-18'}
        item={'type':4,'stem':stem,'stem_evidence':stem,'blanks':['61'],'answer_evidence':answer}
        q=normalize_candidate(item,page,model_interpreted=True);validate_question(q)
        self.assertIn('为（ ）',q['stem']);self.assertEqual(q['blanks'],['61'])
        self.assertEqual(q['source_refs'][0]['stem_evidence'],stem)
        item['stem_evidence']=stem.replace('为 。','为。')
        page['text']=item['stem_evidence']+'\n'+answer
        with self.assertRaisesRegex(ValueError,'空位标记'):
            normalize_candidate(item,page,model_interpreted=True)
    def test_timeout_does_not_poison_next_source_read_for_five_minutes(self):
        from courseagent.web_questions import read_page
        html='<html><title>题目</title><body>'+('输入描述 输出描述 栈的公开练习。'*30)+'</body></html>'
        url='https://example.org/problem'
        with tempfile.TemporaryDirectory() as tmp,patch('courseagent.web_questions.CACHE',Path(tmp)),patch('courseagent.web_questions.fetch',side_effect=[TimeoutError('timed out'),(html,url)]) as fetch:
            with self.assertRaises(TimeoutError):read_page(url)
            page,hit=read_page(url)
            self.assertEqual(fetch.call_count,2);self.assertIn('公开练习',page['text']);self.assertFalse(hit)

class ReplacementTraceTests(unittest.TestCase):
    def test_source_recovery_resumes_unfinished_sibling_before_inspecting(self):
        from courseagent.autonomous_agent import build_agent
        from tests.test_autonomous_agent import document
        for branch,field,failure in [('ordinary','web_search','adaptation_failure'),
                                     ('programming','programming_search','source_failure')]:
            with self.subTest(branch=branch):
                doc=document();doc[field]={failure:{'code':'transport'}}
                doc['programming_questions']=[{'id':'pending','selected':True,
                    'verification_state':{'stage':'source_design','status':'running'}}]
                def recovered(d,*args):
                    d=copy.deepcopy(d);d[field].pop(failure,None);return d
                def reached_verification(payload):
                    self.assertTrue(payload['document']['programming_questions'][0]['selected'])
                    raise RuntimeError('reached unfinished verification')
                with patch('courseagent.workflow.recover_ordinary_sources',side_effect=recovered), \
                     patch('courseagent.workflow.recover_programming_sources',side_effect=recovered), \
                     patch('courseagent.verification_tools.verify_ordinary_answers') as ordinary, \
                     patch('courseagent.verification_tools.verify_programming_answers') as coding, \
                     patch('courseagent.autonomous_agent.check_document') as inspector:
                    ordinary.invoke.side_effect=lambda p:{'document':p['document']}
                    coding.invoke.side_effect=reached_verification
                    with self.assertRaisesRegex(RuntimeError,'reached unfinished verification'):
                        build_agent().invoke({'document':doc,'request':{'prompt':'测试'},'sources':[],
                                              'rounds':1,'events':[],'resume':True})
                    inspector.assert_not_called()
    def test_intermediate_replacement_is_not_marked_as_finally_delivered(self):
        from courseagent.autonomous_agent import build_agent
        from tests.test_autonomous_agent import document
        doc=document();old=doc['questions'][0]['id'];calls=[]
        def planner(d,r,s):
            calls.append(1)
            if len(calls)>1:
                prior=next(q for q in d['questions'] if q['id']==(old if len(calls)==2 else 'replacement-b'))
                d['questions'].append({**prior,'id':'replacement-b' if len(calls)==2 else 'replacement-c','selected':True})
            return d
        def checker(d):
            bad=old if len(calls)==1 else 'replacement-b'
            return {'blocking':len(calls)<3,'issues':[{'kind':'answer','severity':'blocking','question_ids':[bad],'message':'明确内容缺陷'}] if len(calls)<3 else []}
        out=build_agent(planner,checker,lambda *a:{'action':'search','reason':'替换有缺陷的题目'}).invoke({'document':doc,'request':{'prompt':'测试'},'sources':[],'rounds':0,'events':[]})
        history=out['document']['replacement_history']
        self.assertEqual([(h['old_id'],h['new_id'],h['status']) for h in history],[(old,'replacement-b','replaced_again'),('replacement-b','replacement-c','passed_final_validation')])

if __name__=='__main__':unittest.main()
