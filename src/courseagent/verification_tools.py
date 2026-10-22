"""Actual verification and draft-delivery tools; publishing is not a capability."""
from pathlib import Path
from pydantic import Field
from courseagent.agent_contracts import Contract
from courseagent.tool_registry import registered_tool,ToolPolicy

class DocumentInput(Contract):
    document:dict
class DocumentOutput(Contract):
    document:dict
class VerificationInput(DocumentInput):
    retry_failed:bool=False
class DraftInput(Contract):
    root:str=Field(min_length=1)
    document:dict
    classroom_url:str=Field(min_length=1)
    course:str=Field(min_length=1)
class DraftOutput(Contract):
    job:dict

@registered_tool(VerificationInput,DocumentOutput,policy=ToolPolicy(side_effect='read_only',boundary='ordinary_answer_verification'))
def verify_ordinary_answers(document:dict,retry_failed:bool=False)->dict:
    """Blind solve and check ordinary answers without changing teacher review state."""
    from courseagent.ordinary_verification import verify_document
    return {'document':verify_document(document,retry_failed=retry_failed)}

@registered_tool(VerificationInput,DocumentOutput,policy=ToolPolicy(side_effect='isolated_execution',boundary='private_programming_assessment'))
def verify_programming_answers(document:dict,retry_failed:bool=False)->dict:
    """Generate private programs and execute programming assessment checks in isolation."""
    from courseagent.programming_verification import verify_document
    from courseagent.retrieval_tools import progress
    return {'document':verify_document(document,progress=progress,retry_failed=retry_failed)}

@registered_tool(DraftInput,DraftOutput,policy=ToolPolicy(side_effect='unpublished_draft',retryable=False,boundary='machine_validated_unpublished_exam'))
def import_exam_draft(root:str,document:dict,classroom_url:str,course:str)->dict:
    """Import a machine-validated exam into an unpublished draft and reconcile existing receipts."""
    from courseagent.autonomous_agent import validate_machine_delivery
    from courseagent.agent_jobs import start_import
    validate_machine_delivery(document)
    return {'job':start_import(Path(root),document,classroom_url,course,machine_checked=True)}
