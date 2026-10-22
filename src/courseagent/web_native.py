"""Extract explicit text question/option/answer blocks before asking a model.
Never infer an answer or turn an explanation into a question.
"""
import re

QUESTION_LINE = re.compile(r'_{3,}|[（(]\s*[）)]|[？?]')
NUMBERED = re.compile(r'^\s*(?:\d+\.\d+\s*|\d+[.．、)）]\s*)')
HEADING = re.compile(r'(?m)^\s*(?:[一二三四五六七八九十]+[、.．]\s*)?(?:[单双多]项?选择题|单选题|多选题|判断题|判断正误|填空题|简答题|应用题|参考答案|答案解析)\s*[:：]?\s*$')
TASK_VERB = re.compile(r'(?:请|试)(?:求|计算|解释|说明|分析|证明|设计|编写|给出|画出)|(?:^|[，,。；;:：])\s*(?:求|计算|解释|说明|分析|证明|设计|编写|给出|画出)')

def question_lines(text):
    """Literal standalone questions, excluding explanatory sentences."""
    return list(re.finditer(r'(?m)^([^\n]{8,1200})$',text))


def merged_question_blocks(text):
    """Document previews can concatenate a complete numbered exam section."""
    return any(len(re.findall(r'(?:\d+[.．、]\s*[\u4e00-\u9fff])',line))>=2
               for line in text.splitlines())


def question_starts(text):
    """Require a textual task, not navigation labels or empty code calls."""
    headings=list(HEADING.finditer(text))
    def judgment(pos):
        preceding=[h for h in headings if h.start()<pos]
        return bool(preceding and re.search(r'判断题|判断正误',preceding[-1][0]))
    starts=[]
    for m in question_lines(text):
        line=m[1]
        if len(re.findall(r'[\u4e00-\u9fff]',line))<6 or re.search(
                r'因此|所以|答案|解析|根据.*(?:得出|推出)|第[一二三四五六七八九十]+步|欢迎关注|你们学到|向AI',line):continue
        if (re.search(r'==|!=|&&|\|\||->|\?\s*[^?？\n]+:\s*',line)
                and not NUMBERED.match(line) and not re.search(r'请|下列|以下|结果|求|判断',line)):
            continue
        if (QUESTION_LINE.search(line) or NUMBERED.match(line) and
                (judgment(m.start()) or TASK_VERB.search(NUMBERED.sub('',line)) or re.search(r'以下|下列',line))):
            starts.append(m)
    return starts


def has_questions(text):
    if question_starts(text):return True
    # Some document previews place a whole section in one text block. Keep it
    # for model extraction; a navigation label alone is still insufficient.
    return bool(re.search(r'(?:判断正误|[单双多]项选择|单选题|多选题|判断题)[^\n]{0,120}?[（(]?\s*[√×]?\s*[）)]?\s*\d+[.．、]',text))


def simple_questions(page):
    text=page['text'];result=[]
    starts=question_starts(text)
    # Numbered statements in an explicitly labeled judgment section may lack
    # a question mark. Never turn arbitrary prose into judgments.
    headings=list(HEADING.finditer(text))
    def is_judgment(pos):
        preceding=[h for h in headings if h.start()<pos]
        return bool(preceding and re.search(r'判断题|判断正误',preceding[-1][0]))
    for i,m in enumerate(starts):
        if merged_question_blocks(m[1]):continue
        stem=NUMBERED.sub('',m[1]).strip().lstrip('：:').strip()
        end=starts[i+1].start() if i+1<len(starts) else len(text)
        # Also stop at a truncated next question, never absorb it as answer text.
        boundary=re.search(r'(?m)^\s*(?:\d+\.\d+\s*|\d+[.．、)）]\s*)[\u4e00-\u9fff]',text[m.end():end])
        if boundary:end=m.end()+boundary.start()
        tail=text[m.end():min(end,m.end()+1800)]
        markers=list(re.finditer(r'(?:^|\s)([A-H])[.．、:：]\s*',tail))
        answer=re.search(r'(?:正确答案|参考答案|答案(?:为)?)\s*[:：]\s*([^\n]+)',tail)
        solution=re.search(r'【(?:解答|解析)】\s*([\s\S]+)',tail)
        body=tail[:answer.start()] if answer else tail
        section_end=re.search(r'(?m)^\s*(?:[一二三四五六七八九十]+[、.．]\s*)?(?:判断题|判断正误|填空题|单选题|多选题|简答题|应用题|参考答案|答案解析)\s*[:：]?\s*$',body)
        if section_end:body=body[:section_end.start()]
        markers=[x for x in markers if x.start()<len(body)]
        item={'stem':stem,'options':[],'answer':'','blanks':[],'reference_answer':'',
              'stem_evidence':m[1],'answer_evidence':'','fit_reason':'从网页逐字定位完整原题；缺失答案由独立作答补充。'}
        if len(markers)>=2 and [x[1] for x in markers]==list('ABCDEFGH'[:len(markers)]):
            options=[body[x.end():markers[j+1].start() if j+1<len(markers) else len(body)].strip() for j,x in enumerate(markers)]
            if any(not x or len(x)>600 for x in options):continue
            item.update(type=1,options=options,stem_evidence=m[1]+text[m.end():m.end()+len(body)])
            if answer and re.fullmatch(r'[A-H][。.]?',answer[1].strip()):
                item.update(answer=answer[1].strip().rstrip('。.'),answer_evidence=answer[0])
        elif is_judgment(m.start()) and NUMBERED.match(m[1]):
            item['type']=3
            if answer and re.fullmatch(r'正确|错误|对|错|√|×',answer[1].strip()):
                item.update(answer=answer[1].strip(),answer_evidence=answer[0])
        elif re.search(r'_{3,}|[（(]\s*[）)]',stem):
            item['type']=4
            # Copy only an explicit single blank answer. Complex prose is left
            # answerless rather than inventing a parsed mathematical formula.
            if answer and len(re.findall(r'_{3,}|[（(]\s*[）)]',stem))==1 and len(answer[1])<100:
                item.update(blanks=[answer[1].strip().rstrip('。;；')],answer_evidence=answer[0])
        else:
            # Questions asking for an explanation are legitimate answerless
            # short questions, but prose statements never get relabeled.
            if not TASK_VERB.search(stem):continue
            item['type']=5
            if solution and len(solution[1].strip())>=8:
                item.update(reference_answer=solution[1].strip(),answer_evidence=solution[0])
        result.append(item)
    return result

def explicit_questions(page):
    text=page['text'];result=[]
    starts=list(re.finditer(r'(?:^|\n)题目\s*\n?\s*[:：]',text))
    for idx,start in enumerate(starts):
        end=starts[idx+1].start() if idx+1<len(starts) else len(text)
        block=text[start.end():min(end,start.end()+2200)]
        answer_matches=list(re.finditer(r'(?:正确答案|参考答案|你的答案|答案)\s*[:：]\s*([A-O])[.．、]?\s*([^\n]*)',block))
        # A solution post often prints the author's answer before the official
        # answer.  Prefer the explicit correct/reference answer when both are
        # present; otherwise keep the first answer marker.
        answer=next((m for m in answer_matches if re.match(r'(?:正确答案|参考答案)', m[0])),
                    answer_matches[0] if answer_matches else None)
        if not answer:continue
        body=block[:answer.start()];markers=list(re.finditer(r'(?<![a-zA-Z])([A-O])[.．、]\s*',body))
        if len(markers)<2 or [m[1] for m in markers]!=list('ABCDEFGHIJKLMNO'[:len(markers)]):continue
        stem=body[:markers[0].start()].strip();options=[body[m.end():markers[i+1].start() if i+1<len(markers) else len(body)].strip() for i,m in enumerate(markers)]
        options[-1]=re.sub(r'(?:你的答案|正确答案)\s*$', '',options[-1]).strip()
        if not stem or len(stem)>2000 or any(not o or len(o)>2000 for o in options):continue
        typ=1;letter=answer[1];value=letter
        if set(options)<=set(('对','错','正确','错误','是','否')):
            typ=3;value=options[ord(letter)-65] if ord(letter)-65<len(options) else '';options=[]
        result.append({'type':typ,'stem':stem,'options':options,'answer':value,'blanks':[],'reference_answer':'','stem_evidence':body.strip(),'answer_evidence':answer[0],'fit_reason':'网页完整题干、选项和显式答案可直接定位；教学范围及答案正确性仍需教师核对。'})
    seen={re.sub(r'\s+','',q['stem']) for q in result}
    for q in simple_questions(page):
        key=re.sub(r'\s+','',q['stem'])
        if key not in seen:result.append(q);seen.add(key)
    return result
