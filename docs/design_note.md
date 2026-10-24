# Design Note: Multi-Agent SRD-to-Test-Suite Assistant

## Problem
QA engineers spend days turning SRDs into test cases, and coverage gaps (especially negative and boundary scenarios)
are usually found late. I wanted to automate the first draft while keeping accountability with a human.

## Approach
A LangGraph state machine with specialised agents: Parser, Test-design, Reviewer, Script agent, plus a human approval
checkpoint. The Reviewer can send work back to the Test-design agent (bounded loop), which is the main reason this is
a graph and not a single prompt.

## Key decisions and trade-offs
| Decision | Why | Trade-off |
|---|---|---|
| Pydantic structured outputs | Reliable parsing, schema validation | Occasional retries when the model breaks schema |
| Rule-based + LLM reviewer | Rules are cheap and deterministic; the LLM catches semantic gaps | Two review signals to reconcile |
| Revise only flagged requirements | Saves tokens, fits the free tier | Cross-requirement issues are not re-examined |
| Bounded revision loop | Predictable cost and latency | May stop with a few gaps remaining (reported to the user) |
| `interrupt_before` human checkpoint | Test suites need an accountable owner | Adds a manual step |
| Template fallback for scripts | Always produces valid Python | Skeleton, not full automation |
| Groq free tier, small batches | Zero cost, fast inference | Rate limits; chunk and batch sizes kept small |

## Evaluation
Three sample SRDs with keyword ground truth; metrics are requirement recall, coverage, negative-test ratio, tests per
requirement and revisions needed. Results are written to `eval/results.md` (fill in after running with your key).

## What I would improve
1. Persistent checkpointing (SQLite/Postgres) so runs survive restarts.
2. Stronger evaluation: LLM-as-judge plus a small human-labelled set.
3. Multimodal SRDs (UI mockups, flow diagrams).
4. Learn selectors from a live DOM snapshot to produce working Playwright code.
5. Export to Jira / TestRail, and track prompt versions against eval scores (MLOps).
