"""The agent nodes. Each node is one specialised agent in the LangGraph workflow."""
import os
import re
from typing import Callable, Dict, List

from . import prompts
from .config import BATCH_SIZE, CHUNK_CHARS, SCRIPT_BATCH_SIZE
from .exporters import (
    clean_code,
    export_excel,
    export_traceability_md,
    is_valid_python,
    SCRIPT_HEADER,
    template_script,
)
from .llm import invoke_structured, invoke_text
from .schemas import AgentState, RequirementList, ReviewVerdict, TestCaseList

CATEGORIES = {"positive", "negative", "boundary", "edge"}
PRIORITIES = {"high", "medium", "low"}


# ---------------------------------------------------------------- helpers
def chunk_text(text: str, limit: int = CHUNK_CHARS) -> List[str]:
    """Split on blank lines so a requirement is never cut in half."""
    chunks, current = [], ""
    for para in re.split(r"\n\s*\n", text.strip()):
        if current and len(current) + len(para) > limit:
            chunks.append(current)
            current = ""
        current += para + "\n\n"
    if current.strip():
        chunks.append(current)
    return chunks


def _norm_priority(value: str) -> str:
    value = (value or "").strip().lower()
    return value if value in PRIORITIES else "medium"


def _norm_category(value: str) -> str:
    value = (value or "").strip().lower()
    return value if value in CATEGORIES else "positive"


def _norm_type(value: str) -> str:
    return "non-functional" if "non" in (value or "").lower() else "functional"


def _fmt_requirements(reqs: List[Dict]) -> str:
    return "\n".join(f"{r['id']} ({r['type']}, {r['priority']}): {r['title']} - {r['description']}" for r in reqs)


def _fmt_tests(tests: List[Dict]) -> str:
    return "\n".join(f"{t['id']} | {t['requirement_id']} | {t['category']} | {t['title']}" for t in tests)


def _log(state: AgentState, message: str) -> List[str]:
    return list(state.get("log", [])) + [message]


# ---------------------------------------------------------------- node factory
def make_nodes(llm, max_revisions: int, use_llm_scripts: bool) -> Dict[str, Callable]:
    # 1) Parser agent ---------------------------------------------------------
    def parse_requirements(state: AgentState) -> dict:
        seen, requirements = set(), []
        for chunk in chunk_text(state["srd_text"]):
            result = invoke_structured(
                llm, RequirementList, prompts.PARSER_SYSTEM, prompts.PARSER_USER.format(chunk=chunk)
            )
            for raw in result.requirements:
                key = re.sub(r"\W+", " ", raw.title.lower()).strip()
                if not key or key in seen:
                    continue
                seen.add(key)
                requirements.append(
                    {
                        "id": f"REQ-{len(requirements) + 1:03d}",
                        "title": raw.title.strip(),
                        "description": raw.description.strip(),
                        "type": _norm_type(raw.type),
                        "priority": _norm_priority(raw.priority),
                    }
                )
        if not requirements:
            raise ValueError("No requirements could be extracted. Check that the SRD text is readable.")
        return {
            "requirements": requirements,
            "test_cases": [],
            "gap_ids": [],
            "iteration": 0,
            "log": _log(state, f"Parser agent extracted {len(requirements)} requirements"),
        }

    # 2) Test-design agent ----------------------------------------------------
    def design_tests(state: AgentState) -> dict:
        requirements = state["requirements"]
        existing = list(state.get("test_cases", []))
        gap_ids = state.get("gap_ids") or []
        review = state.get("review") or {}
        targets = [r for r in requirements if r["id"] in gap_ids] if gap_ids else requirements
        valid_ids = {r["id"] for r in requirements}
        next_num = len(existing) + 1
        new_tests: List[Dict] = []

        for i in range(0, len(targets), BATCH_SIZE):
            batch = targets[i : i + BATCH_SIZE]
            revision_block = ""
            if gap_ids:
                batch_ids = {r["id"] for r in batch}
                revision_block = prompts.REVISION_BLOCK.format(
                    feedback=review.get("feedback", "Add missing negative and boundary scenarios."),
                    existing=_fmt_tests([t for t in existing if t["requirement_id"] in batch_ids]) or "none",
                )
            result = invoke_structured(
                llm,
                TestCaseList,
                prompts.TEST_DESIGN_SYSTEM,
                prompts.TEST_DESIGN_USER.format(
                    requirements=_fmt_requirements(batch), revision_block=revision_block
                ),
            )
            for raw in result.test_cases:
                if raw.requirement_id not in valid_ids or not raw.steps:
                    continue  # drop hallucinated ids / empty tests
                new_tests.append(
                    {
                        "id": f"TC-{next_num:03d}",
                        "requirement_id": raw.requirement_id,
                        "title": raw.title.strip(),
                        "category": _norm_category(raw.category),
                        "priority": _norm_priority(raw.priority),
                        "preconditions": raw.preconditions.strip(),
                        "steps": [s.strip() for s in raw.steps if s.strip()],
                        "expected_result": raw.expected_result.strip(),
                    }
                )
                next_num += 1

        iteration = state.get("iteration", 0) + 1
        return {
            "test_cases": existing + new_tests,
            "iteration": iteration,
            "log": _log(state, f"Test-design agent pass {iteration}: +{len(new_tests)} tests"),
        }

    # 3) Reviewer agent: deterministic coverage rules + LLM judgement ----------
    def review(state: AgentState) -> dict:
        requirements, tests = state["requirements"], state["test_cases"]
        by_req: Dict[str, List[Dict]] = {r["id"]: [] for r in requirements}
        for t in tests:
            by_req[t["requirement_id"]].append(t)

        no_tests = [rid for rid, ts in by_req.items() if not ts]
        no_negative = [
            r["id"]
            for r in requirements
            if r["type"] == "functional"
            and by_req[r["id"]]
            and not any(t["category"] in ("negative", "boundary", "edge") for t in by_req[r["id"]])
        ]
        covered = len(requirements) - len(no_tests)
        coverage_pct = round(100 * covered / len(requirements), 1)

        verdict = invoke_structured(
            llm,
            ReviewVerdict,
            prompts.REVIEW_SYSTEM,
            prompts.REVIEW_USER.format(requirements=_fmt_requirements(requirements), tests=_fmt_tests(tests)),
        )
        valid = set(by_req)
        semantic = [rid for rid in verdict.semantic_gap_ids if rid in valid]
        gap_ids = sorted(set(no_tests) | set(no_negative) | set(semantic))

        feedback = verdict.feedback.strip()
        if no_tests:
            feedback += f" No tests at all for: {', '.join(no_tests)}."
        if no_negative:
            feedback += f" No negative/boundary tests for: {', '.join(no_negative)}."

        return {
            "gap_ids": gap_ids,
            "review": {
                "coverage_pct": coverage_pct,
                "quality_score": max(1, min(10, verdict.quality_score)),
                "feedback": feedback,
                "gap_ids": gap_ids,
                "revisions": max(0, state.get("iteration", 1) - 1),
            },
            "log": _log(state, f"Reviewer agent: coverage {coverage_pct}%, {len(gap_ids)} requirements flagged"),
        }

    # 4) Human-in-the-loop checkpoint (graph pauses BEFORE this node) ----------
    def human_review(state: AgentState) -> dict:
        return {"approved": True, "log": _log(state, "Human reviewer approved the test suite")}

    # 5) Script agent ------------------------------------------------------------
    def generate_scripts(state: AgentState) -> dict:
        tests = state["test_cases"]
        code = None
        if use_llm_scripts:
            parts = [SCRIPT_HEADER]
            try:
                for i in range(0, len(tests), SCRIPT_BATCH_SIZE):
                    batch = tests[i : i + SCRIPT_BATCH_SIZE]
                    listing = "\n\n".join(
                        f"{t['id']} [{t['requirement_id']}] {t['title']}\nPreconditions: {t['preconditions']}\n"
                        f"Steps: {'; '.join(t['steps'])}\nExpected: {t['expected_result']}"
                        for t in batch
                    )
                    body = clean_code(invoke_text(llm, prompts.SCRIPT_SYSTEM, prompts.SCRIPT_USER.format(tests=listing)))
                    # drop imports/BASE_URL the model repeats; the header already has them
                    body = "\n".join(
                        ln
                        for ln in body.splitlines()
                        if not ln.startswith(("import pytest", "from playwright", "BASE_URL"))
                    )
                    parts.append("\n\n" + body.strip() + "\n")
                candidate = "".join(parts)
                code = candidate if is_valid_python(candidate) else None
            except RuntimeError:
                code = None
        mode = "LLM-generated"
        if code is None:
            code, mode = template_script(tests), "template"
        return {"outputs": {**state.get("outputs", {}), "_script_code": code}, "log": _log(state, f"Script agent: {mode} pytest suite")}

    # 6) Export ----------------------------------------------------------------
    def export(state: AgentState) -> dict:
        run_dir = state.get("run_dir") or "outputs"
        os.makedirs(run_dir, exist_ok=True)
        outputs = dict(state.get("outputs", {}))
        code = outputs.pop("_script_code")
        script_path = os.path.join(run_dir, "test_generated.py")
        with open(script_path, "w", encoding="utf-8") as fh:
            fh.write(code)
        outputs["excel"] = export_excel(
            os.path.join(run_dir, "test_cases.xlsx"), state["requirements"], state["test_cases"], state["review"]
        )
        outputs["pytest"] = script_path
        outputs["traceability"] = export_traceability_md(
            os.path.join(run_dir, "traceability.md"), state["requirements"], state["test_cases"], state["review"]
        )
        return {"outputs": outputs, "log": _log(state, "Exported Excel, pytest suite and traceability report")}

    return {
        "parse_requirements": parse_requirements,
        "design_tests": design_tests,
        "review": review,
        "human_review": human_review,
        "generate_scripts": generate_scripts,
        "export": export,
    }
