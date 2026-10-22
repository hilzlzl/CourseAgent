"""Canonical interface types shared by capability checks, drivers and codecs."""
import copy
import re


def normalize_type(value):
    if not isinstance(value, str):
        raise ValueError('接口类型必须是字符串')
    value = value.strip()
    if value.endswith('[]'):
        return normalize_type(value[:-2]) + '[]'
    match = re.fullmatch(r'(?:list|array|vector)\s*([<\[])(.+)([>\]])', value, re.I)
    if match and (match[1], match[3]) in (('<', '>'), ('[', ']')):
        return normalize_type(match[2]) + '[]'
    aliases = {'int': 'integer', 'bool': 'boolean', 'str': 'string',
               'listnode': 'ListNode', 'treenode': 'TreeNode'}
    return aliases.get(value.casefold(), value)


def normalize_metadata(metadata):
    result = copy.deepcopy(metadata)
    design = bool(result.get('systemdesign') or result.get('classname'))
    methods = [result.get('constructor', {})] + result.get('methods', []) if design else [result]
    for method in methods:
        for param in method.get('params', []):
            param['type'] = normalize_type(param.get('type', ''))
        if 'return' in method:
            method['return']['type'] = normalize_type(method['return'].get('type', 'void'))
    return result
