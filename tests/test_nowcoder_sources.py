import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from courseagent.nowcoder_sources import search_questions,parse_question

class NowcoderSourceTests(unittest.TestCase):
    def test_independent_tags_and_pagination(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            return json.dumps({'code':0,'data':{'problemCount':45,'problemSets':[{'name':'测试','problemId':11 if '581' in url else 22,'problemType':0,'tagList':[]}]}}),url
        with tempfile.TemporaryDirectory() as tmp,patch('courseagent.web_questions.CACHE',Path(tmp)),patch('courseagent.nowcoder_sources.tag_catalog',return_value={'栈':581,'队列':582}),patch('courseagent.nowcoder_sources.fetch_text',side_effect=fetch):
            items,hit,page=search_questions(['栈','队列'],offset=20,with_page=True)
        self.assertEqual(len(items),2);self.assertTrue(all('page=2' in url for url in calls));self.assertEqual(sum('tagId=' in url for url in calls),2);self.assertTrue(all(url.count('tagId=')<=1 for url in calls));self.assertTrue(page['has_more']);self.assertEqual(page['next_offset'],40)
    def test_extracts_formula_and_samples_once(self):
        html='<div class="question-title">栈</div><div class="subject-describe">实现栈<img src="https://www.nowcoder.com/equation?tex=1%20%5Cleq%20n%20%5Cleq%20100000"/><h2>输入描述:</h2>输入n<h2>输出描述:</h2>输出结果<div class="question-oi"><div class="question-oi-mod"><h2>输入</h2><textarea>3\n1 2 3</textarea><div class="question-oi-cont"><pre>3\n1 2 3</pre></div></div><div class="question-oi-mod"><h2>输出</h2><div class="question-oi-cont"><pre>6</pre></div></div></div></div>'
        q=parse_question(html,'https://ac.nowcoder.com/acm/problem/11')
        self.assertEqual(q['source_examples'],[{'input':'3\n1 2 3','output':'6'}]);self.assertIn('\\leq',q['text']);self.assertEqual(q['text'].count('1 2 3'),1);self.assertEqual(q['source_metadata']['interface_kind'],'standard_io')
    def test_missing_statement_is_not_accepted(self):
        with self.assertRaises(ValueError):parse_question('<html>请登录</html>','https://ac.nowcoder.com/acm/problem/11')
    def test_native_candidate_preserves_statement_samples_and_has_no_trusted_code(self):
        from courseagent.native_questions import nowcoder_candidate
        from courseagent.programming_questions import platform_description
        page={'url':'https://ac.nowcoder.com/acm/problem/11','title':'栈',
              'source_metadata':{'provider':'nowcoder','interface_kind':'standard_io'},
              'source_statement':'实现栈。\n输入描述\n输入n\n输出描述\n输出栈顶\n输入\n1\n输出\n2',
              'source_examples':[{'input':'1','output':'2'}]}
        q=nowcoder_candidate(page,['C','C++'])
        self.assertEqual(q['description'],page['source_statement'])
        self.assertEqual(q['public_examples'],page['source_examples'])
        self.assertEqual(q['source_protocol'],'standard_io');self.assertFalse(q['approved'])
        self.assertFalse(q['test_cases'][0]['verified']);self.assertEqual(q['reference_code'],'')
        self.assertEqual(q['source_refs'][0]['method'],'native_structured_question')
        self.assertEqual(platform_description(q).count('公开样例'),0)
        page['source_metadata']['interface_kind']='function'
        self.assertIsNone(nowcoder_candidate(page,['C']))

if __name__=='__main__':unittest.main()
