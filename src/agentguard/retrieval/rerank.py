"""Cross-encoder reranking of (query, chunk text) pairs."""

from typing import Protocol

from sentence_transformers import CrossEncoder
from torch.nn import Identity

from agentguard.models import RetrievedChunk

# Pairs per forward pass inside one predict() call (all candidates go in one call).
RERANK_BATCH_SIZE = 32


class RerankScorer(Protocol):
    """Anything that scores texts against a query (the real Reranker, or a test fake)."""

    def score(self, query: str, texts: list[str]) -> list[float]: ...


class Reranker:
    """CrossEncoder returning raw logits (unbounded; higher = more relevant).

    The library's default sigmoid saturates at ~0.999 for several chunks and hides their
    order, so it is replaced by the identity. M9 tunes `min_rerank_score` on this scale.
    """

    def __init__(self, model_name: str) -> None:
        self._model = CrossEncoder(model_name)

    def score(self, query: str, texts: list[str]) -> list[float]:
        """One raw logit per text, in input order, from a single batched `predict` call."""
        if not texts:
            return []
        pairs = [(query, text) for text in texts]
        scores = self._model.predict(pairs, batch_size=RERANK_BATCH_SIZE, activation_fn=Identity())
        return [float(s) for s in scores]


def rerank(
    scorer: RerankScorer, query: str, candidates: list[RetrievedChunk]
) -> list[RetrievedChunk]:
    """Candidates with `rerank_score` set, sorted best first (ties by chunk_id)."""
    scores = scorer.score(query, [c.chunk.text for c in candidates])
    scored = [
        c.model_copy(update={"rerank_score": s}) for c, s in zip(candidates, scores, strict=True)
    ]
    return sorted(scored, key=lambda c: (-(c.rerank_score or 0.0), c.chunk.chunk_id))
