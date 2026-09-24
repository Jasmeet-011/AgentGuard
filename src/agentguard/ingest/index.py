"""Build the Qdrant (dense) and BM25 (sparse) indexes from chunks.jsonl."""

import logging
import shutil
from collections import Counter
from pathlib import Path

from pydantic import BaseModel
from qdrant_client import QdrantClient, models

from agentguard.config import Settings
from agentguard.models import Chunk
from agentguard.retrieval.dense import COLLECTION_NAME, Embedder, open_qdrant
from agentguard.retrieval.sparse import Bm25Corpus, save_corpus, tokenize

logger = logging.getLogger(__name__)

_UPSERT_BATCH = 256


class IndexBuildError(Exception):
    """The built index does not match the chunks it was built from."""


class IndexSummary(BaseModel):
    """What was indexed, printed by `agentguard ingest`."""

    indexed: int
    toc_excluded_per_firm: dict[str, int]


def indexable_chunks(chunks: list[Chunk]) -> tuple[list[Chunk], dict[str, int]]:
    """Drop table-of-contents chunks (they name every item title and match any keyword query).

    Returns the kept chunks and the number excluded per doc_id.
    """
    kept = [c for c in chunks if not c.is_toc]
    excluded = Counter(c.doc_id for c in chunks if c.is_toc)
    return kept, dict(sorted(excluded.items()))


def build_dense_index(chunks: list[Chunk], client: QdrantClient, embedder: Embedder) -> None:
    """(Re)create the Qdrant collection with one normalized vector per chunk (cosine)."""
    if client.collection_exists(COLLECTION_NAME):
        client.delete_collection(COLLECTION_NAME)
    client.create_collection(
        COLLECTION_NAME,
        vectors_config=models.VectorParams(
            size=embedder.dimension, distance=models.Distance.COSINE
        ),
    )
    vectors = embedder.embed_passages([c.text for c in chunks])
    points = [
        models.PointStruct(id=i, vector=v, payload={"chunk_id": c.chunk_id, "doc_id": c.doc_id})
        for i, (c, v) in enumerate(zip(chunks, vectors, strict=True))
    ]
    for start in range(0, len(points), _UPSERT_BATCH):
        client.upsert(COLLECTION_NAME, points=points[start : start + _UPSERT_BATCH])
    stored = client.count(COLLECTION_NAME).count
    if stored != len(points):
        raise IndexBuildError(
            f"Qdrant collection holds {stored} points after indexing {len(points)} chunks. "
            "Stale points survived a rebuild; delete the qdrant directory and re-ingest."
        )


def build_sparse_corpus(chunks: list[Chunk]) -> Bm25Corpus:
    """Tokenized chunk texts in index order, for BM25."""
    return Bm25Corpus(
        chunk_ids=[c.chunk_id for c in chunks],
        doc_ids=[c.doc_id for c in chunks],
        tokens=[tokenize(c.text) for c in chunks],
    )


def reset_qdrant_dir(qdrant_path: Path) -> None:
    """Delete the local Qdrant storage so the rebuild starts empty.

    qdrant-client's local mode on Windows keeps a deleted collection's points and brings them
    back when a collection of the same name is recreated, so deleting the collection is not
    enough. Only a directory that looks like Qdrant storage (has meta.json) is removed.
    """
    if not qdrant_path.exists():
        return
    if not (qdrant_path / "meta.json").is_file():
        raise IndexBuildError(f"{qdrant_path} exists but is not Qdrant storage; not deleting it.")
    shutil.rmtree(qdrant_path)


def build_indexes(chunks: list[Chunk], settings: Settings) -> IndexSummary:
    """Build both indexes from `chunks`, excluding TOC chunks from each."""
    kept, excluded = indexable_chunks(chunks)
    for doc_id, count in excluded.items():
        logger.info("Excluded %d TOC chunk(s) from the indexes for %s", count, doc_id)
    logger.info("Excluded %d TOC chunks in total", sum(excluded.values()))
    embedder = Embedder(settings.embedding_model, settings.embedding_query_prefix)
    reset_qdrant_dir(settings.qdrant_path)
    client = open_qdrant(settings.qdrant_path)
    try:
        build_dense_index(kept, client, embedder)
    finally:
        client.close()
    save_corpus(build_sparse_corpus(kept), settings.processed_dir)
    return IndexSummary(indexed=len(kept), toc_excluded_per_firm=excluded)
