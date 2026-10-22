"""Retry a question/stage twice; an unrelated failure gets its own allowance."""
import hashlib
import json


def recovery_key(question, stage):
    content = {k:question.get(k) for k in ('id', 'source_description', 'source_reference', 'io_contract')}
    return hashlib.sha256(json.dumps([stage, content], ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def retry_count(report):
    key = report.get('source_failure', {}).get('recovery_key')
    if key:
        return report.get('source_retry_counts', {}).get(key, 0)
    return report.get('producer_recovery_attempts', 0)


def record_retry(report):
    key = report.get('source_failure', {}).get('recovery_key')
    count = retry_count(report) + 1
    if key:
        report.setdefault('source_retry_counts', {})[key] = count
    report['producer_recovery_attempts'] = report.get('producer_recovery_attempts', 0) + 1
    return count
