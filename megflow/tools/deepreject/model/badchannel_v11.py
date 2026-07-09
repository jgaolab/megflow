# -*- coding: utf-8 -*-
"""V11 evidence-fusion bad-channel model.

V11 treats bad-channel detection as persistence-aware evidence fusion:
absolute channel abnormality, same-type relative outlier evidence, local
regional evidence, and sensor-group context are computed separately.  Group
context modulates channel evidence, but it is not allowed to become a standalone
channel-bad logit.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import torch
import torch.nn.functional as F
from torch import nn

from .badchannel_v10 import (
    EPS,
    SENSOR_GRAD,
    SENSOR_MAG,
    SENSOR_PAD,
    STAT_NAMES,
    V10InputMode,
    V10WindowNorm,
    _longest_and_burst_count,
    _normalise_windows,
    _ratio_time,
    _same_type_robust_z,
    _weighted_quantile_time,
    _weighted_std_time,
    _weighted_trimmed_mean_time,
    _window_stats,
)


V11InputMode = V10InputMode
V11WindowNorm = V10WindowNorm

EVIDENCE_NAMES: Tuple[str, ...] = ("abs", "rel", "reg")
POOL_NAMES: Tuple[str, ...] = (
    "q50",
    "q75",
    "q90",
    "q95",
    "trimmed_mean",
    "std",
    "ratio_gt",
    "longest_run_gt",
    "burst_count_gt",
    "weak_topk_mean",
)
GROUP_POOL_NAMES: Tuple[str, ...] = (
    "q50",
    "q75",
    "q90",
    "trimmed_mean",
    "std",
    "ratio_gt",
    "longest_run_gt",
    "burst_count_gt",
)


def _make_feature_names(encoder_dim: int) -> Tuple[str, ...]:
    names: List[str] = []
    for evidence in EVIDENCE_NAMES:
        names.extend(f"{evidence}_{name}" for name in POOL_NAMES)
    names.extend(f"group_{name}" for name in GROUP_POOL_NAMES)
    names.extend(("pos_x", "pos_y", "pos_z", "is_mag", "is_grad"))
    names.extend(f"learned_mean_{i}" for i in range(int(encoder_dim)))
    names.extend(f"learned_rel_q90_{i}" for i in range(int(encoder_dim)))
    return tuple(names)


def _weighted_topk_mean_time(values: torch.Tensor, weights: torch.Tensor, *, fraction: float, min_k: int) -> torch.Tensor:
    valid = weights > 0
    neg = torch.finfo(values.dtype).min
    masked = torch.where(valid, values, torch.full_like(values, neg))
    n_valid = valid.sum(dim=1)
    max_l = int(values.shape[1])
    k = max(int(round(max_l * float(fraction))), int(min_k), 1)
    k = min(k, max_l)
    top = masked.topk(k, dim=1).values
    finite = top > (neg / 2)
    denom = finite.float().sum(dim=1).clamp_min(1.0)
    out = top.masked_fill(~finite, 0.0).sum(dim=1) / denom
    out = torch.where(n_valid > 0, out, torch.zeros_like(out))
    return torch.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


def _pool_evidence(
    values: torch.Tensor,
    valid_lc: torch.Tensor,
    *,
    threshold: float,
    weak_topk_fraction: float,
    weak_topk_min: int,
) -> torch.Tensor:
    weights = valid_lc.float()
    flags = values > float(threshold)
    longest, bursts = _longest_and_burst_count(flags, valid_lc)
    features = [
        _weighted_quantile_time(values, weights, 0.50),
        _weighted_quantile_time(values, weights, 0.75),
        _weighted_quantile_time(values, weights, 0.90),
        _weighted_quantile_time(values, weights, 0.95),
        _weighted_trimmed_mean_time(values, weights),
        _weighted_std_time(values, weights),
        _ratio_time(flags, valid_lc),
        longest,
        bursts,
        _weighted_topk_mean_time(values, weights, fraction=weak_topk_fraction, min_k=weak_topk_min),
    ]
    return torch.stack(features, dim=-1)


def _pool_group_context(group_values: torch.Tensor, window_mask: torch.Tensor, *, threshold: float) -> torch.Tensor:
    valid = window_mask[:, :, None].expand_as(group_values)
    weights = valid.float()
    flags = group_values > float(threshold)
    longest, bursts = _longest_and_burst_count(flags, valid)
    features = [
        _weighted_quantile_time(group_values, weights, 0.50),
        _weighted_quantile_time(group_values, weights, 0.75),
        _weighted_quantile_time(group_values, weights, 0.90),
        _weighted_trimmed_mean_time(group_values, weights),
        _weighted_std_time(group_values, weights),
        _ratio_time(flags, valid),
        longest,
        bursts,
    ]
    return torch.stack(features, dim=-1)


def _same_type_group_score(
    score: torch.Tensor,
    channel_mask: torch.Tensor,
    sensor_type: torch.Tensor,
    *,
    threshold: float,
) -> torch.Tensor:
    out = score.new_zeros((score.shape[0], score.shape[1], 2))
    for b in range(score.shape[0]):
        for group_i, sensor_value in enumerate((SENSOR_MAG, SENSOR_GRAD)):
            idx = channel_mask[b] & (sensor_type[b] == sensor_value)
            if not bool(idx.any().item()):
                continue
            selected = score[b, :, idx]
            q75 = selected.quantile(0.75, dim=1)
            ratio = (selected > float(threshold)).float().mean(dim=1)
            out[b, :, group_i] = 0.7 * q75 + 0.3 * ratio
    return torch.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


def _regional_score(
    score: torch.Tensor,
    channel_mask: torch.Tensor,
    sensor_type: torch.Tensor,
    channel_pos: torch.Tensor,
    *,
    neighbors: int,
) -> torch.Tensor:
    out = torch.zeros_like(score)
    k_req = max(int(neighbors), 1)
    for b in range(score.shape[0]):
        pos = torch.nan_to_num(channel_pos[b].float(), nan=0.0, posinf=0.0, neginf=0.0)
        for sensor_value in (SENSOR_MAG, SENSOR_GRAD):
            idx = (channel_mask[b] & (sensor_type[b] == sensor_value)).nonzero(as_tuple=False).reshape(-1)
            n = int(idx.numel())
            if n <= 1:
                continue
            p = pos[idx]
            dist = torch.cdist(p, p).clamp_min(0.0)
            dist.fill_diagonal_(float("inf"))
            k = min(k_req, n - 1)
            nn_dist, nn_local = dist.topk(k, largest=False, dim=1)
            nn_idx = idx[nn_local]
            finite_dist = torch.where(torch.isfinite(nn_dist), nn_dist, torch.zeros_like(nn_dist))
            scale = finite_dist[finite_dist > 0].median() if bool((finite_dist > 0).any().item()) else finite_dist.new_tensor(1.0)
            weights = torch.exp(-finite_dist / scale.clamp_min(1e-3))
            weights = weights / weights.sum(dim=1, keepdim=True).clamp_min(EPS)
            neigh_score = score[b, :, nn_idx]  # [L, n, k]
            out[b, :, idx] = (neigh_score * weights[None, :, :]).sum(dim=-1)
    return torch.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


class _EvidenceFusionHead(nn.Module):
    """Type-specific head: group context can modulate, not directly decide."""

    def __init__(self, channel_dim: int, group_dim: int, hidden_dim: int, dropout: float, bias_init: float) -> None:
        super().__init__()
        self.channel_net = nn.Sequential(
            nn.LayerNorm(channel_dim),
            nn.Linear(channel_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(float(dropout)),
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
        )
        self.group_mod = nn.Sequential(
            nn.LayerNorm(group_dim),
            nn.Linear(group_dim, hidden_dim * 2),
        )
        self.abs_head = nn.Linear(hidden_dim, 1)
        self.rel_head = nn.Linear(hidden_dim, 1)
        self.reg_head = nn.Linear(hidden_dim, 1)
        self.rel_gate = nn.Linear(hidden_dim, 1)
        self.reg_gate = nn.Linear(hidden_dim, 1)
        nn.init.constant_(self.abs_head.bias, float(bias_init))
        nn.init.constant_(self.rel_head.bias, 0.0)
        nn.init.constant_(self.reg_head.bias, 0.0)
        nn.init.constant_(self.rel_gate.bias, -0.5)
        nn.init.constant_(self.reg_gate.bias, -0.5)

    def forward(self, channel_features: torch.Tensor, group_features: torch.Tensor) -> Tuple[torch.Tensor, Dict[str, torch.Tensor]]:
        h = self.channel_net(channel_features)
        gamma, beta = self.group_mod(group_features).chunk(2, dim=-1)
        # Bounded FiLM: group quality changes interpretation of channel evidence
        # but cannot create a standalone positive channel logit.
        h = h * (1.0 + 0.25 * torch.tanh(gamma)) + 0.25 * torch.tanh(beta)
        h = torch.nan_to_num(h, nan=0.0, posinf=0.0, neginf=0.0)
        abs_logit = self.abs_head(h).squeeze(-1)
        rel_logit = self.rel_head(h).squeeze(-1)
        reg_logit = self.reg_head(h).squeeze(-1)
        rel_gate = torch.sigmoid(self.rel_gate(h).squeeze(-1))
        reg_gate = torch.sigmoid(self.reg_gate(h).squeeze(-1))
        final = abs_logit + rel_gate * rel_logit + reg_gate * reg_logit
        return final, {
            "absolute_logits": abs_logit,
            "relative_logits": rel_logit,
            "regional_logits": reg_logit,
            "relative_gate": rel_gate,
            "regional_gate": reg_gate,
        }


class V11BadChannelNet(nn.Module):
    """Evidence-fusion bad-channel model with type-aware branches."""

    def __init__(
        self,
        *,
        hidden_dim: int = 96,
        temporal_kernel_size: int = 9,
        input_mode: str = V11InputMode.RAW.value,
        window_norm: str = V11WindowNorm.DEMEAN.value,
        trajectory_layers: int = 2,
        trajectory_kernel_size: int = 3,
        channel_transformer_layers: int = 2,
        channel_attention_heads: int = 4,
        channel_ff_dim: int | None = None,
        encoder_chunk_size: int = 4096,
        dropout: float = 0.1,
        global_downweight_alpha: float = 0.0,
        min_window_weight: float = 1.0,
        global_score_threshold: float = 1.0,
        residual_threshold: float = 1.0,
        bad_segment_badness: float = 0.0,
        stat_abnormal_scale: float = 0.35,
        weak_topk_fraction: float = 0.25,
        weak_topk_min: int = 16,
        use_global_reference: bool = False,
        use_sensor_embedding: bool = False,
        channel_head_bias_init: float = -2.0,
        use_logit_calibration: bool = False,
        logit_calibration_bias: float = -2.0,
        regional_neighbors: int = 8,
        group_context_strength: float = 0.25,
    ) -> None:
        super().__init__()
        hidden = max(16, int(hidden_dim))
        self.input_mode = str(input_mode)
        self.window_norm = str(window_norm)
        self.encoder_chunk_size = max(int(encoder_chunk_size), 1)
        self.learned_encoder_dim = max(8, hidden // 4)
        self.residual_threshold = float(residual_threshold)
        self.global_score_threshold = float(global_score_threshold)
        self.stat_abnormal_scale = float(stat_abnormal_scale)
        self.weak_topk_fraction = float(weak_topk_fraction)
        self.weak_topk_min = int(weak_topk_min)
        self.regional_neighbors = int(regional_neighbors)
        self.group_context_strength = float(group_context_strength)
        self.temporal_kernel_size = int(temporal_kernel_size)
        self.trajectory_layers = int(trajectory_layers)
        self.trajectory_kernel_size = int(trajectory_kernel_size)
        self.channel_transformer_layers = int(channel_transformer_layers)
        self.channel_attention_heads = int(channel_attention_heads)
        self.channel_ff_dim = channel_ff_dim
        self.global_downweight_alpha = float(global_downweight_alpha)
        self.min_window_weight = float(min_window_weight)
        self.bad_segment_badness = float(bad_segment_badness)
        self.use_global_reference = bool(use_global_reference)
        self.use_sensor_embedding = bool(use_sensor_embedding)
        self.use_logit_calibration = False
        self.logit_calibration_bias = float(logit_calibration_bias)

        in_ch = 2 if self.input_mode == "raw_diff" else 1
        kernel = max(3, int(temporal_kernel_size))
        if kernel % 2 == 0:
            kernel += 1
        self.window_encoder = nn.Sequential(
            nn.Conv1d(in_ch, self.learned_encoder_dim, kernel_size=kernel, padding=kernel // 2),
            nn.GELU(),
            nn.GroupNorm(1, self.learned_encoder_dim),
            nn.Conv1d(self.learned_encoder_dim, self.learned_encoder_dim, kernel_size=5, padding=2),
            nn.GELU(),
            nn.GroupNorm(1, self.learned_encoder_dim),
            nn.AdaptiveAvgPool1d(1),
        )
        abs_in_dim = len(STAT_NAMES) + self.learned_encoder_dim
        self.absolute_evidence = nn.Sequential(
            nn.LayerNorm(abs_in_dim),
            nn.Linear(abs_in_dim, max(16, hidden // 2)),
            nn.GELU(),
            nn.Linear(max(16, hidden // 2), 1),
        )
        channel_dim = len(EVIDENCE_NAMES) * len(POOL_NAMES) + 5 + 2 * self.learned_encoder_dim
        group_dim = len(GROUP_POOL_NAMES)
        head_dim = max(16, hidden // 2)
        self.mag_head = _EvidenceFusionHead(channel_dim, group_dim, head_dim, float(dropout), float(channel_head_bias_init))
        self.grad_head = _EvidenceFusionHead(channel_dim, group_dim, head_dim, float(dropout), float(channel_head_bias_init))
        self.feature_names = _make_feature_names(self.learned_encoder_dim)

    @staticmethod
    def _masks(batch: Dict[str, torch.Tensor], x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        bsz, windows, channels, _ = x.shape
        device = x.device
        channel_mask = batch.get("channel_mask")
        channel_mask = torch.ones((bsz, channels), dtype=torch.bool, device=device) if channel_mask is None else channel_mask.to(device).bool()
        window_mask = batch.get("window_mask")
        window_mask = torch.ones((bsz, windows), dtype=torch.bool, device=device) if window_mask is None else window_mask.to(device).bool()
        if "sensor_type" not in batch:
            raise KeyError("V11BadChannelNet requires batch['sensor_type']")
        sensor_type = batch["sensor_type"].to(device=device).long()
        if sensor_type.shape != channel_mask.shape:
            raise ValueError(f"sensor_type shape {tuple(sensor_type.shape)} does not match channel_mask {tuple(channel_mask.shape)}")
        real_bad = channel_mask & ~((sensor_type == SENSOR_MAG) | (sensor_type == SENSOR_GRAD))
        if bool(real_bad.any().item()):
            b, c = real_bad.nonzero(as_tuple=False)[0].tolist()
            value = int(sensor_type[b, c].item())
            raise ValueError(f"Invalid V11 sensor_type={value} at batch={b}, channel={c}; real channels must be 1=mag or 2=grad")
        sensor_type = torch.where(channel_mask, sensor_type, torch.zeros_like(sensor_type))
        return channel_mask, window_mask, sensor_type

    def _make_encoder_input(self, x: torch.Tensor) -> torch.Tensor:
        x_norm = _normalise_windows(x, self.window_norm)
        dx = F.pad(x_norm.diff(dim=-1), (1, 0))
        if self.input_mode == "raw":
            return x_norm.unsqueeze(1)
        if self.input_mode == "diff":
            return dx.unsqueeze(1)
        return torch.stack((x_norm, dx), dim=1)

    def _encode_waveform(self, x: torch.Tensor, valid_lc: torch.Tensor) -> torch.Tensor:
        bsz, windows, channels, samples = x.shape
        flat = x.reshape(bsz * windows * channels, samples)
        valid_flat = valid_lc.reshape(-1)
        out = x.new_zeros((flat.shape[0], self.learned_encoder_dim))
        if bool(valid_flat.any().item()):
            valid_x = flat[valid_flat]
            parts: List[torch.Tensor] = []
            chunk = max(int(self.encoder_chunk_size), 1)
            for start in range(0, valid_x.shape[0], chunk):
                y = self.window_encoder(self._make_encoder_input(valid_x[start : start + chunk])).squeeze(-1)
                parts.append(y)
            out[valid_flat] = torch.cat(parts, dim=0)
        return torch.nan_to_num(out.reshape(bsz, windows, channels, self.learned_encoder_dim), nan=0.0, posinf=0.0, neginf=0.0)

    def _build_evidence_features(
        self,
        stats: torch.Tensor,
        learned: torch.Tensor,
        channel_mask: torch.Tensor,
        window_mask: torch.Tensor,
        sensor_type: torch.Tensor,
        channel_pos: torch.Tensor,
    ) -> Tuple[torch.Tensor, Dict[str, torch.Tensor]]:
        valid_lc = window_mask[:, :, None] & channel_mask[:, None, :]
        abs_input = torch.cat((stats, learned), dim=-1)
        abs_score = F.softplus(self.absolute_evidence(abs_input).squeeze(-1)).clamp(max=20.0)
        abs_score = torch.where(valid_lc, abs_score, torch.zeros_like(abs_score))

        stat_z = _same_type_robust_z(stats, channel_mask, sensor_type, detach_reference=True).abs()
        learned_z = _same_type_robust_z(learned, channel_mask, sensor_type, min_scale=0.05, clip_value=8.0, detach_reference=True).abs()
        abs_z = _same_type_robust_z(abs_score.unsqueeze(-1), channel_mask, sensor_type, min_scale=0.05, clip_value=8.0, detach_reference=True).squeeze(-1)
        severity_idx = torch.tensor((0, 1, 2, 3, 4, 5, 7), device=stats.device)
        stat_rel = stat_z.index_select(dim=-1, index=severity_idx).mean(dim=-1)
        learned_rel = learned_z.mean(dim=-1)
        rel_score = (0.45 * F.relu(abs_z) + 0.35 * stat_rel + 0.20 * learned_rel).clamp(max=20.0)
        rel_score = torch.where(valid_lc, rel_score, torch.zeros_like(rel_score))

        reg_score = _regional_score(abs_score, channel_mask, sensor_type, channel_pos, neighbors=self.regional_neighbors)
        reg_score = torch.where(valid_lc, reg_score, torch.zeros_like(reg_score))

        group_score = _same_type_group_score(abs_score, channel_mask, sensor_type, threshold=self.global_score_threshold)
        group_pool = _pool_group_context(group_score, window_mask, threshold=self.global_score_threshold)

        pooled_abs = _pool_evidence(
            abs_score,
            valid_lc,
            threshold=self.global_score_threshold,
            weak_topk_fraction=self.weak_topk_fraction,
            weak_topk_min=self.weak_topk_min,
        )
        pooled_rel = _pool_evidence(
            rel_score,
            valid_lc,
            threshold=self.residual_threshold,
            weak_topk_fraction=self.weak_topk_fraction,
            weak_topk_min=self.weak_topk_min,
        )
        pooled_reg = _pool_evidence(
            reg_score,
            valid_lc,
            threshold=self.global_score_threshold,
            weak_topk_fraction=self.weak_topk_fraction,
            weak_topk_min=self.weak_topk_min,
        )
        learned_mean = (learned * valid_lc[:, :, :, None].float()).sum(dim=1) / valid_lc.float().sum(dim=1).clamp_min(1.0)[:, :, None]
        learned_rel_q90 = _weighted_quantile_time(learned_z, valid_lc[:, :, :, None].float().expand_as(learned_z), 0.90)
        pos = torch.nan_to_num(channel_pos.float(), nan=0.0, posinf=0.0, neginf=0.0)
        type_oh = torch.stack((sensor_type == SENSOR_MAG, sensor_type == SENSOR_GRAD), dim=-1).float()
        features = torch.cat((pooled_abs, pooled_rel, pooled_reg, pos[..., :3], type_oh, learned_mean, learned_rel_q90), dim=-1)
        features = torch.where(channel_mask[:, :, None], features, torch.zeros_like(features))
        diag = {
            "E_abs": abs_score,
            "E_rel": rel_score,
            "E_reg": reg_score,
            "E_grp": group_score,
            "stat_z": stat_z,
            "learned_z": learned_z,
            "group_pool": group_pool,
            "persistence_features": features,
        }
        return torch.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0), diag

    def _type_aware_logits(
        self,
        features: torch.Tensor,
        group_pool: torch.Tensor,
        channel_mask: torch.Tensor,
        sensor_type: torch.Tensor,
    ) -> Tuple[torch.Tensor, Dict[str, torch.Tensor]]:
        logits = features.new_zeros(features.shape[:2])
        abs_logits = features.new_zeros(features.shape[:2])
        rel_logits = features.new_zeros(features.shape[:2])
        reg_logits = features.new_zeros(features.shape[:2])
        rel_gate = features.new_zeros(features.shape[:2])
        reg_gate = features.new_zeros(features.shape[:2])
        for group_i, (sensor_value, head) in enumerate(((SENSOR_MAG, self.mag_head), (SENSOR_GRAD, self.grad_head))):
            idx = channel_mask & (sensor_type == sensor_value)
            if not bool(idx.any().item()):
                continue
            group_features = group_pool[:, group_i, :][:, None, :].expand(-1, features.shape[1], -1)
            final, parts = head(features[idx], group_features[idx])
            logits[idx] = final
            abs_logits[idx] = parts["absolute_logits"]
            rel_logits[idx] = parts["relative_logits"]
            reg_logits[idx] = parts["regional_logits"]
            rel_gate[idx] = parts["relative_gate"]
            reg_gate[idx] = parts["regional_gate"]
        aux = {
            "absolute_logits": torch.where(channel_mask, abs_logits, torch.zeros_like(abs_logits)),
            "relative_logits": torch.where(channel_mask, rel_logits, torch.zeros_like(rel_logits)),
            "regional_logits": torch.where(channel_mask, reg_logits, torch.zeros_like(reg_logits)),
            "relative_gate": torch.where(channel_mask, rel_gate, torch.zeros_like(rel_gate)),
            "regional_gate": torch.where(channel_mask, reg_gate, torch.zeros_like(reg_gate)),
        }
        return torch.where(channel_mask, logits, torch.zeros_like(logits)), aux

    def forward(self, batch: Dict[str, torch.Tensor], *, return_diagnostics: bool = False):
        x = torch.nan_to_num(batch["x"].float(), nan=0.0, posinf=0.0, neginf=0.0)
        channel_mask, window_mask, sensor_type = self._masks(batch, x)
        valid_lc = window_mask[:, :, None] & channel_mask[:, None, :]
        channel_pos = batch.get("channel_pos")
        if channel_pos is None:
            channel_pos = x.new_zeros((x.shape[0], x.shape[2], 3))
        else:
            channel_pos = channel_pos.to(device=x.device, dtype=x.dtype)
            if channel_pos.shape[-1] < 3:
                pad = x.new_zeros((*channel_pos.shape[:-1], 3 - channel_pos.shape[-1]))
                channel_pos = torch.cat((channel_pos, pad), dim=-1)
            channel_pos = channel_pos[..., :3]
        x_norm = _normalise_windows(x, self.window_norm)
        stats = _window_stats(x_norm)
        learned = self._encode_waveform(x_norm, valid_lc)
        stats = torch.where(valid_lc[:, :, :, None], stats, torch.zeros_like(stats))
        learned = torch.where(valid_lc[:, :, :, None], learned, torch.zeros_like(learned))
        features, diag = self._build_evidence_features(stats, learned, channel_mask, window_mask, sensor_type, channel_pos)
        logits, aux = self._type_aware_logits(features, diag["group_pool"], channel_mask, sensor_type)
        logits = torch.nan_to_num(logits, nan=0.0, posinf=0.0, neginf=0.0)
        if not return_diagnostics:
            return logits
        diagnostics = {
            "E_abs": diag["E_abs"],
            "E_rel": diag["E_rel"],
            "E_reg": diag["E_reg"],
            "E_grp": diag["E_grp"],
            "residual_z": diag["E_rel"],
            "global_badness": diag["E_grp"],
            "window_weight": window_mask.float(),
            "persistence_features": diag["persistence_features"],
            "persistence_feature_names": self.feature_names,
            "group_pool": diag["group_pool"],
            "raw_logits": logits,
            "absolute_logits": aux["absolute_logits"],
            "relative_logits": aux["relative_logits"],
            "regional_logits": aux["regional_logits"],
            "relative_gate": aux["relative_gate"],
            "regional_gate": aux["regional_gate"],
            "has_mag": ((sensor_type == SENSOR_MAG) & channel_mask).any(dim=1),
            "has_grad": ((sensor_type == SENSOR_GRAD) & channel_mask).any(dim=1),
        }
        return logits, diagnostics
