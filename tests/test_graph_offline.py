"""Offline test: runs the full LangGraph workflow with a fake LLM (no API key, no network).

It proves the wiring: parse -> design -> review -> revision loop -> human pause -> scripts -> export.
"""
import ast
import os
import re

from langchain_core.messages import AIMessage

from src.runner import is_paused_for_review, new_run, stream_until_pause
from src.schemas import (
    RawRequirement,
    RawTestCase,
    RequirementList,
    ReviewVerdict,
    TestCaseList,
)

SRD = "The user shall log in with email and password.\n\nPasswords must be 8 to 64 characters."


class FakeStructured:
    def __init__(self, schema):
        self.schema = schema

    def invoke(self, messages):
        text = " ".join(m[1] if isinstance(m, tuple) else m.content for m in messages)
        if self.schema is RequirementList:
            return RequirementList(
                requirements=[
                    RawRequirement(title="Login", description="Log in with email and password", type="functional", priority="high"),
                    RawRequirement(title="Password length", description="8 to 64 characters", type="functional", priority="medium"),
                ]
            )
        if self.schema is TestCaseList:
            ids = sorted(set(re.findall(r"REQ-\d{3}", text)))
            is_revision = "REVISION REQUEST" in text
            cases = []
            for rid in ids:
                cat = "negative" if is_revision else "positive"
                cases.append(RawTestCase(requirement_id=rid, title=f"{cat} case for {rid}", category=cat,
                                         steps=["open page", "submit form"], expected_result="as specified", priority="high"))
            cases.append(RawTestCase(requirement_id="REQ-999", title="hallucinated", category="positive",
                                     steps=["x"], expected_result="y", priority="low"))  # must be dropped
            return TestCaseList(test_cases=cases)
        if self.schema is ReviewVerdict:
            return ReviewVerdict(semantic_gap_ids=["REQ-777"], quality_score=8, feedback="Add negative cases.")
        raise AssertionError(f"unexpected schema {self.schema}")


class FakeLLM:
    def with_structured_output(self, schema):
        return FakeStructured(schema)

    def invoke(self, messages):
        return AIMessage(content="```python\ndef test_tc_001_demo(page):\n    assert True\n```")


def run(use_llm_scripts: bool, tmp_path):
    os.environ["OUTPUT_DIR"] = str(tmp_path)
    graph, config, initial = new_run(FakeLLM(), SRD, max_revisions=2, use_llm_scripts=use_llm_scripts)
    initial["run_dir"] = str(tmp_path / "run")
    state = stream_until_pause(graph, initial, config)
    assert is_paused_for_review(graph, config), "graph must pause for human approval"
    return graph, config, state


def test_revision_loop_and_human_pause(tmp_path):
    graph, config, state = run(False, tmp_path)
    assert len(state["requirements"]) == 2
    assert all(t["requirement_id"] != "REQ-999" for t in state["test_cases"]), "hallucinated ids are dropped"
    assert state["iteration"] == 2, "positive-only first pass must trigger exactly one revision"
    assert state["review"]["coverage_pct"] == 100.0
    assert state["gap_ids"] == [], "negative tests added in the revision clear the gap"

    # human edit: remove one test, then resume
    edited = state["test_cases"][1:]
    graph.update_state(config, {"test_cases": edited})
    final = stream_until_pause(graph, None, config)
    assert not is_paused_for_review(graph, config)
    for key in ("excel", "pytest", "traceability"):
        assert os.path.exists(final["outputs"][key]), key
    ast.parse(open(final["outputs"]["pytest"], encoding="utf-8").read())  # generated code must be valid python


def test_llm_script_mode(tmp_path):
    graph, config, _ = run(True, tmp_path)
    final = stream_until_pause(graph, None, config)
    code = open(final["outputs"]["pytest"], encoding="utf-8").read()
    ast.parse(code)
    assert "test_tc_001_demo" in code
