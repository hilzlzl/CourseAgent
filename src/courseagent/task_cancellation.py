"""Cancellation escapes broad model/source retry handlers."""
class TaskStopped(BaseException):
    pass


def check_stopped():
    from courseagent.model_client import TASK_BUDGET, BudgetExhausted
    budget=TASK_BUDGET.get()
    if budget and budget.get('deadline_exceeded'):
        raise BudgetExhausted('任务运行时间预算已用完；正在保存检查点，可继续当前任务')
    if budget and budget.get('stop_requested') and budget['stop_requested']():
        raise TaskStopped('教师已停止当前任务')
