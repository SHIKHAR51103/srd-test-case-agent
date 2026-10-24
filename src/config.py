"""Central configuration. Values can be overridden through environment variables / .env."""
import os

from dotenv import load_dotenv

load_dotenv()

# Groq retired the Llama 3.x models on 2026-08-16. These replacements support structured outputs.
DEFAULT_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
AVAILABLE_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]
MAX_REVISIONS = int(os.getenv("MAX_REVISIONS", "2"))

# Free-tier friendly sizes: keep each LLM call small so we stay under token-per-minute limits.
CHUNK_CHARS = 5000        # SRD text per requirement-extraction call
BATCH_SIZE = 5            # requirements per test-design call
SCRIPT_BATCH_SIZE = 6     # test cases per script-generation call

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "outputs")