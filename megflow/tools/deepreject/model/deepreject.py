# -*- coding: utf-8 -*-
"""
DeepReject: 可学习通道编码 + GNN + Transformer + 窗口级伪迹/可选坏道头。
节点输入仅来自 x_raw 经 PerChannelTemporalEncoder，计算通道特征。
"""
from __future__ import annotations

import math
import torch
import torch.nn as nn
from typing import List, Literal, Optional, Tuple

from torch_geometric.data import Batch
from torch_geometric.nn import (
    ChebConv,
    GATv2Conv,
    GCNConv,
    GINConv,
    GlobalAttention,
    SAGEConv,
    TransformerConv,
    global_add_pool,
    global_max_pool,
)
from torch_geometric.utils import softmax as pyg_softmax

WindowNormMode = Literal["none", "demean", "standardize"]
EncoderNormMode = Literal["group", "batch", "instance"]
GnnConvType = Literal["gcn", "gatv2", "sage", "transformer", "gin", "cheb"]
GraphPoolType = Literal["mean", "max", "mean_max", "attention"]
TemporalEncoderVersion = Literal["v1", "multiscale"]
TemporalContextMode = Literal["causal", "bidirectional"]
TemporalPosEncodingMode = Literal["none", "sinusoidal"]
TemporalDiffBranchMode = Literal["none", "light", "full"]
TemporalInputMode = Literal["raw", "diff", "raw_diff"]
TemporalCheckpointMode = Literal["none", "raw", "diff", "both"]
LocalMilPoolMode = Literal["topk_mean", "logsumexp"]

from .encoder import LightDiffTemporalEncoder, MultiScalePerChannelTemporalEncoder, PerChannelTemporalEncoder


class ArtifactMetricHead(nn.Module):
    """
    fusion→隐层→``z_pre``→``z = normalize(z_pre)``→logits（CE 与 center/margin 均用单位球上的 z，几何一致、实现简单）。
    含可学习 ``normal_center``（无约束 c）；训练时 center/margin 使用 ``ĉ = c/||c||`` 与 z 同处单位球。
    与旧版 ``nn.Sequential`` 伪迹头 state_dict 键名不同；仅 ``pre_logit_embed_dim>0`` 时使用。
    """

    def __init__(
        self,
        fusion_dim: int,
        prediction_hidden_dim: int,
        predictor_dropout_rate: float,
        num_window_classes: int,
        pre_logit_embed_dim: int,
    ):
        super().__init__()
        d = int(pre_logit_embed_dim)
        if d <= 0:
            raise ValueError(f"pre_logit_embed_dim 须 > 0，收到 {pre_logit_embed_dim!r}")
        self.pre_logit_embed_dim = d
        self.fusion_to_hidden = nn.Sequential(
            nn.Linear(fusion_dim, prediction_hidden_dim),
            nn.ReLU(),
            nn.Dropout(predictor_dropout_rate),
        )
        self.embed_proj = nn.Linear(prediction_hidden_dim, d)
        self.logit_head = nn.Linear(d, num_window_classes)
        # 随机单位向量初始化，避免 c=0 且 z 在单位球上时 center 目标与 CE 几何不一致；加载旧 ckpt 仍可为零（损失内会处理）
        _c0 = torch.randn(d, dtype=torch.float32)
        _c0 = _c0 / _c0.norm(p=2).clamp(min=1e-12)
        self.normal_center = nn.Parameter(_c0.clone())

    @property
    def uses_pre_logit_embedding(self) -> bool:
        return True

    def forward(self, fusion: torch.Tensor, return_z: bool = False):
        h = self.fusion_to_hidden(fusion)
        z_pre = self.embed_proj(h)
        z = torch.nn.functional.normalize(z_pre, dim=-1, eps=1e-12)
        logits = self.logit_head(z)
        if return_z:
            return logits, z
        return logits


class _DepthwiseTCNBlock(nn.Module):
    """Small residual TCN block that preserves the feature dimension."""

    def __init__(self, dim: int, kernel_size: int, dilation: int, dropout: float):
        super().__init__()
        pad = (int(kernel_size) // 2) * int(dilation)
        self.net = nn.Sequential(
            nn.Conv1d(
                dim,
                dim,
                kernel_size=int(kernel_size),
                padding=pad,
                dilation=int(dilation),
                groups=dim,
            ),
            nn.Conv1d(dim, dim, kernel_size=1),
            nn.GELU(),
            nn.Dropout(float(dropout)),
        )
        self.norm = nn.LayerNorm(dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        y = self.net(x)
        if y.size(-1) != x.size(-1):
            y = y[..., : x.size(-1)]
        out = x + y
        return self.norm(out.transpose(1, 2)).transpose(1, 2)


class TemporalResidualTCN(nn.Module):
    """Linear-time temporal refinement used by optional sequence heads."""

    def __init__(self, dim: int, num_layers: int = 2, kernel_size: int = 3, dropout: float = 0.1):
        super().__init__()
        self.layers = nn.ModuleList(
            [
                _DepthwiseTCNBlock(
                    dim=dim,
                    kernel_size=int(kernel_size),
                    dilation=2**i,
                    dropout=float(dropout),
                )
                for i in range(max(int(num_layers), 1))
            ]
        )

    def forward_bdl(self, y: torch.Tensor) -> torch.Tensor:
        # y: (B, D, L)
        for layer in self.layers:
            y = layer(y)
        return y

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (L, D)
        y = self.forward_bdl(x.transpose(0, 1).unsqueeze(0))
        return y.squeeze(0).transpose(0, 1)


class DeepReject(nn.Module):
    """
    混合 GNN-Transformer 窗口级伪迹检测：
    可学习通道编码 -> GNN -> 图级池化 -> Transformer -> 伪迹头；可选坏道头。
    若 ``pre_logit_embed_dim>0``，伪迹头为 fusion→隐层→z_pre→L2 得 z→logits；z 同时用于 center/margin（与 train 中 return_pre_logit_embedding 一致）。
    """

    def __init__(
        self,
        learned_feat_dim: int = 32,
        gnn_hidden_dim: int = 64,
        gnn_num_layers: int = 2,
        gnn_dropout_rate: float = 0.2,
        gnn_conv_type: GnnConvType = "gcn",
        gnn_conv_heads: int = 4,
        gnn_sage_aggr: str = "mean",
        gnn_cheb_K: int = 3,
        graph_pool: GraphPoolType = "mean",
        transformer_num_layers: int = 2,
        num_attention_heads: int = 4,
        transformer_ff_dim: Optional[int] = None,
        transformer_dropout_rate: float = 0.1,
        prediction_hidden_dim: int = 64,
        predictor_dropout_rate: float = 0.2,
        num_window_classes: int = 2,
        pre_logit_embed_dim: Optional[int] = None,
        use_bad_channel_head: bool = True,
        bad_channel_hidden_dim: int = 32,
        encoder_chunk_size: Optional[int] = 512,
        window_norm: WindowNormMode = "none",
        encoder_norm: EncoderNormMode = "group",
        temporal_encoder_version: TemporalEncoderVersion = "v1",
        multiscale_pool: str = "mean",
        temporal_input_mode: TemporalInputMode = "raw",
        temporal_diff_branch: TemporalDiffBranchMode = "none",
        diff_branch_feat_dim: int = 0,
        use_temporal_encoder_checkpoint: bool = False,
        temporal_encoder_checkpoint_mode: TemporalCheckpointMode = "none",
        use_raw_correction_gate: bool = False,
        raw_correction_hidden_dim: int = 8,
        raw_correction_feat_dim: int = 16,
        raw_correction_max_scale: float = 0.2,
        raw_correction_max_shift: float = 0.2,
        use_channel_metadata: bool = False,
        sensor_type_embed_dim: int = 8,
        position_embed_dim: int = 16,
        temporal_context: TemporalContextMode = "causal",
        temporal_pos_encoding: TemporalPosEncodingMode = "none",
        use_sequence_tcn_head: bool = False,
        sequence_tcn_layers: int = 2,
        sequence_tcn_kernel_size: int = 3,
        use_local_mil_artifact_branch: bool = False,
        local_mil_pool: LocalMilPoolMode = "topk_mean",
        local_mil_topk: int = 8,
        local_mil_gate_init: float = 0.05,
        use_cross_task_gating: bool = False,
        cross_task_gate_init: float = 0.05,
        cross_task_max_gate: float = 0.2,
        cross_task_topk: int = 8,
        detach_cross_task_summary: bool = False,
        use_bad_channel_trajectory_tcn: bool = False,
        bad_channel_tcn_layers: int = 2,
        bad_channel_tcn_kernel_size: int = 3,
    ):
        super().__init__()
        self.use_bad_channel_head = use_bad_channel_head
        self._encoder_chunk_size = encoder_chunk_size
        if window_norm not in ("none", "demean", "standardize"):
            raise ValueError(f"window_norm 须为 none|demean|standardize，收到: {window_norm!r}")
        self.window_norm: WindowNormMode = window_norm
        if encoder_norm not in ("group", "batch", "instance"):
            raise ValueError(f"encoder_norm 须为 group|batch|instance，收到: {encoder_norm!r}")
        self.encoder_norm: EncoderNormMode = encoder_norm
        if temporal_encoder_version not in ("v1", "multiscale"):
            raise ValueError(f"temporal_encoder_version 须为 v1|multiscale，收到: {temporal_encoder_version!r}")
        self.temporal_encoder_version: TemporalEncoderVersion = temporal_encoder_version  # type: ignore[assignment]
        if temporal_input_mode not in ("raw", "diff", "raw_diff"):
            raise ValueError(f"temporal_input_mode 须为 raw|diff|raw_diff，收到: {temporal_input_mode!r}")
        self.temporal_input_mode: TemporalInputMode = temporal_input_mode  # type: ignore[assignment]
        if temporal_diff_branch not in ("none", "light", "full"):
            raise ValueError(f"temporal_diff_branch 须为 none|light|full，收到: {temporal_diff_branch!r}")
        self.temporal_diff_branch: TemporalDiffBranchMode = temporal_diff_branch  # type: ignore[assignment]
        if temporal_encoder_checkpoint_mode not in ("none", "raw", "diff", "both"):
            raise ValueError(
                "temporal_encoder_checkpoint_mode 须为 none|raw|diff|both，"
                f"收到: {temporal_encoder_checkpoint_mode!r}"
            )
        if use_temporal_encoder_checkpoint and temporal_encoder_checkpoint_mode == "none":
            temporal_encoder_checkpoint_mode = "raw"
        self.temporal_encoder_checkpoint_mode: TemporalCheckpointMode = temporal_encoder_checkpoint_mode  # type: ignore[assignment]
        self.use_temporal_encoder_checkpoint = self.temporal_encoder_checkpoint_mode != "none"
        if temporal_context not in ("causal", "bidirectional"):
            raise ValueError(f"temporal_context 须为 causal|bidirectional，收到: {temporal_context!r}")
        self.temporal_context: TemporalContextMode = temporal_context  # type: ignore[assignment]
        if temporal_pos_encoding not in ("none", "sinusoidal"):
            raise ValueError(f"temporal_pos_encoding 须为 none|sinusoidal，收到: {temporal_pos_encoding!r}")
        self.temporal_pos_encoding: TemporalPosEncodingMode = temporal_pos_encoding  # type: ignore[assignment]
        self.use_channel_metadata = bool(use_channel_metadata)
        self.use_sequence_tcn_head = bool(use_sequence_tcn_head)
        self.use_bad_channel_trajectory_tcn = bool(use_bad_channel_trajectory_tcn)
        self.use_raw_correction_gate = bool(use_raw_correction_gate)
        self.raw_correction_max_scale = max(float(raw_correction_max_scale), 0.0)
        self.raw_correction_max_shift = max(float(raw_correction_max_shift), 0.0)
        self.use_local_mil_artifact_branch = bool(use_local_mil_artifact_branch)
        if local_mil_pool not in ("topk_mean", "logsumexp"):
            raise ValueError(f"local_mil_pool 须为 topk_mean|logsumexp，收到: {local_mil_pool!r}")
        self.local_mil_pool: LocalMilPoolMode = local_mil_pool  # type: ignore[assignment]
        self.local_mil_topk = max(int(local_mil_topk), 1)
        self.use_cross_task_gating = bool(use_cross_task_gating)
        self.cross_task_max_gate = max(float(cross_task_max_gate), 0.0)
        self.cross_task_topk = max(int(cross_task_topk), 1)
        self.detach_cross_task_summary = bool(detach_cross_task_summary)
        self._last_bad_pre_logits_list: Optional[List[torch.Tensor]] = None

        valid_conv = ("gcn", "gatv2", "sage", "transformer", "gin", "cheb")
        if gnn_conv_type not in valid_conv:
            raise ValueError(f"gnn_conv_type 须为 {valid_conv}，收到: {gnn_conv_type!r}")
        self.gnn_conv_type: GnnConvType = gnn_conv_type  # type: ignore[assignment]
        self.gnn_conv_heads = int(gnn_conv_heads)
        self.gnn_sage_aggr = gnn_sage_aggr
        self.gnn_cheb_K = int(gnn_cheb_K)

        if graph_pool not in ("mean", "max", "mean_max", "attention"):
            raise ValueError(
                f"graph_pool 须为 mean|max|mean_max|attention，收到: {graph_pool!r}"
            )
        self.graph_pool: GraphPoolType = graph_pool  # type: ignore[assignment]

        if gnn_conv_type in ("gatv2", "transformer") and gnn_hidden_dim % self.gnn_conv_heads != 0:
            raise ValueError(
                f"gnn_hidden_dim ({gnn_hidden_dim}) 须能被 gnn_conv_heads ({self.gnn_conv_heads}) 整除"
                f"（{gnn_conv_type} 多头拼接后维数等于 gnn_hidden_dim）"
            )
        if gnn_cheb_K < 1:
            raise ValueError(f"gnn_cheb_K 须 >= 1，收到 {gnn_cheb_K}")

        node_feat_dim = learned_feat_dim

        temporal_in_channels = 2 if self.temporal_input_mode == "raw_diff" else 1
        if temporal_encoder_version == "multiscale":
            self.learned_encoder = MultiScalePerChannelTemporalEncoder(
                in_channels=temporal_in_channels,
                hidden_channels=24,
                learned_feat_dim=learned_feat_dim,
                multiscale_pool=multiscale_pool,
                encoder_norm=encoder_norm,
            )
        else:
            self.learned_encoder = PerChannelTemporalEncoder(
                in_channels=temporal_in_channels,
                hidden_channels=32,
                learned_feat_dim=learned_feat_dim,
                encoder_norm=encoder_norm,
            )
        self.diff_encoder: Optional[nn.Module] = None
        self.diff_feature_fusion: Optional[nn.Module] = None
        self.diff_branch_feat_dim = 0
        if self.temporal_diff_branch != "none":
            if int(diff_branch_feat_dim) > 0:
                diff_dim = int(diff_branch_feat_dim)
            elif self.temporal_diff_branch == "full":
                diff_dim = int(learned_feat_dim)
            else:
                diff_dim = max(int(learned_feat_dim) // 2, 8)
            self.diff_branch_feat_dim = diff_dim
            if self.temporal_diff_branch == "full":
                self.diff_encoder = PerChannelTemporalEncoder(
                    in_channels=1,
                    hidden_channels=32,
                    learned_feat_dim=diff_dim,
                    encoder_norm=encoder_norm,
                )
            else:
                self.diff_encoder = LightDiffTemporalEncoder(
                    in_channels=1,
                    hidden_channels=max(diff_dim, 8),
                    learned_feat_dim=diff_dim,
                    encoder_norm=encoder_norm,
                )
            self.diff_feature_fusion = nn.Sequential(
                nn.LayerNorm(int(learned_feat_dim) + diff_dim),
                nn.Linear(int(learned_feat_dim) + diff_dim, int(learned_feat_dim)),
            )
        self.raw_correction_encoder: Optional[nn.Module] = None
        self.raw_correction_scale: Optional[nn.Module] = None
        self.raw_correction_shift: Optional[nn.Module] = None
        self.raw_correction_feat_dim = 0
        if self.use_raw_correction_gate:
            corr_dim = max(int(raw_correction_feat_dim), 1)
            self.raw_correction_feat_dim = corr_dim
            self.raw_correction_encoder = LightDiffTemporalEncoder(
                in_channels=1,
                hidden_channels=max(int(raw_correction_hidden_dim), 1),
                learned_feat_dim=corr_dim,
                encoder_norm=encoder_norm,
            )
            self.raw_correction_scale = nn.Sequential(
                nn.LayerNorm(corr_dim),
                nn.Linear(corr_dim, int(learned_feat_dim)),
            )
            self.raw_correction_shift = nn.Sequential(
                nn.LayerNorm(corr_dim),
                nn.Linear(corr_dim, int(learned_feat_dim)),
            )
            assert isinstance(self.raw_correction_scale[-1], nn.Linear)
            assert isinstance(self.raw_correction_shift[-1], nn.Linear)
            nn.init.zeros_(self.raw_correction_scale[-1].weight)
            nn.init.zeros_(self.raw_correction_scale[-1].bias)
            nn.init.zeros_(self.raw_correction_shift[-1].weight)
            nn.init.zeros_(self.raw_correction_shift[-1].bias)

        self.sensor_type_embedding: Optional[nn.Embedding] = None
        self.position_mlp: Optional[nn.Module] = None
        self.metadata_proj: Optional[nn.Linear] = None
        if self.use_channel_metadata:
            se_dim = max(int(sensor_type_embed_dim), 1)
            pe_dim = max(int(position_embed_dim), 1)
            self.sensor_type_embedding = nn.Embedding(3, se_dim)
            self.position_mlp = nn.Sequential(
                nn.Linear(3, pe_dim),
                nn.GELU(),
                nn.Linear(pe_dim, pe_dim),
            )
            self.metadata_proj = nn.Linear(se_dim + pe_dim, learned_feat_dim)

        self.gnn_convs = nn.ModuleList()
        self.gnn_convs.append(self._make_gnn_conv(node_feat_dim, gnn_hidden_dim))
        for _ in range(gnn_num_layers - 1):
            self.gnn_convs.append(self._make_gnn_conv(gnn_hidden_dim, gnn_hidden_dim))
        self.gnn_dropout = nn.Dropout(gnn_dropout_rate)

        self.pool_reduce: Optional[nn.Linear] = None
        self.graph_pool_attn: Optional[GlobalAttention] = None
        if graph_pool == "mean_max":
            self.pool_reduce = nn.Linear(2 * gnn_hidden_dim, gnn_hidden_dim)
        elif graph_pool == "attention":
            gate_h = max(gnn_hidden_dim // 2, 1)
            gate_nn = nn.Sequential(
                nn.Linear(gnn_hidden_dim, gate_h),
                nn.Tanh(),
                nn.Linear(gate_h, 1),
            )
            self.graph_pool_attn = GlobalAttention(gate_nn)

        ff_dim = transformer_ff_dim or max(gnn_hidden_dim * 4, 256)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=gnn_hidden_dim,
            nhead=num_attention_heads,
            dim_feedforward=ff_dim,
            dropout=transformer_dropout_rate,
            activation="relu",
            batch_first=True,
            norm_first=False,
        )
        self.transformer_encoder = nn.TransformerEncoder(encoder_layer, num_layers=transformer_num_layers)

        fusion_dim = 2 * gnn_hidden_dim
        self.bad_to_artifact_mlp: Optional[nn.Module] = None
        self.artifact_to_bad_mlp: Optional[nn.Module] = None
        self.cross_task_alpha_raw: Optional[nn.Parameter] = None
        self.cross_task_beta_raw: Optional[nn.Parameter] = None
        if self.use_cross_task_gating:
            self.bad_to_artifact_mlp = nn.Sequential(
                nn.Linear(3, max(fusion_dim // 4, 8)),
                nn.GELU(),
                nn.Linear(max(fusion_dim // 4, 8), fusion_dim),
            )
            self.artifact_to_bad_mlp = nn.Sequential(
                nn.Linear(2, max(gnn_hidden_dim // 4, 8)),
                nn.GELU(),
                nn.Linear(max(gnn_hidden_dim // 4, 8), gnn_hidden_dim),
            )
            init = float(cross_task_gate_init)
            max_gate = max(float(cross_task_max_gate), 1e-4)
            init = min(max(init, 1e-6), max_gate - 1e-6)
            raw = math.log(init / (max_gate - init))
            self.cross_task_alpha_raw = nn.Parameter(torch.tensor(raw, dtype=torch.float32))
            self.cross_task_beta_raw = nn.Parameter(torch.tensor(raw, dtype=torch.float32))

        self.sequence_tcn: Optional[TemporalResidualTCN] = None
        if self.use_sequence_tcn_head:
            self.sequence_tcn = TemporalResidualTCN(
                dim=fusion_dim,
                num_layers=sequence_tcn_layers,
                kernel_size=sequence_tcn_kernel_size,
                dropout=predictor_dropout_rate,
            )
        ped: Optional[int] = None
        if pre_logit_embed_dim is not None and int(pre_logit_embed_dim) > 0:
            ped = int(pre_logit_embed_dim)
        self._artifact_metric_mode = ped is not None
        if self._artifact_metric_mode:
            assert ped is not None
            self.artifact_predictor = ArtifactMetricHead(
                fusion_dim=fusion_dim,
                prediction_hidden_dim=prediction_hidden_dim,
                predictor_dropout_rate=predictor_dropout_rate,
                num_window_classes=num_window_classes,
                pre_logit_embed_dim=ped,
            )
        else:
            self.artifact_predictor = nn.Sequential(
                nn.Linear(fusion_dim, prediction_hidden_dim),
                nn.ReLU(),
                nn.Dropout(predictor_dropout_rate),
                nn.Linear(prediction_hidden_dim, num_window_classes),
            )

        self.local_artifact_head: Optional[nn.Module] = None
        self.local_mil_gamma: Optional[nn.Parameter] = None
        if self.use_local_mil_artifact_branch:
            self.local_artifact_head = nn.Sequential(
                nn.LayerNorm(gnn_hidden_dim),
                nn.Linear(gnn_hidden_dim, 1),
            )
            self.local_mil_gamma = nn.Parameter(torch.tensor(float(local_mil_gate_init), dtype=torch.float32))

        if use_bad_channel_head:
            self.bad_channel_tcn: Optional[TemporalResidualTCN] = None
            if self.use_bad_channel_trajectory_tcn:
                self.bad_channel_tcn = TemporalResidualTCN(
                    dim=gnn_hidden_dim,
                    num_layers=bad_channel_tcn_layers,
                    kernel_size=bad_channel_tcn_kernel_size,
                    dropout=0.1,
                )
            self.bad_channel_pre_head: Optional[nn.Module] = None
            if self.use_cross_task_gating:
                self.bad_channel_pre_head = nn.Sequential(
                    nn.Linear(gnn_hidden_dim, bad_channel_hidden_dim),
                    nn.ReLU(),
                    nn.Dropout(0.1),
                    nn.Linear(bad_channel_hidden_dim, 2),
                )
            self.bad_channel_head = nn.Sequential(
                nn.Linear(gnn_hidden_dim, bad_channel_hidden_dim),
                nn.ReLU(),
                nn.Dropout(0.1),
                nn.Linear(bad_channel_hidden_dim, 2),
            )
        else:
            self.bad_channel_tcn = None
            self.bad_channel_pre_head = None
            self.bad_channel_head = None

        self.gnn_hidden_dim = gnn_hidden_dim
        self._causal_mask_cache: Optional[torch.Tensor] = None

    def _make_gnn_conv(self, in_ch: int, out_ch: int) -> nn.Module:
        t = self.gnn_conv_type
        h = self.gnn_conv_heads
        if t == "gcn":
            return GCNConv(in_ch, out_ch)
        if t == "gatv2":
            return GATv2Conv(
                in_ch,
                out_ch // h,
                heads=h,
                concat=True,
                dropout=0.0,
                add_self_loops=True,
            )
        if t == "sage":
            return SAGEConv(in_ch, out_ch, aggr=self.gnn_sage_aggr)
        if t == "transformer":
            return TransformerConv(
                in_ch,
                out_ch // h,
                heads=h,
                concat=True,
                dropout=0.0,
                beta=False,
            )
        if t == "gin":
            mlp = nn.Sequential(
                nn.Linear(in_ch, out_ch),
                nn.ReLU(),
                nn.Linear(out_ch, out_ch),
            )
            return GINConv(mlp, train_eps=True)
        if t == "cheb":
            return ChebConv(in_ch, out_ch, K=self.gnn_cheb_K, normalization="sym")
        raise RuntimeError(f"未知 gnn_conv_type: {t}")

    @staticmethod
    def _node_valid_weight(batch: Batch, device: torch.device, dtype: torch.dtype) -> torch.Tensor:
        """每节点 0/1；无 node_valid 时全 1，与旧 checkpoint 及旧数据兼容。"""
        if hasattr(batch, "node_valid") and batch.node_valid is not None:
            return batch.node_valid.to(device=device, dtype=dtype).reshape(-1).clamp(0.0, 1.0)
        n = int(batch.num_nodes) if batch.num_nodes is not None else int(batch.x_raw.size(0))
        return torch.ones(n, device=device, dtype=dtype)

    @staticmethod
    def _mask_edge_index(edge_index: torch.Tensor, w: torch.Tensor) -> torch.Tensor:
        row, col = edge_index
        keep = (w[row] > 0.5) & (w[col] > 0.5)
        return edge_index[:, keep]

    def _pool_windows_masked(
        self, x: torch.Tensor, node_batch_idx: torch.Tensor, w: torch.Tensor
    ) -> torch.Tensor:
        """节点级 x -> 每窗口（子图）一条 gnn_hidden_dim；w=0 的节点不参与池化（与旧版 w 全 1 时等价）。"""
        w1 = w.reshape(-1, 1)
        sum_w = global_add_pool(w1, node_batch_idx)
        if self.graph_pool == "mean":
            num = global_add_pool(x * w1, node_batch_idx)
            denom = sum_w.clamp(min=1e-6)
            out = num / denom
            return torch.where(sum_w > 0, out, torch.zeros_like(out))
        if self.graph_pool == "max":
            neg = torch.finfo(x.dtype).min
            xm = x.clone()
            xm = xm.masked_fill((w < 0.5).unsqueeze(-1), neg)
            out = global_max_pool(xm, node_batch_idx)
            sw = global_add_pool(w1, node_batch_idx)
            return torch.where(sw > 0, out, torch.zeros_like(out))
        if self.graph_pool == "mean_max":
            assert self.pool_reduce is not None
            xm_num = global_add_pool(x * w1, node_batch_idx)
            xm = xm_num / sum_w.clamp(min=1e-6)
            xm = torch.where(sum_w > 0, xm, torch.zeros_like(xm))
            neg = torch.finfo(x.dtype).min
            xa_in = x.clone()
            xa_in = xa_in.masked_fill((w < 0.5).unsqueeze(-1), neg)
            xa = global_max_pool(xa_in, node_batch_idx)
            sw = global_add_pool(w1, node_batch_idx)
            xa = torch.where(sw > 0, xa, torch.zeros_like(xa))
            return self.pool_reduce(torch.cat([xm, xa], dim=-1))
        if self.graph_pool == "attention":
            assert self.graph_pool_attn is not None
            gate = self.graph_pool_attn.gate_nn(x)
            inv = w < 0.5
            gate = gate.masked_fill(inv.unsqueeze(-1), float("-inf"))
            alpha = pyg_softmax(gate, node_batch_idx, dim=0)
            alpha = torch.nan_to_num(alpha, nan=0.0, posinf=0.0, neginf=0.0)
            out = global_add_pool(alpha * x, node_batch_idx)
            sw = global_add_pool(w1, node_batch_idx).view(-1)
            return torch.where(sw.unsqueeze(-1) > 0, out, torch.zeros_like(out))
        raise RuntimeError(f"未知 graph_pool: {self.graph_pool}")

    def _scaled_x_in_for_encoder(self, batch: Batch) -> torch.Tensor:
        if not hasattr(batch, "x_raw_scale") or batch.x_raw_scale is None:
            raise ValueError("Batch 需包含 x_raw_scale（每节点一系数，与 x_raw 同行对应）。")
        w = self._node_valid_weight(batch, batch.x_raw.device, batch.x_raw.dtype).view(-1, 1)
        x_raw = batch.x_raw
        if x_raw.dim() == 2:
            x_in = (x_raw * w).unsqueeze(1)
        else:
            x_in = x_raw * w.unsqueeze(-1)
        x_in = x_in * batch.x_raw_scale.view(-1, 1, 1).to(dtype=x_in.dtype)
        # 每个节点一行 (1, T)，沿时间维；均在 x_raw_scale 之后，train/推理一致
        if self.window_norm == "demean":
            x_in = x_in - x_in.mean(dim=-1, keepdim=True)
        elif self.window_norm == "standardize":
            mean = x_in.mean(dim=-1, keepdim=True)
            var = x_in.var(dim=-1, keepdim=True, unbiased=False).clamp_min(1e-12)
            x_in = (x_in - mean) / var.sqrt()
        return x_in

    def _encode_temporal_in_chunks(
        self,
        enc: nn.Module,
        x_in: torch.Tensor,
        *,
        use_checkpoint: bool = False,
    ) -> torch.Tensor:
        def _run(chunk: torch.Tensor) -> torch.Tensor:
            if use_checkpoint and self.training and torch.is_grad_enabled():
                from torch.utils.checkpoint import checkpoint

                return checkpoint(enc, chunk, use_reentrant=False)
            return enc(chunk)

        cs = self._encoder_chunk_size
        if cs is not None and cs > 0 and x_in.size(0) > cs:
            parts: List[torch.Tensor] = []
            for s in range(0, x_in.size(0), cs):
                parts.append(_run(x_in[s : s + cs]))
            return torch.cat(parts, dim=0)
        return _run(x_in)

    @staticmethod
    def _fixed_temporal_diff(x_in: torch.Tensor) -> torch.Tensor:
        """固定一阶差分，首点补 0，保持与 raw 输入相同长度。"""
        if x_in.size(-1) <= 1:
            return torch.zeros_like(x_in)
        dx = x_in[..., 1:] - x_in[..., :-1]
        pad0 = x_in.new_zeros((*x_in.shape[:-1], 1))
        return torch.cat([pad0, dx], dim=-1)

    def _learned_features_from_x_raw(self, batch: Batch) -> torch.Tensor:
        raw_x_in = self._scaled_x_in_for_encoder(batch)
        x_in = raw_x_in
        if self.temporal_input_mode == "diff":
            x_in = self._fixed_temporal_diff(x_in)
        elif self.temporal_input_mode == "raw_diff":
            x_in = torch.cat([x_in, self._fixed_temporal_diff(x_in)], dim=1)
        ckpt_raw = self.temporal_encoder_checkpoint_mode in ("raw", "both")
        raw_feat = self._encode_temporal_in_chunks(self.learned_encoder, x_in, use_checkpoint=ckpt_raw)
        if (
            self.raw_correction_encoder is not None
            and self.raw_correction_scale is not None
            and self.raw_correction_shift is not None
        ):
            corr = self._encode_temporal_in_chunks(self.raw_correction_encoder, raw_x_in, use_checkpoint=False)
            scale = torch.tanh(self.raw_correction_scale(corr)) * self.raw_correction_max_scale
            shift = torch.tanh(self.raw_correction_shift(corr)) * self.raw_correction_max_shift
            raw_feat = raw_feat * (1.0 + scale) + shift
        if self.diff_encoder is None or self.diff_feature_fusion is None:
            return raw_feat
        diff_in = self._fixed_temporal_diff(x_in)
        ckpt_diff = self.temporal_encoder_checkpoint_mode in ("diff", "both")
        diff_feat = self._encode_temporal_in_chunks(self.diff_encoder, diff_in, use_checkpoint=ckpt_diff)
        return self.diff_feature_fusion(torch.cat([raw_feat, diff_feat], dim=-1))

    @staticmethod
    def _sensor_type_ids_from_batch(batch: Batch) -> torch.Tensor:
        if hasattr(batch, "sensor_type") and batch.sensor_type is not None:
            return batch.sensor_type.reshape(-1).long().clamp(0, 2)
        if not hasattr(batch, "x_raw_scale") or batch.x_raw_scale is None:
            n = int(batch.num_nodes) if batch.num_nodes is not None else int(batch.x_raw.size(0))
            return torch.zeros(n, device=batch.x_raw.device, dtype=torch.long)
        scale = batch.x_raw_scale.reshape(-1).float()
        mag = scale >= 1e14
        return torch.where(
            mag,
            torch.ones_like(scale, dtype=torch.long),
            torch.full_like(scale, 2, dtype=torch.long),
        )

    @staticmethod
    def _normalized_node_pos3(batch: Batch) -> torch.Tensor:
        n = int(batch.num_nodes) if batch.num_nodes is not None else int(batch.x_raw.size(0))
        device = batch.x_raw.device
        dtype = batch.x_raw.dtype
        if not hasattr(batch, "meg_ch_pos") or batch.meg_ch_pos is None:
            return torch.zeros((n, 3), device=device, dtype=dtype)
        pos = batch.meg_ch_pos.to(device=device, dtype=dtype)
        if pos.dim() != 2:
            pos = pos.reshape(n, -1)
        if pos.size(1) < 3:
            pos = torch.cat([pos, pos.new_zeros((pos.size(0), 3 - pos.size(1)))], dim=1)
        pos = pos[:, :3]
        b = batch.batch
        ones = torch.ones((pos.size(0), 1), device=device, dtype=dtype)
        cnt = global_add_pool(ones, b).clamp(min=1.0)
        mean = global_add_pool(pos, b) / cnt
        centered = pos - mean[b]
        sq = (centered * centered).sum(dim=1, keepdim=True)
        scale = torch.sqrt(3.0 * global_add_pool(sq, b) / cnt).clamp(min=1e-8)
        return centered / scale[b]

    def _add_channel_metadata(self, x: torch.Tensor, batch: Batch) -> torch.Tensor:
        if not self.use_channel_metadata:
            return x
        assert self.sensor_type_embedding is not None
        assert self.position_mlp is not None
        assert self.metadata_proj is not None
        st = self._sensor_type_ids_from_batch(batch).to(device=x.device)
        pos = self._normalized_node_pos3(batch).to(device=x.device, dtype=x.dtype)
        meta = torch.cat([self.sensor_type_embedding(st), self.position_mlp(pos)], dim=-1)
        return x + self.metadata_proj(meta).to(dtype=x.dtype)

    def _get_causal_mask(self, L: int, device: torch.device) -> torch.Tensor:
        mask = torch.triu(torch.ones(L, L, device=device).bool(), diagonal=1)
        return mask

    @staticmethod
    def _sinusoidal_pos_encoding(L: int, dim: int, device: torch.device, dtype: torch.dtype) -> torch.Tensor:
        pos = torch.arange(L, device=device, dtype=torch.float32).unsqueeze(1)
        div = torch.exp(
            torch.arange(0, dim, 2, device=device, dtype=torch.float32)
            * (-math.log(10000.0) / max(dim, 1))
        )
        pe = torch.zeros((L, dim), device=device, dtype=torch.float32)
        pe[:, 0::2] = torch.sin(pos * div)
        if dim > 1:
            pe[:, 1::2] = torch.cos(pos * div[: pe[:, 1::2].shape[1]])
        return pe.to(dtype=dtype)

    def _cross_gate(self, raw: Optional[nn.Parameter]) -> torch.Tensor:
        if raw is None:
            return torch.tensor(0.0, device=next(self.parameters()).device)
        return float(self.cross_task_max_gate) * torch.sigmoid(raw)

    @staticmethod
    def _recording_slices(ptr: torch.Tensor, recording_lengths: List[int]) -> Optional[List[Tuple[int, int, int, int]]]:
        out: List[Tuple[int, int, int, int]] = []
        g0 = 0
        for Lr in recording_lengths:
            if Lr <= 0:
                out.append((g0, 0, int(ptr[g0].item()), int(ptr[g0].item())))
                continue
            counts = ptr[g0 + 1 : g0 + Lr + 1] - ptr[g0 : g0 + Lr]
            if bool((counts != counts[0]).any().item()):
                return None
            c = int(counts[0].item())
            start = int(ptr[g0].item())
            end = int(ptr[g0 + Lr].item())
            out.append((g0, c, start, end))
            g0 += Lr
        return out

    def _bad_features_from_trajectory(
        self,
        x: torch.Tensor,
        ptr: torch.Tensor,
        recording_lengths: List[int],
    ) -> Optional[List[torch.Tensor]]:
        slices = self._recording_slices(ptr, recording_lengths)
        if slices is None:
            return None
        out: List[torch.Tensor] = []
        for _g0, c, start, end in slices:
            if c <= 0:
                continue
            Lr = (end - start) // c
            seq = x[start:end].reshape(Lr, c, -1)
            if self.bad_channel_tcn is not None and self.use_bad_channel_trajectory_tcn:
                seq = self.bad_channel_tcn.forward_bdl(seq.permute(1, 2, 0)).permute(2, 0, 1)
            out.append(seq)
        return out

    def _bad_logits_from_feature_sequences(
        self, seqs: List[torch.Tensor], head: nn.Module
    ) -> List[torch.Tensor]:
        out: List[torch.Tensor] = []
        for seq in seqs:
            Lr, c, d = seq.shape
            logits = head(seq.reshape(Lr * c, d))
            out.extend(logits[j * c : (j + 1) * c] for j in range(Lr))
        return out

    def _bad_summary_from_logits(self, logits_list: List[torch.Tensor]) -> List[torch.Tensor]:
        out = []
        for logits in logits_list:
            p = torch.softmax(logits, dim=-1)[:, 1]
            k = min(self.cross_task_topk, int(p.numel()))
            topk_mean = p.topk(k).values.mean() if k > 0 else p.new_zeros(())
            out.append(torch.stack([p.mean(), p.max(), topk_mean], dim=0))
        return out

    def _local_mil_logits_for_recording(self, seq: torch.Tensor) -> Optional[torch.Tensor]:
        if self.local_artifact_head is None:
            return None
        Lr, c, d = seq.shape
        scores = self.local_artifact_head(seq.reshape(Lr * c, d)).reshape(Lr, c)
        if self.local_mil_pool == "logsumexp":
            pooled = torch.logsumexp(scores, dim=1) - math.log(max(c, 1))
        else:
            k = min(self.local_mil_topk, c)
            pooled = scores.topk(k, dim=1).values.mean(dim=1)
        return pooled

    def forward(
        self,
        batch: Batch,
        recording_lengths: Optional[List[int]] = None,
        return_bad_channel_logits: bool = False,
        return_pre_logit_embedding: bool = False,
    ) -> Tuple[List[torch.Tensor], Optional[List[torch.Tensor]], Optional[List[torch.Tensor]]]:
        """
        batch: PyG Batch，子图数为所有记录的所有窗口数之和；batch.batch 为节点到图索引。
        recording_lengths: 每条记录的窗口数 [L1, L2, ...]，若为 None 则视为单条记录。
        始终返回三元组 (artifact_logits_list, bad_channel_logits_list 或 None, pre_logit_z_list 或 None)。
        pre_logit_z_list: 仅当 return_pre_logit_embedding 且为度量头时
          为 list of (L_r, D)，每项为 **L2 归一后的 z**（与 CE logits 所用嵌入一致，并供 center/margin）。
        """
        return self._forward_from_batch(
            batch, recording_lengths, return_bad_channel_logits, return_pre_logit_embedding
        )

    def _forward_from_batch(
        self,
        batch: Batch,
        recording_lengths: Optional[List[int]],
        return_bad_channel_logits: bool,
        return_pre_logit_embedding: bool,
    ) -> Tuple[List[torch.Tensor], Optional[List[torch.Tensor]], Optional[List[torch.Tensor]]]:
        if not hasattr(batch, "x_raw") or batch.x_raw is None:
            raise ValueError("Batch 需包含 x_raw，由可学习编码器生成节点特征。")
        node_batch_idx = batch.batch
        ptr = getattr(batch, "ptr", None)
        if ptr is not None:
            # ptr.shape[0]-1 为 Python 侧元数据，避免 batch.max().item() 触发 GPU 同步
            n_graphs = int(ptr.shape[0]) - 1
        else:
            n_graphs = int(node_batch_idx.max().item()) + 1
        w = self._node_valid_weight(batch, batch.x_raw.device, batch.x_raw.dtype)
        edge_index = self._mask_edge_index(batch.edge_index, w)
        x = self._learned_features_from_x_raw(batch)
        x = self._add_channel_metadata(x, batch)

        for conv in self.gnn_convs:
            x = conv(x, edge_index)
            x = torch.relu(x)
            x = self.gnn_dropout(x)
            x = x * w.unsqueeze(1)

        window_embeddings = self._pool_windows_masked(x, node_batch_idx, w)
        if recording_lengths is None:
            recording_lengths = [window_embeddings.size(0)]

        self._last_bad_pre_logits_list = None
        seqs: Optional[List[torch.Tensor]] = None
        bad_pre_by_record: Optional[List[torch.Tensor]] = None
        ptr = getattr(batch, "ptr", None)
        if ptr is not None and (
            self.use_cross_task_gating
            or self.use_local_mil_artifact_branch
            or (return_bad_channel_logits and self.use_bad_channel_trajectory_tcn)
        ):
            seqs = self._bad_features_from_trajectory(x, ptr, recording_lengths)
        if self.use_cross_task_gating and seqs is not None and self.bad_channel_pre_head is not None:
            bad_pre_logits_list = self._bad_logits_from_feature_sequences(seqs, self.bad_channel_pre_head)
            self._last_bad_pre_logits_list = bad_pre_logits_list
            bad_summary_list = self._bad_summary_from_logits(bad_pre_logits_list)
            if self.detach_cross_task_summary:
                bad_summary_list = [s.detach() for s in bad_summary_list]
            bad_pre_by_record = []
            off = 0
            for Lr in recording_lengths:
                bad_pre_by_record.append(torch.stack(bad_summary_list[off : off + Lr], dim=0))
                off += Lr

        all_artifact: List[torch.Tensor] = []
        want_z = bool(return_pre_logit_embedding and self._artifact_metric_mode)
        all_z: Optional[List[torch.Tensor]] = [] if want_z else None
        offset = 0
        for rec_i, Lr in enumerate(recording_lengths):
            emb_r = window_embeddings[offset : offset + Lr]
            offset += Lr
            if self.temporal_pos_encoding == "sinusoidal":
                emb_r = emb_r + self._sinusoidal_pos_encoding(
                    Lr, emb_r.size(-1), emb_r.device, emb_r.dtype
                )
            causal = self._get_causal_mask(Lr, emb_r.device) if self.temporal_context == "causal" else None
            h_seq = emb_r.unsqueeze(0)
            temporal = self.transformer_encoder(h_seq, mask=causal).squeeze(0)
            fusion = torch.cat([emb_r, temporal], dim=-1)
            if self.sequence_tcn is not None:
                fusion = self.sequence_tcn(fusion)
            if (
                self.use_cross_task_gating
                and bad_pre_by_record is not None
                and self.bad_to_artifact_mlp is not None
                and self.cross_task_alpha_raw is not None
            ):
                fusion = fusion + self._cross_gate(self.cross_task_alpha_raw) * self.bad_to_artifact_mlp(
                    bad_pre_by_record[rec_i].to(device=fusion.device, dtype=fusion.dtype)
                )
            if want_z:
                logits_r, z_r = self.artifact_predictor(fusion, return_z=True)  # type: ignore[call-arg]
                assert all_z is not None
                all_z.append(z_r)
            elif self._artifact_metric_mode:
                logits_r = self.artifact_predictor(fusion, return_z=False)  # type: ignore[call-arg]
            else:
                logits_r = self.artifact_predictor(fusion)
            if self.use_local_mil_artifact_branch and seqs is not None and rec_i < len(seqs):
                local = self._local_mil_logits_for_recording(seqs[rec_i])
                if local is not None and self.local_mil_gamma is not None:
                    delta = torch.zeros_like(logits_r)
                    delta[:, 1] = self.local_mil_gamma.to(device=logits_r.device, dtype=logits_r.dtype) * local.to(
                        device=logits_r.device, dtype=logits_r.dtype
                    )
                    logits_r = logits_r + delta
            all_artifact.append(logits_r)

        out_bad: Optional[List[torch.Tensor]] = None
        if return_bad_channel_logits and self.bad_channel_head is not None:
            ptr = getattr(batch, "ptr", None)
            if seqs is not None:
                final_seqs = seqs
                if (
                    self.use_cross_task_gating
                    and self.artifact_to_bad_mlp is not None
                    and self.cross_task_beta_raw is not None
                ):
                    modded = []
                    for seq, logits_r in zip(seqs, all_artifact):
                        probs = torch.softmax(logits_r, dim=-1)
                        p_art = probs[:, 1]
                        entropy = -(probs * probs.clamp(min=1e-12).log()).sum(dim=-1)
                        art_summary = torch.stack([p_art, entropy], dim=-1)
                        if self.detach_cross_task_summary:
                            art_summary = art_summary.detach()
                        m = self.artifact_to_bad_mlp(art_summary.to(device=seq.device, dtype=seq.dtype))
                        gate = self._cross_gate(self.cross_task_beta_raw).to(device=seq.device, dtype=seq.dtype)
                        modded.append(seq + gate * m.unsqueeze(1))
                    final_seqs = modded
                out_bad = self._bad_logits_from_feature_sequences(final_seqs, self.bad_channel_head)
            if out_bad is None:
                node_logits = self.bad_channel_head(x)
            if out_bad is None and ptr is not None:
                out_bad = [node_logits[ptr[i] : ptr[i + 1]] for i in range(n_graphs)]
            elif out_bad is None:
                out_bad = [node_logits]
        z_out: Optional[List[torch.Tensor]] = all_z if want_z else None
        return all_artifact, out_bad, z_out  # 第三项无 z 时为 None，便于调用方统一解包
