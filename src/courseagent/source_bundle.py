"""One provenance contract for native and HTML question readers."""
import re
from urllib.parse import urlparse
from pydantic import Field
from courseagent.agent_contracts import Contract


class QuestionBundle(Contract):
    provider: str
    problem_id: str=''
    canonical_url: str
    statement: str
    samples: list[dict]=Field(default_factory=list)
    constraints: str=''
    source_difficulty: str=''
    tags: list[str]=Field(default_factory=list)
    interface_kind: str='unknown'
    interface: dict=Field(default_factory=dict)
    reference_candidates: list[dict]=Field(default_factory=list)
    access_status: str='ok'


def bundle_for(page,provider):
    meta=page.get('source_metadata',{})
    kind=meta.get('interface_kind','unknown')
    text=page.get('text','')
    if kind=='unknown':
        if re.search(r'实现.{0,12}(?:函数|方法)|完成.{0,12}(?:函数|方法)|class Solution|函数接口|接口定义',text):kind='function'
        elif re.search(r'输入(?:格式|描述)[\s\S]*输出(?:格式|描述)',text):kind='standard_io'
    return QuestionBundle(provider=provider,problem_id=str(meta.get('question_id') or urlparse(page['url']).path.rstrip('/').split('/')[-1]),
        canonical_url=page['url'],statement=text,samples=page.get('source_examples',[]),constraints=meta.get('constraints',''),source_difficulty=str(meta.get('difficulty') or meta.get('difficulty_raw') or ''),
        tags=meta.get('tags',[]),interface_kind=kind,interface=meta.get('interface',{}),
        reference_candidates=page.get('reference_solutions',[])).model_dump()
