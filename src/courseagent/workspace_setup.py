"""Create a blank workspace and an original, minimal OOXML export template.

Never copy developer data, download a template, or replace an existing file.
"""
from courseagent.paths import ROOT as WORKSPACE_ROOT
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED
from io import BytesIO

MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def template_bytes():
    headers = [
        ['试题类型', '标题', *['选项' + chr(65+i) for i in range(15)], '答案', '分数', '知识点', '题目解析'],
        ['任务名称 ', '描述', '知识点', '题目得分', '难度', '时间限制（秒）',
         *[item for i in range(1, 5) for item in ('编程语言'+str(i), '学员初始代码')], '用户名',
         *[item for i in range(1, 5) for item in (f'测试用例({i})输入', f'测试用例({i})输出')], '题目解析', '参考答案'],
        ['描述', '知识点', '题目得分', '文件夹目录', '难度', '题目解析', '时间限制（秒）', '编程语言',
         '程序代码', '测试用例(1)输入', '测试用例(1)输出', '是否允许学生调试', '答案A', '答案B', '答案C', '答案D', '答案E'],
    ]
    content_types = ('<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                     + ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, 4)) + '</Types>')
    workbook = ET.Element('workbook', xmlns=MAIN)
    sheets = ET.SubElement(workbook, 'sheets')
    for i, name in enumerate(('普通题', '编程题', '程序填空题'), 1):
        ET.SubElement(sheets, 'sheet', name=name, sheetId=str(i), attrib={f'{{{REL}}}id': f'rId{i}'})
    buffer = BytesIO()
    with ZipFile(buffer, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', content_types)
        archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="'+REL+'/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr('xl/workbook.xml', ET.tostring(workbook, encoding='utf-8', xml_declaration=True))
        archive.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join(f'<Relationship Id="rId{i}" Type="{REL}/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1,4))+'</Relationships>')
        for i, names in enumerate(headers, 1):
            sheet = ET.Element('worksheet', xmlns=MAIN)
            ET.SubElement(sheet, 'dimension', ref=f'A1:Y1')
            row = ET.SubElement(ET.SubElement(sheet, 'sheetData'), 'row', r='1')
            for column, name in enumerate(names, 65):
                cell = ET.SubElement(row, 'c', r=f'{chr(column)}1', t='inlineStr')
                ET.SubElement(ET.SubElement(cell, 'is'), 't').text = name
            archive.writestr(f'xl/worksheets/sheet{i}.xml', ET.tostring(sheet, encoding='utf-8', xml_declaration=True))
    return buffer.getvalue()


def write_if_absent(path, content):
    """Exclusive creation also protects against concurrent API/Worker startup."""
    try:
        with path.open('xb') as stream:
            stream.write(content)
        return True
    except FileExistsError:
        return False


def initialize_workspace(root):
    root = Path(root)
    for directory in ('data', 'data/documents', 'outputs'):
        (root/directory).mkdir(parents=True, exist_ok=True)
    initial = {
        'data/review.json': {'name': '我的课程作业', 'version': 0, 'questions': [], 'programming_questions': []},
        'data/sources.json': {'sources': [], 'errors': []},
    }
    created = []
    for relative, document in initial.items():
        if write_if_absent(root/relative, json.dumps(document, ensure_ascii=False, indent=2).encode()):
            created.append(relative)
    if write_if_absent(root/'data/template.xlsx', template_bytes()):
        created.append('data/template.xlsx')
    return created


if __name__ == '__main__':
    created = initialize_workspace(WORKSPACE_ROOT)
    print('工作区就绪；新建文件：' + (', '.join(created) or '无（已有文件均保留）'))
