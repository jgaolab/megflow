# -*- coding: utf-8 -*-
"""基于通道物理位置的 KNN / 距离阈值图构建，得到 edge_index。"""
from __future__ import annotations

import numpy as np
from typing import Optional, Tuple

try:
    from sklearn.neighbors import NearestNeighbors
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False


def build_edge_index_knn(
    pos: np.ndarray,
    k: int = 6,
    include_self: bool = False,
) -> np.ndarray:
    """
    基于位置 pos (n_channels, 2 或 3) 的 K 近邻无向图。
    返回 edge_index [2, num_edges]，COO 格式，双向边。
    """
    if not HAS_SKLEARN:
        raise RuntimeError("build_edge_index_knn 需要 sklearn.neighbors.NearestNeighbors")
    n = pos.shape[0]
    k_eff = min(k + (0 if include_self else 1), n)
    nbrs = NearestNeighbors(n_neighbors=k_eff, algorithm="auto", metric="euclidean").fit(pos)
    indices = nbrs.kneighbors(pos, return_distance=False)
    if not include_self:
        indices = indices[:, 1:]
    rows = np.repeat(np.arange(n), indices.shape[1])
    cols = indices.ravel()
    edge_index = np.stack([rows, cols], axis=0)
    edge_index_bidir = np.hstack([edge_index, edge_index[[1, 0], :]])
    edge_index_bidir = np.unique(edge_index_bidir, axis=1)
    return edge_index_bidir.astype(np.int64)


def build_edge_index_threshold(
    pos: np.ndarray,
    max_dist: float,
) -> np.ndarray:
    """
    距离阈值邻接：距离 <= max_dist 的通道对连边（无向）。
    pos: (n_channels, 2 或 3)。
    """
    if not HAS_SKLEARN:
        raise RuntimeError("build_edge_index_threshold 需要 sklearn")
    nbrs = NearestNeighbors(radius=max_dist, algorithm="auto", metric="euclidean").fit(pos)
    pairs = nbrs.radius_neighbors_graph(pos, radius=max_dist)
    pairs = (pairs + pairs.T) > 0
    rows, cols = np.where(np.triu(pairs, k=1))
    edge_index = np.stack([rows, cols], axis=0)
    edge_index_bidir = np.hstack([edge_index, edge_index[[1, 0], :]])
    return edge_index_bidir.astype(np.int64)


def build_edge_index(
    pos: np.ndarray,
    method: str = "knn",
    k: int = 6,
    max_dist: Optional[float] = None,
) -> np.ndarray:
    """
    统一接口：method in ('knn', 'threshold')。
    knn: 使用 k 近邻；threshold: 使用 max_dist 阈值（必须提供 max_dist）。
    """
    if method == "knn":
        return build_edge_index_knn(pos, k=k)
    if method == "threshold":
        if max_dist is None:
            raise ValueError("threshold 需提供 max_dist")
        return build_edge_index_threshold(pos, max_dist=max_dist)
    raise ValueError("method 应为 'knn' 或 'threshold'")
