"""Chunk the postmortem corpus, embed each chunk, upsert into Qdrant.

Run standalone: `python ingest.py`. Safe to re-run — recreates the
collection from scratch each time rather than trying to diff/update, since
the corpus is small (tens of chunks) and full rebuilds take seconds.
"""

from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer

from rag_config import COLLECTION_NAME, EMBEDDING_MODEL, POSTMORTEMS_DIR, QDRANT_PATH
from chunking import load_all_chunks


def ingest() -> int:
    chunks = load_all_chunks(POSTMORTEMS_DIR)
    if not chunks:
        print(f"No postmortems found in {POSTMORTEMS_DIR}")
        return 0

    print(f"Loaded {len(chunks)} chunks from {POSTMORTEMS_DIR}")

    model = SentenceTransformer(EMBEDDING_MODEL)
    vectors = model.encode([c.text for c in chunks], show_progress_bar=False)

    client = QdrantClient(path=QDRANT_PATH)
    if client.collection_exists(COLLECTION_NAME):
        client.delete_collection(COLLECTION_NAME)
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=vectors.shape[1], distance=Distance.COSINE),
    )

    points = [
        PointStruct(id=i, vector=vectors[i].tolist(), payload={**chunks[i].metadata, "text": chunks[i].text})
        for i in range(len(chunks))
    ]
    client.upsert(collection_name=COLLECTION_NAME, points=points)

    print(f"Upserted {len(points)} points into Qdrant collection '{COLLECTION_NAME}' at {QDRANT_PATH}")
    return len(points)


if __name__ == "__main__":
    ingest()
