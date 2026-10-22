"""Conservative matching of explicit PDF choice answers to existing Word questions."""
import copy
import re
import unicodedata


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text).lower() if c.isalnum())


def choice_answers(source):
    if source['kind'] != 'pdf' or '答案' not in source['name']:
        return []
    lines = []
    for chunk in source['chunks']:
        lines.extend((line, chunk['page']) for line in chunk['text'].splitlines())
    result, current, choice_section = [], None, False
    for line, page in lines:
        if re.match(r'^\s*\d+[．.]\s*(?:单选|选择|多选)', line):
            choice_section = True
            continue
        if re.match(r'^\s*\d+[．.]\s*(?:算法|简答|判断|填空)', line):
            if current: result.append(current)
            current = None
            choice_section = False
        if not choice_section: continue
        match = re.match(r'^\s*[（(]\s*(\d+)\s*[）)]\s*(.*)', line)
        if match:
            if current: result.append(current)
            current = {'number': int(match[1]), 'lines': [match[2]], 'pages': [page]}
        elif current:
            current['lines'].append(line)
            if page not in current['pages']: current['pages'].append(page)
    if current: result.append(current)
    answers = []
    for block in result:
        text = '\n'.join(block['lines'])
        answer = re.search(r'(?:参考答案|答案)\s*[:：]\s*([A-OＡ-Ｏ]+)\s*(?:\n|$)', text)
        if not answer: continue
        before = text[:answer.start()]
        markers = list(re.finditer(r'(?<![A-Za-z])([A-OＡ-Ｏ])[．.]\s*', before))
        if len(markers) < 2: continue
        letters = [unicodedata.normalize('NFKC', m[1]) for m in markers]
        if letters != [chr(65+i) for i in range(len(letters))]: continue
        options = [before[m.end():markers[i+1].start() if i+1<len(markers) else len(before)].strip() for i,m in enumerate(markers)]
        answers.append({'number': block['number'], 'stem': before[:markers[0].start()].strip(),
                        'options': options, 'answer': unicodedata.normalize('NFKC', answer[1]),
                        'explanation': re.sub(r'^\s*(?:解释|解析)\s*[:：]\s*', '', text[answer.end():]).strip(),
                        'refs': [{'document_id': source['id'], 'page': p} for p in block['pages']], 'source': source['name']})
    return answers


def attach_answers(document, sources):
    result = copy.deepcopy(document)
    answers = [a for source in sources for a in choice_answers(source)]
    matched, conflicts = 0, 0
    for q in result['questions']:
        if q['type'] not in (1,2) or q.get('origin') != 'document': continue
        stem = normalized(q['stem'])
        candidates = [a for a in answers if a['number'] == q.get('source_number') and
                      len(stem) >= 6 and (normalized(a['stem']) == stem or normalized(a['stem']).startswith(stem)) and
                      [normalized(v) for v in a['options']] == [normalized(v) for v in q.get('options',[])]]
        if not candidates: continue
        if len({a['answer'] for a in candidates}) != 1:
            conflicts += 1
            continue
        a = candidates[0]
        if q.get('answer'):
            if q['answer']==a['answer'] and normalized(a['stem'])==stem and not q.get('answer_provenance'):
                from courseagent.answer_policy import mark_supplied_key
                q['source_refs']=q.get('source_refs',[])+[r for r in a['refs'] if r not in q.get('source_refs',[])]
                mark_supplied_key(q,a['refs'],'literal_stem_and_ordered_options')
            continue
        if normalized(a['stem']) != stem:
            q['stem'] = a['stem']  # Restore missing multi-line statement from the matched source.
        q['answer'] = a['answer']
        if not q.get('explanation'): q['explanation'] = a['explanation']
        q['source_refs'] = q.get('source_refs',[]) + [r for r in a['refs'] if r not in q.get('source_refs',[])]
        q['approved'] = False
        q.pop('approval_snapshot',None)
        from courseagent.answer_policy import mark_supplied_key
        mark_supplied_key(q, a['refs'], 'literal_stem_and_ordered_options')
        q['warning'] = '采用配套资料标准答案；只检查原文提取、题答匹配和导入格式。'
        matched += 1
    result['answer_matching'] = {'matched': matched, 'conflicts': conflicts}
    return attach_algorithm_answers(result, sources)


def attach_algorithm_answers(document, sources):
    """Use companion filename, question number and statement prefix; ignore numbered code steps."""
    result = copy.deepcopy(document)
    matched = 0
    for source in sources:
        if source['kind'] != 'pdf' or '答案' not in source['name']: continue
        companion = normalized(source['name'].rsplit('.',1)[0].replace('答案',''))
        questions = [q for q in result['questions'] if q['type']==5 and q.get('origin')=='document' and
                     normalized(q.get('source','').rsplit('.',1)[0])==companion]
        text = ''
        pages = []
        for chunk in source['chunks']:
            pages.append((len(text), chunk['page']))
            text += chunk['text']+'\n'
        positions = []
        for marker in re.finditer(r'(?m)^\s*[（(]\s*(\d+)\s*[）)]\s*', text):
            prefix = normalized(text[marker.end():marker.end()+500])
            matches = [q for q in questions if q.get('source_number')==int(marker[1]) and
                       len(normalized(q['stem']))>=20 and prefix.startswith(normalized(q['stem'])[:30])]
            if len(matches)==1: positions.append((marker.start(), matches[0]))
        for i,(start,q) in enumerate(positions):
            if q.get('reference_answer'): continue
            if sum(other['id']==q['id'] for _,other in positions)!=1: continue
            end = positions[i+1][0] if i+1<len(positions) else len(text)
            block = text[start:end]
            answer = re.search(r'\[(?:题目分析|算法思路|算法描述)\]|【(?:题目分析|算法思路|算法描述|答案)】|(?:参考答案|答案)\s*[:：]', block)
            if not answer: continue
            q['reference_answer'] = block[answer.start():].strip()
            refs = [{'document_id':source['id'],'page':page} for offset,page in pages
                    if offset < end and next((o for o,p in pages if p==page+1),len(text)) > start]
            q['source_refs'] = q.get('source_refs',[])+[r for r in refs if r not in q.get('source_refs',[])]
            q['approved']=False;q.pop('approval_snapshot',None)
            q['difficulty_basis']='import_default'
            from courseagent.answer_policy import mark_supplied_key
            mark_supplied_key(q, refs, 'companion_document_number_and_stem')
            q['warning']='采用同名配套 PDF 标准答案；检查提取与题答匹配，导出为人工评分简答题。'
            matched += 1
    result.setdefault('answer_matching',{})['algorithm_matched']=matched
    result['answer_matching']['matched']=result['answer_matching'].get('matched',0)+matched
    return result
