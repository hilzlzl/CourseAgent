"""Small, reviewed output conventions for token-based judging, not an SPJ.

Only source identities with understood semantics receive a convention. Sorting
changes representation only; it must never reorder values inside a path/pair.
"""
import copy
import io

VERSION = 'fixed-output-policy-v1'
ORDER_RULE = '结果按字典序升序排列；多个序列按逐项比较的字典序排列，不改变每个序列内部的次序。'
SORTABLE = {
    'two-sum', 'find-common-characters', 'majority-element-ii',
    'merge-intervals', 'path-sum-ii',
    'er-cha-shu-zhong-he-wei-mou-yi-zhi-de-lu-jing-lcof',
    # Distinct node values and minimum flips determine the set; only the
    # order of listing those nodes is free in this published task.
    'flip-binary-tree-to-match-preorder-traversal',
}
STRUCTURAL = {
    'construct-binary-tree-from-preorder-and-postorder-traversal':
        '前序与后序不能唯一确定单孩子方向，固定树输出会拒绝合法答案',
    'delete-node-in-a-bst':
        '删除结点可采用前驱或后继等策略，合法结果树形不唯一',
}


def retain_validated_inputs(original, migrated):
    from courseagent.programming_verification import current_report
    report = current_report(original)
    if report and report.get('passed') and report.get('source_evidence'):
        migrated['io_migration'] = {
            'previous_basis': report['basis'], 'previous_case_basis': report['case_basis'],
            'previous_method': report['method'], 'assessment': copy.deepcopy(report.get('assessment', {})),
            'input_provenance': 'previously_source_validated_inputs_only'}


def source_slug(q):
    from courseagent.selection_policy import canonical_source
    for ref in q.get('source_refs', []):
        identity = canonical_source(ref.get('url', ''))
        if identity.startswith('leetcode:'):
            return identity.split(':', 1)[1]
    return ''


def structural_issue(q):
    if q.get('answer_provenance') or q.get('origin') == 'web_programming_adapted':
        return ''
    return STRUCTURAL.get(source_slug(q), '')


def apply_input_policy(q):
    """A fixed 9x9 Sudoku board is nine lines, retaining exact cell values."""
    if (source_slug(q) != 'valid-sudoku' or q.get('answer_provenance') or q.get('approved')
            or q.get('origin') == 'web_programming_adapted'):
        return False
    old = q.get('io_contract', {})
    if old.get('kind') != 'function' or len(old.get('params', [])) != 1:
        return False
    spec = old['params'][0]['encoding']
    if spec.get('kind') == 'fixed_char_grid':
        return False
    if spec != {'kind': 'array', 'item': {'kind': 'array', 'item': {'kind': 'string'}}}:
        return False
    from courseagent.stdio_contract import parse_input, serialize_input
    migrated = copy.deepcopy(q)
    migrated['io_contract']['params'][0]['encoding'] = {'kind':'fixed_char_grid', 'rows':9, 'cols':9}
    for field in ('public_examples', 'test_cases'):
        for case in migrated.get(field, []):
            case['input'] = serialize_input(migrated['io_contract'], parse_input(old, case['input']))
            if field == 'test_cases':
                case['verified'] = False
    for field in ('execution_verification', 'verification_state', 'approval_snapshot', 'io_migration',
                  'statement_adaptation', 'statement_adaptation_retry', 'platform_description'):
        migrated.pop(field, None)
    migrated['input_policy'] = {'version': VERSION, 'layout': 'sudoku-nine-lines'}
    retain_validated_inputs(q, migrated)
    q.clear()
    q.update(migrated)
    return True


def apply_output_policy(q):
    """Atomically migrate samples/cases and invalidate all dependent evidence.

    Existing approved snapshots are left for explicit re-review. Newly admitted
    candidates receive the same convention in statements and executable drivers.
    """
    if q.get('answer_provenance') or q.get('approved') or q.get('origin') == 'web_programming_adapted':
        return False
    contract = q.get('io_contract', {})
    if (source_slug(q) not in SORTABLE or contract.get('kind') != 'function'
            or contract.get('output', {}).get('kind') != 'array'):
        return False
    if contract['output'].get('order') == 'lexicographic':
        return False
    from courseagent.stdio_contract import _read_value, serialize_output
    migrated = copy.deepcopy(q)
    migrated['io_contract']['output']['order'] = 'lexicographic'
    for field in ('public_examples', 'test_cases'):
        for case in migrated.get(field, []):
            stream = io.StringIO(case['output'])
            value = _read_value(stream, contract['output'])
            if stream.read().strip():
                raise ValueError('输出规范化失败：样例包含额外字段')
            case['output'] = serialize_output(migrated['io_contract'], value)
            if field == 'test_cases':
                case['verified'] = False
                case['output_basis'] = '输出表示已规范化，等待重新隔离执行核对'
    # Statement adaptation will rebuild prose and examples before admission.
    for field in ('execution_verification', 'verification_state', 'approval_snapshot',
                  'statement_adaptation', 'statement_adaptation_retry', 'platform_description'):
        migrated.pop(field, None)
    migrated['output_policy'] = {'version': VERSION, 'order': 'lexicographic'}
    retain_validated_inputs(q, migrated)
    q.clear()
    q.update(migrated)
    return True
