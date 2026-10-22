"""Versioned boundary contracts; legacy document payloads remain backwards compatible."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

class AssignmentSpec(Contract):
    course: str = ''
    topics: list[str] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    programming_count: int = Field(default=0, ge=0, le=300)
    @model_validator(mode='after')
    def quotas(self):
        if any(k not in ('1','2','3','4','5') or n < 0 or n > 300 for k,n in self.counts.items()):
            raise ValueError('Invalid ordinary question quota')
        return self

class QuestionSpecification(Contract):
    input_format: str = Field(min_length=1)
    output_format: str = Field(min_length=1)
    constraints: str = Field(min_length=1)
    output_kind: Literal['unique_tokens']
    allows_empty_output: bool = False
    ambiguities: list[str] = Field(default_factory=list)

class CoverageObligation(Contract):
    id: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1)
    category: Literal['normal','boundary','adversarial','scale']

class AssessmentPlan(Contract):
    specification: QuestionSpecification
    obligations: list[CoverageObligation] = Field(min_length=3, max_length=12)
    @model_validator(mode='after')
    def distinct_ids(self):
        if len({o.id for o in self.obligations}) != len(self.obligations):
            raise ValueError('Duplicate coverage obligation ids')
        if self.specification.ambiguities:
            raise ValueError('Unresolved programming specification ambiguity: '+ '; '.join(self.specification.ambiguities))
        return self


class SourceInputDesign(Contract):
    """Design our inputs for a published problem; no verdict on its validity."""
    generator_code: str = Field(min_length=1, max_length=50000)
    input_validator_code: str = Field(min_length=1, max_length=50000)
    obligations: list[CoverageObligation] = Field(min_length=3, max_length=12)

    @model_validator(mode='after')
    def distinct_ids(self):
        if len({o.id for o in self.obligations}) != len(self.obligations):
            raise ValueError('Duplicate coverage obligation ids')
        if not {'normal', 'boundary', 'adversarial'} <= {o.category for o in self.obligations}:
            raise ValueError('Input design needs normal, boundary and adversarial goals')
        return self

class WrongSolution(Contract):
    id: str = Field(min_length=1, max_length=80)
    fault: str = Field(min_length=1)
    code: str = Field(min_length=1, max_length=50000)

class MutationDesign(Contract):
    wrong_solutions: list[WrongSolution] = Field(min_length=2, max_length=3)
    @model_validator(mode='after')
    def distinct_ids(self):
        if len({m.id for m in self.wrong_solutions}) != len(self.wrong_solutions):
            raise ValueError('Duplicate wrong solution ids')
        return self

class SearchInput(Contract):
    query: str = Field(min_length=1, max_length=2000)
class SearchOutput(Contract):
    items: list[dict]
    cache_hit: bool
class ReadInput(Contract):
    url: str = Field(min_length=1, max_length=4000)
class ReadOutput(Contract):
    page: dict
    cache_hit: bool
class ExecuteInput(Contract):
    code: str = Field(min_length=1, max_length=50000)
    stdin: str = ''
    output_limit: int = Field(default=65536, ge=65536, le=4194304)
class ExecuteOutput(Contract):
    ok: bool
    status: str
    output: str
    error: str
    returncode: int | None = None

class NativeExecuteInput(ExecuteInput):
    language: Literal['Python','C','C++','Java']

class NativeExecuteOutput(ExecuteOutput):
    compile_cache_hit: bool = False

class SourceSearchInput(Contract):
    provider: Literal['web','leetcode','nowcoder','luogu','acwing']
    query: str = Field(min_length=1, max_length=2000)
    topics: list[str] = Field(default_factory=list)
    difficulty: int = Field(default=0, ge=0, le=3)
    offset: int = Field(default=0, ge=0)

class SourceSearchOutput(SearchOutput):
    pagination: dict = Field(default_factory=dict)

class HybridSearchInput(Contract):
    query: str = Field(min_length=1,max_length=2000)
    kinds: list[Literal['ordinary','programming','material']] | None = None
    providers: list[str] | None = None
    source_ids: list[str] | None = None
    exclude_ids: list[str] = Field(default_factory=list)
    record_ids: list[str] | None = None
    limit: int = Field(default=20,ge=1,le=200)

class HybridSearchOutput(Contract):
    items: list[dict]
    diagnostics: dict
