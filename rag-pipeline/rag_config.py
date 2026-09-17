"""Shared config for the RAG pipeline.

Qdrant runs embedded (on-disk, no server process) rather than as a Docker
container — this host has already struggled running the full otel-demo
stack alone (see IMPLEMENTATION_DETAILS.md), so another container wasn't
worth the resource cost for what's still a local-dev tool. Embeddings are a
local sentence-transformers model rather than a hosted API, since no
Voyage/OpenAI key is available here — see IMPLEMENTATION_DETAILS.md for the
full reasoning on both.
"""

from pathlib import Path

POSTMORTEMS_DIR = Path(__file__).resolve().parent.parent / "data" / "postmortems"
QDRANT_PATH = str(Path(__file__).resolve().parent / "qdrant_data")
COLLECTION_NAME = "postmortems"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # 384-dim, small, well-established default
