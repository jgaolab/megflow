# -*- coding: utf-8 -*-
"""
从原始 MEG 窗口数据构建 PyG Data 列表（每记录一条列表，每窗口一个 Data）。
节点特征在模型内由 x_raw 经可学习编码器得到，此处不再计算手工特征或静态全局特征。
"""
from __future__ import annotations

import numpy as np
from typing import List, Optional, Any, Dict

from . import graph

try:
    import torch
    from torch_geometric.data import Data
except ImportError as e:
    torch = None
    Data = None
    _import_err = e


def _channel_pos_to_xyz3(channel_pos: np.ndarray, n_channels: int) -> np.ndarray:
    cp = np.asarray(channel_pos, dtype=np.float32).reshape(n_channels, -1)
    if cp.shape[1] >= 3:
        return cp[:, :3].copy()
    out = np.zeros((n_channels, 3), dtype=np.float32)
    out[:, : cp.shape[1]] = cp
    return out


def build_recording_data_list(
    window_signals: List[np.ndarray],
    window_labels: np.ndarray,
    sfreq: float,
    channel_pos: np.ndarray,
    x_raw_channel_scale: np.ndarray,
    *,
    edge_method: str = "knn",
    edge_k: int = 6,
    edge_max_dist: Optional[float] = None,
    x_raw_downsample: Optional[int] = None,
    y_bad_channel: np.ndarray,
    node_valid: Optional[np.ndarray] = None,
) -> List[Data]:
    """
    一条记录构建为 [Data_window_1, Data_window_2, ...]。

    window_signals: list of (n_channels, T) 每个 1s 窗口的原始数据。
    window_labels: (n_windows,) 二值 0/1 窗口级伪迹标签。
    channel_pos: (n_channels, 2 或 3) 通道位置，用于建图。
    x_raw_downsample: 若设且 >1，对 x_raw 沿时间步下采样以控制计算量。
    y_bad_channel: (n_channels,) 坏道标签 0/1，与节点顺序一致。
    x_raw_channel_scale: (n_channels,) 每通道幅值系数（mag / grad 等），必填。
    node_valid: (n_channels,) 可选，1=参与 GNN/池化，0=图内 mask（仍保留节点与 KNN 拓扑）；缺省全 1，与旧版行为一致。
    """
    if torch is None or Data is None:
        raise RuntimeError("需要 torch 与 torch_geometric")
    n_windows = len(window_signals)
    assert len(window_labels) == n_windows
    if sfreq <= 0:
        raise ValueError("sfreq 必须为正")
    n_channels = window_signals[0].shape[0]
    x_raw_channel_scale = np.asarray(x_raw_channel_scale, dtype=np.float64).reshape(-1)
    if x_raw_channel_scale.shape[0] != n_channels:
        raise ValueError(
            f"x_raw_channel_scale 长度 {x_raw_channel_scale.shape[0]} 与通道数 {n_channels} 不一致"
        )
    sensor_type = np.where(x_raw_channel_scale >= 1e14, 1, 2).astype(np.int64)
    y_bad_arr = np.asarray(y_bad_channel, dtype=np.int64).reshape(-1)
    if y_bad_arr.shape[0] != n_channels:
        raise ValueError(
            f"y_bad_channel 长度 {y_bad_arr.shape[0]} 与通道数 {n_channels} 不一致"
        )
    y_bad_t = torch.from_numpy(y_bad_arr).long()

    if node_valid is not None:
        nv = np.asarray(node_valid, dtype=np.int64).reshape(-1)
        if nv.shape[0] != n_channels:
            raise ValueError(
                f"node_valid 长度 {nv.shape[0]} 与通道数 {n_channels} 不一致"
            )
        node_valid_t = torch.from_numpy(nv).float()
    else:
        node_valid_t = torch.ones(n_channels, dtype=torch.float32)

    edge_index = graph.build_edge_index(
        channel_pos, method=edge_method, k=edge_k, max_dist=edge_max_dist
    )
    edge_t = torch.from_numpy(edge_index).long()

    out: List[Data] = []
    for t in range(n_windows):
        raw_signal = window_signals[t].astype(np.float32)
        raw_signal = np.nan_to_num(raw_signal, nan=0.0, posinf=0.0, neginf=0.0)
        if x_raw_downsample and x_raw_downsample > 1:
            raw_signal = raw_signal[:, ::x_raw_downsample]

        y_art = torch.tensor([int(window_labels[t])], dtype=torch.long)
        kwargs: Dict[str, Any] = {
            "x_raw": torch.from_numpy(raw_signal).float(),
            "edge_index": edge_t,
            "y_artifact": y_art,
            "num_nodes": n_channels,
            "y_bad_channel": y_bad_t,
            "x_raw_scale": torch.from_numpy(x_raw_channel_scale.astype(np.float32)),
            "sensor_type": torch.from_numpy(sensor_type),
            "node_valid": node_valid_t,
            # BrainOmni：每通道位置 xyz；(n,2) 时补第三维 0
            "meg_ch_pos": torch.from_numpy(
                _channel_pos_to_xyz3(np.asarray(channel_pos, dtype=np.float32), n_channels)
            ),
        }
        out.append(Data(**kwargs))
    return out
