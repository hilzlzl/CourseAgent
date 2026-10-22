"""Recall filter for source discovery; final question relevance is checked later."""
ALIASES = {
    '顺序查找': ('顺序查找','线性查找','linear search'),
    '折半查找': ('折半查找','二分查找','二分搜索','二分法查找','二分（对半）查找','对半查找','binary search'),
    '二分查找': ('折半查找','二分查找','二分搜索','二分法查找','二分（对半）查找','对半查找','binary search'),
    '二叉排序树': ('二叉排序树','二叉搜索树','binary search tree'),
    '二叉搜索树': ('二叉排序树','二叉搜索树','binary search tree'),
    '散列查找': ('散列','哈希','hash'),
    '哈希查找': ('散列','哈希','hash'),
    '查找算法': ('查找', '二分搜索', '二叉排序树', '二叉搜索树', 'AVL', '哈希', '散列', 'B树', 'B-树', 'binary search', 'linear search'),
    '查找': ('查找', '二分搜索', '二叉排序树', '二叉搜索树', 'AVL', '哈希', '散列', 'B树', 'B-树', 'binary search', 'linear search'),
    '排序算法': ('排序', 'sorting', 'sort'),
    '栈和队列': ('栈', '队列', 'stack', 'queue'),
    '栈': ('栈','stack'),
    '队列': ('队列','queue'),
    '二叉树': ('二叉树', '哈夫曼', '线索树', '二叉搜索', 'binary tree'),
}


def topic_matches(topics, text):
    from courseagent.selection_policy import normalized_topic
    folded = text.casefold()
    return any(term.casefold() in folded
               for topic in (normalized_topic(t) for t in topics)
               for term in ALIASES.get(topic, (topic,)))
