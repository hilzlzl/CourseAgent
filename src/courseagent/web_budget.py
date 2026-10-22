"""Shared per-run limits, including failed model calls; cache reads are free."""
LIMITS = {'model_calls': 14, 'adaptation_rounds': 4, 'search_rounds': 6,
          'pages': 12, 'read_attempts': 48}


def call_limit(web):
    return max(LIMITS['model_calls'], min(40, int(web.get('model_call_limit', LIMITS['model_calls']))))


def model_cached(web, kind, key, prompt, data, validate=None):
    from courseagent.web_questions import cached
    from courseagent.agent_roles import ask_role
    def compute():
        if web.get('model_calls', 0) >= call_limit(web):
            from courseagent.model_client import BudgetExhausted
            raise BudgetExhausted('已达到本轮模型调用预算')
        web['model_calls'] = web.get('model_calls', 0) + 1
        return ask_role('validator' if 'check' in kind or 'verify' in kind else 'author', prompt, data)
    options={'validate':validate} if validate else {}
    value, hit = cached(kind, key, compute, ttl=7*86400,**options)
    web['cache_hits'] = web.get('cache_hits', 0) + int(hit)
    return value
