"""Public ACM list and statement adapter; no authentication or private submissions."""
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit, parse_qs
from bs4 import BeautifulSoup


def fetch_text(url):
    if urlsplit(url).path.endswith('/json'):
        import gzip
        from io import BytesIO
        from urllib.request import Request, build_opener
        from courseagent.web_questions import public_url, PublicRedirect
        public_url(url)
        with build_opener(PublicRedirect()).open(Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=18) as response:
            public_url(response.url)
            raw=response.read(2_000_001)
            if len(raw)>2_000_000:raise ValueError('牛客题库响应过大')
            if raw[:2]==b'\x1f\x8b':
                with gzip.GzipFile(fileobj=BytesIO(raw)) as stream:raw=stream.read(2_000_001)
                if len(raw)>2_000_000:raise ValueError('牛客题库响应过大')
            return raw.decode('utf-8'),response.url
    from courseagent.source_access import fetch_source
    return fetch_source(url)


def tag_catalog():
    from courseagent.web_questions import cached
    def compute():
        html,_=fetch_text('https://ac.nowcoder.com/acm/problem/list')
        match=re.search(r'\ballTagArray\s*:',html)
        if not match:raise ValueError('牛客题库标签结构已变化')
        groups,_=json.JSONDecoder().raw_decode(html[match.end():].lstrip())
        return {tag['name']:tag['id'] for group in groups for tag in [group]+group.get('childTags',[]) if isinstance(tag.get('id'),int)}
    return cached('nowcoder-public-tags-v1','acm',compute,ttl=86400)[0]


def search_questions(topics,difficulty=0,*,offset=0,with_page=False):
    from courseagent.web_questions import cached
    from courseagent.selection_policy import normalized_topic
    if type(offset) is not int or offset<0 or offset%20:raise ValueError('牛客分页位置不正确')
    catalog=tag_catalog()
    terms=list(dict.fromkeys(t for t in topics if t not in ('数据结构','算法','课程','搜索')))
    aliases={'二叉排序树':'二叉搜索树','二分查找':'二分','哈希查找':'哈希','深度优先搜索':'深度优先搜索','广度优先搜索':'广度优先搜索'}
    def compute():
        batches=[];total=0;has_more=False
        requests=[]
        for term in terms[:4]:
            name=normalized_topic(term);candidates=(term,name,aliases.get(name,''))
            tag=next((catalog[t] for t in candidates if t in catalog),None)
            # Title keywords recover basic/template exercises absent from a
            # newer tag taxonomy; never AND several course topics together.
            requests.append((term,{'keyword':term}))
            if tag:requests.append((term,{'tagId':tag}))
            elif aliases.get(name) and aliases[name]!=term:requests.append((term,{'keyword':aliases[name]}))
        def read(request):
            term,filters=request
            params={'page':offset//20+1,'pageSize':20,**filters}
            raw,_=fetch_text('https://ac.nowcoder.com/acm/problem/list/json?'+urlencode(params))
            value=json.loads(raw)
            if value.get('code')!=0 or not isinstance(value.get('data'),dict):raise ValueError('牛客公开题库检索未成功')
            data=value['data'];rows=data.get('problemSets')
            if not isinstance(rows,list):raise ValueError('牛客公开题库返回结构已变化')
            count=data.get('problemCount',0)
            return count,[{'url':'https://ac.nowcoder.com/acm/problem/'+str(row['problemId']),
                'title':row['name'],'discovery_topics':[term]+[t['name'] for t in row.get('tagList',[])],
                'source_difficulty':row.get('difficulty'),'source_interface_type':row.get('problemType'),
                'engine':'nowcoder_public'} for row in rows if isinstance(row.get('problemId'),int)]
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(4,max(1,len(requests)))) as pool:
            for count,rows in pool.map(read,requests):
                total+=count;has_more|=offset+len(rows)<count;batches.append(rows)
        items=[];seen=set()
        for i in range(20):
            for batch in batches:
                if i<len(batch) and batch[i]['url'] not in seen:items.append(batch[i]);seen.add(batch[i]['url'])
        # ACM standard-I/O problems are easier to preserve faithfully than practice function interfaces.
        items.sort(key=lambda item:item.get('source_interface_type')!=0)
        return {'items':items,'pagination':{'next_offset':offset+20,'has_more':has_more,'total':total}}
    data,hit=cached('nowcoder-public-search-v2',json.dumps([terms,offset],ensure_ascii=False),compute,ttl=86400)
    result=(data['items'],hit,data['pagination'])
    return result if with_page else result[:2]


def parse_question(html,url):
    soup=BeautifulSoup(html,'html.parser');body=soup.select_one('.subject-describe');title=soup.select_one('.question-title')
    if not body or not title:raise ValueError('牛客公开题面结构未取得')
    samples=[]
    for sample in body.select('.question-oi'):
        parts=sample.select('.question-oi-mod');pair={}
        for part in parts:
            header=part.find('h2');value=part.select_one('.question-oi-cont pre') or part.find('textarea')
            if header and value:
                key='input' if '输入' in header.get_text() else 'output' if '输出' in header.get_text() else None
                if key:pair[key]=value.get_text('',strip=False).replace('\r\n','\n')
        if set(pair)=={'input','output'}:samples.append(pair)
    for image in body.find_all('img'):
        src=image.get('src','');tex=parse_qs(urlsplit(src).query).get('tex',[''])[0]
        image.replace_with('$'+tex.rstrip('\\')+'$' if tex else image.get('alt') or '[题面图片：'+src+']')
    for duplicate in body.select('textarea,.code-copy-btn'):duplicate.decompose()
    for br in body.find_all('br'):br.replace_with('\n')
    text=body.get_text('\n',strip=True)
    meta={'provider':'nowcoder','question_id':urlsplit(url).path.rstrip('/').split('/')[-1],
          'access_mode':'nowcoder_public_html','interface_kind':'standard_io' if re.search('输入描述[\\s\\S]*输出描述',text) else 'unknown'}
    return {'url':url,'title':title.get_text(' ',strip=True),'text':text,'source_statement':text,
            'source_examples':samples,'source_metadata':meta,'retrieved_at':datetime.now(timezone.utc).isoformat()}


def read_question(url):
    from courseagent.web_questions import cached
    def compute():
        html,final=fetch_text(url)
        if not re.fullmatch(r'/acm/problem/\d+/?',urlsplit(final).path):raise ValueError('牛客题面跳转到非原题页面')
        return parse_question(html,final)
    return cached('nowcoder-public-question-v1',url,compute,ttl=86400)
