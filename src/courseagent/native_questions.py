"""Use structured public question data directly, rather than asking an LLM to copy it."""
import copy
import hashlib
import json
from courseagent.leetcode_driver import python_driver


def blank_initial_code(q):
    """Clear automatic scaffolds without discarding unchanged algorithm evidence."""
    if q.get('answer_provenance'):return False
    changed=any(item.get('starter_code') for item in q.get('languages',[]))
    from courseagent.programming_verification import current_report,basis
    report=current_report(q) if changed else None
    for item in q.get('languages',[]):item['starter_code']=''
    if changed:
        q['approved']=False
        q.pop('approval_snapshot',None)
        if report:
            report['basis']=basis(q)
            q['execution_verification']=report
    q.get('execution_verification',{}).pop('template_io',None)
    return bool(changed)


def upgrade_native_question(q):
    """Convert legacy native candidates in place; never edit delivery snapshots."""
    from courseagent.stdio_contract import VERSION,make_contract,source_values,serialize_input,serialize_output,student_statement
    cleared=blank_initial_code(q)
    meta=q.get('source_metadata',{})
    if meta.get('provider')!='leetcode' or not meta.get('interface'):return cleared
    if q.get('io_contract',{}).get('version')==VERSION:return cleared
    if q.get('answer_provenance'):return False  # Teacher materials retain their own I/O and trusted answers.
    source=q.get('source_description') or q['description'].split('\n\n运行约定：')[0]
    contract=make_contract(meta['interface'],source)
    from courseagent.programming_verification import basis,case_basis
    from courseagent.source_verification import evidence_valid
    old_report=q.get('execution_verification',{})
    can_reuse=(old_report.get('passed') is True and old_report.get('basis')==basis(q)
              and old_report.get('case_basis')==case_basis(q) and evidence_valid(old_report,q))
    original_examples=copy.deepcopy(q.get('source_public_examples') or q['public_examples'])
    examples=[]
    for example in original_examples:
        values=source_values(example['input'])
        examples.append({'input':serialize_input(contract,values),
                         'output':serialize_output(contract,json.loads(example['output']),values)})
    if any(not e['output'] for e in examples):raise ValueError('公开操作样例没有任何可评测的输出')
    cases=[];seen={}
    for case in q.get('test_cases',[]):
        values=source_values(case['input'])
        converted={**case,'input':serialize_input(contract,values),
                   'output':serialize_output(contract,json.loads(case['output']),values),'verified':False}
        if converted['input'] in seen:
            existing=seen[converted['input']]
            if converted['output']!=existing['output']:raise ValueError('相同输入转换后出现冲突输出')
            existing['obligation_ids']=sorted(set(existing.get('obligation_ids',[])+converted.get('obligation_ids',[])))
            if converted.get('visibility')=='public':existing['visibility']='public'
        else:cases.append(converted);seen[converted['input']]=converted
    if not cases:cases=[dict(e,visibility='public',verified=False,excel_selected=i<4,
                         purpose='原题样例转换为标准输入输出',output_basis='原题参数与结果保持一致，仅转换表示') for i,e in enumerate(examples)]
    # Build everything before touching a resumable question.
    languages=[{'language':l['language'],'starter_code':''} for l in q['languages']]
    description=student_statement(source,contract,examples)
    q.update(source_description=source,source_public_examples=original_examples,
             io_contract=contract,source_protocol='standard_io',description=description,
             description_format='markdown',description_includes_examples=True,
             public_examples=examples,languages=languages,
             test_cases=cases,
             approved=False,reference_code='')
    if can_reuse:
        q['io_migration']={'previous_basis':old_report['basis'],'previous_case_basis':old_report['case_basis'],
                           'previous_method':old_report['method'],'assessment':copy.deepcopy(old_report.get('assessment',{})),
                           'input_provenance':'previously_source_validated_inputs_only'}
    for field in ('approval_snapshot','execution_verification','verification_state','verification_retry_failures'):
        q.pop(field,None)
    return True


def nowcoder_candidate(page,languages):
    """Preserve public ACM statements and samples without a copying LLM call."""
    meta=page.get('source_metadata',{})
    if meta.get('provider')!='nowcoder' or meta.get('interface_kind')!='standard_io':return None
    statement=page.get('source_statement');examples=page.get('source_examples',[])
    if not statement or not examples:return None
    q={'id':'programming-native-'+hashlib.sha256((page['url']+'\0'+statement).encode()).hexdigest()[:24],
       'kind':'programming','title':page['title'],'description':statement,
       'description_format':'plain','description_includes_examples':True,
       'knowledge':'、'.join(meta.get('tags',[])),
       'score':10,'difficulty':0,'time_limit_seconds':3,'estimated_minutes':20,
       'languages':[{'language':language,'starter_code':''} for language in languages],
       'test_cases':[dict(e,visibility='public',verified=False,excel_selected=i<4,
           purpose='原题公开样例',output_basis='牛客公开题面直接提供') for i,e in enumerate(examples)],
       'public_examples':copy.deepcopy(examples),'approved':False,'selected':False,
       'origin':'web_programming','source':page['title'],'source_tier':0,'source_protocol':'standard_io',
       'source_metadata':copy.deepcopy(meta),
       'source_refs':[{'url':page['url'],'retrieved_at':page.get('retrieved_at',''),
           'stem_evidence':statement[:1500],'answer_status':'source_explicit','method':'native_structured_question'}],
       'source_identity':{'kind':'original','url':page['url'],'statement_sha256':hashlib.sha256(statement.encode()).hexdigest()},
       'reference_code':'','selection_reason':'直接读取牛客原题和公开样例，继续检查课程匹配、来源程序及隐藏输入。'}
    if page.get('source_bundle'):q['source_bundle']=copy.deepcopy(page['source_bundle'])
    if page.get('reference_solutions'):q['source_reference']=copy.deepcopy(page['reference_solutions'][0])
    from courseagent.programming_questions import validate_programming
    try:validate_programming(q,False)
    except (ValueError,TypeError,KeyError):return None
    return q


def leetcode_candidate(page,languages):
    meta=page.get('source_metadata',{})
    if meta.get('provider')!='leetcode' or meta.get('paid'):return None
    interface=meta.get('interface',{});examples=page.get('source_examples',[])
    if not examples or not page.get('source_statement'):return None
    try:python_driver(interface)
    except ValueError:return None
    design=bool(interface.get('systemdesign') or interface.get('classname'))
    for e in examples:
        if not isinstance(e.get('input'),str) or not isinstance(e.get('output'),str):return None
        try:json.loads(e['output'])
        except ValueError:return None
    kind='class' if design else 'function'
    if design:
        protocol=('标准输入依次提供两个 JSON 数组：第一个为操作名数组，第二个为逐次调用的参数数组；'
                  '两数组长度相同，首项为构造类名和构造参数。通常各占一行，空白和换行仅为分隔。'
                  '输出一个 JSON 数组，与操作逐项对应，构造函数及 void 方法输出 null。')
    else:
        names='、'.join(p['name'] for p in interface.get('params',[]))
        protocol=('标准输入按接口参数顺序（'+names+'）依次提供各参数的 JSON 值；'
                  '可保留原样例的参数名 = 值表示，参数之间用逗号或空白分隔。输出返回值的单个 JSON 表示。')
    # Preserve historical candidate identity; this legacy description is replaced
    # by the student standard-I/O statement before the candidate is returned.
    description=(page.get('source_statement_markdown') or page['source_statement'])+'\n\n运行约定：保留原题样例的 JSON 输入与输出表示。'+protocol+'完整程序从标准输入读取数据，按原接口调用；Python 初始模板提供调用驱动，类中的算法由你完成。其他语言可自行实现相同协议。'
    identifier=hashlib.sha256((page['url']+'\0'+description).encode()).hexdigest()[:24]
    q={'id':'programming-native-'+identifier,'kind':'programming','title':page['title'],
       'description':description,'description_format':'markdown' if page.get('source_statement_markdown') else 'plain','description_includes_examples':True,'knowledge':'、'.join(meta.get('tags',[])),
       'score':10,'difficulty':0,'time_limit_seconds':3,'estimated_minutes':20,
       'languages':[{'language':language,'starter_code':''} for language in languages],
       'test_cases':[dict(e,visibility='public',verified=False,excel_selected=i<4,purpose='原题公开样例',output_basis='原生题面明确提供') for i,e in enumerate(examples)],
       'public_examples':copy.deepcopy(examples),'approved':False,'selected':False,
       'origin':'web_programming','source':page['title'],'source_tier':0,'source_protocol':kind,
       'source_metadata':copy.deepcopy(meta),'source_refs':[{'url':page['url'],'retrieved_at':page.get('retrieved_at',''),
          'stem_evidence':page['source_statement'][:1500],'answer_status':'source_explicit','method':'native_structured_question'}],
       'reference_code':'','selection_reason':'原生题库题面、接口和公开样例直接提取；接受原题定义，继续核对本系统的执行适配与隐藏输入生成。'}
    if page.get('reference_solutions'):
        q['source_reference']=copy.deepcopy(min(page['reference_solutions'],key=lambda r:r.get('language')!='Python'))
    from courseagent.programming_questions import validate_programming
    try:upgrade_native_question(q)
    except (ValueError,KeyError,TypeError):return None
    validate_programming(q,False)
    return q
