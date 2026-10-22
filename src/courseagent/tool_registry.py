"""Validated LangChain tools with auditable, explicit execution policies.

Policies describe capability, not authorization. No publish tool is registered.
Exceptions propagate to existing graph retry/budget handling; never silently retry writes.
"""
from dataclasses import dataclass
from functools import wraps
from threading import RLock
from pydantic import BaseModel
from langchain_core.tools import StructuredTool
from courseagent.observability import span

@dataclass(frozen=True)
class ToolPolicy:
    side_effect: str = 'read_only'
    retryable: bool = True
    max_attempts: int = 1
    boundary: str = 'public_evidence'
    error_types: tuple[str,...] = ('ValidationError','ValueError','RuntimeError','TimeoutError')

REGISTRY = {}
LOCK = RLock()

def registered_tool(input_model: type[BaseModel], output_model: type[BaseModel], *, policy=ToolPolicy()):
    def decorate(fn):
        if policy.side_effect not in ('read_only','isolated_execution','unpublished_draft'):
            raise ValueError('Unsupported external side effect')
        @wraps(fn)
        def checked(**kwargs):
            args = input_model.model_validate(kwargs)
            with span('registry_'+fn.__name__, 'tool', {'side_effect':policy.side_effect,'retryable':policy.retryable}) as metrics:
                result = fn(**args.model_dump())
                clean = output_model.model_validate(result).model_dump(exclude_unset=True)
                metrics['output_validated'] = True
                return clean
        value = StructuredTool.from_function(checked, name=fn.__name__, description=fn.__doc__ or fn.__name__, args_schema=input_model)
        with LOCK:
            REGISTRY[fn.__name__] = (value, input_model, output_model, policy)
        return value
    return decorate

def manifest():
    # Lazy import registers tools without invoking network, models, or execution.
    from courseagent import retrieval_tools; from courseagent import code_sandbox; from courseagent import native_sandbox; from courseagent import verification_tools
    with LOCK:
        return [{'name':name,'input_schema':im.model_json_schema(),'output_schema':om.model_json_schema(),
                 'policy':{'side_effect':p.side_effect,'retryable':p.retryable,'max_attempts':p.max_attempts,
                           'boundary':p.boundary,'error_types':list(p.error_types)}}
                for name,(_,im,om,p) in sorted(REGISTRY.items())]
