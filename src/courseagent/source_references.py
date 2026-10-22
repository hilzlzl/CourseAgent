"""Bounded public editorial discovery. A code block is never evidence of AC status."""
import ast
import re
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup, ParserRejectedMarkup

LANGUAGES={'python':'Python','python3':'Python','py':'Python','cpp':'C++','c++':'C++','c':'C','java':'Java'}


def valid_reference(ref):
    if not isinstance(ref,dict) or ref.get('language') not in set(LANGUAGES.values()):return False
    local=ref.get('status')=='teacher_material' and bool(ref.get('document_id'))
    if not local and ref.get('status') not in ('official_editorial','public_editorial','accepted_submission'):return False
    p=urlparse(ref.get('url',''))
    if not local and (p.scheme not in ('http','https') or not p.hostname or p.username or p.password):return False
    code=ref.get('code','')
    if not isinstance(code,str) or not 20<=len(code)<=20000:return False
    # Extraction is a syntax screen, never an execution/correctness claim.
    if ref['language']=='Python':
        try:
            tree=ast.parse(code)
            return bool(tree.body) and bool(re.search(r'\b(def|class|import|print|input|for|while)\b',code))
        except (ValueError,SyntaxError):return False
    if ref['language']=='Java':return bool(re.search(r'\bclass\s+\w+',code)) and '{' in code
    return bool(re.search(r'#include|\b(?:int|void|bool|class|struct)\s+\w+',code)) and '{' in code


def python_reference(ref):
    return isinstance(ref,dict) and ref.get('language')=='Python' and valid_reference(ref)


def extract_references(content, url):
    """Literal multilingual blocks, including NowCoder's table renderer."""
    blocks=[]
    def markdown(text):
        for m in re.finditer(r'```([^\n]*)\n(.*?)```',text,re.S):
            label=m[1].strip().split(' ',1)[0].lower()
            if label in LANGUAGES:blocks.append((LANGUAGES[label],m[2]))
    def literal(code,label=''):
        # Some NowCoder Python tokens have "java" CSS classes. Python syntax
        # is stronger evidence than an unreliable syntax-highlighter class.
        if re.search(r'(?m)^\s*(?:def \w+\(|class \w+(?:\([^\n]*\))?:|from \w+ import |import (?:sys|collections)|print\()',code):
            try:ast.parse(code);blocks.append(('Python',code));return
            except SyntaxError:pass
        hints=re.findall(r'python3?|\bcpp\b|c\+\+|\bjava\b|\bc\b',label,re.I)
        language=LANGUAGES.get(hints[0].lower()) if hints else None
        if not language:
            if re.search(r'\bclass\s+\w+.*\{|\bpublic static void main',code) and 'System.' in code:language='Java'
            elif re.search(r'#include|using namespace std|std::',code):language='C++' if re.search(r'iostream|bits/|std::|cout|cin|class |vector',code) else 'C'
        if language:blocks.append((language,code))
    # Editorials are often Markdown containing C++ angle brackets or malformed
    # HTML diagrams. Extract literal fences before attempting HTML parsing;
    # unrelated markup must not discard valid programs in the same article.
    markdown(content)
    try:soup = BeautifulSoup(content, 'html.parser')
    except ParserRejectedMarkup:soup = BeautifulSoup('', 'html.parser')
    for node in soup.select('pre'):
        label = ' '.join(node.get('class', [])) + ' ' + str(node)
        code = node.get_text('', strip=False)
        literal(code,label)
    for node in soup.select('td.code .container'):
        lines=node.select('.line')
        if lines:literal('\n'.join(line.get_text('',strip=False).replace('\xa0',' ') for line in lines),' '.join(node.get('class',[])))
    # Some public pages store Markdown in JSON, not in the rendered body.
    import json
    for script in soup.select('script[type="application/json"], script#__NEXT_DATA__'):
        try:
            payload = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        def visit(value, depth=0):
            if depth > 12:
                return
            if isinstance(value, str):
                markdown(value)
            elif isinstance(value, dict):
                for child in value.values():
                    visit(child, depth + 1)
            elif isinstance(value, list):
                for child in value[:100]:
                    visit(child, depth + 1)
        visit(payload)
    refs = []
    for language,code in dict.fromkeys((language,code.strip()) for language,code in blocks):
        ref = {'code': code, 'language': language, 'url': url,
               'status': 'public_editorial', 'accepted_verified': False,
               'retrieval_method': 'literal_public_code_block'}
        if valid_reference(ref):
            refs.append(ref)
    refs.sort(key=lambda r:r['language']!='Python')
    return refs[:8]


def discover_reference(question):
    """Try the known question, its editorial links and up to two search hits.

    No arbitrary AC claim, login bypass or private submission API. A source miss
    is cached briefly, and falls back to the existing differential verifier.
    """
    ref = question.get('source_reference')
    from courseagent.answer_policy import supplied_key, trusted_key
    if supplied_key(question):
        return ref if trusted_key(question) and valid_reference(ref) else None
    if question.get('origin')=='web_programming_adapted':return None
    if isinstance(ref,dict) and ref.get('status')=='teacher_material':return None
    if valid_reference(ref):
        return ref
    from courseagent.source_adapters import provider_for
    urls = [r.get('url', '') for r in question.get('source_refs', [])]
    urls = [u for u in urls if provider_for(u) in ('leetcode', 'luogu', 'nowcoder', 'acwing')]
    if not urls:
        return None
    from courseagent.web_questions import cached, search
    from courseagent.source_access import fetch_source as fetch
    import json
    key = json.dumps([urls[:1], question.get('title', '')], ensure_ascii=False)

    def compute():
        url = urls[0]
        provider = provider_for(url)
        if provider == 'leetcode':
            from courseagent.algorithm_sources import supports, read_question
            if supports(url):
                try:
                    page, _ = read_question(url)
                    for item in page.get('reference_solutions', []):
                        if valid_reference(item):
                            return item
                except (ValueError, RuntimeError, OSError, KeyError):
                    pass
            # Native reader already queried editorials; don't repeat a web crawl.
            return None
        parts=urlparse(url).path.strip('/').split('/')
        ident=(parts[2] if provider=='nowcoder' and len(parts)>2 and parts[:2]==['acm','problem'] else parts[-1])
        candidates = [url]
        if provider=='nowcoder' and re.fullmatch(r'\d+',ident) and '/acm/problem/' in url:
            candidates.append('https://ac.nowcoder.com/acm/problem/blogs/'+ident)
        if provider == 'luogu' and re.fullmatch(r'[A-Z]+\d+', ident):
            candidates.append('https://www.luogu.com.cn/problem/solution/' + ident)
        visited = set()

        def read(candidate):
            if candidate in visited or provider_for(candidate) != provider:
                return None
            visited.add(candidate)
            try:
                html, final = fetch(candidate)
                if provider_for(final) != provider:
                    return None
                # A linked article must identify this problem, not merely its topic.
                if candidate != url and not problem_linked(html,url,ident,provider):
                    return None
                refs = extract_references(html, final)
                if refs:
                    return {**refs[0], 'problem_url': url}
                # Luogu solution listings link actual /article/ pages.
                if len(candidates) < 6:
                    soup = BeautifulSoup(html, 'html.parser')
                    anchors=soup.select('a[href]')
                    if provider=='nowcoder':
                        anchors.sort(key=lambda a:not bool(re.search(r'python',
                            (a.find_parent(class_='subject-analysis-item') or a).get_text(' ',strip=True),re.I)))
                    for a in anchors:
                        link = urljoin(final, a['href'])
                        if provider=='nowcoder' and '/n/' in urlparse(link).path:
                            link=link.split('?',1)[0].split('#',1)[0]
                        path=urlparse(link).path
                        article_path=(re.fullmatch(r'/(?:article|n)/[A-Za-z0-9_-]+/?',path) or
                                      re.fullmatch(r'/discuss/\d+/?',path) or
                                      re.fullmatch(r'/solution/content/\d+/?',path))
                        if provider_for(link) == provider and article_path:
                            if link not in candidates:
                                candidates.append(link)
                            if len(candidates) >= 6:
                                break
            except (ValueError, RuntimeError, OSError):
                pass
            return None

        # Hard page bound avoids turning every missing reference into a long crawl.
        for candidate in candidates:
            if len(visited) >= 3:
                break
            found = read(candidate)
            if found:
                return found
        if len(visited) < 3:
            try:
                domain = {'nowcoder':'nowcoder.com','luogu':'luogu.com.cn','acwing':'acwing.com'}[provider]
                hits, _ = search(f'{ident} {question.get("title", "")} 题解 代码 site:{domain}')
                for hit in hits[:2]:
                    if len(visited) >= 3:
                        break
                    found = read(hit['url'])
                    if found:
                        return found
            except (ValueError, RuntimeError, OSError, KeyError):
                pass
        return None

    # A login or temporary source miss must not poison continuation for an hour.
    value, _ = cached('public-reference-v5', key, compute, ttl=120)
    return value if valid_reference(value) else None


def problem_linked(html,url,ident,provider):
    """An arbitrary digit appearing in an article is not problem identity."""
    from courseagent.source_adapters import provider_for
    soup=BeautifulSoup(html,'html.parser')
    expected=urlparse(url).path.rstrip('/')
    if any(urlparse(urljoin(url,a['href'])).path.rstrip('/')==expected
           and provider_for(urljoin(url,a['href']))==provider for a in soup.select('a[href]')):
        return True
    text=soup.get_text(' ',strip=True)
    if provider=='luogu':return re.search(r'(?<![A-Z0-9])'+re.escape(ident)+r'(?![A-Z0-9])',text) is not None
    if provider=='nowcoder' and '/acm/problem/blogs/' in urlparse(url).path:return False
    return re.search(r'(?:题号|题目编号|NC|AcWing)\s*[:：.]?\s*'+re.escape(ident)+r'(?!\d)',text,re.I) is not None or url in html
