"""Deterministic Python invocation adapter. Contains no problem-solving algorithm.

The source samples remain JSON (or named JSON arguments). Unsupported custom
types fail explicitly, leaving the existing solver-adaptation path available.
"""
import json
import re

SCALAR={'integer','int','long','double','float','boolean','bool','string','character','char','void'}


def python_driver(metadata, io_contract=None):
    if not isinstance(metadata,dict):raise ValueError('缺少力扣接口元数据')
    from courseagent.interface_types import normalize_metadata
    metadata = normalize_metadata(metadata)
    design=bool(metadata.get('systemdesign') or metadata.get('classname'))
    entries=([metadata.get('constructor',{})]+metadata.get('methods',[])) if design else [metadata]
    if design and not re.fullmatch(r'[A-Za-z_]\w*',metadata.get('classname','')):raise ValueError('类名不合法')
    for method in entries:
        if method.get('name') and not re.fullmatch(r'[A-Za-z_]\w*',method['name']):raise ValueError('方法名不合法')
        types=[p.get('type','') for p in method.get('params',[])]+[method.get('return',{}).get('type','void')]
        for value in types:
            base=value
            while base.endswith('[]'):base=base[:-2]
            if base not in SCALAR|{'ListNode','TreeNode'}:raise ValueError('暂不支持的力扣接口类型：'+value)
    if not design and not metadata.get('name'):raise ValueError('缺少函数入口')
    if not design and metadata.get('return',{}).get('type')=='void':raise ValueError('就地修改接口需要单独适配输出')
    # repr encodes source metadata as data, never as interpolated source text.
    prelude='from typing import *\nfrom collections import *\nimport math, heapq, bisect\n'
    prelude+='import collections, functools, itertools, random, string, bisect, heapq, math, operator\n'
    # Public platform editorials rely on these standard-library names being
    # preimported by the judge. Restore that runtime, preserving source code.
    prelude+='from operator import add, sub, mul, truediv, floordiv, mod, neg, itemgetter, attrgetter\n'
    prelude+='from functools import cache, lru_cache, reduce, cmp_to_key\n'
    # The source judge permits deep tree recursion; Python's local default of
    # 1000 frames must not turn a legitimate skew tree into an algorithm error.
    # Execution remains subject to the sandbox's time/memory limits.
    prelude+='import sys\nsys.setrecursionlimit(100000)\n'
    prelude+='''class ListNode:
    def __init__(self, val=0, next=None): self.val, self.next = val, next
class TreeNode:
    def __init__(self, val=0, left=None, right=None): self.val, self.left, self.right = val, left, right
'''
    driver='\n_lc_meta='+repr(metadata)+'\n'+'''import json as _lc_json, sys as _lc_sys
def _lc_read(text):
    result=[]; decoder=_lc_json.JSONDecoder(); pos=0
    while pos<len(text):
        while pos<len(text) and text[pos] in ' \\t\\r\\n,': pos+=1
        if pos==len(text): break
        # LeetCode descriptions may show nums = [...], target = 2.
        if text[pos].isalpha() or text[pos]=='_':
            import re
            match=re.match(r'[A-Za-z_]\\w*\\s*=\\s*', text[pos:])
            if match: pos+=match.end()
        value,end=decoder.raw_decode(text,pos);result.append(value);pos=end
    return result
def _lc_decode(value, kind):
    if kind.endswith('[]'): return [_lc_decode(x,kind[:-2]) for x in value]
    if kind=='ListNode':
        head=tail=ListNode()
        for x in value: tail.next=ListNode(x);tail=tail.next
        return head.next
    if kind=='TreeNode':
        if not value or value[0] is None:return None
        root=TreeNode(value[0]);pending=deque([root]);index=1
        while pending and index<len(value):
            node=pending.popleft()
            for side in ('left','right'):
                if index>=len(value):break
                x=value[index];index+=1
                if x is not None:
                    child=TreeNode(x);setattr(node,side,child);pending.append(child)
        if any(x is not None for x in value[index:]):raise ValueError('invalid tree encoding')
        return root
    return value
def _lc_encode(value, kind):
    if kind=='void': return None
    if kind.endswith('[]'):return [_lc_encode(x,kind[:-2]) for x in value]
    if kind=='ListNode':
        result=[];seen=set()
        while value:
            if id(value) in seen:raise ValueError('cyclic returned list')
            seen.add(id(value));result.append(value.val);value=value.next
        return result
    if kind=='TreeNode':
        result=[];pending=deque([value]);seen=set()
        while pending:
            node=pending.popleft()
            if node is None:result.append(None);continue
            if id(node) in seen:raise ValueError('cyclic returned tree')
            seen.add(id(node));result.append(node.val);pending.extend([node.left,node.right])
        while result and result[-1] is None:result.pop()
        return result
    return value
def _lc_args(values, spec):
    params=spec.get('params',[])
    if not isinstance(values,list) or len(values)!=len(params):raise ValueError('argument count mismatch')
    return [_lc_decode(v,p['type']) for v,p in zip(values,params)]
_lc_values=_lc_read(_lc_sys.stdin.read())
if _lc_meta.get('systemdesign') or _lc_meta.get('classname'):
    if len(_lc_values)!=2:raise ValueError('expected operations and argument arrays')
    operations,arguments=_lc_values
    if len(operations)!=len(arguments) or not operations or operations[0]!=_lc_meta['classname']:raise ValueError('invalid constructor sequence')
    instance=globals()[_lc_meta['classname']](*_lc_args(arguments[0],_lc_meta.get('constructor',{})))
    methods={m['name']:m for m in _lc_meta.get('methods',[])};result=[None]
    for operation,args in zip(operations[1:],arguments[1:]):
        if operation not in methods:raise ValueError('unknown operation')
        method=methods[operation];value=getattr(instance,operation)(*_lc_args(args,method))
        result.append(_lc_encode(value,method.get('return',{}).get('type','void')))
else:
    instance=Solution();value=getattr(instance,_lc_meta['name'])(*_lc_args(_lc_values,_lc_meta))
    result=_lc_encode(value,_lc_meta.get('return',{}).get('type','void'))
print(_lc_json.dumps(result,ensure_ascii=False))
'''
    if io_contract:
        from courseagent.stdio_contract import runtime_source
        driver=driver.replace('_lc_values=_lc_read(_lc_sys.stdin.read())',
            runtime_source()+'\n_c_io='+repr(io_contract)+'\n_lc_values=parse_input(_c_io,_lc_sys.stdin.read())')
        driver=driver.replace('print(_lc_json.dumps(result,ensure_ascii=False))',
            '_lc_sys.stdout.write(serialize_output(_c_io,result,_lc_values))')
    return {'prelude_code':prelude,'driver_code':driver,'driver_kind':'c_stdio_metadata_python_v1' if io_contract else 'leetcode_metadata_python_v1'}


def outputs_equal(actual,expected,question):
    if question.get('source_protocol') in ('function','class'):
        try:
            # bool is not interchangeable with integer in JSON results.
            def typed(value):
                if isinstance(value,list):return ('list',tuple(typed(v) for v in value))
                if isinstance(value,dict):return ('object',tuple(sorted((k,typed(v)) for k,v in value.items())))
                return (type(value).__name__,value)
            return typed(json.loads(actual))==typed(json.loads(expected))
        except (ValueError,TypeError):return False
    return actual.split()==expected.split()
