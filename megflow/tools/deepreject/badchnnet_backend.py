# -*- coding: utf-8 -*-
"""BadChnNet five-fold ensemble inference."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import torch

from .config import (
    DEFAULT_BADCHNNET_WEIGHTS_DIR,
    DEFAULT_FOLDS,
    badchnnet_kwargs_from_config,
    chunk_config_from_badchnnet_config,
    fold_dirs,
    load_model_config,
    window_duration_from_config,
)
from .model.badchannel_v11 import V11BadChannelNet
from .postprocess import predict_bad_channels_lcb_per_type_mad


def _fold_paths(weights_dir: Path, folds: Sequence[int]) -> List[Tuple[int, Path, Path]]:
    out: List[Tuple[int, Path, Path]] = []
    for fold, fold_dir in zip(folds, fold_dirs(Path(weights_dir), list(folds)), strict=True):
        ckpt = fold_dir / "best.pt"
        cfg = fold_dir / "model_config.json"
        if not ckpt.is_file():
            raise FileNotFoundError(f"BadChnNet fold_{fold} checkpoint missing: {ckpt}")
        if not cfg.is_file():
            raise FileNotFoundError(f"BadChnNet fold_{fold} model_config missing: {cfg}")
        out.append((int(fold), ckpt, cfg))
    return out


def _chunk_spans(
    n_windows: int,
    *,
    chunk_windows: int,
    chunk_stride: int,
    min_chunk_windows: int,
) -> List[Tuple[int, int]]:
    n = int(n_windows)
    if n <= 0:
        return []
    cw = max(int(chunk_windows), 1)
    stride = max(int(chunk_stride), 1)
    if n <= cw:
        return [(0, n)]
    spans: List[Tuple[int, int]] = []
    for start in range(0, n, stride):
        end = min(start + cw, n)
        if end - start >= int(min_chunk_windows):
            spans.append((start, end))
        if end >= n:
            break
    final = (max(0, n - cw), n)
    if spans and spans[-1] != final and final[1] - final[0] >= int(min_chunk_windows):
        spans.append(final)
    if not spans:
        spans = [(0, n)]
    uniq: List[Tuple[int, int]] = []
    seen = set()
    for sp in spans:
        if sp not in seen:
            uniq.append(sp)
            seen.add(sp)
    return uniq


def infer_window_duration(weights_dir: Path = DEFAULT_BADCHNNET_WEIGHTS_DIR, folds: Sequence[int] = DEFAULT_FOLDS) -> float:
    first = _fold_paths(Path(weights_dir), list(folds))[0][2]
    return window_duration_from_config(load_model_config(first), fallback=2.0)


def infer_chunk_config(weights_dir: Path = DEFAULT_BADCHNNET_WEIGHTS_DIR, folds: Sequence[int] = DEFAULT_FOLDS) -> Dict[str, int]:
    first = _fold_paths(Path(weights_dir), list(folds))[0][2]
    return chunk_config_from_badchnnet_config(load_model_config(first))


def load_badchnnet_model(ckpt_path: Path, config_path: Path, *, device: torch.device) -> V11BadChannelNet:
    cfg = badchnnet_kwargs_from_config(load_model_config(config_path))
    model = V11BadChannelNet(**cfg).to(device)
    try:
        obj = torch.load(Path(ckpt_path), map_location=device, weights_only=True)
    except TypeError:
        obj = torch.load(Path(ckpt_path), map_location=device)
    state = obj.get("model_state", obj) if isinstance(obj, dict) else obj
    if not isinstance(state, dict):
        raise ValueError(f"Cannot read state_dict from {ckpt_path}")
    if any(str(k).startswith("module.") for k in state.keys()):
        state = {str(k).removeprefix("module."): v for k, v in state.items()}
    model.load_state_dict(state, strict=True)
    model.eval()
    return model


def _make_batch(rec: Dict[str, Any], start: int, end: int, device: torch.device) -> Dict[str, torch.Tensor]:
    x = torch.from_numpy(rec["x"][start:end]).unsqueeze(0).float()
    n_channels = int(x.shape[2])
    n_windows = int(x.shape[1])
    return {
        "x": x.to(device),
        "channel_pos": torch.from_numpy(rec["channel_pos"]).unsqueeze(0).float().to(device),
        "sensor_type": torch.from_numpy(rec["sensor_type"]).unsqueeze(0).long().to(device),
        "channel_mask": torch.ones(1, n_channels, dtype=torch.bool, device=device),
        "window_mask": torch.ones(1, n_windows, dtype=torch.bool, device=device),
    }


@torch.no_grad()
def infer_badchnnet_recording(
    model: V11BadChannelNet,
    rec: Dict[str, Any],
    *,
    device: torch.device,
    chunk_windows: int,
    chunk_stride: int,
    min_chunk_windows: int,
    chunk_prob_aggregation: str = "mean",
) -> np.ndarray:
    n_windows = int(rec["x"].shape[0])
    spans = _chunk_spans(
        n_windows,
        chunk_windows=int(chunk_windows),
        chunk_stride=int(chunk_stride),
        min_chunk_windows=int(min_chunk_windows),
    )
    probs: List[torch.Tensor] = []
    for start, end in spans:
        logits = model(_make_batch(rec, int(start), int(end), device))
        probs.append(torch.sigmoid(logits[0]).detach().cpu())
    stacked = torch.stack(probs, dim=0)
    if chunk_prob_aggregation == "mean":
        out = stacked.mean(dim=0)
    elif chunk_prob_aggregation == "max":
        out = stacked.max(dim=0).values
    else:
        raise ValueError(f"unknown chunk_prob_aggregation: {chunk_prob_aggregation}")
    return out.numpy().astype(np.float32, copy=False)


def _predict_one_fold(
    fold: int,
    ckpt: Path,
    config: Path,
    rec: Dict[str, Any],
    *,
    device: torch.device,
    chunk_windows: int,
    chunk_stride: int,
    min_chunk_windows: int,
    chunk_prob_aggregation: str,
) -> Tuple[int, np.ndarray]:
    model = load_badchnnet_model(ckpt, config, device=device)
    try:
        probs = infer_badchnnet_recording(
            model,
            rec,
            device=device,
            chunk_windows=chunk_windows,
            chunk_stride=chunk_stride,
            min_chunk_windows=min_chunk_windows,
            chunk_prob_aggregation=chunk_prob_aggregation,
        )
        return int(fold), probs
    finally:
        del model
        if device.type == "cuda":
            torch.cuda.empty_cache()


def load_badchnnet_models(
    *,
    weights_dir: Path = DEFAULT_BADCHNNET_WEIGHTS_DIR,
    folds: Sequence[int] = DEFAULT_FOLDS,
    device: torch.device,
) -> List[Tuple[int, V11BadChannelNet]]:
    """Load all BadChnNet fold models once for repeated-file inference."""
    models: List[Tuple[int, V11BadChannelNet]] = []
    for fold, ckpt, cfg in _fold_paths(Path(weights_dir), list(folds)):
        models.append((int(fold), load_badchnnet_model(ckpt, cfg, device=device)))
    return models


def _predict_loaded_one_fold(
    fold: int,
    model: V11BadChannelNet,
    rec: Dict[str, Any],
    *,
    device: torch.device,
    chunk_windows: int,
    chunk_stride: int,
    min_chunk_windows: int,
    chunk_prob_aggregation: str,
) -> Tuple[int, np.ndarray]:
    probs = infer_badchnnet_recording(
        model,
        rec,
        device=device,
        chunk_windows=chunk_windows,
        chunk_stride=chunk_stride,
        min_chunk_windows=min_chunk_windows,
        chunk_prob_aggregation=chunk_prob_aggregation,
    )
    return int(fold), probs


def predict_loaded_badchnnet_ensemble(
    models: Sequence[Tuple[int, V11BadChannelNet]],
    rec: Dict[str, Any],
    *,
    weights_dir: Path = DEFAULT_BADCHNNET_WEIGHTS_DIR,
    folds: Sequence[int] = DEFAULT_FOLDS,
    device: torch.device,
    fold_workers: int = 5,
    chunk_windows: Optional[int] = None,
    chunk_stride: Optional[int] = None,
    min_chunk_windows: Optional[int] = None,
    chunk_prob_aggregation: str = "mean",
    lambda_lcb: float = 1.0,
    floor: float = 0.56,
    z: float = 3.0,
    min_type_channels: int = 8,
) -> Dict[str, np.ndarray]:
    loaded = list(models)
    inferred = infer_chunk_config(Path(weights_dir), list(folds))
    cw = int(chunk_windows or inferred["chunk_windows"])
    cs = int(chunk_stride or inferred["chunk_stride"])
    mcw = int(min_chunk_windows or inferred["min_chunk_windows"])
    workers = max(1, min(int(fold_workers), len(loaded)))
    results: List[Tuple[int, np.ndarray]] = []
    if workers == 1:
        for fold, model in loaded:
            results.append(
                _predict_loaded_one_fold(
                    fold,
                    model,
                    rec,
                    device=device,
                    chunk_windows=cw,
                    chunk_stride=cs,
                    min_chunk_windows=mcw,
                    chunk_prob_aggregation=chunk_prob_aggregation,
                )
            )
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [
                ex.submit(
                    _predict_loaded_one_fold,
                    fold,
                    model,
                    rec,
                    device=device,
                    chunk_windows=cw,
                    chunk_stride=cs,
                    min_chunk_windows=mcw,
                    chunk_prob_aggregation=chunk_prob_aggregation,
                )
                for fold, model in loaded
            ]
            for fut in futs:
                results.append(fut.result())
    results.sort(key=lambda item: item[0])
    fold_ids = np.asarray([r[0] for r in results], dtype=np.int64)
    fold_probs = np.stack([r[1] for r in results], axis=0).astype(np.float32, copy=False)
    pred, mean_prob, fold_std, lcb_score = predict_bad_channels_lcb_per_type_mad(
        rec["ch_names"],
        fold_probs,
        lambda_lcb=float(lambda_lcb),
        floor=float(floor),
        z=float(z),
        min_type_channels=int(min_type_channels),
    )
    return {
        "folds": fold_ids,
        "fold_probs": fold_probs,
        "bad_channel_probs": mean_prob,
        "bad_channel_fold_std": fold_std,
        "bad_channel_lcb_score": lcb_score,
        "bad_channel_pred": pred,
    }


def predict_badchnnet_ensemble(
    rec: Dict[str, Any],
    *,
    weights_dir: Path = DEFAULT_BADCHNNET_WEIGHTS_DIR,
    folds: Sequence[int] = DEFAULT_FOLDS,
    device: torch.device,
    fold_workers: int = 5,
    chunk_windows: Optional[int] = None,
    chunk_stride: Optional[int] = None,
    min_chunk_windows: Optional[int] = None,
    chunk_prob_aggregation: str = "mean",
    lambda_lcb: float = 1.0,
    floor: float = 0.56,
    z: float = 3.0,
    min_type_channels: int = 8,
) -> Dict[str, np.ndarray]:
    paths = _fold_paths(Path(weights_dir), list(folds))
    inferred = infer_chunk_config(Path(weights_dir), list(folds))
    cw = int(chunk_windows or inferred["chunk_windows"])
    cs = int(chunk_stride or inferred["chunk_stride"])
    mcw = int(min_chunk_windows or inferred["min_chunk_windows"])
    workers = max(1, min(int(fold_workers), len(paths)))
    results: List[Tuple[int, np.ndarray]] = []
    if workers == 1:
        for fold, ckpt, cfg in paths:
            results.append(
                _predict_one_fold(
                    fold,
                    ckpt,
                    cfg,
                    rec,
                    device=device,
                    chunk_windows=cw,
                    chunk_stride=cs,
                    min_chunk_windows=mcw,
                    chunk_prob_aggregation=chunk_prob_aggregation,
                )
            )
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [
                ex.submit(
                    _predict_one_fold,
                    fold,
                    ckpt,
                    cfg,
                    rec,
                    device=device,
                    chunk_windows=cw,
                    chunk_stride=cs,
                    min_chunk_windows=mcw,
                    chunk_prob_aggregation=chunk_prob_aggregation,
                )
                for fold, ckpt, cfg in paths
            ]
            for fut in futs:
                results.append(fut.result())
    results.sort(key=lambda item: item[0])
    fold_ids = np.asarray([r[0] for r in results], dtype=np.int64)
    fold_probs = np.stack([r[1] for r in results], axis=0).astype(np.float32, copy=False)
    pred, mean_prob, fold_std, lcb_score = predict_bad_channels_lcb_per_type_mad(
        rec["ch_names"],
        fold_probs,
        lambda_lcb=float(lambda_lcb),
        floor=float(floor),
        z=float(z),
        min_type_channels=int(min_type_channels),
    )
    return {
        "folds": fold_ids,
        "fold_probs": fold_probs,
        "bad_channel_probs": mean_prob,
        "bad_channel_fold_std": fold_std,
        "bad_channel_lcb_score": lcb_score,
        "bad_channel_pred": pred,
    }
