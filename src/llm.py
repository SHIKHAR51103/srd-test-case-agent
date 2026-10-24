"""Groq LLM factory and a retrying structured-output helper."""
import os
import time
from typing import Optional, Type, TypeVar

from pydantic import BaseModel

from .config import DEFAULT_MODEL

T = TypeVar("T", bound=BaseModel)


def get_llm(model: Optional[str] = None, api_key: Optional[str] = None):
    """Return a ChatGroq client. The key comes from the argument or the GROQ_API_KEY env var."""
    from langchain_groq import ChatGroq

    key = api_key or os.getenv("GROQ_API_KEY")
    if not key:
        raise RuntimeError(
            "GROQ_API_KEY is missing. Get a free key at https://console.groq.com/keys "
            "and put it in .env or the Streamlit sidebar."
        )
    return ChatGroq(model=model or DEFAULT_MODEL, temperature=0.1, api_key=key, max_retries=4)


def invoke_structured(llm, schema: Type[T], system: str, user: str, retries: int = 3) -> T:
    """Call the LLM and force output into `schema`, retrying on parse errors / rate limits."""
    try:
        # JSON-schema mode is supported by the current Groq models; fall back to the library default.
        runner = llm.with_structured_output(schema, method="json_schema")
    except (TypeError, ValueError, NotImplementedError):
        runner = llm.with_structured_output(schema)
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        try:
            result = runner.invoke([("system", system), ("human", user)])
            if result is None:
                raise ValueError("model returned no structured output")
            return result
        except Exception as exc:  # noqa: BLE001 - we retry on anything the provider throws
            last_error = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"LLM call failed after {retries} attempts: {last_error}")


def invoke_text(llm, system: str, user: str, retries: int = 3) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        try:
            return llm.invoke([("system", system), ("human", user)]).content
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"LLM call failed after {retries} attempts: {last_error}")