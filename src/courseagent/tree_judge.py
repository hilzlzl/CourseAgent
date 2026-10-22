"""Trusted, fixed tree oracles. Never evaluate or execute retrieved/model code."""
from collections import deque
import re

FORMAT='binary_tree_level_tokens_v1'
TASKS={
 'preorder':'输出二叉树的前序遍历（根、左、右）。',
 'inorder':'输出二叉树的中序遍历（左、根、右）。',
 'postorder':'输出二叉树的后序遍历（左、右、根）。',
 'level_order':'输出二叉树的层序遍历，按层从左到右输出实际节点。',
 'max_depth':'输出二叉树的最大深度，即根到最远叶子路径的节点数。',
 'min_depth':'输出二叉树的最小深度，即根到最近叶子路径的节点数。',
 'invert':'交换每个节点的左右子树，输出翻转后二叉树的层序序列。',
 'leaf_count':'输出二叉树的叶子节点数量。叶子节点没有左右孩子。',
 'node_count':'输出二叉树实际节点的数量。',
}
INPUT=('一行，用空格分隔整数和小写 null；不用方括号、逗号或 Python 的 None。'
       '按队列顺序构建：第一个值为根，随后依次为每个非空节点读两个孩子（先左后右）；'
       'null 表示该孩子为空，空节点不再读取孩子。缺失的尾部孩子视为空。'
       '空树输入 null。例如 1 2 null 3 4 表示根1的左孩子2、右孩子空，2的孩子为3和4。')
CONSTRAINTS='最多1000个实际节点，节点值为-100000至100000的整数。输入必须是合法的上述层序序列；允许只有右孩子。'


def infer_task(title):
 """Only exact common task names opt into a full, explicit adaptation."""
 title=re.sub(r'[\s的]','',title)
 aliases={
  '二叉树前序遍历':'preorder','二叉树先序遍历':'preorder',
  '二叉树中序遍历':'inorder','二叉树后序遍历':'postorder',
  '二叉树层序遍历':'level_order','二叉树层次遍历':'level_order',
  '二叉树最大深度':'max_depth','二叉树最小深度':'min_depth',
  '翻转二叉树':'invert','二叉树翻转':'invert','二叉树镜像':'invert',
  '二叉树叶子节点数量':'leaf_count','二叉树叶子节点计数':'leaf_count',
  '二叉树节点数量':'node_count','二叉树节点计数':'node_count',
 }
 return aliases.get(title)


def parse_tree(text):
 if not isinstance(text,str):raise ValueError('二叉树输入必须为文字')
 tokens=text.split()
 if not tokens or len(tokens)>2001:raise ValueError('二叉树层序输入为空或超过长度约束')
 if any(t!='null' and not re.fullmatch(r'-?\d+',t) for t in tokens):
  raise ValueError('二叉树输入须为空格分隔的整数/null，不能使用列表括号、逗号或None')
 values=[None if t=='null' else int(t) for t in tokens]
 if sum(v is not None for v in values)>1000 or any(v is not None and abs(v)>100000 for v in values):raise ValueError('二叉树输入超出节点数或数值范围')
 if values[0] is None:
  if any(v is not None for v in values[1:]):raise ValueError('空根后不能有非空节点')
  return []
 nodes=[[values[0],None,None]];queue=deque([0]);index=1
 while queue and index<len(values):
  parent=queue.popleft()
  for side in (1,2):
   if index>=len(values):break
   value=values[index];index+=1
   if value is not None:
    child=len(nodes);nodes.append([value,None,None]);nodes[parent][side]=child;queue.append(child)
 if any(v is not None for v in values[index:]):raise ValueError('层序序列存在没有父节点的非空元素')
 return nodes


def expected_output(text,task):
 if task not in TASKS:raise ValueError('未知二叉树评测任务')
 nodes=parse_tree(text)
 if task in ('max_depth','min_depth','leaf_count','node_count'):
  if not nodes:return '0\n'
  queue=deque([(0,1)]);depths=[];leaves=0
  while queue:
   i,d=queue.popleft();_,left,right=nodes[i]
   if left is None and right is None:leaves+=1;depths.append(d)
   for child in (left,right):
    if child is not None:queue.append((child,d+1))
  value={'max_depth':max(depths),'min_depth':min(depths),'leaf_count':leaves,'node_count':len(nodes)}[task]
  return str(value)+'\n'
 if not nodes:return ('null' if task=='invert' else 'EMPTY')+'\n'
 if task=='invert':
  queue=deque([0]);result=[]
  while queue:
   i=queue.popleft()
   if i is None:result.append('null');continue
   value,left,right=nodes[i];result.append(str(value));queue.extend((right,left))
  while result[-1]=='null':result.pop()
 elif task=='level_order':
  queue=deque([0]);result=[]
  while queue:
   i=queue.popleft();value,left,right=nodes[i];result.append(str(value))
   for child in (left,right):
    if child is not None:queue.append(child)
 else:
  stack=[(0,False)];result=[]
  while stack:
   i,emit=stack.pop()
   if i is None:continue
   value,left,right=nodes[i]
   if emit:result.append(str(value));continue
   order={'preorder':[(right,False),(left,False),(i,True)],'inorder':[(right,False),(i,True),(left,False)],'postorder':[(i,True),(right,False),(left,False)]}[task]
   stack.extend(order)
 return ' '.join(result)+'\n'


def output_format(task):
 if task in ('max_depth','min_depth','leaf_count','node_count'):return '一行，一个整数。空树输出0。'
 if task=='invert':return '一行，空格分隔的整数/null，使用输入中的队列层序规则；删除尾部null，保留中间null。空树输出null。不输出方括号或逗号。'
 return '一行，空格分隔的节点值，不输出方括号、逗号或空节点。空树输出EMPTY。'


def apply_contract(q,task):
 """Explicit adaptation: replace statement AND cases, never strip input punctuation."""
 if task not in TASKS:raise ValueError('未知二叉树评测任务')
 q['judge_contract']={'format':FORMAT,'task':task}
 q['title']={'preorder':'二叉树前序遍历','inorder':'二叉树中序遍历','postorder':'二叉树后序遍历','level_order':'二叉树层序遍历','max_depth':'二叉树最大深度','min_depth':'二叉树最小深度','invert':'翻转二叉树','leaf_count':'二叉树叶子节点计数','node_count':'二叉树节点计数'}[task]
 q['description']=TASKS[task]+'\n\n输入格式：\n'+INPUT+'\n\n输出格式：\n'+output_format(task)+'\n\n数据范围与约束：\n'+CONSTRAINTS
 fixtures=[('1 2 3 4 5 6 7','普通完全二叉树'),('null','空树'),('8','单节点'),
           ('1 2 null 3 4','缺少右孩子；空节点不占孩子读取位置'),
           ('1 null 2 null 3 null 4','只有右孩子；最小深度不可误取空分支'),
           ('-1 0 -2 0 3','负数、零与重复值'),('1 2 3 4','左右深度不等，最近叶子在浅层'),
           (' '.join(map(str,range(1,1001))),'最大实际节点数1000')]
 q['test_cases']=[{'input':text+'\n','output':expected_output(text,task),'purpose':purpose,
                  'output_basis':f'本地固定二叉树算法计算，契约{FORMAT}，任务{task}；未执行模型、网页或学生程序。',
                  'verification_method':'builtin_tree_oracle_v1','verified':False,'visibility':'public' if i==0 else 'hidden','excel_selected':i<4} for i,(text,purpose) in enumerate(fixtures)]
 q['public_examples']=[{'input':q['test_cases'][0]['input'],'output':q['test_cases'][0]['output']}]
 # Previous code may parse Python lists or implement another serialization contract.
 q['reference_code']='';q['languages']=[{**item,'starter_code':''} for item in q['languages']]
 q['explanation']='';q['approved']=False;q.pop('approval_snapshot',None)
 return q


def validate_contract(q):
 contract=q.get('judge_contract')
 if not contract:return
 if not isinstance(contract,dict) or contract.get('format')!=FORMAT or contract.get('task') not in TASKS:raise ValueError('二叉树评测契约不正确')
 task=contract['task']
 # Any changes to contract-bearing statement require explicitly removing/rebuilding it.
 required=('输入格式：\n'+INPUT,'输出格式：\n'+output_format(task),'数据范围与约束：\n'+CONSTRAINTS,TASKS[task])
 if not all(part in q['description'] for part in required):raise ValueError('题面已偏离固定二叉树评测契约，请重建契约或改为人工评测')
 for case in q.get('test_cases',[])+q.get('public_examples',[]):
  if case.get('output','').strip()!=expected_output(case.get('input',''),task).strip():raise ValueError('二叉树用例预期输出与固定算法不一致')
