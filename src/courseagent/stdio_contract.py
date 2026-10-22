"""A single C-style I/O contract for statements, samples, drivers and tests.

Source JSON is only consumed at the import boundary, never student stdin.
The executable codec is also embedded verbatim in isolated reference drivers.
"""
import copy
import inspect
import io
import json
import math
import re

VERSION = 'c-stdio-v1'
INTEGER = {'integer', 'int', 'long'}
REAL = {'double', 'float'}
BOOLEAN = {'boolean', 'bool'}
STRING = {'string', 'character', 'char'}


def descriptor(type_name, matrix=False):
    from courseagent.interface_types import normalize_type
    type_name = normalize_type(type_name)
    if type_name.endswith('[]'):
        child=descriptor(type_name[:-2])
        return {'kind':'matrix' if matrix and child['kind']=='array' else 'array', 'item':child['item'] if matrix and child['kind']=='array' else child}
    if type_name in INTEGER:return {'kind':'int'}
    if type_name in REAL:return {'kind':'real'}
    if type_name in BOOLEAN:return {'kind':'bool'}
    if type_name in STRING:return {'kind':'string'}
    if type_name=='ListNode':return {'kind':'array','item':{'kind':'int'}}
    if type_name=='TreeNode':return {'kind':'tree'}
    if type_name=='void':return {'kind':'void'}
    raise ValueError('尚无标准输入输出协议的类型：'+str(type_name))


def make_contract(metadata, statement=''):
    from courseagent.interface_types import normalize_metadata
    metadata = normalize_metadata(metadata)
    from courseagent.leetcode_driver import python_driver
    python_driver(metadata)  # Validate interface identifiers and supported types.
    def method(m):
        params=[]
        for p in m.get('params',[]):
            # Only an explicitly described matrix gets a rectangular layout.
            # General nested arrays retain per-row lengths (e.g. adjacency lists).
            matrix=p['type'].endswith('[][]') and bool(re.search(r'矩阵|\bmatrix\b',statement,re.I))
            params.append({'name':p['name'],'type':p['type'],'encoding':descriptor(p['type'],matrix)})
        return {'name':m.get('name',''), 'params':params,
                'return_type':m.get('return',{}).get('type','void'),
                'output':descriptor(m.get('return',{}).get('type','void'))}
    if metadata.get('systemdesign') or metadata.get('classname'):
        return {'version':VERSION,'kind':'class','classname':metadata['classname'],
                'constructor':method(metadata.get('constructor',{})),
                'methods':[method(m) for m in metadata.get('methods',[])]}
    result={'version':VERSION,'kind':'function',**method(metadata)}
    if result['output']['kind']=='void':raise ValueError('就地修改接口尚未指定标准输出')
    return result


def source_values(text):
    """Read original named/consecutive JSON values without executing text."""
    result=[];decoder=json.JSONDecoder();pos=0
    while pos<len(text):
        while pos<len(text) and text[pos] in ' \t\r\n,':pos+=1
        if pos==len(text):break
        name=re.match(r'[A-Za-z_]\w*\s*=\s*',text[pos:])
        if name:pos+=name.end()
        value,pos=decoder.raw_decode(text,pos);result.append(value)
    return result


def _scalar(value, kind):
    if kind=='bool':
        if type(value) is not bool:raise ValueError('布尔参数必须是真假值')
        return '1' if value else '0'
    if kind=='int':
        if type(value) is not int or not -(2**63)<=value<2**63:raise ValueError('整数超出有符号64位范围')
        return str(value)
    if kind=='real':
        if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('非法实数')
        return str(value)
    if kind=='string':
        if not isinstance(value,str) or '\n' in value or '\r' in value:raise ValueError('字符串必须占一整行，可含空格或为空')
        return value
    raise ValueError('非法标量类型')


def _write_value(value, spec):
    kind=spec['kind']
    if kind in ('int','real','bool','string'):return [_scalar(value,kind)]
    if kind=='void':
        if value is not None:raise ValueError('无返回值操作不能有结果')
        return []
    if not isinstance(value,list):raise ValueError('数组或树编码必须为列表')
    if kind == 'fixed_char_grid':
        if (len(value) != spec['rows'] or any(not isinstance(row, list) or len(row) != spec['cols']
                or any(not isinstance(v, str) or len(v) != 1 or v.isspace() for v in row) for row in value)):
            raise ValueError('固定字符棋盘尺寸或字符不合法')
        return [''.join(row) for row in value]
    if kind=='tree':
        if any(x is not None and type(x) is not int for x in value):raise ValueError('树节点应为整数或空节点')
        return [str(len(value)),' '.join('#' if x is None else _scalar(x,'int') for x in value)]
    item=spec['item']
    if kind=='matrix':
        width=len(value[0]) if value else 0
        if any(not isinstance(row,list) or len(row)!=width for row in value):raise ValueError('矩阵各行长度必须相同')
        if item['kind'] not in ('int','real','bool'):raise ValueError('该矩阵类型需要逐元素协议')
        return [str(len(value))+' '+str(width)]+[' '.join(_scalar(v,item['kind']) for v in row) for row in value]
    if kind!='array':raise ValueError('未知输入编码')
    if spec.get('order') == 'lexicographic':
        value = sorted(value)
    if item['kind'] in ('int','real','bool'):
        return [str(len(value)),' '.join(_scalar(v,item['kind']) for v in value)]
    return [str(len(value))]+[line for v in value for line in _write_value(v,item)]


def _read_scalar(token, kind):
    if kind=='string':return token
    if kind=='bool':
        if token not in ('0','1'):raise ValueError('布尔值只能写0或1')
        return token=='1'
    if kind=='int':
        if not re.fullmatch(r'[+-]?\d+',token):raise ValueError('需要十进制整数')
        value=int(token);_scalar(value,kind);return value
    value=float(token);_scalar(value,'real');return value


def _line(stream):
    line=stream.readline()
    if line=='':raise ValueError('输入行数不足')
    return line.rstrip('\n').rstrip('\r')


def _count(text):
    value=_read_scalar(text.strip(),'int')
    if not 0<=value<=1000000:raise ValueError('长度应为0至1000000')
    return value


def _read_value(stream, spec):
    kind=spec['kind']
    if kind=='void':return None
    if kind == 'fixed_char_grid':
        value = [list(_line(stream)) for _ in range(spec['rows'])]
        _write_value(value, spec)
        return value
    if kind in ('int','real','bool','string'):
        line=_line(stream)
        if kind!='string' and len(line.split())!=1:raise ValueError('标量参数应单独占一行')
        return _read_scalar(line if kind=='string' else line.strip(),kind)
    if kind=='matrix':
        dims=_line(stream).split()
        if len(dims)!=2:raise ValueError('矩阵首行应为行数和列数')
        rows,cols=map(_count,dims);value=[]
        if rows*cols>1000000:raise ValueError('矩阵过大')
        for _ in range(rows):
            tokens=_line(stream).split()
            if len(tokens)!=cols:raise ValueError('矩阵列数不一致')
            value.append([_read_scalar(t,spec['item']['kind']) for t in tokens])
        return value
    size=_count(_line(stream))
    if kind=='tree':
        tokens=_line(stream).split()
        if len(tokens)!=size:raise ValueError('树节点编码长度不一致')
        value=[None if t=='#' else _read_scalar(t,'int') for t in tokens]
        # Reject encodings that silently lose non-null orphan nodes.
        pending=1 if value and value[0] is not None else 0;index=1
        while pending and index<size:
            pending-=1
            for _ in range(2):
                if index<size:
                    pending+=value[index] is not None;index+=1
        if any(x is not None for x in value[index:]):raise ValueError('树编码含无父节点的元素')
        return value
    item=spec['item']
    if item['kind'] in ('int','real','bool'):
        tokens=_line(stream).split()
        if len(tokens)!=size:raise ValueError('数组长度与元素数不一致')
        return [_read_scalar(t,item['kind']) for t in tokens]
    return [_read_value(stream,item) for _ in range(size)]


def serialize_input(contract, values):
    lines=[]
    if contract['kind']=='function':
        if len(values)!=len(contract['params']):raise ValueError('参数数量不一致')
        for value,p in zip(values,contract['params']):lines+=_write_value(value,p['encoding'])
    else:
        if len(values)!=2:raise ValueError('需要操作及参数序列')
        operations,arguments=values
        if len(operations)!=len(arguments) or not operations or operations[0]!=contract['classname']:raise ValueError('构造操作不匹配')
        methods={m['name']:m for m in contract['methods']}
        lines.append(str(len(operations)))
        for i,(op,args) in enumerate(zip(operations,arguments)):
            method=contract['constructor'] if i==0 else methods.get(op)
            if not method or len(args)!=len(method['params']):raise ValueError('操作或参数数量不一致')
            lines.append(op)
            for value,p in zip(args,method['params']):lines+=_write_value(value,p['encoding'])
    return '\n'.join(lines)+'\n'


def parse_input(contract, text):
    stream=io.StringIO(text)
    if contract['kind']=='function':values=[_read_value(stream,p['encoding']) for p in contract['params']]
    else:
        count=_count(_line(stream));operations=[];arguments=[]
        methods={m['name']:m for m in contract['methods']}
        for i in range(count):
            op=_line(stream).strip();method=contract['constructor'] if i==0 and op==contract['classname'] else methods.get(op) if i else None
            if not method:raise ValueError('未知操作或缺少首个构造操作')
            operations.append(op);arguments.append([_read_value(stream,p['encoding']) for p in method['params']])
        if not operations:raise ValueError('操作序列不能为空')
        values=[operations,arguments]
    if stream.read().strip():raise ValueError('输入含额外内容或仍为函数参数/JSON格式')
    return values


def serialize_output(contract, value, values=None):
    if contract['kind']=='function':lines=_write_value(value,contract['output'])
    else:
        operations=values[0]
        if not isinstance(value,list) or len(value)!=len(operations):raise ValueError('操作输出数量不一致')
        methods={m['name']:m for m in contract['methods']};lines=[]
        for i,(op,v) in enumerate(zip(operations,value)):
            spec={'kind':'void'} if i==0 else methods[op]['output']
            lines+=_write_value(v,spec)
    return '\n'.join(lines)+'\n' if lines else ''


def runtime_source():
    functions=(_scalar,_write_value,_read_scalar,_line,_count,_read_value,serialize_input,parse_input,serialize_output)
    return 'import io, re, math\n'+ '\n'.join(inspect.getsource(f) for f in functions)


def describe_value(spec, name, is_output=False):
    kind=spec['kind']
    if kind == 'fixed_char_grid':
        return f"{name}：固定 {spec['rows']} 行，每行 {spec['cols']} 个字符，字符之间不加空格，不写行数、列数或逐行长度。"
    if kind=='int':return f'{name}：一个十进制整数，单独占一行。'
    if kind=='real':return f'{name}：一个实数，单独占一行。'
    if kind=='bool':return f'{name}：单独一行，1 表示真，0 表示假。'
    if kind=='string':return f'{name}：一整行文字，可含空格或为空。'
    if kind=='tree':return f'{name}：第一行给出层序编码的元素个数，第二行按层序给出各元素，以空格分隔；# 表示空节点。空树写 0，下一行留空。'
    if kind=='matrix':return f'{name}：第一行给出行数 m 和列数 n，随后 m 行每行给出 n 个元素，元素间用空格分隔。'
    item=spec['item']
    if item['kind'] in ('int','real','bool'):
        return f'{name}：第一行给出元素个数 n，第二行给出 n 个元素，以空格分隔。'+('结果为空时，第一行写 0，第二行留空。' if is_output else 'n 必须满足下方数据范围；仅在原题明确允许空数组时，才能输入 n=0，此时第二行留空。')+('布尔元素使用 1 和 0。' if item['kind']=='bool' else '')
    return f'{name}：先用一行给出元素个数，随后依次按以下格式输入各元素：'+describe_value(item,'每个元素',is_output)


def format_sections(contract):
    if contract['kind']=='function':
        inputs='按以下顺序输入，各部分连续排列。所有长度和取值均须满足数据范围；格式说明不放宽原题约束：\n\n'+'\n\n'.join(describe_value(p['encoding'],p['name']) for p in contract['params'])
        output=describe_value(contract['output'],'计算结果',True).replace('输入','输出')
    else:
        inputs=('第一行输入操作总数 q（包含初始化）。之后依次输入各操作：操作名单独占一行，参数按下面的顺序紧随其后。第一项必须为 '+contract['classname']+'。\n\n')
        for name,m in [(contract['classname'],contract['constructor'])]+[(m['name'],m) for m in contract['methods']]:
            inputs+=name+'：'+('无参数。' if not m['params'] else ' '.join(describe_value(p['encoding'],p['name']) for p in m['params']))+'\n\n'
        output='按操作执行顺序输出有返回值操作的结果；初始化和无返回值操作不输出。\n\n'
        for m in contract['methods']:
            if m['output']['kind']!='void':output+=m['name']+'：'+describe_value(m['output'],'结果',True).replace('输入','输出')+'\n\n'
    return inputs.strip(),output.strip()


def student_statement(source, contract, examples):
    from courseagent.platform_format import code_block
    # Source examples are replaced together, preserving task and constraints.
    text=source.split('\n\n运行约定：')[0]
    starts=list(re.finditer(r'(?m)^(?:#{1,6}\s*)?(?:示例\s*\d*|Example\s*\d*)\s*[：:]',text))
    constraints=re.search(r'(?m)^(?:#{1,6}\s*)?(?:提示|约束|数据范围|Constraints)\s*[：:]',text)
    task=text[:starts[0].start() if starts else constraints.start() if constraints else len(text)].strip()
    limits=text[constraints.end():].strip() if constraints else ''
    task=task.replace('在传递给函数之前','在给定的输入中').replace('请你编写一个函数','请你编写一个程序').replace('编写一个函数','编写一个程序').replace('返回','输出')
    # Only change output notation; input strings such as "true" keep their meaning.
    if contract['kind']=='function' and contract['output']['kind']=='bool':
        task=re.sub(r'输出\s*`*\s*true\s*`*\s*或\s*`*\s*false\s*`*','输出 1 或 0',task)
        task=re.sub(r'输出\s*`*\s*\b(true|false)\b\s*`*',
                    lambda m:'输出 '+('1' if m[1]=='true' else '0')+' ',task)
    inputs,outputs=format_sections(contract)
    result='### 题目描述\n\n'+task+'\n\n编写完整程序，从标准输入读取数据，将结果写到标准输出。\n\n### 输入格式\n\n'+inputs+'\n\n### 输出格式\n\n'+outputs
    if limits:result+='\n\n### 数据范围\n\n'+limits
    for i,e in enumerate(examples,1):
        result+=f'\n\n### 样例输入 {i}\n\n'+code_block(e['input'].rstrip('\n'))+f'\n\n### 样例输出 {i}\n\n'+code_block(e['output'].rstrip('\n'))
    return result
