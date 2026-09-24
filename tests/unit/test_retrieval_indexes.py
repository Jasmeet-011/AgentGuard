"""Index building and the real BM25 / Qdrant backends, with a fake embedder (no models)."""

from pathlib import Path

import pytest

from agentguard.ingest.index import (
    IndexBuildError,
    build_dense_index,
    build_sparse_corpus,
    indexable_chunks,
    reset_qdrant_dir,
)
from agentguard.models import Chunk
from agentguard.retrieval.dense import DenseSearcher, open_qdrant
from agentguard.retrieval.sparse import SparseSearcher, save_corpus, tokenize


def chunk(doc_id: str, i: int, text: str, is_toc: bool = False) -> Chunk:
    return Chunk(
        chunk_id=f"{doc_id}-p1-{i}",
        firm_name=doc_id,
        doc_id=doc_id,
        doc_type="part2a",
        adv_item=3 if is_toc else 5,
        is_toc=is_toc,
        item_title=None,
        page_start=1,
        page_end=1,
        text=text,
        token_count=len(text.split()),
    )


CHUNKS = [
    chunk("acme", 0, "Acme charges an annual advisory fee of 1.25% of assets"),
    chunk("acme", 1, "Acme has custody of client assets"),
    chunk("zeta", 0, "Zeta charges a flat annual fee of $1,200"),
    chunk("zeta", 1, "Zeta disciplinary history: none"),
    chunk("zeta", 2, "Item 5 Fees Item 9 Disciplinary Item 15 Custody", is_toc=True),
]


class FakeEmbedder:
    """Bag-of-keywords vectors over a tiny vocabulary: deterministic, no model download."""

    VOCAB = ("fee", "custody", "disciplinary", "flat")
    dimension = len(VOCAB)

    def _vec(self, text: str) -> list[float]:
        words = text.lower()
        v = [float(w in words) for w in self.VOCAB]
        return v if any(v) else [0.01] * self.dimension

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, query: str) -> list[float]:
        return self._vec(query)


def test_toc_chunks_excluded_and_counted_per_firm() -> None:
    kept, excluded = indexable_chunks(CHUNKS)
    assert [c.chunk_id for c in kept] == [c.chunk_id for c in CHUNKS if not c.is_toc]
    assert excluded == {"zeta": 1}


def test_tokenize_keeps_numbers_and_percentages() -> None:
    assert tokenize("Fees: 1.25% of $1,000,000; Item 5.") == [
        "fees",
        "1.25%",
        "of",
        "1,000,000",
        "item",
        "5",
    ]


@pytest.fixture
def sparse(tmp_path: Path) -> SparseSearcher:
    kept, _ = indexable_chunks(CHUNKS)
    save_corpus(build_sparse_corpus(kept), tmp_path)
    return SparseSearcher(tmp_path)


def test_bm25_ranks_keyword_match_first(sparse: SparseSearcher) -> None:
    hits = sparse.search("custody of client assets", k=5, doc_ids=None)
    assert hits[0][0] == "acme-p1-1"
    assert all(score > 0 for _, score in hits)


def test_bm25_filter_applies_before_top_k(sparse: SparseSearcher) -> None:
    query = "advisory fee 1.25% flat"
    # Unfiltered, acme's fee chunk ranks first (two matching terms vs zeta's one).
    assert sparse.search(query, k=1, doc_ids=None)[0][0] == "acme-p1-0"
    # Filtered to zeta, k=1 still returns zeta's chunk: the filter runs before top-k.
    assert [cid for cid, _ in sparse.search(query, k=1, doc_ids=["zeta"])] == ["zeta-p1-0"]


def test_bm25_excludes_toc_and_zero_scores(sparse: SparseSearcher) -> None:
    hits = sparse.search("disciplinary custody fees", k=10, doc_ids=None)
    assert "zeta-p1-2" not in {cid for cid, _ in hits}
    assert sparse.search("xyzzy", k=10, doc_ids=None) == []


def test_missing_bm25_file_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="agentguard ingest"):
        SparseSearcher(tmp_path)


@pytest.fixture
def dense(tmp_path: Path) -> DenseSearcher:
    client = open_qdrant(tmp_path / "qdrant")
    kept, _ = indexable_chunks(CHUNKS)
    embedder = FakeEmbedder()
    build_dense_index(kept, client, embedder)  # type: ignore[arg-type]
    return DenseSearcher(client, embedder)  # type: ignore[arg-type]


def test_qdrant_search_and_filter(dense: DenseSearcher) -> None:
    assert dense.search("custody", k=1, doc_ids=None)[0][0] == "acme-p1-1"
    filtered = dense.search("custody", k=2, doc_ids=["zeta"])
    assert filtered and all(cid.startswith("zeta") for cid, _ in filtered)
    assert len(dense.search("fee", k=10, doc_ids=None)) == 4  # TOC chunk not indexed


def test_rebuild_after_reset_holds_only_new_points(tmp_path: Path) -> None:
    path = tmp_path / "qdrant"
    client = open_qdrant(path)
    build_dense_index(CHUNKS[:4], client, FakeEmbedder())  # type: ignore[arg-type]
    client.close()
    reset_qdrant_dir(path)
    client = open_qdrant(path)
    build_dense_index(CHUNKS[:1], client, FakeEmbedder())  # type: ignore[arg-type]
    searcher = DenseSearcher(client, FakeEmbedder())  # type: ignore[arg-type]
    assert [cid for cid, _ in searcher.search("fee", k=10, doc_ids=None)] == ["acme-p1-0"]
    client.close()


def test_stale_points_after_rebuild_fail_loudly(tmp_path: Path) -> None:
    # Documents the qdrant-client local-mode behavior reset_qdrant_dir works around: without
    # the reset, old points can survive; the count check must then raise, not pass silently.
    client = open_qdrant(tmp_path / "qdrant")
    build_dense_index(CHUNKS[:4], client, FakeEmbedder())  # type: ignore[arg-type]
    try:
        build_dense_index(CHUNKS[:1], client, FakeEmbedder())  # type: ignore[arg-type]
    except IndexBuildError:
        pass
    else:
        assert client.count("chunks").count == 1
    client.close()


def test_reset_refuses_non_qdrant_directory(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("keep me", encoding="utf-8")
    with pytest.raises(IndexBuildError, match="not Qdrant storage"):
        reset_qdrant_dir(tmp_path)
    assert (tmp_path / "notes.txt").exists()
    reset_qdrant_dir(tmp_path / "missing")  # no-op
