"""Extract local teaching sources. Source text is data, never workflow instructions."""
from courseagent.paths import ROOT as WORKSPACE_ROOT
import hashlib
import re
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = WORKSPACE_ROOT
FILES = ROOT/'data/documents'
MATERIAL_DIRS = ('课堂ppt参考（pdf形式）','教材习题及解答','参考题目及答案')
W = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}


def source_id(path):
    return hashlib.sha256(path.name.encode()).hexdigest()[:16]


def docx_paragraphs(path):
    with ZipFile(path) as z:
        if sum(x.file_size for x in z.infolist()) > 100_000_000:
            raise ValueError('Word 解压后内容过大')
        tree = ET.fromstring(z.read('word/document.xml'))
    result = []
    for number, p in enumerate(tree.findall('.//w:p', W), 1):
        pieces = []
        for run in p.findall('.//w:r', W):
            text = ''.join(n.text or '' for n in run.findall('w:t', W))
            align = run.find('w:rPr/w:vertAlign', W)
            if align is not None and align.get('{'+W['w']+'}val') == 'superscript':
                text = text.translate(str.maketrans('0123456789', '⁰¹²³⁴⁵⁶⁷⁸⁹'))
            pieces.append(text)
        text = ''.join(pieces).strip()
        if text:
            result.append({'paragraph': number, 'text': text})
    return result


def read_source(path):
    path=Path(path)
    stat=path.stat()
    cache_key=hashlib.sha256((str(path.resolve())+':'+str(stat.st_mtime_ns)+':'+str(stat.st_size)+':materials-v1').encode()).hexdigest()
    cache=ROOT/'data/material-text-cache'/f'{cache_key}.json'
    try:return json.loads(cache.read_text(encoding='utf-8'))
    except (OSError,ValueError):pass
    sid = source_id(path)
    if path.suffix.lower() == '.pdf':
        from pypdf import PdfReader
        reader = PdfReader(path)
        chunks = [{'page': i+1, 'text': (page.extract_text() or '').strip()} for i, page in enumerate(reader.pages)]
        warning = '图示和公式可能需要对照原页检查。'
        if not any(c['text'] for c in chunks):
            warning = '未提取到文字，可能是扫描 PDF；当前尚未接入 OCR。'
    elif path.suffix.lower() == '.docx':
        chunks = docx_paragraphs(path)
        warning = '当前按文字和题号提取；图片、复杂公式需对照原文。'
    else:
        raise ValueError('目前支持 .docx 和有文字层的 .pdf')
    role='course_scope' if path.parent.name==MATERIAL_DIRS[0] else 'textbook_exercises' if path.parent.name==MATERIAL_DIRS[1] else 'reference_questions'
    result={'id': sid, 'name': path.name, 'kind': path.suffix.lower()[1:], 'chunks': chunks,
            'path':str(path.resolve()),'material_role':role,
            'answer_hint':'absent' if '不提供参考答案' in path.name else 'companion' if path.parent.name==MATERIAL_DIRS[1] or '答案' in path.name else 'inspect',
            'pages': len(chunks) if path.suffix.lower() == '.pdf' else None, 'warning': warning}
    cache.parent.mkdir(parents=True,exist_ok=True)
    from uuid import uuid4
    temp=cache.with_name(cache.name+'.'+uuid4().hex+'.tmp')
    temp.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8');temp.replace(cache)
    return result


def extract_word_questions(source):
    questions, current, kind = [], None, 1
    headings = [('多选', 2), ('判断', 3), ('填空', 4), ('简答', 5), ('算法设计', 5), ('选择', 1), ('单选', 1)]
    for chunk in source['chunks']:
        text = chunk['text']
        if re.match(r'^\d+[．.]\s*', text):
            matched = next((t for h, t in headings if h in text), None)
            if matched:
                if current:
                    questions.append(current)
                    current = None
                kind = matched
                continue
        match = re.match(r'^[（(]\s*(\d+)\s*[）)]\s*(.*)', text)
        if match:
            if current:
                questions.append(current)
            current = {'source_number': int(match[1]), 'stem': match[2], 'body': [], 'type': kind,
                       'source_refs': [{'document_id': source['id'], 'paragraph': chunk['paragraph']}]}
        elif current:
            current['body'].append(text)
    if current:
        questions.append(current)
    for q in questions:
        body = '\n'.join(q.pop('body'))
        q.update(id=f"{source['id']}-{q['type']}-{q['source_number']}", source=source['name'], origin='document',
                 answer='', options=[], blanks=[], reference_answer='', rubric='', explanation='',
                 score=10 if q['type'] == 5 else 2, selected=False, approved=False, difficulty=2 if q['type'] == 5 else 1,
                 estimated_minutes=15 if q['type'] == 5 else 2, knowledge='', warning='原文答案待核对；此题由文档解析得到。')
        if q['type'] in (1, 2):
            body = body.translate(str.maketrans('ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯ', 'ABCDEFGHIJKLMNO'))
            answer_match = re.search(r'(?:参考答案|答案)\s*[:：]\s*([A-O]+)', body)
            if answer_match:
                q['answer'] = answer_match[1]
                body = body[:answer_match.start()]
            markers = list(re.finditer(r'(?<![A-Za-z])([A-O])[．.]\s*', body))
            q['options'] = [body[m.end():markers[i+1].start() if i+1 < len(markers) else len(body)].strip() for i, m in enumerate(markers)]
            q['warning'] = '原文未提供答案，需填写后审核。' if not q['answer'] else '答案由原文提取，需核对。'
        elif q['type'] == 5:
            marker = re.search(r'\[算法思路\]|\[算法描述\]|【答案】|(?:参考答案|答案)\s*[:：]', body)
            if marker:
                q['reference_answer'] = body[marker.end():].strip()
                q['stem'] += '\n' + body[:marker.start()].strip()
            elif body:
                q['stem'] += '\n' + body
            q['warning'] = '算法设计题按简答题处理，需教师人工评分；不是可自动评测的编程题。'
        else:
            q['warning'] = '已识别题型；答案格式需要教师补充。'
        if q.get('answer') or q.get('reference_answer'):
            from courseagent.answer_policy import mark_supplied_key
            mark_supplied_key(q,q['source_refs'],'literal_inline_document_key')
    return questions


def scan_sources():
    sources, errors = [], []
    FILES.mkdir(parents=True, exist_ok=True)
    paths=list(FILES.iterdir())
    for folder in MATERIAL_DIRS:
        directory=ROOT.parent/folder
        if directory.is_dir():paths.extend(directory.rglob('*'))
    for path in sorted(paths):
        if not path.is_file():continue
        if path.suffix.lower() not in ('.docx', '.pdf'):
            continue
        try:
            sources.append(read_source(path))
        except Exception as error:
            errors.append({'name': path.name, 'error': str(error)})
    return sources, errors
