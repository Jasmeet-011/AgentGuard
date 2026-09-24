"""BM25 keyword search over the indexed chunks."""

import pickle
import re
from pathlib import Path

from pydantic import BaseModel
from rank_bm25 import BM25Okapi

BM25_FILENAME = "bm25.pkl"
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*%?")


class Bm25Corpus(BaseModel):
    """What `index.py` pickles: tokenized chunk texts in the same order as `chunk_ids`."""

    chunk_ids: list[str]
    doc_ids: list[str]
    tokens: list[list[str]]


def tokenize(text: str) -> list[str]:
    """Lowercase regex tokens, no stemming. Keeps numbers like "1.25%" and "$1,000" as one."""
    return _TOKEN_RE.findall(text.lower())


def save_corpus(corpus: Bm25Corpus, processed_dir: Path) -> Path:
    """Pickle the tokenized corpus to `{processed_dir}/bm25.pkl`."""
    path = processed_dir / BM25_FILENAME
    with path.open("wb") as f:
        pickle.dump(corpus.model_dump(), f)
    return path


class SparseSearcher:
    """BM25Okapi over the pickled corpus. IDF is computed over the whole corpus."""

    def __init__(self, processed_dir: Path) -> None:
        path = processed_dir / BM25_FILENAME
        if not path.is_file():
            raise FileNotFoundError(f"{path} not found. Run `agentguard ingest` first.")
        with path.open("rb") as f:
            self._corpus = Bm25Corpus.model_validate(pickle.load(f))
        self._bm25 = BM25Okapi(self._corpus.tokens)

    def search(self, query: str, k: int, doc_ids: list[str] | None) -> list[tuple[str, float]]:
        """Top `k` (chunk_id, bm25 score), restricted to `doc_ids` before ranking if given.

        Chunks with a score of 0 (no query term in common) are not returned.
        """
        scores = self._bm25.get_scores(tokenize(query))
        allowed = set(doc_ids) if doc_ids is not None else None
        hits = [
            (chunk_id, float(score))
            for chunk_id, doc_id, score in zip(
                self._corpus.chunk_ids, self._corpus.doc_ids, scores, strict=True
            )
            if score > 0 and (allowed is None or doc_id in allowed)
        ]
        hits.sort(key=lambda hit: (-hit[1], hit[0]))
        return hits[:k]
