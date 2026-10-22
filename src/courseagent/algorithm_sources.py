"""Public LeetCode search/detail/editorial adapter; no login or submission access."""
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from bs4 import BeautifulSoup

TAGS={'栈':'stack','队列':'queue','链表':'linked-list','二叉树':'binary-tree','树':'tree','排序':'sorting','排序算法':'sorting','图':'graph','查找':'binary-search','查找算法':'binary-search','堆':'heap-priority-queue'}
TAGS.update({'折半查找':'binary-search','二分查找':'binary-search',
             '二叉排序树':'binary-search-tree','二叉搜索树':'binary-search-tree',
             '散列查找':'hash-table','哈希查找':'hash-table'})
# Course requests often name the traversal algorithm instead of the chapter
# name.  These are graph discovery aliases, not proof that every returned
# problem is a DFS/BFS exercise; the later page reader and course-fit review
# still decide eligibility from the actual statement.
TAGS.update({
    '深度优先搜索':'depth-first-search', '广度优先搜索':'breadth-first-search',
    'DFS':'depth-first-search', 'BFS':'breadth-first-search', '图遍历':'graph',
    '邻接表':'graph', '邻接矩阵':'graph', '连通图':'graph',
})


def graphql(query, variables):
    request=Request('https://leetcode.cn/graphql/',json.dumps({'query':query,'variables':variables}).encode(),
                    {'Content-Type':'application/json','User-Agent':'Mozilla/5.0'})
    with urlopen(request,timeout=18) as response:
        raw=response.read(2_000_001)
        if len(raw)>2_000_000:raise ValueError('公开题库响应过大')
        value=json.loads(raw)
    if value.get('errors'):raise ValueError('公开题库接口暂不可用')
    return value['data']


def search_questions(topics, difficulty=0, *, offset=0, with_page=False):
    from courseagent.web_questions import cached
    # Several course topics mean union, not LeetCode's multi-tag intersection.
    tags=list(dict.fromkeys(TAGS[t] for t in topics if t in TAGS))[:4]
    tags.sort(key=lambda tag:tag=='graph')
    unknown=[topic for topic in dict.fromkeys(topics) if topic.strip() and topic not in TAGS
             and not (tags and topic in ('数据结构','算法','课程','搜索'))]
    groups=[{'tags':[tag]} for tag in tags[:3 if unknown else 4]]
    groups += [{'searchKeywords':topic} for topic in unknown[:4-len(groups)]]
    if type(offset) is not int or offset<0:raise ValueError('题库分页位置不正确')
    if not groups:
        result=([],False,{'offset':offset,'next_offset':offset,'has_more':False,'total':0})
        return result if with_page else result[:2]
    query='query($filters:QuestionListFilterInput,$skip:Int!){problemsetQuestionList(categorySlug:"",limit:20,skip:$skip,filters:$filters){total questions{title titleSlug difficulty paidOnly}}}'
    def compute():
        batches=[];errors=[]
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(4,len(groups))) as pool:
            jobs=[pool.submit(graphql,query,{'filters':filters,'skip':offset}) for filters in groups]
            for job in jobs:
                try:batches.append(job.result()['problemsetQuestionList'])
                except (ValueError,OSError,KeyError) as error:errors.append(type(error).__name__)
        # Advancing a shared offset after a partial failure would skip the
        # failed topic's unseen questions. Retry that page as a whole instead.
        if errors:raise ValueError('公开题库检索不可用：'+','.join(errors))
        items=[];seen={}
        for position in range(20):
            for filters,batch in zip(groups,batches):
                questions=batch['questions']
                if position>=len(questions):continue
                item=questions[position];slug=item.get('titleSlug','')
                if item.get('paidOnly') or not re.fullmatch(r'[a-z0-9-]+',slug):continue
                labels=filters.get('tags') or [filters.get('searchKeywords','')]
                if slug in seen:
                    seen[slug]['discovery_topics']=list(dict.fromkeys(seen[slug]['discovery_topics']+labels));continue
                item={**item,'discovery_topics':labels};seen[slug]=item;items.append(item)
        has_more=any(offset+len(b['questions'])<b['total'] if isinstance(b.get('total'),int)
                     else len(b['questions'])==20 for b in batches)
        return {'items':items,'pagination':{'offset':offset,'next_offset':offset+20,
                'has_more':has_more,'total':sum(b.get('total',len(b['questions'])) for b in batches)}}
    page,hit=cached('leetcode-search-v4',json.dumps({'groups':groups,'offset':offset},sort_keys=True),compute)
    items=list(page['items'])
    desired={1:'EASY',2:'MEDIUM',3:'HARD'}.get(difficulty)
    items.sort(key=lambda p:(bool(desired and p.get('difficulty','').upper()!=desired),p.get('difficulty','').upper()=='HARD'))
    result=([{'url':'https://leetcode.cn/problems/'+p['titleSlug']+'/', 'title':p.get('titleCn') or p['title'],
             'engine':'leetcode_public','source_difficulty':p.get('difficulty'),
             'discovery_topics':p.get('discovery_topics',[])} for p in items],hit,page['pagination'])
    return result if with_page else result[:2]


def canonical_url(url):
    p=urlparse(url)
    if (p.scheme not in ('http','https') or p.username or p.password or p.port not in (None,80,443)
            or p.hostname not in ('leetcode.cn','www.leetcode.cn','leetcode.com','www.leetcode.com')):
        return None
    match=re.fullmatch(r'/problems/([a-z0-9-]+)(?:/(?:description|solutions|solution|editorial)(?:/[^?#]*)?)?/?',p.path)
    return 'https://leetcode.cn/problems/'+match[1]+'/' if match else None


def supports(url):
    return canonical_url(url) is not None


def extract_examples(statement_html):
    """Read legacy pre blocks and current paragraph/example-block layouts."""
    soup=BeautifulSoup(statement_html,'html.parser')
    blocks=soup.select('pre, .example-block')
    raw='\n'.join(block.get_text(' ',strip=True) for block in blocks)
    # Current statements also use adjacent paragraphs outside any wrapper.
    if not re.search(r'(?:输入|Input)\s*[:：]',raw):raw=soup.get_text(' ',strip=True)
    pattern=(r'(?:输入|Input)\s*[:：]\s*(.*?)\s*(?:输出|Output)\s*[:：]\s*'
             r'(.*?)(?=\s*(?:(?:解释|说明|Explanation|示例|Example|提示|Constraints|约束|输入|Input)'
             r'\s*(?:\d+\s*)?[:：]|$))')
    examples=[]
    for match in re.finditer(pattern,raw,re.S|re.I):
        item={'input':match[1].strip(),'output':match[2].strip()}
        if item['output'] and item not in examples:examples.append(item)
    return examples


def statement_text(statement_html):
    soup = BeautifulSoup(statement_html, 'html.parser')
    for tag in soup.find_all(['sup', 'sub']):
        tag.replace_with(('^' if tag.name == 'sup' else '_') + '(' + tag.get_text('', strip=True) + ')')
    soup.smooth()
    # Inline tags belong to the same sentence; only block boundaries add lines.
    for tag in soup.find_all('br'):tag.replace_with('\n')
    for tag in soup.find_all(['p','div','li','pre','h1','h2','h3','h4']):
        tag.insert_before('\n\n');tag.insert_after('\n\n')
    return re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+','\n\n',soup.get_text('',strip=False).replace('\xa0',' ')).strip()


def statement_markdown(statement_html):
    """Keep source paragraphs and literal sample/code contents in Markdown."""
    from bs4 import NavigableString
    from courseagent.platform_format import markdown_literal,code_block
    soup=BeautifulSoup(statement_html,'html.parser')
    literals=[]
    for tag in soup.find_all(['sup','sub']):
        tag.replace_with(('^' if tag.name=='sup' else '_')+'('+tag.get_text('',strip=True)+')')
    def render(node):
        if isinstance(node,NavigableString):
            return markdown_literal(re.sub(r'\s+',' ',str(node).replace('\xa0',' ')))
        if node.name in ('script','style'):return ''
        if node.name=='pre':
            key='\x00PRE'+str(len(literals))+'\x00'
            literals.append(code_block(node.get_text('',strip=False).strip('\n')))
            return '\n\n'+key+'\n\n'
        if node.name=='code':
            value=node.get_text('',strip=False).replace('\xa0',' ')
            fence='`'*max(1,max((len(m[0])+1 for m in re.finditer(r'`+',value)),default=1))
            return fence+' '+value+' '+fence
        if node.name=='br':return '\n'
        text=''.join(render(c) for c in node.children)
        if node.name in ('p','div','li','h1','h2','h3','h4'):return '\n\n'+text.strip()+'\n\n'
        return text
    result=re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+','\n\n',render(soup)).strip()
    for i,value in enumerate(literals):result=result.replace('\x00PRE'+str(i)+'\x00',value)
    return result


def read_question(url):
    from courseagent.web_questions import cached
    url=canonical_url(url)
    if not url:raise ValueError('不是力扣题目网址')
    slug=urlparse(url).path.split('/')[2]
    def compute():
        query='query($slug:String!){question(titleSlug:$slug){questionId title translatedTitle content translatedContent difficulty isPaidOnly metaData codeSnippets{lang langSlug code} topicTags{name translatedName slug}}}'
        q=graphql(query,{'slug':slug}).get('question')
        if not q or not (q.get('translatedContent') or q.get('content')):raise ValueError('题面不可公开读取')
        if q.get('isPaidOnly'):raise ValueError('跳过付费题目')
        title=q.get('translatedTitle') or q['title']
        statement_html=q.get('translatedContent') or q['content']
        text=statement_text(statement_html)
        examples=extract_examples(statement_html)
        tags=[t.get('translatedName') or t['name'] for t in q.get('topicTags',[])]
        refs=[];reference_events=[]
        try:
            listing=graphql('query($slug:String!){questionSolutionArticles(questionSlug:$slug,first:6,skip:0){edges{node{slug title}}}}',{'slug':slug})
            for edge in listing['questionSolutionArticles']['edges'][:6]:
                article_url=''
                try:
                    article=edge['node'];article_slug=article['slug']
                    article_url=url+'solution/'+article_slug+'/'
                    detail=graphql('query($slug:String!){solutionArticle(slug:$slug){title content}}',{'slug':article_slug}).get('solutionArticle') or {}
                    content=detail.get('content','')
                    from courseagent.source_references import extract_references
                    # Preserve the public article permalink and source code.
                    article_refs=extract_references(content,article_url)
                    for ref in article_refs:
                        refs.append({**ref,'problem_url':url,'status':'official_editorial' if 'leetcode-solution' in article_slug else 'public_editorial'})
                    reference_events.append({'url':article_url,'status':'code_extracted' if article_refs else 'no_supported_code',
                        'languages':list(dict.fromkeys(ref['language'] for ref in article_refs))})
                    # Native function/class execution currently has a Python
                    # driver. A C++/Java snippet without main is not a reason
                    # to abandon a suitable problem before trying another
                    # public editorial from this same bounded listing.
                    if any(ref['language']=='Python' for ref in refs):break
                except Exception as error:
                    reference_events.append({'url':article_url,'status':'article_read_failed','error_type':type(error).__name__})
                    continue
        except Exception as error:
            reference_events.append({'status':'listing_read_failed','error_type':type(error).__name__})
        refs.sort(key=lambda ref:ref['language']!='Python')
        try:interface=json.loads(q.get('metaData') or '{}')
        except (ValueError,TypeError):interface={}
        return {'url':url,'title':title,'text':title+'\n知识点：'+ '、'.join(tags)+'\n'+text,
                'retrieved_at':datetime.now(timezone.utc).isoformat(),
                'source_metadata':{'provider':'leetcode','difficulty':q.get('difficulty'),'tags':tags,'question_id':q['questionId'],
                    'interface_kind':'class' if interface.get('systemdesign') or interface.get('classname') else 'function',
                    'interface':interface,'code_templates':q.get('codeSnippets') or [],'paid':False},
                'source_statement':text,'source_statement_markdown':statement_markdown(statement_html),'source_examples':examples,'reference_solutions':refs,
                'reference_discovery':{'status':'found' if refs else 'not_extracted','events':reference_events,
                    'policy':'compatible-editorial-v2'}}
    def fresh_empty_result(value):
        # A transient editorial/parsing failure must not be remembered as "no
        # code" for the statement's seven-day positive-cache lifetime.
        refs=value.get('reference_solutions',[])
        python_found=any(ref.get('language')=='Python' for ref in refs)
        if refs and not python_found and value.get('reference_discovery',{}).get('policy')!='compatible-editorial-v2':
            raise ValueError('旧题解缓存未检查后续可适配代码，重新读取同题题解')
        if not python_found:
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(value['retrieved_at'])).total_seconds()
            if age>120:raise ValueError('来源代码空结果过期，重新读取关联题解')
    return cached('leetcode-detail-v8',url,compute,ttl=604800,validate=fresh_empty_result)
