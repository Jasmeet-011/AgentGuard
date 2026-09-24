"""Dense search: bge embeddings in a local on-disk Qdrant collection."""

from pathlib import Path

from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer

COLLECTION_NAME = "chunks"


class Embedder:
    """Sentence-transformers model with bge's query/passage asymmetry built in."""

    def __init__(self, model_name: str, query_prefix: str) -> None:
        self._model = SentenceTransformer(model_name)
        self._query_prefix = query_prefix

    @property
    def dimension(self) -> int:
        dimension = self._model.get_embedding_dimension()
        if dimension is None:
            raise ValueError("Embedding model does not report a fixed dimension")
        return dimension

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        """Normalized embeddings for chunk texts (no prefix)."""
        vectors = self._model.encode(texts, normalize_embeddings=True, batch_size=32)
        return vectors.tolist()

    def embed_query(self, query: str) -> list[float]:
        """Normalized embedding for a query, with the model's retrieval instruction prefixed."""
        vector = self._model.encode(self._query_prefix + query, normalize_embeddings=True)
        return vector.tolist()


def open_qdrant(qdrant_path: Path) -> QdrantClient:
    """Local on-disk Qdrant client. Only one client per path may be open at a time."""
    qdrant_path.mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=str(qdrant_path))


def doc_filter(doc_ids: list[str] | None) -> models.Filter | None:
    """Qdrant payload filter restricting results to `doc_ids` (None means no filter)."""
    if doc_ids is None:
        return None
    condition = models.FieldCondition(key="doc_id", match=models.MatchAny(any=doc_ids))
    return models.Filter(must=[condition])


class DenseSearcher:
    """Cosine search over the `chunks` collection built by `index.py`."""

    def __init__(self, client: QdrantClient, embedder: Embedder) -> None:
        if not client.collection_exists(COLLECTION_NAME):
            raise FileNotFoundError(
                f"Qdrant collection {COLLECTION_NAME!r} missing. Run `agentguard ingest` first."
            )
        self._client = client
        self._embedder = embedder

    def search(self, query: str, k: int, doc_ids: list[str] | None) -> list[tuple[str, float]]:
        """Top `k` (chunk_id, cosine similarity), filtered to `doc_ids` inside Qdrant if given."""
        response = self._client.query_points(
            COLLECTION_NAME,
            query=self._embedder.embed_query(query),
            query_filter=doc_filter(doc_ids),
            limit=k,
            with_payload=["chunk_id"],
        )
        return [(str(p.payload["chunk_id"]), float(p.score)) for p in response.points if p.payload]
