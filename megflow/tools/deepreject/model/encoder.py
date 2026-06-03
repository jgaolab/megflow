# -*- coding: utf-8 -*-
"""可学习的通道级时序编码器：1D CNN 将 [T] 压成 [learned_feat_dim]。"""
from __future__ import annotations

import torch
import torch.nn as nn
from typing import Optional, Sequence


def _group_norm_num_groups(num_channels: int, preferred: int = 8) -> int:
    """取能整除 num_channels 的组数（优先 8），便于 GroupNorm。"""
    g = min(preferred, num_channels)
    while g > 1 and num_channels % g != 0:
        g -= 1
    return g


def _conv_norm_layer(num_channels: int, encoder_norm: str) -> nn.Module:
    n = encoder_norm.lower()
    if n == "group":
        return nn.GroupNorm(_group_norm_num_groups(num_channels), num_channels)
    if n == "batch":
        return nn.BatchNorm1d(num_channels)
    if n == "instance":
        # 每样本、每通道在时间维上归一；不累计 running 统计，eval 与 train 行为一致
        return nn.InstanceNorm1d(num_channels, affine=True, track_running_stats=False)
    raise ValueError(f"encoder_norm 须为 group|batch|instance，收到: {encoder_norm!r}")


class PerChannelTemporalEncoder(nn.Module):
    """
    对每个通道独立：1D CNN + 池化，输入 (C, T) -> 输出 (C, learned_feat_dim)。
    支持可变 T：通过 AdaptiveAvgPool1d(1) 得到固定长度。

    encoder_norm：group=按样本在「通道组×时间」上归一；batch=BatchNorm1d；
    instance=InstanceNorm1d（每样本每通道沿时间维，不依赖 batch 组成；可能削弱幅值线索，仅作消融）。
    """

    def __init__(
        self,
        in_channels: int = 1,
        hidden_channels: int = 16,
        learned_feat_dim: int = 16,
        kernel_sizes: Optional[list] = None,
        encoder_norm: str = "group",
    ):
        super().__init__()
        if encoder_norm.lower() not in ("group", "batch", "instance"):
            raise ValueError(f"encoder_norm 须为 group|batch|instance，收到: {encoder_norm!r}")
        self.encoder_norm = encoder_norm.lower()
        if kernel_sizes is None:
            kernel_sizes = [7, 5, 3]
        layers = []
        c_in = in_channels
        for k in kernel_sizes:
            layers += [
                nn.Conv1d(c_in, hidden_channels, k, padding=k // 2),
                _conv_norm_layer(hidden_channels, self.encoder_norm),
                nn.ReLU(inplace=True),
                nn.MaxPool1d(2),
            ]
            c_in = hidden_channels
        self.convs = nn.Sequential(*layers)
        self.pool = nn.AdaptiveAvgPool1d(1)
        self.proj = nn.Linear(hidden_channels, learned_feat_dim)
        self._learned_feat_dim = learned_feat_dim

    @property
    def learned_feat_dim(self) -> int:
        return self._learned_feat_dim

    def forward(self, x_raw: torch.Tensor) -> torch.Tensor:
        """
        x_raw: (N, C, T) 或 (C, T)。每个通道一行，即 N 为节点数、C=1、T 为时间点；
        若为 (C, T) 则 C 为通道数，需在外部保证与节点一致。
        输出: (N, learned_feat_dim) 或 (C, learned_feat_dim)。
        """
        if x_raw.dim() == 2:
            x_raw = x_raw.unsqueeze(1)
        h = self.convs(x_raw)
        h = self.pool(h).squeeze(-1)
        return self.proj(h)


class LightDiffTemporalEncoder(nn.Module):
    """
    轻量 diff 分支：输入固定差分后的 (N, 1, T)，输出较小的 diff embedding。

    它不替代主 raw encoder，只作为低成本辅助路径；full diff 分支则直接复用
    PerChannelTemporalEncoder。
    """

    def __init__(
        self,
        in_channels: int = 1,
        hidden_channels: int = 16,
        learned_feat_dim: int = 16,
        encoder_norm: str = "group",
    ):
        super().__init__()
        if encoder_norm.lower() not in ("group", "batch", "instance"):
            raise ValueError(f"encoder_norm 须为 group|batch|instance，收到: {encoder_norm!r}")
        self.encoder_norm = encoder_norm.lower()
        self.net = nn.Sequential(
            nn.Conv1d(in_channels, hidden_channels, kernel_size=5, padding=2),
            _conv_norm_layer(hidden_channels, self.encoder_norm),
            nn.GELU(),
            nn.MaxPool1d(2),
            nn.Conv1d(hidden_channels, hidden_channels, kernel_size=3, padding=1),
            _conv_norm_layer(hidden_channels, self.encoder_norm),
            nn.GELU(),
            nn.MaxPool1d(2),
        )
        self.pool = nn.AdaptiveAvgPool1d(1)
        self.proj = nn.Linear(hidden_channels, learned_feat_dim)
        self._learned_feat_dim = learned_feat_dim

    @property
    def learned_feat_dim(self) -> int:
        return self._learned_feat_dim

    def forward(self, x_raw: torch.Tensor) -> torch.Tensor:
        if x_raw.dim() == 2:
            x_raw = x_raw.unsqueeze(1)
        h = self.net(x_raw)
        h = self.pool(h).squeeze(-1)
        return self.proj(h)


class _DepthwiseSeparableBlock(nn.Module):
    """Lightweight temporal block used by the optional multiscale encoder."""

    def __init__(self, channels: int, kernel_size: int, dilation: int, encoder_norm: str):
        super().__init__()
        pad = (int(kernel_size) // 2) * int(dilation)
        self.net = nn.Sequential(
            nn.Conv1d(
                channels,
                channels,
                kernel_size=int(kernel_size),
                padding=pad,
                dilation=int(dilation),
                groups=channels,
            ),
            nn.Conv1d(channels, channels, kernel_size=1),
            _conv_norm_layer(channels, encoder_norm),
            nn.ReLU(inplace=True),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class MultiScalePerChannelTemporalEncoder(nn.Module):
    """
    Lightweight multiscale alternative to :class:`PerChannelTemporalEncoder`.

    It keeps the same input/output contract, so the downstream GNN shape remains
    unchanged. The old encoder is still the default; this module is only used
    when explicitly requested by ``temporal_encoder_version="multiscale"``.
    """

    def __init__(
        self,
        in_channels: int = 1,
        hidden_channels: int = 24,
        learned_feat_dim: int = 16,
        kernel_sizes: Optional[Sequence[int]] = None,
        dilations: Optional[Sequence[int]] = None,
        multiscale_pool: str = "mean",
        encoder_norm: str = "group",
    ):
        super().__init__()
        if encoder_norm.lower() not in ("group", "batch", "instance"):
            raise ValueError(f"encoder_norm 须为 group|batch|instance，收到: {encoder_norm!r}")
        if multiscale_pool not in ("mean", "mean_max_std"):
            raise ValueError(f"multiscale_pool 须为 mean|mean_max_std，收到: {multiscale_pool!r}")
        self.encoder_norm = encoder_norm.lower()
        self.multiscale_pool = multiscale_pool
        if kernel_sizes is None:
            kernel_sizes = (5, 9)
        if dilations is None:
            dilations = (1, 4)
        if len(kernel_sizes) != len(dilations):
            raise ValueError("kernel_sizes 与 dilations 长度必须一致")
        if len(kernel_sizes) < 1:
            raise ValueError("multiscale encoder 至少需要一个分支")

        self.stem = nn.Sequential(
            nn.Conv1d(in_channels, hidden_channels, kernel_size=7, padding=3),
            _conv_norm_layer(hidden_channels, self.encoder_norm),
            nn.ReLU(inplace=True),
        )
        self.branches = nn.ModuleList(
            [
                _DepthwiseSeparableBlock(
                    hidden_channels,
                    kernel_size=int(k),
                    dilation=int(d),
                    encoder_norm=self.encoder_norm,
                )
                for k, d in zip(kernel_sizes, dilations)
            ]
        )
        self.pool = nn.AdaptiveAvgPool1d(1)
        stats_per_branch = 3 if self.multiscale_pool == "mean_max_std" else 1
        self.proj = nn.Linear(hidden_channels * len(self.branches) * stats_per_branch, learned_feat_dim)
        self._learned_feat_dim = learned_feat_dim

    @property
    def learned_feat_dim(self) -> int:
        return self._learned_feat_dim

    def forward(self, x_raw: torch.Tensor) -> torch.Tensor:
        if x_raw.dim() == 2:
            x_raw = x_raw.unsqueeze(1)
        h0 = self.stem(x_raw)
        pooled = []
        for branch in self.branches:
            h = branch(h0)
            mean = self.pool(h).squeeze(-1)
            if self.multiscale_pool == "mean_max_std":
                maxv = h.amax(dim=-1)
                std = h.std(dim=-1, unbiased=False)
                pooled.append(torch.cat([mean, maxv, std], dim=-1))
            else:
                pooled.append(mean)
        return self.proj(torch.cat(pooled, dim=-1))
