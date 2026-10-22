"""Named model roles with shared task budgets and explicit LangChain routing."""
from contextvars import ContextVar
from courseagent.observability import span

ROLE = ContextVar('educoder_model_role', default=None)
ROLES = ('planner', 'searcher', 'author', 'solver', 'validator', 'test_designer', 'supervisor', 'ordinary_solver', 'answer_judge', 'assessment_planner', 'mutation_designer')


def ask_role(role, instructions, data):
    if role not in ROLES:
        raise ValueError('未知模型角色')
    from courseagent.model_client import chat_json
    token = ROLE.set(role)
    try:
        with span('role_' + role, metrics={'role': role}):
            return chat_json(instructions, data)
    finally:
        ROLE.reset(token)
