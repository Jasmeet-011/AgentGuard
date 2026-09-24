"""Reciprocal rank fusion: merge several ranked lists of chunk_ids into one."""

import math


def rrf_fuse(rankings: list[list[str]], rrf_k: int) -> list[tuple[str, float]]:
    """Fuse ranked lists with `score(id) = sum over lists of 1 / (rrf_k + rank)`, rank from 1.

    Returns (chunk_id, score) sorted best first. Ties are broken deterministically: first by
    the best rank the id reached in any list, then by chunk_id. Scores are summed with
    `math.fsum`, so they do not depend on the order of `rankings`.
    """
    if rrf_k <= 0:
        raise ValueError(f"rrf_k must be positive, got {rrf_k}")
    contributions: dict[str, list[float]] = {}
    best_rank: dict[str, int] = {}
    for ranking in rankings:
        if len(set(ranking)) != len(ranking):
            raise ValueError(f"A ranking contains duplicate ids: {ranking}")
        for rank, chunk_id in enumerate(ranking, start=1):
            contributions.setdefault(chunk_id, []).append(1.0 / (rrf_k + rank))
            best_rank[chunk_id] = min(rank, best_rank.get(chunk_id, rank))
    scores = {chunk_id: math.fsum(parts) for chunk_id, parts in contributions.items()}
    order = sorted(scores, key=lambda cid: (-scores[cid], best_rank[cid], cid))
    return [(chunk_id, scores[chunk_id]) for chunk_id in order]
