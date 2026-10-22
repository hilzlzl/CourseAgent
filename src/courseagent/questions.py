"""Question schemas, approval snapshots, and the verified Educoder Excel mapping."""
from courseagent.paths import ROOT as WORKSPACE_ROOT
import math
import re
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

TYPE_NAMES = {1: '单选题', 2: '多选题', 3: '判断题', 4: '填空题', 5: '简答题'}
NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
ET.register_namespace('', NS)
REVIEW_FIELDS = ('type', 'stem', 'options', 'answer', 'blanks', 'reference_answer',
                 'rubric', 'score', 'knowledge', 'explanation', 'source', 'source_refs')


def review_content(q):
    return {field: q.get(field) for field in REVIEW_FIELDS}


def validate_question(q, approved_only=False):
    if not isinstance(q, dict) or q.get('type') not in TYPE_NAMES:
        raise ValueError('当前支持单选、多选、判断、填空、简答五种题型')
    if q.get('teacher_difficulty',0) not in (0,1,2,3):
        raise ValueError('教师标注难度不正确')
    minutes = q.get('estimated_minutes',2)
    if isinstance(minutes,bool) or not isinstance(minutes,(int,float)) or not math.isfinite(minutes) or not 0 < minutes <= 10000:
        raise ValueError('参考用时必须为大于0且不超过10000的分钟数')
    label = f"题目 {q.get('source_number') or q.get('id', '')}"
    if not isinstance(q.get('stem'), str) or not q['stem'].strip():
        raise ValueError(label + '：题干不能为空')
    score = q.get('score')
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or score <= 0:
        raise ValueError(label + '：分值必须为正数')
    if q['type'] in (1, 2):
        options = q.get('options')
        if not isinstance(options, list) or not 2 <= len(options) <= 15 or not all(isinstance(s, str) and s.strip() for s in options):
            raise ValueError(label + '：需要 2–15 个非空选项')
        answer = q.get('answer', '')
        if not isinstance(answer, str) or not answer or any(a not in 'ABCDEFGHIJKLMNO'[:len(options)] for a in answer) or len(set(answer)) != len(answer):
            raise ValueError(label + '：答案必须使用对应选项字母，且不能重复')
        if q['type'] == 1 and len(answer) != 1:
            raise ValueError(label + '：单选题只能有一个正确答案')
        if q['type'] == 2 and len(answer) < 2:
            raise ValueError(label + '：多选题至少选择两个正确答案')
    elif q['type'] == 3:
        if q.get('answer') not in ('正确', '错误'):
            raise ValueError(label + '：判断题答案必须为“正确”或“错误”')
    elif q['type'] == 4:
        blanks = q.get('blanks')
        if not isinstance(blanks, list) or not 1 <= len(blanks) <= 8 or not all(isinstance(s, str) and s.strip() for s in blanks):
            raise ValueError(label + '：填写 1–8 个空的标准答案')
        markers = len(re.findall(r'_{3,}|[（(]\s*[）)]', q['stem']))
        if markers != len(blanks):
            raise ValueError(label + f'：题干识别到 {markers} 个空，但填写了 {len(blanks)} 个答案，请使用 ____ 或（  ）标记')
    elif q['type'] == 5:
        if not isinstance(q.get('reference_answer'), str) or not q['reference_answer'].strip():
            raise ValueError(label + '：简答题需要参考答案')
    texts = [q['stem'], *q.get('options', []), *q.get('blanks', []),
             q.get('reference_answer', ''), q.get('rubric', ''), q.get('knowledge', ''), q.get('explanation', '')]
    if any(not isinstance(s, str) or len(s) > 32767 or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', s) for s in texts):
        raise ValueError(label + '：文本包含无效字符或超过 Excel 长度上限')
    if approved_only and (q.get('approved') is not True or q.get('approval_snapshot') != review_content(q)):
        raise ValueError(label + '：尚未审核确认，或审核后内容发生变化')


def validate(document, approved_only=False):
    if not isinstance(document, dict) or not isinstance(document.get('questions'), list):
        raise ValueError('审核内容格式不正确')
    name = document.get('name', '')
    if not isinstance(name, str) or not name.strip() or len(name) > 60:
        raise ValueError('试卷名称必须为 1–60 个字符')
    selected = [q for q in document['questions'] if isinstance(q, dict) and q.get('selected')]
    from courseagent.programming_questions import validate_programming
    programming = document.get('programming_questions', [])
    if not isinstance(programming, list) or any(not isinstance(q, dict) for q in programming):
        raise ValueError('编程题题库格式不正确')
    programming = [q for q in programming if q.get('selected')]
    if not 1 <= len(selected) + len(programming) <= 300:
        raise ValueError('请选择 1–300 道题')
    counts=(document.get('plan') or {}).get('spec',{}).get('counts',{})
    if approved_only and counts and any(sum(q['type']==int(t) for q in selected)!=n for t,n in counts.items()):
        raise ValueError('组卷未完成：已选题型数量不符合本次要求，请补齐后再完成审核、导出或导入。')
    programming_count = (document.get('plan') or {}).get('spec',{}).get('programming_count', 0)
    if approved_only and programming_count and len(programming) != programming_count:
        raise ValueError('组卷未完成：编程题数量不符合本次要求，请补齐后再完成审核、导出或导入。')
    for q in selected:
        validate_question(q, approved_only)
    for q in programming:
        validate_programming(q, approved_only)
    return selected + programming


def normalize_approvals(document):
    for q in document['questions']:
        if not q.get('approved'):
            continue
        try:
            validate_question(q, True)
        except ValueError:
            q['approved'] = False
            q.pop('approval_snapshot', None)
    from courseagent.programming_questions import normalize_document
    return normalize_document(document)


def excel_values(q):
    values = {'A': q['type'], 'B': q['stem'], 'S': q['score'], 'T': q.get('knowledge', '')[:50], 'U': q.get('explanation', '')}
    if q['type'] in (1, 2):
        from courseagent.platform_format import option_texts
        values.update({chr(67+i): value for i, value in enumerate(option_texts(q['options']))})
        values['R'] = ''.join(sorted(q['answer']))
    elif q['type'] == 3:
        values['R'] = q['answer']
    elif q['type'] == 4:
        values.update({chr(67+i): value for i, value in enumerate(q['blanks'])})
    else:
        values['C'] = q['reference_answer']
        if q.get('rubric', '').strip():
            values['U'] = (values['U'] + '\n\n评分要点：\n' + q['rubric']).strip()
    if any(isinstance(v, str) and len(v) > 32767 for v in values.values()):
        raise ValueError('合并后的参考答案或解析超过 Excel 单元格长度上限')
    return values


def export_xlsx(document, approved_only=True, template=None):
    questions = validate(document, approved_only)
    if any(q.get('selected') for q in document.get('programming_questions', [])):
        from courseagent.programming_questions import export_programming_xlsx
        ordinary = {k: v for k, v in document.items() if k != 'programming_questions'}
        # Ordinary worksheet validation must not require the programming worksheet twice.
        import copy
        ordinary = copy.deepcopy(ordinary)
        if ordinary.get('plan'):ordinary['plan']['spec']['programming_count']=0
        return export_programming_xlsx(document['programming_questions'], ordinary, approved_only, template)
    template = template or WORKSPACE_ROOT/'data/template.xlsx'
    with ZipFile(template) as source:
        sheet = ET.fromstring(source.read('xl/worksheets/sheet1.xml'))
        data = sheet.find(f'{{{NS}}}sheetData')
        for row in list(data):
            if row.get('r') != '1':
                data.remove(row)
        for index, q in enumerate(questions, 2):
            row = ET.SubElement(data, f'{{{NS}}}row', {'r': str(index)})
            for col, value in sorted(excel_values(q).items()):
                cell = ET.SubElement(row, f'{{{NS}}}c', {'r': f'{col}{index}'})
                if isinstance(value, (int, float)):
                    ET.SubElement(cell, f'{{{NS}}}v').text = str(value)
                else:
                    cell.set('t', 'inlineStr')
                    text = ET.SubElement(ET.SubElement(cell, f'{{{NS}}}is'), f'{{{NS}}}t')
                    text.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
                    text.text = str(value)
        sheet.find(f'{{{NS}}}dimension').set('ref', f'A1:W{len(questions)+1}')
        stream = BytesIO()
        with ZipFile(stream, 'w', ZIP_DEFLATED) as target:
            for info in source.infolist():
                content = source.read(info.filename)
                if info.filename == 'xl/worksheets/sheet1.xml':
                    content = ET.tostring(sheet, encoding='utf-8', xml_declaration=True)
                elif re.fullmatch(r'xl/worksheets/sheet[23]\.xml', info.filename):
                    other = ET.fromstring(content)
                    rows = other.find(f'{{{NS}}}sheetData')
                    for row in list(rows):
                        if row.get('r') != '1':
                            rows.remove(row)
                    other.find(f'{{{NS}}}dimension').set('ref', 'A1:Y1')
                    content = ET.tostring(other, encoding='utf-8', xml_declaration=True)
                target.writestr(info, content)
    return stream.getvalue()
