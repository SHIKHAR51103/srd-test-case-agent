"""Small helpers shared by the Streamlit app, the CLI and the evaluation script."""
import os
import uuid
from datetime import datetime
from typing import Callable, Dict, Optional, Tuple

from .config import OUTPUT_DIR
from .graph import build_graph


def new_run(llm, srd_text: str, max_revisions: int, use_llm_scripts: bool) -> Tuple[object, dict, dict]:
    """Create a graph + thread config + initial state."""
    graph = build_graph(llm, max_revisions=max_revisions, use_llm_scripts=use_llm_scripts)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    config = {"configurable": {"thread_id": run_id}}
    initial = {"srd_text": srd_text, "run_dir": os.path.join(OUTPUT_DIR, run_id), "log": [], "outputs": {}}
    return graph, config, initial


def stream_until_pause(graph, payload, config, on_node: Optional[Callable[[str], None]] = None) -> Dict:
    """Run the graph until it finishes or hits the human-review pause. Returns the state values."""
    for event in graph.stream(payload, config, stream_mode="updates"):
        for node in event:
            if not node.startswith("__") and on_node:
                on_node(node)
    return graph.get_state(config).values


def is_paused_for_review(graph, config) -> bool:
    return "human_review" in (graph.get_state(config).next or ())
