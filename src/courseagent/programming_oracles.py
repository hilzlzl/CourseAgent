"""Fixed independent checks for common source tasks; no generated code runs here.

Unsupported sources remain unassessed. These finite case checks do not certify
teaching fit, requested algorithm use, or test-suite fault detection strength.
"""
from collections import Counter, deque

VERSION = 'fixed-source-oracles-v1'


def _tree_levels(encoded):
    if not encoded or encoded[0] is None:
        return []
    levels = [[encoded[0]]]
    queue = deque([(encoded[0], 0)])
    index = 1
    while queue:
        _, depth = queue.popleft()
        for _ in range(2):
            if index == len(encoded):
                break
            value = encoded[index]
            index += 1
            if value is not None:
                if len(levels) <= depth + 1:
                    levels.append([])
                levels[depth + 1].append(value)
                queue.append((value, depth + 1))
    return levels


SUPPORTED = {
    'sort-an-array', 'sort-list', 'insertion-sort-list', 'binary-search',
    'search-insert-position', 'find-first-and-last-position-of-element-in-sorted-array',
    'find-minimum-in-rotated-sorted-array', 'find-minimum-in-rotated-sorted-array-ii',
    'contains-duplicate', 'majority-element', 'majority-element-ii',
    'binary-tree-level-order-traversal', 'binary-tree-level-order-traversal-ii',
    'binary-tree-zigzag-level-order-traversal', 'maximum-depth-of-binary-tree',
    'er-cha-shu-de-shen-du-lcof',
}


def check_case(question, text, output):
    from courseagent.programming_output_policy import source_slug
    from courseagent.stdio_contract import parse_input, serialize_output
    slug = source_slug(question)
    contract = question.get('io_contract')
    if (slug not in SUPPORTED or not contract or contract.get('kind') != 'function'
            or question.get('answer_provenance') or question.get('origin') == 'web_programming_adapted'):
        return {'status': 'unassessed', 'method': VERSION}
    try:
        values = parse_input(contract, text)
        data = values[0]
        if slug in ('sort-an-array', 'sort-list', 'insertion-sort-list'):
            result = sorted(data)
        elif slug in ('binary-search', 'search-insert-position',
                      'find-first-and-last-position-of-element-in-sorted-array'):
            target = values[1]
            positions = [i for i, value in enumerate(data) if value == target]
            if slug == 'binary-search':
                result = positions[0] if positions else -1
            elif slug == 'search-insert-position':
                result = sum(value < target for value in data)
            else:
                result = [positions[0], positions[-1]] if positions else [-1, -1]
        elif slug.startswith('find-minimum-in-rotated-sorted-array'):
            result = min(data)
        elif slug == 'contains-duplicate':
            result = len(set(data)) != len(data)
        elif slug.startswith('majority-element'):
            counts = Counter(data)
            if slug == 'majority-element':
                result = next(value for value, count in counts.items() if count > len(data) // 2)
            elif contract['output'].get('order') != 'lexicographic':
                return {'status': 'unassessed', 'method': VERSION, 'reason': '输出顺序尚未统一'}
            else:
                result = sorted(value for value, count in counts.items() if count > len(data) // 3)
        else:
            levels = _tree_levels(data)
            if slug in ('maximum-depth-of-binary-tree', 'er-cha-shu-de-shen-du-lcof'):
                result = len(levels)
            elif slug == 'binary-tree-level-order-traversal-ii':
                result = levels[::-1]
            elif slug == 'binary-tree-zigzag-level-order-traversal':
                result = [row if i % 2 == 0 else row[::-1] for i, row in enumerate(levels)]
            else:
                result = levels
        expected = serialize_output(contract, result)
    except (ValueError, TypeError, KeyError, IndexError, StopIteration) as error:
        return {'status': 'unassessed', 'method': VERSION, 'reason': '独立核验器无法处理此输入：' + type(error).__name__}
    return {'status': 'passed' if expected.split() == output.split() else 'mismatch',
            'method': VERSION, **({'expected': expected} if expected.split() != output.split() else {})}
