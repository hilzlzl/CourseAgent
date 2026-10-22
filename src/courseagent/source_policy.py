"""Explicit source tiers, never inferred from a search keyword alone."""
from urllib.parse import urlparse
import re

ALGORITHM_DOMAINS = ('leetcode.cn', 'leetcode.com', 'nowcoder.com', 'luogu.com.cn', 'luogu.com', 'acwing.com')


def search_redirect(url):
    """Allow discovery redirects through; eligibility uses the resolved page URL."""
    p = urlparse(url)
    host = (p.hostname or '').lower()
    return ((host in ('sogou.com', 'www.sogou.com', 'baidu.com', 'www.baidu.com', 'so.com', 'www.so.com') and p.path == '/link')
            or (host in ('bing.com', 'www.bing.com') and p.path.startswith('/ck/')))


def problem_url(url):
    """A bank hostname alone does not identify a problem page."""
    routes = {
        'leetcode.cn': r'/problems/[a-z0-9-]+(?:/description)?/?',
        'leetcode.com': r'/problems/[a-z0-9-]+(?:/description)?/?',
        'nowcoder.com': r'/(?:acm/problem/\d+|practice/[A-Za-z0-9]+|ta/[^/]+/question-ranking/[^/]+)/?',
        'luogu.com.cn': r'/problem/[A-Za-z]+\d+/?',
        'luogu.com': r'/problem/[A-Za-z]+\d+/?',
        'acwing.com': r'/problem/content/\d+/?',
    }
    p = urlparse(url)
    host = (p.hostname or '').lower()
    if p.scheme not in ('http','https') or p.username or p.password:
        return False
    return any((host == d or host.endswith('.'+d)) and re.fullmatch(route,p.path)
               for d,route in routes.items())


def search_page(url):
    """Search portals are discovery tools, never question evidence pages."""
    host=(urlparse(url).hostname or '').lower()
    return host in ('baidu.com','www.baidu.com','sogou.com','www.sogou.com',
                    'bing.com','www.bing.com','cn.bing.com','so.com','www.so.com',
                    'ai.so.com','e.so.com','wenku.so.com','m.so.com','m.baidu.com') and not search_redirect(url)


def clean_query(query):
    # Accept the common site.domain typo, but never carry a site's constraint
    # or a different site's problem id into another provider's query.
    return re.sub(r'\bsite(?::|[.＝=：])\S+', '', query, flags=re.I).strip()


def bank_queries(topics, batch=0, suggested=()):
    suffix = ('题目 输入输出 样例', '编程题 公开题解', '算法练习 数据范围')[batch % 3]
    queries = [topics[(batch+i)%len(topics)]+' '+suffix+' site:'+domain for i,domain in enumerate(
               ('nowcoder.com/acm/problem/', 'luogu.com.cn/problem/', 'acwing.com/problem/content/'))] if topics else []
    # Preserve a suggested query's intended provider; never zip it against an
    # unrelated fixed provider list. Only accept actual bank discovery queries.
    hints=[]
    for q in suggested:
        q=re.sub(r'\bsite[.＝=：](?=[a-z0-9.-]+\.)','site:',q,flags=re.I)
        sites=re.findall(r'\bsite:(\S+)',q,re.I)
        if len(sites)==1 and any(sites[0].split('/')[0] == d or sites[0].split('/')[0].endswith('.'+d)
                                for d in ALGORITHM_DOMAINS):hints.append(q)
    return list(dict.fromkeys(hints+queries))


def algorithm_question(q):
    return any(source_tier(r.get('url', ''), programming=True) == 0
               for r in q.get('source_refs', []))


def published_algorithm_question(q):
    """Original bank problems, not discussions, editorials or adapted exercises."""
    import re
    if q.get('origin') == 'web_programming_adapted':
        return False
    routes = {
        'leetcode.cn': r'/problems/[a-z0-9-]+(?:/description)?/?',
        'leetcode.com': r'/problems/[a-z0-9-]+(?:/description)?/?',
        'nowcoder.com': r'/(?:acm/problem/\d+|practice/[A-Za-z0-9]+)(?:/)?',
        'luogu.com.cn': r'/problem/[A-Za-z0-9]+/?',
        'luogu.com': r'/problem/[A-Za-z0-9]+/?',
        'acwing.com': r'/problem/content/\d+/?',
    }
    for ref in q.get('source_refs', []):
        if ref.get('answer_status') != 'source_explicit':
            continue
        parsed = urlparse(ref.get('url', ''))
        if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password:
            continue
        host = (parsed.hostname or '').lower()
        if any((host == domain or host.endswith('.' + domain)) and re.fullmatch(route, parsed.path)
               for domain, route in routes.items()):
            return True
    return False


def prefer_algorithm_candidates(candidates, locked=()):
    """Cache hit must not promote blogs ahead of professional problem banks."""
    from courseagent.source_references import valid_reference
    return sorted(candidates, key=lambda q: (q['id'] not in locked,
                  not algorithm_question(q), interface_cost(q), not valid_reference(q.get('source_reference'))))


def interface_cost(q):
    """Prefer supported adapters, without changing or excluding source problems."""
    protocol = q.get('source_protocol') or q.get('source_metadata', {}).get('interface_kind')
    if protocol == 'standard_io':
        return 0
    metadata = q.get('source_metadata', {}).get('interface')
    if protocol in ('function', 'class') and metadata:
        from courseagent.leetcode_driver import python_driver
        try:
            python_driver(metadata)
        except (ValueError, TypeError, KeyError, AttributeError):
            return 2
        return 0
    return 1


def source_tier(url, title='', programming=False):
    host=(urlparse(url).hostname or '').lower()
    if programming and any(host==d or host.endswith('.'+d) for d in ALGORITHM_DOMAINS):return 0
    if not programming and (host.endswith('.edu.cn') or host.endswith('.edu')) and any(w in title for w in ('习题','试题','题库','考试','练习')):return 0
    if host.endswith('.edu.cn') or host.endswith('.edu') or any(w in title for w in ('课程习题','题库','试题','习题','练习题')):return 1
    return 2


def programming_queries(topics, batch=0):
    if batch==0:
        return bank_queries(topics,batch)
    return [topic+' '+suffix for topic in topics for suffix in
            ('算法题 课程习题 输入输出','编程练习 题解 边界条件','算法 实例 解答')]


def order_links(links, programming=False):
    if not programming:
        # Preview/paywall document hosts often expose titles but omit options.
        # Prefer readable course/blog question sets, keeping previews as fallback.
        preview_hosts=('book118.com','doc88.com','docin.com','renrendoc.com','wenku.baidu.com','wenku.docs.qq.com')
        def priority(row):
            host=(urlparse(row['url']).hostname or '').lower()
            preview=any(host==d or host.endswith('.'+d) for d in preview_hosts)
            return (preview,source_tier(row['url'],row.get('title',''),False))
        return sorted(links,key=priority)
    # Interleave sites within the same tier so one site's long result list
    # cannot consume every read slot before a second source is considered.
    counts = {}
    ordered = []
    for link in links:
        host = (urlparse(link['url']).hostname or '').lower().removeprefix('www.')
        count = counts.get(host, 0)
        counts[host] = count + 1
        ordered.append((source_tier(link['url'],link.get('title',''),True), count, link))
    ordered.sort(key=lambda item:item[:2])
    return [item[2] for item in ordered]
