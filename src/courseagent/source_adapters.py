"""Source-specific public capabilities. No login, submission, or private-test access."""
from dataclasses import asdict, dataclass
import re
from urllib.parse import urlparse
from typing import Protocol

@dataclass(frozen=True)
class Capabilities:
    provider: str
    discovery: str
    reader: str
    public_reference_code: bool = False
    private_tests: bool = False

class QuestionSource(Protocol):
    capabilities: Capabilities
    def search(self, query: str, topics: list[str], difficulty: int = 0): ...
    def read(self, url: str): ...

class WebSearchSource:
    capabilities = Capabilities('web','search_engine','public_html')
    def search(self, query, topics=(), difficulty=0):
        from courseagent.web_questions import search
        return search(query)
    def read(self, url):
        from courseagent.web_questions import read_page
        return read_page(url)

class LeetCodeSource(WebSearchSource):
    capabilities = Capabilities('leetcode','public_graphql_cn','public_graphql_cn_or_html',True)
    def search(self, query, topics=(), difficulty=0, *, offset=0, with_page=False):
        from courseagent.algorithm_sources import search_questions
        return search_questions(list(topics) or [query],difficulty,offset=offset,with_page=with_page)
    def read(self, url):
        from courseagent.algorithm_sources import supports, read_question
        if supports(url):
            try:
                page,hit=read_question(url)
                return {**page,'source_metadata':{**page.get('source_metadata',{}),'access_mode':'public_graphql_cn'}},hit
            except (ValueError,RuntimeError,OSError,KeyError):
                page,hit=super().read(url)
                return {**page,'source_metadata':{**page.get('source_metadata',{}),'native_read_fallback':True}},hit
        return super().read(url)

class NowCoderSource(WebSearchSource):
    capabilities = Capabilities('nowcoder','public_acm_list_or_domain_search','public_acm_html_or_generic',True)
    def search(self, query, topics=(), difficulty=0, *, offset=0, with_page=False):
        if topics:
            try:
                from courseagent.nowcoder_sources import search_questions
                return search_questions(topics,difficulty,offset=offset,with_page=with_page)
            except (ValueError,OSError,KeyError,TypeError):
                if offset:raise
        # The ACM bank and associated editorials are under ac.nowcoder.com.
        # Keep /practice coverage too, without limiting the whole provider to it.
        from courseagent.source_policy import clean_query
        sites=re.findall(r'\bsite:(\S+)',query,re.I)
        route=next((s for s in sites if s.lower() in (
            'nowcoder.com/acm/problem/','ac.nowcoder.com/acm/problem/',
            'www.nowcoder.com/practice/','nowcoder.com/practice/')), 'nowcoder.com')
        return super().search(clean_query(query)+' site:'+route)
    def read(self,url):
        if re.fullmatch(r'/acm/problem/\d+/?',urlparse(url).path):
            try:
                from courseagent.nowcoder_sources import read_question
                return read_question(url)
            except (ValueError,OSError,KeyError,TypeError):pass
        return super().read(url)

class LuoguSource(WebSearchSource):
    capabilities = Capabilities('luogu','domain_search_engine','public_html')
    def search(self, query, topics=(), difficulty=0):
        from courseagent.source_policy import clean_query
        return super().search(clean_query(query)+' site:luogu.com.cn/problem/')

class AcWingSource(WebSearchSource):
    capabilities = Capabilities('acwing','domain_search_engine','public_html')
    def search(self, query, topics=(), difficulty=0):
        from courseagent.source_policy import clean_query
        return super().search(clean_query(query)+' site:acwing.com/problem/content/')

class LocalDocumentSource:
    capabilities = Capabilities('local_document','sqlite_hybrid_index','uploaded_docx')
    def search(self, query, topics=(), difficulty=0):
        from courseagent.retrieval_runtime import get_index
        return get_index().search(query,kinds=['material'],providers=['local_document'])

class CourseMaterialSource(LocalDocumentSource):
    capabilities = Capabilities('course_material','sqlite_hybrid_index','uploaded_pdf_text')
    def search(self, query, topics=(), difficulty=0):
        from courseagent.retrieval_runtime import get_index
        return get_index().search(query,kinds=['material'],providers=['course_material'])

SOURCES={s.capabilities.provider:s for s in (WebSearchSource(),LeetCodeSource(),NowCoderSource(),LuoguSource(),AcWingSource(),LocalDocumentSource(),CourseMaterialSource())}

def provider_for(url):
    host=(urlparse(url).hostname or '').lower()
    for name,domains in [('leetcode',('leetcode.cn','leetcode.com')),('nowcoder',('nowcoder.com','nowcoder.net')),('luogu',('luogu.com.cn','luogu.com')),('acwing',('acwing.com',))]:
        if any(host==d or host.endswith('.'+d) for d in domains):return name
    return 'web'

def read_question_page(url):
    parsed=urlparse(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,80,443):
        raise ValueError('Only public HTTP(S) evidence URLs are allowed')
    source=SOURCES[provider_for(url)]
    page,hit=source.read(url)
    final_source=SOURCES[provider_for(page['url'])]
    metadata={**page.get('source_metadata',{}),'provider':final_source.capabilities.provider,
              'access_mode':page.get('source_metadata',{}).get('access_mode','public_html'),'private_tests_available':False}
    if final_source.capabilities.provider in ('nowcoder','luogu','acwing'):
        explicit=re.search(r'难度\s*[:：]?\s*(入门|普及[-−]?|普及[+]提高|提高[-−]?|提高[+]省选|省选|简单|中等|困难|较难)',page.get('text',''))
        if explicit:
            metadata['difficulty_raw']=explicit[1];metadata['difficulty_evidence']=explicit[0]
    from courseagent.source_bundle import bundle_for
    result={**page,'source_metadata':metadata}
    result['source_bundle']=bundle_for(result,metadata['provider'])
    metadata['interface_kind']=result['source_bundle']['interface_kind']
    return result,hit

def search_source(provider, query, topics=(), difficulty=0, *, offset=0, with_page=False):
    if provider not in SOURCES or provider in ('local_document','course_material'):
        raise ValueError('Unsupported public discovery provider')
    if provider in ('leetcode','nowcoder'):
        return SOURCES[provider].search(query,topics,difficulty,offset=offset,with_page=with_page)
    if offset:raise ValueError('This search provider does not support offsets')
    return SOURCES[provider].search(query,topics,difficulty)

def manifest():
    return [asdict(source.capabilities) for source in SOURCES.values()]
