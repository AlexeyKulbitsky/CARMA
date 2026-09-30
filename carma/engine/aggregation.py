"""Edge aggregation (spec «Ядро», 2): component edges folded up to the nodes of one level."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from carma.engine.tree import ComponentTree
from carma.store.api import ComponentEdge


@dataclass(frozen=True)
class LevelEdge:
    src: str
    dst: str
    refs: int
    calls: int
    uses: int
    src_boundary: bool = False
    dst_boundary: bool = False


def level_edges(edges: Iterable[ComponentEdge], tree: ComponentTree, scope: str) -> list[LevelEdge]:
    """Sum of the edges whose ends fall into different nodes of the level; edges between two boundary nodes drop out."""
    sums: dict[tuple[str, str], list[int]] = {}
    boundary: dict[str, bool] = {}
    for e in edges:
        src, dst = tree.node_at(scope, e.src), tree.node_at(scope, e.dst)
        if src is None or dst is None or src[0] == dst[0] or (src[1] and dst[1]):
            continue
        boundary[src[0]], boundary[dst[0]] = src[1], dst[1]
        total = sums.setdefault((src[0], dst[0]), [0, 0, 0])
        total[0] += e.refs
        total[1] += e.calls
        total[2] += e.uses
    return [LevelEdge(a, b, *sums[(a, b)], boundary[a], boundary[b]) for a, b in sorted(sums)]
