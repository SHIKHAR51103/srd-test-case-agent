"""Headless run (auto-approves the human checkpoint):  python cli.py path/to/srd.txt"""
import sys

from src.config import DEFAULT_MODEL, MAX_REVISIONS
from src.llm import get_llm
from src.runner import new_run, stream_until_pause

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python cli.py <srd.txt>")
    with open(sys.argv[1], encoding="utf-8") as fh:
        text = fh.read()
    graph, config, initial = new_run(get_llm(DEFAULT_MODEL), text, MAX_REVISIONS, use_llm_scripts=False)
    state = stream_until_pause(graph, initial, config, on_node=lambda n: print(f"[ok] {n}"))
    state = stream_until_pause(graph, None, config, on_node=lambda n: print(f"[ok] {n}"))
    print("\n".join(state["log"]))
    print("Files:", state["outputs"])
