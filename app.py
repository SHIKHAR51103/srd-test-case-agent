"""Streamlit UI: upload an SRD -> agents generate tests -> human edits/approves -> download outputs."""
import os

import pandas as pd
import streamlit as st

from src.config import AVAILABLE_MODELS, DEFAULT_MODEL, MAX_REVISIONS
from src.llm import get_llm
from src.loaders import load_srd
from src.runner import is_paused_for_review, new_run, stream_until_pause

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "eval", "samples")
NODE_LABELS = {
    "parse_requirements": "Parser agent - extracting requirements",
    "design_tests": "Test-design agent - writing test cases",
    "review": "Reviewer agent - checking coverage and quality",
    "human_review": "Human approval",
    "generate_scripts": "Script agent - generating Playwright/pytest code",
    "export": "Exporting files",
}

st.set_page_config(page_title="SRD to Test Cases - Multi-Agent QA", page_icon="🧪", layout="wide")
st.title("🧪 SRD → Test Cases: Multi-Agent QA Assistant")
st.caption("LangGraph agents on Groq: parse → design → review (loop) → human approval → Excel + Playwright/pytest")

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Settings")
    api_key = st.text_input("Groq API key", type="password", value=os.getenv("GROQ_API_KEY", ""),
                            help="Free key: console.groq.com/keys")
    model = st.selectbox("Model", AVAILABLE_MODELS, index=AVAILABLE_MODELS.index(DEFAULT_MODEL)
                         if DEFAULT_MODEL in AVAILABLE_MODELS else 0)
    max_rev = st.slider("Max reviewer revision loops", 0, 4, MAX_REVISIONS)
    llm_scripts = st.checkbox("Generate automation code with the LLM", value=False,
                              help="Off = deterministic skeleton (fast, no extra tokens).")

# ---------------------------------------------------------------- input
tab_up, tab_paste, tab_sample = st.tabs(["Upload SRD", "Paste text", "Sample SRDs"])
srd_text = ""
with tab_up:
    up = st.file_uploader("PDF, DOCX, TXT or MD", type=["pdf", "docx", "txt", "md"])
    if up:
        try:
            srd_text = load_srd(up.name, up.getvalue())
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))
with tab_paste:
    pasted = st.text_area("Paste SRD text", height=220)
    if pasted.strip():
        srd_text = pasted
with tab_sample:
    samples = sorted(f for f in os.listdir(SAMPLES_DIR) if f.endswith(".txt")) if os.path.isdir(SAMPLES_DIR) else []
    choice = st.selectbox("Pick a sample", ["-"] + samples)
    if choice != "-":
        with open(os.path.join(SAMPLES_DIR, choice), encoding="utf-8") as fh:
            srd_text = fh.read()
        st.text_area("Preview", srd_text, height=220, disabled=True)

if srd_text:
    st.info(f"SRD loaded: {len(srd_text):,} characters")

# ---------------------------------------------------------------- run
if st.button("Generate test suite", type="primary", disabled=not srd_text):
    try:
        llm = get_llm(model, api_key or None)
    except RuntimeError as exc:
        st.error(str(exc))
        st.stop()
    graph, config, initial = new_run(llm, srd_text, max_rev, llm_scripts)
    st.session_state.update(graph=graph, config=config, state=None, done=False)
    with st.status("Agents are working...", expanded=True) as status:
        try:
            st.session_state.state = stream_until_pause(
                graph, initial, config, on_node=lambda n: status.write(f"✅ {NODE_LABELS.get(n, n)}")
            )
            status.update(label="Draft ready for your review", state="complete")
        except Exception as exc:  # noqa: BLE001
            status.update(label="Run failed", state="error")
            st.error(f"{exc}")

# ---------------------------------------------------------------- human review
state = st.session_state.get("state")
graph = st.session_state.get("graph")
config = st.session_state.get("config")

if state and graph and not st.session_state.get("done") and is_paused_for_review(graph, config):
    review = state["review"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Requirements", len(state["requirements"]))
    c2.metric("Test cases", len(state["test_cases"]))
    c3.metric("Coverage", f"{review['coverage_pct']}%")
    c4.metric("Reviewer score", f"{review['quality_score']}/10")
    st.write(f"**Reviewer feedback:** {review['feedback']}  \n**Revision loops used:** {review['revisions']}")

    with st.expander("Extracted requirements", expanded=False):
        st.dataframe(pd.DataFrame(state["requirements"]), use_container_width=True, hide_index=True)

    st.subheader("Human review: edit, add or delete test cases, then approve")
    df = pd.DataFrame(state["test_cases"]).copy()
    df["steps"] = df["steps"].apply(lambda s: "\n".join(s))
    edited = st.data_editor(df, num_rows="dynamic", use_container_width=True, hide_index=True, key="editor")

    if st.button("✅ Approve and generate files", type="primary"):
        edited = edited.fillna("")
        rows = edited.to_dict("records")
        for i, row in enumerate(rows, 1):
            row["steps"] = [s.strip() for s in str(row["steps"]).split("\n") if s.strip()]
            row["id"] = row["id"] or f"TC-{i:03d}"
        valid_ids = {r["id"] for r in state["requirements"]}
        rows = [r for r in rows if r.get("requirement_id") in valid_ids and r["steps"]]
        graph.update_state(config, {"test_cases": rows})  # human edits become part of the graph state
        with st.spinner("Generating files..."):
            st.session_state.state = stream_until_pause(graph, None, config)
        st.session_state.done = True
        st.rerun()

# ---------------------------------------------------------------- downloads
if state and st.session_state.get("done"):
    st.success("Done. Your files are ready.")
    out = state["outputs"]
    d1, d2, d3 = st.columns(3)
    with open(out["excel"], "rb") as fh:
        d1.download_button("⬇ Excel test cases", fh.read(), "test_cases.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with open(out["pytest"], "rb") as fh:
        d2.download_button("⬇ Playwright/pytest suite", fh.read(), "test_generated.py", "text/x-python")
    with open(out["traceability"], "rb") as fh:
        d3.download_button("⬇ Traceability report", fh.read(), "traceability.md", "text/markdown")
    with st.expander("Agent activity log"):
        for line in state.get("log", []):
            st.write("• " + line)
