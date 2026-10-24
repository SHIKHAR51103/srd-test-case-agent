"""Pydantic schemas (LLM structured outputs) and the LangGraph state."""
from typing import Any, Dict, List, TypedDict

from pydantic import BaseModel, Field


# ---------- structured outputs the LLM must return ----------
class RawRequirement(BaseModel):
    title: str = Field(description="Short title, max 12 words")
    description: str = Field(description="One or two sentences, testable, taken from the SRD")
    type: str = Field(description="'functional' or 'non-functional'")
    priority: str = Field(description="'high', 'medium' or 'low'")


class RequirementList(BaseModel):
    requirements: List[RawRequirement]


class RawTestCase(BaseModel):
    requirement_id: str = Field(description="Exactly one of the REQ-xxx ids given in the prompt")
    title: str
    category: str = Field(description="'positive', 'negative', 'boundary' or 'edge'")
    preconditions: str = Field(default="", description="State required before the test")
    steps: List[str] = Field(description="Atomic, numbered-style user actions")
    expected_result: str = Field(description="Observable, verifiable outcome")
    priority: str = Field(description="'high', 'medium' or 'low'")


class TestCaseList(BaseModel):
    __test__ = False  # stop pytest trying to collect this as a test class
    test_cases: List[RawTestCase]


class ReviewVerdict(BaseModel):
    semantic_gap_ids: List[str] = Field(
        description="Requirement ids whose tests are present but shallow or miss an important scenario"
    )
    quality_score: int = Field(description="Overall quality 1-10")
    feedback: str = Field(description="Concrete instructions on what scenarios to add")


# ---------- graph state ----------
class AgentState(TypedDict, total=False):
    srd_text: str
    requirements: List[Dict[str, Any]]
    test_cases: List[Dict[str, Any]]
    review: Dict[str, Any]
    gap_ids: List[str]
    iteration: int
    approved: bool
    run_dir: str
    outputs: Dict[str, str]
    log: List[str]
