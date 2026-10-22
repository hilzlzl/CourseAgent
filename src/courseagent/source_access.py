"""Bounded source reads: HTTP first, existing teacher-authorized Chrome fallback.

Browser failures are access failures, never empty question material. No login,
submission or platform-write actions are performed by this reader.
"""
from courseagent.paths import ROOT as WORKSPACE_ROOT, BROWSER
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from urllib.parse import urlparse
from bs4 import BeautifulSoup

ROOT=WORKSPACE_ROOT
LOCK=threading.RLock()
FAILURES={}


class SourceAccessError(ValueError):
    def __init__(self,status):
        self.status=status
        super().__init__('题目来源访问状态：'+status)


def transient_failure(error):
    from urllib.error import HTTPError,URLError
    if isinstance(error,HTTPError):return error.code==429 or error.code>=500
    if isinstance(error,(TimeoutError,ConnectionError,URLError)):return True
    return any(word in str(error).lower() for word in (
        'browser_busy','browser_unavailable','browser_timeout_or_invalid_response',
        'timed out','connection reset','connection refused','temporary failure',
        'http 429','http 500','http 502','http 503','http 504'))


def access_status(html,url):
    p=urlparse(url)
    soup=BeautifulSoup(html,'html.parser')
    title=soup.title.get_text(' ',strip=True).lower() if soup.title else ''
    text=soup.get_text(' ',strip=True)
    if any(word in p.path.lower() for word in ('/login','/sign_in','/passport')) or '/sign_in' in p.query:
        return 'needs_login'
    if any(word in title for word in ('captcha','just a moment','access denied','安全验证')):
        return 'blocked'
    if len(text)<150:return 'insufficient_content'
    if ('请先登录' in text or '登录后查看' in text) and not any(word in text for word in ('输入格式','输入描述','题目描述','示例 1')):
        return 'needs_login'
    return 'ok'


def browser_fetch(url):
    from courseagent.import_jobs import runtime_command,windows_path
    from courseagent.source_adapters import provider_for
    if os.environ.get('EDUCODER_TRACE_MODE')=='offline_tests':raise SourceAccessError('offline_browser_disabled')
    if provider_for(url)=='web':raise SourceAccessError('unsupported_browser_source')
    # A dedicated read-only tab may share a configured local CDP browser. The
    # fallback uses the existing project profile; a busy profile is not reset.
    endpoint=os.environ.get('EDUCODER_SOURCE_CDP_URL','')
    if endpoint:
        p=urlparse(endpoint)
        if p.scheme!='http' or p.hostname not in ('127.0.0.1','localhost','::1') or p.username or p.password:
            raise SourceAccessError('invalid_cdp_endpoint')
    command,is_windows,module=runtime_command(ROOT)
    path=windows_path if is_windows else str
    command[1]=path(BROWSER/'source_browser.cjs')
    command+=['--url',url,'--profile',path(ROOT/'.browser-profile'),'--module',module]
    if endpoint:command+=['--cdp',endpoint]
    with LOCK:
        (ROOT/'data').mkdir(parents=True,exist_ok=True)
        with (ROOT/'data').joinpath('source-browser.lock').open('a') as lock:
            import fcntl
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise SourceAccessError('browser_busy')
            try:
                result=subprocess.run(command,capture_output=True,timeout=32,env=os.environ.copy())
                if result.returncode:raise SourceAccessError('browser_unavailable')
                value=json.loads(result.stdout)
                if value.get('status')!='ok':raise SourceAccessError(value.get('status','browser_unavailable'))
                if len(value.get('html','').encode())>2_000_000:raise SourceAccessError('content_too_large')
                return value['html'],value['url']
            except (subprocess.TimeoutExpired,ValueError,KeyError) as error:
                if isinstance(error,SourceAccessError):raise
                raise SourceAccessError('browser_timeout_or_invalid_response') from None
            finally:fcntl.flock(lock,fcntl.LOCK_UN)


def fetch_source(url):
    from courseagent.web_questions import fetch
    from courseagent.source_adapters import provider_for
    if provider_for(url)=='web':return fetch(url)
    failure=FAILURES.get(url)
    if failure and time.monotonic()-failure[0]<60:raise SourceAccessError(failure[1])
    from courseagent.observability import span
    provider=provider_for(url)
    try:
        with span('source_http',metrics={'provider':provider}):html,final=fetch(url)
        if access_status(html,final)=='ok':return html,final
    except (ValueError,OSError):pass
    try:
        with span('source_browser',metrics={'provider':provider}):html,final=browser_fetch(url)
        status=access_status(html,final)
        if status!='ok':raise SourceAccessError(status)
        if provider_for(final)!=provider_for(url):raise SourceAccessError('unexpected_redirect')
        FAILURES.pop(url,None)
        return html,final
    except SourceAccessError as error:
        if not transient_failure(error):FAILURES[url]=(time.monotonic(),error.status)
        raise
