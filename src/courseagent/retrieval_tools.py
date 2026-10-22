"""LangChain tools backed by the existing bounded, cached public-web readers."""
from courseagent.tool_registry import registered_tool
from courseagent.agent_contracts import SearchInput, SearchOutput, ReadInput, ReadOutput
from courseagent.observability import span

def progress(message):
    from courseagent.model_client import TASK_BUDGET, BudgetExhausted
    import time
    budget=TASK_BUDGET.get()
    if budget and time.monotonic()>=budget['deadline']:
        raise BudgetExhausted('任务运行时间预算已用完，停止新增检索；保留当前结果以便继续')
    if budget and budget.get('on_activity'):budget['on_activity'](message)


@registered_tool(SearchInput, SearchOutput)
def search_public_questions(query: str) -> dict:
    """Search public web pages for a course/topic query; return links and cache status."""
    from courseagent.web_questions import search
    progress('正在搜索：'+query[:160])
    with span('tool_search_public_questions', 'tool') as metrics:
        items, hit = search(query)
        metrics.update(result_count=len(items), cache_hit=hit)
        if items and items[0].get('search_diagnostics'):
            progress('部分搜索入口不可用，已取得备用结果：'+'；'.join(items[0]['search_diagnostics'])[:150])
        progress('搜索取得 '+str(len(items))+' 条链接，正在筛选素材')
        return {'items': items, 'cache_hit': hit}


@registered_tool(ReadInput, ReadOutput)
def read_public_question_page(url: str) -> dict:
    """Read a public HTTP(S) page as untrusted evidence. Reject local/private URLs."""
    from courseagent.source_adapters import read_question_page
    progress('正在读取素材网页：'+url[:160])
    with span('tool_read_public_question_page', 'tool') as metrics:
        page, hit = read_question_page(url)
        metrics.update(content_chars=len(page.get('text', '')), cache_hit=hit)
        progress('已读取素材：'+page.get('title','网页')[:120])
        return {'page': page, 'cache_hit': hit}


from courseagent.agent_contracts import SourceSearchInput, SourceSearchOutput, HybridSearchInput, HybridSearchOutput

@registered_tool(SourceSearchInput, SourceSearchOutput)
def search_question_source(provider: str, query: str, topics: list[str] | None = None, difficulty: int = 0, offset: int = 0) -> dict:
    """Discover public problem links using the declared provider capability, not private tests."""
    from courseagent.source_adapters import search_source
    progress('正在检索题目来源：'+provider)
    result=search_source(provider,query,topics or [],difficulty,offset=offset,with_page=True)
    items,hit=result[:2]
    return {'items':items,'cache_hit':hit,'pagination':result[2] if len(result)>2 else {}}

@registered_tool(HybridSearchInput, HybridSearchOutput)
def search_indexed_questions(query: str, kinds: list[str] | None = None, providers: list[str] | None = None,
                             source_ids: list[str] | None = None, exclude_ids: list[str] | None = None, record_ids: list[str] | None = None, limit: int = 20) -> dict:
    """Retrieve provenance-bearing candidates using Chinese BM25 and local semantic FAISS RRF fusion."""
    from courseagent.retrieval_runtime import get_index
    progress('正在混合检索候选与参考材料：'+query[:120])
    return get_index().search(query,kinds=kinds,providers=providers,source_ids=source_ids,exclude_ids=exclude_ids or [],record_ids=record_ids,limit=limit)
