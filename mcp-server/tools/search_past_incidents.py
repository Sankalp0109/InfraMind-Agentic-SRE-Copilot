"""search_past_incidents: hybrid retrieval over the postmortem corpus.

Wraps rag-pipeline/retrieve.py's search_past_incidents(). The RAG pipeline
lives in a sibling directory with its own heavy dependencies (torch via
sentence-transformers) — imported lazily inside call(), not at module load
time, so mcp-server startup and tools/list stay fast even in a session that
never actually calls this tool. First real call still pays the one-time
model-load cost (observed several seconds to tens of seconds on this host);
every call after that reuses retrieve.py's own cached singletons.
"""

import json
import sys
from pathlib import Path

NAME = "search_past_incidents"
DESCRIPTION = (
    "Search historical postmortems for incidents similar to the current one. "
    "Read-only. Call once symptoms are established (after metrics/traces/logs), "
    "not as a first step — it's most useful once there's something concrete to "
    "match against."
)
READ_ONLY = True
INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Incident description to search for, e.g. 'payment charges failing with invalid token errors'.",
        },
        "service": {
            "type": "string",
            "description": "Optional — restrict results to postmortems tagged with this service.",
        },
        "top_k": {
            "type": "integer",
            "description": "Max results to return. Defaults to 5.",
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}

_RAG_PIPELINE_DIR = Path(__file__).resolve().parent.parent.parent / "rag-pipeline"


def call(query: str, service: str | None = None, top_k: int = 5) -> tuple[list[dict], bool]:
    if str(_RAG_PIPELINE_DIR) not in sys.path:
        sys.path.insert(0, str(_RAG_PIPELINE_DIR))

    try:
        from retrieve import search_past_incidents as _search
    except ImportError as exc:
        return [
            {
                "type": "text",
                "text": f"RAG pipeline unavailable (missing dependency: {exc}). "
                "Run `pip install -r rag-pipeline/requirements.txt`.",
            }
        ], True

    results = _search(query, service=service, top_k=top_k)
    if not results:
        return [{"type": "text", "text": "No matching past incidents found."}], False

    summary = [
        {
            "title": r["title"],
            "section": r["section"],
            "service": r["service"],
            "source_file": r["source_file"],
            "score": round(r["score"], 3),
            "excerpt": r["text"],
        }
        for r in results
    ]
    return [{"type": "text", "text": json.dumps(summary, indent=2)}], False
