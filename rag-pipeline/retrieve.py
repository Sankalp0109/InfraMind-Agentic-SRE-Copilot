"""Hybrid retrieval: Qdrant vector search + BM25, merged by reciprocal rank
fusion, reranked with a local cross-encoder.

Why hybrid: pure vector search can conflate semantically similar incidents
across different services (e.g. two "service is slow" postmortems for
different services can embed close together even though they're
unrelated), while BM25 anchors on exact service names and error strings
that a paraphrase-tolerant embedding can blur past. See
IMPLEMENTATION_DETAILS.md for why the 18-postmortem corpus deliberately
includes near-duplicate incidents to make this claim testable rather than
asserted.

Run standalone: `python retrieve.py "some incident description"`.
"""

import sys

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder, SentenceTransformer

from chunking import Chunk, load_all_chunks
from rag_config import COLLECTION_NAME, EMBEDDING_MODEL, POSTMORTEMS_DIR, QDRANT_PATH

CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RRF_K = 60  # standard reciprocal-rank-fusion smoothing constant
VECTOR_TOP_N = 20
BM25_TOP_N = 20
RERANK_CANDIDATES = 15

_state: dict = {}  # lazily-initialized singletons — see _ensure_loaded()


def _tokenize(text: str) -> list[str]:
    return text.lower().split()


def _ensure_loaded() -> None:
    """Load the embedding model, cross-encoder, Qdrant client, and BM25
    index once per process rather than per call — all cheap to hold in
    memory for this corpus size, expensive to reload every query."""
    if _state:
        return

    chunks: list[Chunk] = load_all_chunks(POSTMORTEMS_DIR)
    _state["chunks"] = chunks
    _state["bm25"] = BM25Okapi([_tokenize(c.text) for c in chunks])
    _state["embedder"] = SentenceTransformer(EMBEDDING_MODEL)
    _state["cross_encoder"] = CrossEncoder(CROSS_ENCODER_MODEL)
    _state["qdrant"] = QdrantClient(path=QDRANT_PATH)


def _vector_search(query: str, service: str | None, top_n: int) -> list[int]:
    """Returns chunk indices (== Qdrant point ids, see ingest.py) ranked by
    vector similarity."""
    vector = _state["embedder"].encode(query).tolist()
    query_filter = None
    if service:
        query_filter = Filter(must=[FieldCondition(key="service", match=MatchValue(value=service))])

    results = _state["qdrant"].query_points(
        collection_name=COLLECTION_NAME, query=vector, query_filter=query_filter, limit=top_n
    )
    return [point.id for point in results.points]


def _bm25_search(query: str, service: str | None, top_n: int) -> list[int]:
    """Returns chunk indices ranked by BM25 score, filtered by service
    post-hoc (the index covers the whole corpus; filtering happens on the
    ranked output rather than building a separate index per service)."""
    scores = _state["bm25"].get_scores(_tokenize(query))
    chunks = _state["chunks"]
    ranked = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)
    if service:
        ranked = [i for i in ranked if chunks[i].metadata.get("service") == service]
    return ranked[:top_n]


def _reciprocal_rank_fusion(*ranked_lists: list[int]) -> list[int]:
    scores: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank, chunk_id in enumerate(ranked):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)
    return sorted(scores, key=lambda cid: scores[cid], reverse=True)


def search_past_incidents(query: str, service: str | None = None, top_k: int = 5) -> list[dict]:
    _ensure_loaded()
    chunks = _state["chunks"]

    vector_ranked = _vector_search(query, service, VECTOR_TOP_N)
    bm25_ranked = _bm25_search(query, service, BM25_TOP_N)
    fused = _reciprocal_rank_fusion(vector_ranked, bm25_ranked)[:RERANK_CANDIDATES]

    if not fused:
        return []

    pairs = [(query, chunks[cid].text) for cid in fused]
    cross_scores = _state["cross_encoder"].predict(pairs)
    reranked = sorted(zip(fused, cross_scores), key=lambda pair: pair[1], reverse=True)[:top_k]

    return [
        {
            "score": float(score),
            "title": chunks[cid].metadata["title"],
            "section": chunks[cid].metadata["section"],
            "service": chunks[cid].metadata.get("service"),
            "source_file": chunks[cid].metadata["source_file"],
            "text": chunks[cid].text,
        }
        for cid, score in reranked
    ]


if __name__ == "__main__":
    query_arg = " ".join(sys.argv[1:]) or "payment service latency spike after config change"
    for r in search_past_incidents(query_arg):
        print(f"[{r['score']:.3f}] {r['title']} — {r['section']} ({r['source_file']})")
