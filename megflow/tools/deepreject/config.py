# -*- coding: utf-8 -*-
"""Configuration helpers for the standalone Torch DeepReject package."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_CKPT = PACKAGE_DIR / "weights" / "best.pt"
DEFAULT_MODEL_CONFIG = PACKAGE_DIR / "weights" / "model_config.json"


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


def window_duration_from_config(config: Dict[str, Any], fallback: float = 2.0) -> float:
    value: Optional[Any] = config.get("window_duration_sec")
    if value is None:
        return float(fallback)
    return float(value)
