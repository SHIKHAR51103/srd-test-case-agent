"""Evaluation harness: runs the agents on each sample SRD and scores the output against ground truth.

Usage:  python -m eval.evaluate            (needs GROQ_API_KEY)

Metrics
  requirement_recall  share of ground-truth requirements found (keyword match on extracted requirements)
  coverage_pct        share of extracted requirements with >=1 test case (from the reviewer agent)
  negative_ratio      share of tests that are negative / boundary / edge (not only happy paths)
  tests_per_req       average number of tests per requirement
  revisions           reviewer loops that were needed
"""
import json
import os
import sys

from src.config import DEFAULT_MODEL, MAX_REVISIONS
from src.llm import get_llm
from src.runner import new_run, stream_until_pause

HERE = os.path.dirname(os.path.abspath(__file__))


def recall(requirements, ground_truth) -> float:
    corpus = [(r["title"] + " " + r["description"]).lower() for r in requirements]
    hits = sum(any(any(k in text for k in keywords) for text in corpus) for keywords in ground_truth)
    return hits / len(ground_truth)


def evaluate(llm) -> list:
    with open(os.path.join(HERE, "ground_truth.json"), encoding="utf-8") as fh:
        truth = json.load(fh)
    rows = []
    for name, keywords in truth.items():
        with open(os.path.join(HERE, "samples", name), encoding="utf-8") as fh:
            text = fh.read()
        graph, config, initial = new_run(llm, text, MAX_REVISIONS, use_llm_scripts=False)
        stream_until_pause(graph, initial, config)                 # runs until the human checkpoint
        state = stream_until_pause(graph, None, config)            # auto-approve
        tests, reqs, review = state["test_cases"], state["requirements"], state["review"]
        rows.append(
            {
                "sample": name,
                "requirements": len(reqs),
                "tests": len(tests),
                "requirement_recall": round(recall(reqs, keywords), 2),
                "coverage_pct": review["coverage_pct"],
                "negative_ratio": round(sum(t["category"] != "positive" for t in tests) / max(len(tests), 1), 2),
                "tests_per_req": round(len(tests) / max(len(reqs), 1), 1),
                "revisions": review["revisions"],
            }
        )
        print(rows[-1], flush=True)
    return rows


def to_markdown(rows, model) -> str:
    cols = list(rows[0])
    lines = [f"# Evaluation results (model: {model})", "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rows]
    avg = lambda c: round(sum(r[c] for r in rows) / len(rows), 2)  # noqa: E731
    lines += ["", f"**Average recall:** {avg('requirement_recall')}  |  **Average negative ratio:** {avg('negative_ratio')}"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    model = DEFAULT_MODEL
    results = evaluate(get_llm(model))
    path = os.path.join(HERE, "results.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(to_markdown(results, model))
    print(f"\nWrote {path}")
    sys.exit(0)
