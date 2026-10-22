import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
from courseagent.programming_sourcing import candidate_topic_matches


class TopicFitTests(unittest.TestCase):
    def test_incidental_queue_does_not_make_tree_task_a_queue_task(self):
        q={'title':'按层次插入二叉树并前序遍历','knowledge':'二叉树，遍历',
           'description':'使用队列进行层序构建，再输出树的前序遍历。'}
        self.assertFalse(candidate_topic_matches(['栈','队列'],q))
        self.assertTrue(candidate_topic_matches(['二叉树'],q))

    def test_direct_topic_and_standard_applications_remain_candidates(self):
        self.assertTrue(candidate_topic_matches(['栈'],{'title':'有效括号','knowledge':'字符串'}))
        self.assertTrue(candidate_topic_matches(['队列'],{'title':'用队列实现栈','knowledge':''}))
        self.assertTrue(candidate_topic_matches(['排序算法'],{'title':'合并排序序列','knowledge':''}))

    def test_course_mapping_keeps_only_grounded_actions_without_extra_model_call(self):
        from courseagent.programming_sourcing import native_course_fit
        from courseagent.teaching_plan import goal_evidence
        goals=[{'id':'g1','name':'队列应用','keywords':['队列']},
               {'id':'g2','name':'操作实现','keywords':['实现']}]
        q={'title':'卡牌轮转','description':'取出队首，将下一张卡牌移到队尾。','knowledge':'队列'}
        s={'request':{'prompt':'队列编程题'},'spec':{'topics':['队列'],'teaching_plan':{'goals':goals}}}
        response={'fit':True,'reason':'队列模拟','task_family':'轮转','goal_alignment':[
            {'goal_id':'g1','relation':'application','evidence':'取出队首','assessment_action':'模拟队列轮转'},
            {'goal_id':'g2','relation':'direct','evidence':'虚构的题面要求','assessment_action':'实现队列'},
            {'goal_id':'unknown','relation':'direct','evidence':'取出队首','assessment_action':'动作'}]}
        report={}
        with tempfile.TemporaryDirectory() as tmp,patch('courseagent.web_questions.CACHE',Path(tmp)),\
             patch('courseagent.model_client.model_status',return_value={'model':'fixture'}),\
             patch('courseagent.programming_sourcing.ask_role',return_value=response) as model:
            self.assertTrue(native_course_fit(q,s,report))
        self.assertEqual(model.call_count,1)
        self.assertEqual(model.call_args.args[2]['teaching_goals'][0]['id'],'g1')
        self.assertEqual(len(q['course_fit']['goal_alignment']),1)
        self.assertEqual(goal_evidence(q,goals)[0]['kind'],'application')


if __name__=='__main__':unittest.main()
