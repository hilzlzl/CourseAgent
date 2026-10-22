"""Private per-question checkpoints and public, content-free verification progress."""
import copy
import hashlib
import json
import os
import threading
import uuid
from pathlib import Path

CACHE_VERSION = 'question-stages-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class StageCache:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.lock = threading.RLock()

    def path(self, stage, inputs):
        return self.folder / (digest([CACHE_VERSION, stage, inputs]) + '.json')

    def load(self, stage, inputs):
        try:
            value = json.loads(self.path(stage, inputs).read_text())
            delta = value['delta']
            if not isinstance(delta, dict) or value['checksum'] != digest(delta):
                return None
            return copy.deepcopy(delta)
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def save(self, stage, inputs, delta):
        with self.lock:
            self.folder.mkdir(parents=True, exist_ok=True)
            path = self.path(stage, inputs)
            temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
            try:
                fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'w') as stream:
                    json.dump({'checksum': digest(delta), 'delta': delta}, stream, ensure_ascii=False)
                temp.replace(path)
            finally:
                temp.unlink(missing_ok=True)

    def invalidate(self, stage, inputs):
        with self.lock:
            self.path(stage, inputs).unlink(missing_ok=True)


def failure_info(error):
    """Bounded deterministic routing; never use provider bodies or arbitrary LLM actions."""
    from courseagent.model_client import BudgetExhausted
    text = str(error)
    if getattr(error, 'failure_code', None):
        code = error.failure_code
        return {'code': code, 'action': 'pause' if code == 'configuration' else 'retry_verification',
                'retryable': code != 'configuration',
                'error_type': getattr(error, 'provider_error_type', type(error).__name__)}
    if isinstance(error, BudgetExhausted):
        return {'code': 'budget', 'action': 'pause', 'retryable': True}
    if '模型输出达到 token 上限' in text:
        return {'code': 'output_limit', 'action': 'retry_verification', 'retryable': True}
    if isinstance(error, (TimeoutError, ConnectionError)) or any(s in text for s in ('HTTP 429', 'HTTP 500', 'HTTP 502', 'HTTP 503', 'HTTP 504', '连接失败', '连接超时', 'LangChain 模型调用失败')):
        return {'code': 'transport', 'action': 'retry_verification', 'retryable': True}
    if any(s in text for s in ('HTTP 400', 'HTTP 401', 'HTTP 402', 'HTTP 403', 'HTTP 404', '模型尚未配置')):
        return {'code': 'configuration', 'action': 'pause', 'retryable': False}
    if 'Unresolved programming specification ambiguity' in text or 'unsupported_reason' in text or '任务尚不能执行验证' in text:
        return {'code': 'specification', 'action': 'replace', 'retryable': False}
    return {'code': 'format', 'action': 'retry_verification', 'retryable': True}


def publish(kind, question, stage, *, status='running', reused=False, failure=None):
    question['verification_state'] = {
        'kind': kind, 'stage': stage, 'status': status, 'reused': reused,
        **({'failure': failure} if failure else {})}
    from courseagent.model_client import TASK_BUDGET
    budget = TASK_BUDGET.get()
    if budget and budget.get('on_question_checkpoint'):
        budget['on_question_checkpoint'](kind, copy.deepcopy(question))


def summary(document):
    from courseagent.ordinary_verification import current
    from courseagent.programming_verification import current_report
    rows = []
    for field, kind, checker in [('questions', 'ordinary', current), ('programming_questions', 'programming', current_report)]:
        for q in document.get(field, []):
            if not q.get('selected'):
                continue
            report = checker(q)
            passed = bool(report and (report.get('passed') is True if kind == 'programming' else report.get('verdict') == 'pass'))
            if kind=='programming' and q.get('statement_repair_request'):passed=False
            state = q.get('verification_state', {})
            rows.append({'id': q['id'], 'kind': kind, 'type': q.get('type'),
                         'status': 'verified' if passed else state.get('status', 'pending'),
                         'stage': state.get('stage', 'pending'), 'reused': state.get('reused', False),
                         'answer_policy':q.get('answer_provenance',{}).get('kind','independent_check'),
                         'failure_code': state.get('failure', {}).get('code')})
    return {'total': len(rows), 'verified': sum(r['status'] == 'verified' for r in rows),
            'trusted_material_count':sum(r['answer_policy']=='teacher_material' for r in rows), 'items': rows}


def merge_updates(document, updates):
    """Overlay only verification fields for unchanged questions; never selection or edits."""
    from courseagent.ordinary_verification import basis as ordinary_basis
    from courseagent.programming_verification import basis as coding_basis
    result=copy.deepcopy(document)
    for field,kind,identity,keys in [
        ('questions','ordinary',ordinary_basis,('ordinary_blind_solution','ordinary_blind_check','ordinary_content_check','verification_state')),
        ('programming_questions','programming',coding_basis,('test_cases','execution_verification','verification_retry_failures','verification_state'))]:
        for q in result.get(field,[]):
            update=updates.get((kind,q['id']))
            if update and identity(q)==identity(update):
                for key in keys:
                    if key in update:q[key]=copy.deepcopy(update[key])
    return result


def task_budget(request):
    """Size default runs by requested workload; continuation retains all prior artifacts."""
    from courseagent.workflow import parse_request
    try:
        spec = parse_request({'request': {'prompt': request['prompt'], 'use_model': False}})['spec']
        ordinary, coding = sum(spec['counts'].values()), spec.get('programming_count', 0)
    except (ValueError, KeyError, TypeError):
        return {'max_calls': 100, 'max_seconds': 1500}
    return {'max_calls': min(180, max(60, 24 + ordinary * 2 + coding * 18)),
            'max_seconds': min(2400, max(600, 180 + ordinary * 25 + coding * 360))}
