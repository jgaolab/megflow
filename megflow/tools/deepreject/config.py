# -*- coding: utf-8 -*-
"""Configuration helpers for the standalone MEGFlow package."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


PACKAGE_DIR = Path(__file__).resolve().parent
WEIGHTS_DIR = PACKAGE_DIR / "weights"

# Legacy single-checkpoint constants kept for compatibility with old imports.
# The final standalone runtime uses the fold directories below instead.
DEFAULT_CKPT = WEIGHTS_DIR / "best.pt"
DEFAULT_MODEL_CONFIG = WEIGHTS_DIR / "model_config.json"

DEFAULT_BADSEGNET_WEIGHTS_DIR = WEIGHTS_DIR / "badsegnet"
DEFAULT_BADCHNNET_WEIGHTS_DIR = WEIGHTS_DIR / "badchnnet"
DEFAULT_FOLDS = (0, 1, 2, 3, 4)

BADSEGNET_POSTPROCESS = {
    "hysteresis_high": 0.89,
    "hysteresis_low": 0.18,
    "merge_gap_sec": 10.0,
    "min_duration_sec": 0.0,
    "short_keep_threshold": 0.97,
}

BADCHNNET_POSTPROCESS = {
    "lambda_lcb": 1.0,
    "floor": 0.56,
    "z": 3.0,
    "min_type_channels": 8,
}


MODEL_CONFIG_TO_DEEPREJECT_KWARGS = {
    "learned_feat_dim": "learned_feat_dim",
    "gnn_hidden_dim": "gnn_hidden_dim",
    "gnn_num_layers": "gnn_num_layers",
    "gnn_conv_type": "gnn_conv_type",
    "gnn_conv_heads": "gnn_conv_heads",
    "gnn_sage_aggr": "gnn_sage_aggr",
    "gnn_cheb_K": "gnn_cheb_K",
    "graph_pool": "graph_pool",
    "transformer_num_layers": "transformer_num_layers",
    "num_attention_heads": "num_attention_heads",
    "transformer_ff_dim": "transformer_ff_dim",
    "prediction_hidden_dim": "prediction_hidden_dim",
    "pre_logit_embed_dim": "pre_logit_embed_dim",
    "use_bad_channel_head": "use_bad_channel_head",
    "encoder_chunk_size": "encoder_chunk_size",
    "window_norm": "window_norm",
    "encoder_norm": "encoder_norm",
    "temporal_encoder_version": "temporal_encoder_version",
    "multiscale_pool": "multiscale_pool",
    "temporal_input_mode": "temporal_input_mode",
    "temporal_diff_branch": "temporal_diff_branch",
    "diff_branch_feat_dim": "diff_branch_feat_dim",
    "use_temporal_encoder_checkpoint": "use_temporal_encoder_checkpoint",
    "temporal_encoder_checkpoint_mode": "temporal_encoder_checkpoint_mode",
    "use_raw_correction_gate": "use_raw_correction_gate",
    "raw_correction_hidden_dim": "raw_correction_hidden_dim",
    "raw_correction_feat_dim": "raw_correction_feat_dim",
    "raw_correction_max_scale": "raw_correction_max_scale",
    "raw_correction_max_shift": "raw_correction_max_shift",
    "use_channel_metadata": "use_channel_metadata",
    "sensor_type_embed_dim": "sensor_type_embed_dim",
    "position_embed_dim": "position_embed_dim",
    "temporal_context": "temporal_context",
    "temporal_pos_encoding": "temporal_pos_encoding",
    "use_sequence_tcn_head": "use_sequence_tcn_head",
    "sequence_tcn_layers": "sequence_tcn_layers",
    "sequence_tcn_kernel_size": "sequence_tcn_kernel_size",
    "use_local_mil_artifact_branch": "use_local_mil_artifact_branch",
    "local_mil_pool": "local_mil_pool",
    "local_mil_topk": "local_mil_topk",
    "local_mil_gate_init": "local_mil_gate_init",
    "use_cross_task_gating": "use_cross_task_gating",
    "cross_task_gate_init": "cross_task_gate_init",
    "cross_task_max_gate": "cross_task_max_gate",
    "cross_task_topk": "cross_task_topk",
    "detach_cross_task_summary": "detach_cross_task_summary",
    "use_bad_channel_trajectory_tcn": "use_bad_channel_trajectory_tcn",
    "bad_channel_tcn_layers": "bad_channel_tcn_layers",
    "bad_channel_tcn_kernel_size": "bad_channel_tcn_kernel_size",
}


def load_model_config(config_path: Path) -> Dict[str, Any]:
    with Path(config_path).open("r", encoding="utf-8") as f:
        return json.load(f)


def fold_dirs(weights_dir: Path, folds: Optional[List[int]] = None) -> List[Path]:
    fold_ids = list(DEFAULT_FOLDS if folds is None else folds)
    return [Path(weights_dir) / f"fold_{int(fold)}" for fold in fold_ids]


def deepreject_kwargs_from_config(config: Dict[str, Any]) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}
    for key, kw in MODEL_CONFIG_TO_DEEPREJECT_KWARGS.items():
        if key in config:
            kwargs[kw] = config[key]
    if kwargs.get("transformer_ff_dim", None) == 0:
        kwargs["transformer_ff_dim"] = None
    if kwargs.get("pre_logit_embed_dim", None) == 0:
        kwargs["pre_logit_embed_dim"] = None
    if kwargs.get("encoder_chunk_size", None) == 0:
        kwargs["encoder_chunk_size"] = None
    return kwargs


def badchnnet_kwargs_from_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Extract V11BadChannelNet kwargs from a saved fold model_config.json."""
    cfg = dict(config.get("model_config") or config)
    cfg.pop("global_feature_dim", None)
    return cfg


def window_duration_from_config(config: Dict[str, Any], fallback: float = 2.0) -> float:
    args = config.get("args") if isinstance(config.get("args"), dict) else {}
    value: Optional[Any] = config.get("window_duration_sec", args.get("duration_sec"))
    if value is None:
        return float(fallback)
    return float(value)


def chunk_config_from_badchnnet_config(config: Dict[str, Any]) -> Dict[str, int]:
    args = config.get("args") if isinstance(config.get("args"), dict) else {}
    return {
        "chunk_windows": int(args.get("chunk_windows") or 128),
        "chunk_stride": int(args.get("chunk_stride") or args.get("chunk_windows") or 128),
        "min_chunk_windows": int(args.get("min_chunk_windows") or 8),
    }
