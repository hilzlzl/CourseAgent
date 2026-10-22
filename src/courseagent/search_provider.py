"""Optional Tavily structured retrieval; existing public search remains available."""
import json
import os
from urllib.request import Request, urlopen


def configured():
    return bool(os.environ.get('EDUCODER_TAVILY_API_KEY'))


def search(query):
    payload = {'query': query, 'max_results': 8, 'search_depth': 'basic',
               'include_answer': False, 'include_raw_content': False}
    request = Request('https://api.tavily.com/search', json.dumps(payload).encode(),
                      {'Content-Type': 'application/json',
                       'Authorization': 'Bearer ' + os.environ['EDUCODER_TAVILY_API_KEY']})
    try:
        with urlopen(request, timeout=20) as response:
            result = json.loads(response.read(2_000_000))
        items = []
        for item in result.get('results', [])[:8]:
            if isinstance(item, dict) and isinstance(item.get('url'), str) and isinstance(item.get('title'), str):
                items.append({'url': item['url'], 'title': item['title'], 'query': query,
                              'engine': 'tavily', 'score': item.get('score')})
        if not items:
            raise ValueError('搜索服务未返回结果')
        return items
    except Exception:
        raise ValueError('结构化搜索服务不可用，切换公开搜索来源') from None
