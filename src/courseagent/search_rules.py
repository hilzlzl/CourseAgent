"""Small deterministic rules for common data-structure search questions.

These rules are deliberately conservative.  Returning ``None`` leaves the
question on the model-backed path; a rule only fires when the statement gives
all of the data needed for an unambiguous calculation.
"""
import math
import re


def _choice(values, expected):
    expected = str(expected).strip()
    for i, value in enumerate(values):
        text = re.sub(r'\s+', '', str(value)).replace('−', '-').replace('–', '-')
        for token in ('(n+1)/2', '(n-1)/2', 'n/2', 'n'):
            text = text.replace(token * 3, token).replace(token * 2, token)
        if text == expected:
            return chr(65 + i)
    return None


def _binary_depths(n):
    depths = []
    def visit(lo, hi, depth):
        if lo > hi:
            return
        mid = (lo + hi) // 2
        depths.append(depth)
        visit(lo, mid - 1, depth + 1)
        visit(mid + 1, hi, depth + 1)
    visit(0, n - 1, 1)
    return depths


def solve(q):
    """Return ``(fields, reason)`` for a safe rule match, otherwise ``None``."""
    stem = str(q.get('stem', ''))
    compact = re.sub(r'\s+', '', stem)
    typ = q.get('type')
    options = q.get('options', [])

    if typ == 4:
        if '二分查找' in compact and (('顺序存储' in compact or '有序排列' in compact)
                                      or ('线性表' in compact and '必须' in compact)):
            return {'blanks': ['采用顺序存储结构，且元素按关键字有序排列']}, '二分查找的随机访问和有序性条件由规则确定'
        if '遍历一棵二叉排序树' in compact and '有序序列' in compact:
            return {'blanks': ['中序']}, '二叉排序树中序遍历得到有序序列'
        if '顺序查找' in compact and '顺序表' in compact and '链表' in compact:
            return {'blanks': ['链表']}, '顺序查找策略与存储结构无关'
        if '顺序查找' in compact and '平均查找长度' in compact and '每个元素' in compact and '不成功' not in compact:
            return {'blanks': ['(n+1)/2']}, '等概率成功顺序查找的平均查找长度为 (n+1)/2'
        if '哈希冲突' in compact and '下一个' in compact and re.search(r'空(?:闲)?位置', compact):
            return {'blanks': ['空位置']}, '开放定址法继续探测可用槽位'

    if typ != 1 or not options:
        return None

    if '顺序查找' in compact and '不成功' in compact and re.search(r'平均比较次数', compact):
        if re.search(r'长度为n|长度为\d+.*线性表', compact):
            return {'answer': _choice(options, 'n')}, '顺序查找失败必须比较全部 n 个元素'

    m = re.search(r'长度为\s*(\d+)', compact)
    if not m:
        m = re.search(r'R\[0\.\.?(\d+)\]', compact)
    n = int(m.group(1)) if m else None
    if n is not None and '折半查找' in compact and '不成功' in compact and '最大' in compact:
        expected = math.floor(math.log2(n)) + 1
        answer = _choice(options, expected)
        if answer:
            return {'answer': answer}, f'折半查找失败最大比较次数按判定树高度计算为 {expected}'

    if n is not None and '折半查找' in compact and '成功所需的平均比较次数' in compact:
        depths = _binary_depths(n)
        total = sum(depths)
        answer = _choice(options, f'{total}/{n}')
        if answer:
            return {'answer': answer}, f'按 n={n} 的折半查找判定树计算成功平均比较次数为 {total}/{n}'

    target = re.search(r'查找关键字为\s*(-?\d+)', compact)
    sequence = re.search(r'有序表[（(]([^）)]+)[）)]', stem)
    if target and sequence and '折半查找' in compact and '次比较' in compact:
        try:
            values = [int(x) for x in re.findall(r'-?\d+', sequence.group(1))]
            key = int(target.group(1)); lo, hi, count = 0, len(values) - 1, 0
            while lo <= hi:
                count += 1
                mid = (lo + hi) // 2
                if values[mid] == key:
                    answer = _choice(options, count)
                    if answer:
                        return {'answer': answer}, f'按题面序列模拟折半查找得到 {count} 次比较'
                    break
                if values[mid] < key: lo = mid + 1
                else: hi = mid - 1
        except (ValueError, IndexError):
            pass
    return None
