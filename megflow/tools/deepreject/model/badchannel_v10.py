from __future__ import annotations

from enum import Enum
from typing import Dict, List, Tuple

import torch
from torch import nn


SENSOR_PAD = 0
SENSOR_MAG = 1
SENSOR_GRAD = 2

EPS = 1e-6


class V10InputMode(str, Enum):
    RAW = "raw"
    RAW_AND_STATS = "raw_and_stats"


class V10WindowNorm(str, Enum):
    NONE = "none"
    DEMEAN = "demean"
    ZSCORE = "zscore"


STAT_NAMES: Tuple[str, ...] = (
    "log_rms",
    "log_std",
    "log_ptp",
    "log_max_abs",
    "log_diff_rms",
    "flat_ratio",
    "mean",
    "kurtosis",
)
RAW_AGGS: Tuple[str, ...] = ("q50", "q90", "std")
Z_AGGS: Tuple[str, ...] = ("q50", "q90")
ABS_Z_AGGS: Tuple[str, ...] = ("q50", "q75", "q90", "max", "ratio_gt2p5")
SEVERITY_AGGS: Tuple[str, ...] = (
    "q50",
    "q75",
    "q90",
    "q95",
    "trimmed_mean",
    "std",
    "ratio_gt1p5",
    "ratio_gt2p5",
    "longest_run_gt1p5",
    "burst_count_gt1p5",
)


def _feature_names() -> Tuple[str, ...]:
    names: List[str] = []
    for name in STAT_NAMES:
        names.extend(f"raw_{name}_{agg}" for agg in RAW_AGGS)
    for name in STAT_NAMES:
        names.extend(f"same_type_z_{name}_{agg}" for agg in Z_AGGS)
    for name in STAT_NAMES:
        names.extend(f"same_type_abs_z_{name}_{agg}" for agg in ABS_Z_AGGS)
    names.extend(f"severity_{agg}" for agg in SEVERITY_AGGS)
    return tuple(names)


V10_CHANNEL_FEATURE_NAMES: Tuple[str, ...] = _feature_names()
V10_PERSISTENCE_FEATURE_NAMES: Tuple[str, ...] = V10_CHANNEL_FEATURE_NAMES


def _learned_feature_names(encoder_dim: int) -> Tuple[str, ...]:
    names: List[str] = []
    for i in range(int(encoder_dim)):
        names.extend(
            (
                f"learned_enc{i}_q50",
                f"learned_enc{i}_q90",
                f"learned_enc{i}_std",
                f"same_type_learned_abs_z{i}_q75",
                f"same_type_learned_abs_z{i}_q90",
            )
        )
    names.extend(
        (
            "learned_severity_q50",
            "learned_severity_q75",
            "learned_severity_q90",
            "learned_severity_ratio_gt1p5",
            "learned_severity_longest_run_gt1p5",
            "learned_severity_burst_count_gt1p5",
        )
    )
    return tuple(names)


def _normalise_windows(x: torch.Tensor, mode: str) -> torch.Tensor:
    mode = str(mode or V10WindowNorm.DEMEAN.value).lower()
    if mode == "standardize":
        mode = V10WindowNorm.ZSCORE.value
    if mode == V10WindowNorm.NONE.value:
        return x
    center = x - x.mean(dim=-1, keepdim=True)
    if mode == V10WindowNorm.ZSCORE.value:
        scale = center.std(dim=-1, keepdim=True, unbiased=False).clamp_min(EPS)
        return center / scale
    return center


def _window_stats(x: torch.Tensor) -> torch.Tensor:
    x = torch.nan_to_num(x.float(), nan=0.0, posinf=0.0, neginf=0.0)
    centered = x - x.mean(dim=-1, keepdim=True)
    rms = torch.sqrt((x * x).mean(dim=-1).clamp_min(0.0) + EPS)
    std = centered.std(dim=-1, unbiased=False).clamp_min(EPS)
    max_v = x.amax(dim=-1)
    min_v = x.amin(dim=-1)
    ptp = (max_v - min_v).abs().clamp_min(EPS)
    max_abs = x.abs().amax(dim=-1).clamp_min(EPS)
    if x.shape[-1] > 1:
        diff = x.diff(dim=-1)
        diff_rms = torch.sqrt((diff * diff).mean(dim=-1).clamp_min(0.0) + EPS)
        flat_ratio = (diff.abs() < 1e-6).float().mean(dim=-1)
    else:
        diff_rms = torch.zeros_like(rms)
        flat_ratio = torch.ones_like(rms)
    z = centered / std.unsqueeze(-1).clamp_min(EPS)
    kurtosis = (z.pow(4).mean(dim=-1) - 3.0).clamp(min=-10.0, max=50.0)
    stats = torch.stack(
        (
            torch.log1p(rms),
            torch.log1p(std),
            torch.log1p(ptp),
            torch.log1p(max_abs),
            torch.log1p(diff_rms),
            flat_ratio.clamp(min=0.0, max=1.0),
            x.mean(dim=-1),
            kurtosis,
        ),
        dim=-1,
    )
    return torch.nan_to_num(stats, nan=0.0, posinf=0.0, neginf=0.0)


def _same_type_robust_z(
    values: torch.Tensor,
    channel_mask: torch.Tensor,
    sensor_type: torch.Tensor,
    *,
    min_scale: float = EPS,
    clip_value: float | None = 20.0,
    detach_reference: bool = False,
) -> torch.Tensor:
    out = torch.zeros_like(values)
    for b in range(values.shape[0]):
        for sensor_value in (SENSOR_MAG, SENSOR_GRAD):
            idx = channel_mask[b] & (sensor_type[b] == sensor_value)
            n = int(idx.sum().item())
            if n <= 1:
                continue
            selected = values[b, :, idx, :]
            median = selected.median(dim=1).values
            mad = (selected - median[:, None, :]).abs().median(dim=1).values
            scale = (1.4826 * mad).clamp_min(float(min_scale))
            if detach_reference:
                median = median.detach()
                scale = scale.detach()
            z = (selected - median[:, None, :]) / scale[:, None, :]
            if clip_value is not None and float(clip_value) > 0:
                z = z.clamp(min=-float(clip_value), max=float(clip_value))
            out[b, :, idx, :] = z
    return torch.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


def _weighted_mean_time(values: torch.Tensor, weights: torch.Tensor) -> torch.Tensor:
    weights = weights.to(dtype=values.dtype)
    denom = weights.sum(dim=1).clamp_min(EPS)
    out = (values * weights).sum(dim=1) / denom
    return torch.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


def _weighted_std_time(values: torch.Tensor, weights: torch.Tensor) -> torch.Tensor:
    mean = _weighted_mean_time(values, weights)
    weights = weights.to(dtype=values.dtype)
    denom = weights.sum(dim=1).clamp_min(EPS)
    var = ((values - mean[:, None, :]).pow(2) * weights).sum(dim=1) / denom
    return torch.sqrt(var.clamp_min(EPS))


def _weighted_quantile_time(values: torch.Tensor, weights: torch.Tensor, q: float) -> torch.Tensor:
    weights = weights.to(dtype=values.dtype)
    valid = weights > 0
    masked = torch.where(valid, values, torch.full_like(values, float("inf")))
    sorted_values, order = masked.sort(dim=1)
    sorted_weights = weights.gather(dim=1, index=order)
    total = sorted_weights.sum(dim=1)
    cutoff = (total * float(q)).clamp_min(EPS)
    cdf = sorted_weights.cumsum(dim=1)
    idx = (cdf >= cutoff[:, None, :]).float().argmax(dim=1, keepdim=True)
    out = sorted_values.gather(dim=1, index=idx).squeeze(1)
    out = torch.where(total > 0, out, torch.zeros_like(out))
    return torch.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


def _weighted_trimmed_mean_time(values: torch.Tensor, weights: torch.Tensor, low_q: float = 0.1, high_q: float = 0.9) -> torch.Tensor:
    lo = _weighted_quantile_time(values, weights, low_q)
    hi = _weighted_quantile_time(values, weights, high_q)
    keep = (values >= lo[:, None, :]) & (values <= hi[:, None, :]) & (weights > 0)
    trimmed_weights = torch.where(keep, weights, torch.zeros_like(weights))
    return _weighted_mean_time(values, trimmed_weights)


def _weighted_max_time(values: torch.Tensor, weights: torch.Tensor) -> torch.Tensor:
    valid = weights > 0
    masked = torch.where(valid, values, torch.full_like(values, -float("inf")))
    out = masked.amax(dim=1)
    out = torch.where(valid.any(dim=1), out, torch.zeros_like(out))
    return torch.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


def _ratio_time(flags: torch.Tensor, valid: torch.Tensor) -> torch.Tensor:
    flags = flags & valid
    denom = valid.float().sum(dim=1).clamp_min(EPS)
    out = flags.float().sum(dim=1) / denom
    return torch.where(valid.any(dim=1), out, torch.zeros_like(out))


def _longest_and_burst_count(flags: torch.Tensor, valid: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
    seq = flags & valid
    bsz, _, channels = seq.shape
    run = torch.zeros((bsz, channels), dtype=torch.float32, device=seq.device)
    longest = torch.zeros_like(run)
    bursts = torch.zeros_like(run)
    prev = torch.zeros((bsz, channels), dtype=torch.bool, device=seq.device)
    for t in range(seq.shape[1]):
        cur = seq[:, t, :]
        run = torch.where(cur, run + 1.0, torch.zeros_like(run))
        longest = torch.maximum(longest, run)
        bursts = bursts + (cur & ~prev).float()
        prev = cur
    denom = valid.float().sum(dim=1).clamp_min(1.0)
    return longest / denom, bursts / denom


class _TypeDecisionHead(nn.Module):
    def __init__(self, feature_dim: int, hidden_dim: int, dropout: float, bias_init: float) -> None:
        super().__init__()
        self.backbone = nn.Sequential(
            nn.LayerNorm(feature_dim),
            nn.Linear(feature_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
        )
        self.absolute_head = nn.Linear(hidden_dim, 1)
        self.relative_head = nn.Linear(hidden_dim, 1)
        self.gate_head = nn.Linear(hidden_dim, 1)
        self.group_head = nn.Sequential(
            nn.LayerNorm(hidden_dim),
            nn.Linear(hidden_dim, max(8, hidden_dim // 2)),
            nn.GELU(),
            nn.Linear(max(8, hidden_dim // 2), 1),
        )
        nn.init.constant_(self.absolute_head.bias, float(bias_init))
        nn.init.constant_(self.relative_head.bias, 0.0)
        nn.init.constant_(self.gate_head.bias, -1.0)
        last = self.group_head[-1]
        if isinstance(last, nn.Linear) and last.bias is not None:
            nn.init.constant_(last.bias, float(bias_init))

    def channel_logits(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        h = self.backbone(x)
        absolute = self.absolute_head(h).squeeze(-1)
        relative = self.relative_head(h).squeeze(-1)
        gate = torch.sigmoid(self.gate_head(h).squeeze(-1))
        final = absolute + gate * relative
        return final, absolute, relative, gate, h

    def group_logit(self, x: torch.Tensor) -> torch.Tensor:
        return self.group_head(x).squeeze(-1)


class V10BadChannelNet(nn.Module):
    """Bad-channel model with same-type residual and gated relative evidence."""

    def __init__(
        self,
        *,
        hidden_dim: int = 96,
        temporal_kernel_size: int = 9,
        input_mode: str = V10InputMode.RAW.value,
        window_norm: str = V10WindowNorm.DEMEAN.value,
        trajectory_layers: int = 2,
        trajectory_kernel_size: int = 3,
        channel_transformer_layers: int = 2,
        channel_attention_heads: int = 4,
        channel_ff_dim: int | None = None,
        encoder_chunk_size: int = 4096,
        dropout: float = 0.1,
        global_downweight_alpha: float = 0.75,
        min_window_weight: float = 0.25,
        global_score_threshold: float = 2.5,
        residual_threshold: float = 1.5,
        bad_segment_badness: float = 0.75,
        stat_abnormal_scale: float = 0.35,
        weak_topk_fraction: float = 0.20,
        weak_topk_min: int = 8,
        use_global_reference: bool = True,
        use_sensor_embedding: bool = False,
        channel_head_bias_init: float = -2.0,
        use_logit_calibration: bool = False,
        logit_calibration_bias: float = -2.0,
    ) -> None:
        super().__init__()
        self.input_mode = str(input_mode)
        self.window_norm = str(window_norm)
        self.residual_threshold = float(residual_threshold)
        self.global_score_threshold = float(global_score_threshold)
        hidden = max(16, int(hidden_dim))
        self.learned_encoder_dim = max(8, hidden // 4)
        self.feature_names = V10_CHANNEL_FEATURE_NAMES + _learned_feature_names(self.learned_encoder_dim)
        feature_dim = len(self.feature_names)
        head_dim = max(16, hidden // 2)
        kernel = max(3, int(temporal_kernel_size))
        if kernel % 2 == 0:
            kernel += 1
        self.window_encoder = nn.Sequential(
            nn.Conv1d(1, self.learned_encoder_dim, kernel_size=kernel, padding=kernel // 2),
            nn.GELU(),
            nn.Conv1d(self.learned_encoder_dim, self.learned_encoder_dim, kernel_size=3, padding=1),
            nn.GELU(),
        )
        self.mag_head = _TypeDecisionHead(feature_dim, head_dim, float(dropout), float(channel_head_bias_init))
        self.grad_head = _TypeDecisionHead(feature_dim, head_dim, float(dropout), float(channel_head_bias_init))

        # Keep compatibility attributes for existing configs and checkpoints.
        self.temporal_kernel_size = int(temporal_kernel_size)
        self.trajectory_layers = int(trajectory_layers)
        self.trajectory_kernel_size = int(trajectory_kernel_size)
        self.channel_transformer_layers = int(channel_transformer_layers)
        self.channel_attention_heads = int(channel_attention_heads)
        self.channel_ff_dim = channel_ff_dim
        self.encoder_chunk_size = int(encoder_chunk_size)
        self.global_downweight_alpha = float(global_downweight_alpha)
        self.min_window_weight = float(min_window_weight)
        self.bad_segment_badness = float(bad_segment_badness)
        self.stat_abnormal_scale = float(stat_abnormal_scale)
        self.weak_topk_fraction = float(weak_topk_fraction)
        self.weak_topk_min = int(weak_topk_min)
        self.use_global_reference = bool(use_global_reference)
        self.use_sensor_embedding = bool(use_sensor_embedding)
        self.use_logit_calibration = False
        self.logit_calibration_bias = float(logit_calibration_bias)

    @staticmethod
    def _masks(batch: Dict[str, torch.Tensor], x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        bsz, windows, channels, _ = x.shape
        device = x.device
        channel_mask = batch.get("channel_mask")
        if channel_mask is None:
            channel_mask = torch.ones((bsz, channels), dtype=torch.bool, device=device)
        else:
            channel_mask = channel_mask.to(device=device).bool()
        window_mask = batch.get("window_mask")
        if window_mask is None:
            window_mask = torch.ones((bsz, windows), dtype=torch.bool, device=device)
        else:
            window_mask = window_mask.to(device=device).bool()
        if "sensor_type" not in batch:
            raise KeyError("V10BadChannelNet requires batch['sensor_type']")
        sensor_type = batch["sensor_type"].to(device=device).long()
        if sensor_type.shape != channel_mask.shape:
            raise ValueError(f"sensor_type shape {tuple(sensor_type.shape)} does not match channel_mask {tuple(channel_mask.shape)}")
        real_bad = channel_mask & ~((sensor_type == SENSOR_MAG) | (sensor_type == SENSOR_GRAD))
        if bool(real_bad.any().item()):
            b, c = real_bad.nonzero(as_tuple=False)[0].tolist()
            value = int(sensor_type[b, c].item())
            raise ValueError(f"Invalid V10 sensor_type={value} at batch={b}, channel={c}; real channels must be 1=mag or 2=grad")
        sensor_type = torch.where(channel_mask, sensor_type, torch.zeros_like(sensor_type))
        return channel_mask, window_mask, sensor_type

    def _build_features(
        self,
        stats: torch.Tensor,
        stat_z: torch.Tensor,
        learned: torch.Tensor,
        learned_z: torch.Tensor,
        channel_mask: torch.Tensor,
        window_mask: torch.Tensor,
    ) -> Tuple[torch.Tensor, Dict[str, torch.Tensor]]:
        valid_lc = window_mask[:, :, None] & channel_mask[:, None, :]
        weights = valid_lc.float()
        abs_z = stat_z.abs()
        learned_abs_z = learned_z.abs()
        severity_idx = torch.tensor((0, 1, 2, 3, 4, 5, 7), device=stats.device)
        stat_severity = abs_z.index_select(dim=-1, index=severity_idx).mean(dim=-1)
        learned_severity = learned_abs_z.mean(dim=-1)
        severity = 0.5 * stat_severity + 0.5 * learned_severity
        severity = torch.where(valid_lc, severity, torch.zeros_like(severity))
        learned_severity = torch.where(valid_lc, learned_severity, torch.zeros_like(learned_severity))

        features: List[torch.Tensor] = []
        for d in range(len(STAT_NAMES)):
            v = stats[..., d]
            features.append(_weighted_quantile_time(v, weights, 0.50))
            features.append(_weighted_quantile_time(v, weights, 0.90))
            features.append(_weighted_std_time(v, weights))
        for d in range(len(STAT_NAMES)):
            v = stat_z[..., d]
            features.append(_weighted_quantile_time(v, weights, 0.50))
            features.append(_weighted_quantile_time(v, weights, 0.90))
        for d in range(len(STAT_NAMES)):
            v = abs_z[..., d]
            features.append(_weighted_quantile_time(v, weights, 0.50))
            features.append(_weighted_quantile_time(v, weights, 0.75))
            features.append(_weighted_quantile_time(v, weights, 0.90))
            features.append(_weighted_max_time(v, weights))
            features.append(_ratio_time(v > 2.5, valid_lc))

        features.append(_weighted_quantile_time(severity, weights, 0.50))
        features.append(_weighted_quantile_time(severity, weights, 0.75))
        features.append(_weighted_quantile_time(severity, weights, 0.90))
        features.append(_weighted_quantile_time(severity, weights, 0.95))
        features.append(_weighted_trimmed_mean_time(severity, weights))
        features.append(_weighted_std_time(severity, weights))
        features.append(_ratio_time(severity > self.residual_threshold, valid_lc))
        features.append(_ratio_time(severity > self.global_score_threshold, valid_lc))
        longest, bursts = _longest_and_burst_count(severity > self.residual_threshold, valid_lc)
        features.append(longest)
        features.append(bursts)

        for d in range(self.learned_encoder_dim):
            v = learned[..., d]
            vz = learned_abs_z[..., d]
            features.append(_weighted_quantile_time(v, weights, 0.50))
            features.append(_weighted_quantile_time(v, weights, 0.90))
            features.append(_weighted_std_time(v, weights))
            features.append(_weighted_quantile_time(vz, weights, 0.75))
            features.append(_weighted_quantile_time(vz, weights, 0.90))
        features.append(_weighted_quantile_time(learned_severity, weights, 0.50))
        features.append(_weighted_quantile_time(learned_severity, weights, 0.75))
        features.append(_weighted_quantile_time(learned_severity, weights, 0.90))
        features.append(_ratio_time(learned_severity > self.residual_threshold, valid_lc))
        learned_longest, learned_bursts = _longest_and_burst_count(learned_severity > self.residual_threshold, valid_lc)
        features.append(learned_longest)
        features.append(learned_bursts)

        out = torch.stack(features, dim=-1)
        out = torch.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)
        out = torch.where(channel_mask[:, :, None], out, torch.zeros_like(out))
        diagnostics = {
            "severity": severity,
            "stat_severity": stat_severity,
            "learned_severity": learned_severity,
            "abs_stat_z": abs_z,
            "learned_abs_z": learned_abs_z,
            "persistence_features": out,
        }
        return out, diagnostics

    def _encode_waveform(self, x: torch.Tensor, valid_lc: torch.Tensor) -> torch.Tensor:
        bsz, windows, channels, samples = x.shape
        flat = x.reshape(bsz * windows * channels, samples)
        valid_flat = valid_lc.reshape(-1)
        out = x.new_zeros((flat.shape[0], self.learned_encoder_dim))
        if bool(valid_flat.any().item()):
            valid_x = flat[valid_flat].unsqueeze(1)
            chunk = max(int(self.encoder_chunk_size), 1)
            parts: List[torch.Tensor] = []
            for start in range(0, valid_x.shape[0], chunk):
                y = self.window_encoder(valid_x[start : start + chunk])
                parts.append(y.mean(dim=-1))
            out[valid_flat] = torch.cat(parts, dim=0)
        return torch.nan_to_num(out.reshape(bsz, windows, channels, self.learned_encoder_dim), nan=0.0, posinf=0.0, neginf=0.0)

    def _type_aware_logits(
        self,
        features: torch.Tensor,
        channel_mask: torch.Tensor,
        sensor_type: torch.Tensor,
        *,
        compute_group: bool,
    ) -> Tuple[torch.Tensor, Dict[str, torch.Tensor]]:
        logits = features.new_zeros(features.shape[:2])
        absolute = features.new_zeros(features.shape[:2])
        relative = features.new_zeros(features.shape[:2])
        gate = features.new_zeros(features.shape[:2])
        group_logits = features.new_zeros((features.shape[0], 2))
        for group_idx, (sensor_value, head) in enumerate(((SENSOR_MAG, self.mag_head), (SENSOR_GRAD, self.grad_head))):
            idx = channel_mask & (sensor_type == sensor_value)
            if bool(idx.any().item()):
                final_t, abs_t, rel_t, gate_t, hidden_t = head.channel_logits(features[idx])
                logits[idx] = final_t
                absolute[idx] = abs_t
                relative[idx] = rel_t
                gate[idx] = gate_t
            if compute_group:
                for b in range(features.shape[0]):
                    idx_b = channel_mask[b] & (sensor_type[b] == sensor_value)
                    if bool(idx_b.any().item()):
                        hidden_b = head.backbone(features[b, idx_b])
                        group_logits[b, group_idx] = head.group_logit(hidden_b.mean(dim=0, keepdim=True)).squeeze(0)
        logits = torch.where(channel_mask, logits, torch.zeros_like(logits))
        aux = {
            "absolute_logits": torch.where(channel_mask, absolute, torch.zeros_like(absolute)),
            "relative_logits": torch.where(channel_mask, relative, torch.zeros_like(relative)),
            "relative_gate": torch.where(channel_mask, gate, torch.zeros_like(gate)),
            "group_logits": group_logits,
        }
        return logits, aux

    def forward(self, batch: Dict[str, torch.Tensor], *, return_diagnostics: bool = False):
        x = batch["x"].float()
        channel_mask, window_mask, sensor_type = self._masks(batch, x)
        x_norm = _normalise_windows(torch.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0), self.window_norm)
        stats = _window_stats(x_norm)
        stat_z = _same_type_robust_z(stats, channel_mask=channel_mask, sensor_type=sensor_type)
        valid_lc = window_mask[:, :, None] & channel_mask[:, None, :]
        learned = self._encode_waveform(x_norm, valid_lc)
        learned_z = _same_type_robust_z(
            learned,
            channel_mask=channel_mask,
            sensor_type=sensor_type,
            min_scale=0.05,
            clip_value=8.0,
            detach_reference=True,
        )
        stats = torch.where(valid_lc[:, :, :, None], stats, torch.zeros_like(stats))
        stat_z = torch.where(valid_lc[:, :, :, None], stat_z, torch.zeros_like(stat_z))
        learned = torch.where(valid_lc[:, :, :, None], learned, torch.zeros_like(learned))
        learned_z = torch.where(valid_lc[:, :, :, None], learned_z, torch.zeros_like(learned_z))
        features, diag = self._build_features(stats, stat_z, learned, learned_z, channel_mask, window_mask)
        logits, aux = self._type_aware_logits(features, channel_mask, sensor_type, compute_group=return_diagnostics)
        logits = torch.nan_to_num(logits, nan=0.0, posinf=0.0, neginf=0.0)
        if not return_diagnostics:
            return logits

        bsz = window_mask.shape[0]
        windows = window_mask.shape[1]
        global_badness = logits.new_zeros((bsz, windows, 2))
        window_weight = window_mask.float()
        severity = diag["severity"]
        diagnostics = {
            "window_stats": stats,
            "stat_z": stat_z,
            "learned_window_features": learned,
            "learned_z": learned_z,
            "residual_z": severity,
            "severity": severity,
            "stat_severity": diag["stat_severity"],
            "learned_severity": diag["learned_severity"],
            "global_badness": global_badness,
            "window_weight": window_weight,
            "persistence_features": diag["persistence_features"],
            "persistence_feature_names": self.feature_names,
            "same_type_global_features": diag["persistence_features"],
            "raw_logits": logits,
            "absolute_logits": aux["absolute_logits"],
            "relative_logits": aux["relative_logits"],
            "relative_gate": aux["relative_gate"],
            "group_logits": aux["group_logits"],
            "has_mag": ((sensor_type == SENSOR_MAG) & channel_mask).any(dim=1),
            "has_grad": ((sensor_type == SENSOR_GRAD) & channel_mask).any(dim=1),
        }
        return logits, diagnostics
