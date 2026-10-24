"""LangGraph workflow:

  parse_requirements -> design_tests -> review --(gaps & budget left)--> design_tests  (revision loop)
                                           \\--(clean or budget spent)--> [PAUSE] human_review
                                                                            -> generate_scripts -> export
"""
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .agents import make_nodes
from .config import MAX_REVISIONS
from .schemas import AgentState


def build_graph(llm, max_revisions: int = MAX_REVISIONS, use_llm_scripts: bool = False):
    nodes = make_nodes(llm, max_revisions, use_llm_scripts)

    def route_after_review(state: AgentState) -> str:
        # iteration counts design passes: pass 1 is the first draft, the rest are revisions.
        needs_work = bool(state.get("gap_ids"))
        revisions_used = state.get("iteration", 1) - 1
        return "revise" if needs_work and revisions_used < max_revisions else "approve"

    graph = StateGraph(AgentState)
    for name, fn in nodes.items():
        graph.add_node(name, fn)

    graph.add_edge(START, "parse_requirements")
    graph.add_edge("parse_requirements", "design_tests")
    graph.add_edge("design_tests", "review")
    graph.add_conditional_edges("review", route_after_review, {"revise": "design_tests", "approve": "human_review"})
    graph.add_edge("human_review", "generate_scripts")
    graph.add_edge("generate_scripts", "export")
    graph.add_edge("export", END)

    # interrupt_before gives the human-in-the-loop pause; MemorySaver keeps state while paused.
    return graph.compile(checkpointer=MemorySaver(), interrupt_before=["human_review"])
