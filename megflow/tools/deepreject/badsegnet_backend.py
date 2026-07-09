# -*- coding: utf-8 -*-
"""BadSegNet five-fold ensemble inference."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import torch

from .config import (
    DEFAULT_BADSEGNET_WEIGHTS_DIR,
    DEFAULT_FOLDS,
    fold_dirs,
    load_model_config,
    window_duration_from_config,
)
from .torch_backend import load_torch_model, predict_data_list_torch


def _fold_paths(weights_dir: Path, folds: Sequence[int]) -> List[Tuple[int, Path, Path]]:
    out: List[Tuple[int, Path, Path]] = []
    for fold, fold_dir in zip(folds, fold_dirs(Path(weights_dir), list(folds)), strict=True):
        ckpt = fold_dir / "best.pt"
        cfg = fold_dir / "model_config.json"
        if not ckpt.is_file():
            raise FileNotFoundError(f"BadSegNet fold_{fold} checkpoint missing: {ckpt}")
        if not cfg.is_file():
            raise FileNotFoundError(f"BadSegNet fold_{fold} model_config missing: {cfg}")
        out.append((int(fold), ckpt, cfg))
    return out


def infer_window_duration(weights_dir: Path = DEFAULT_BADSEGNET_WEIGHTS_DIR, folds: Sequence[int] = DEFAULT_FOLDS) -> float:
    first = _fold_paths(Path(weights_dir), list(folds))[0][2]
    return window_duration_from_config(load_model_config(first), fallback=2.0)


def _predict_one_fold(
    fold: int,
    ckpt: Path,
    config: Path,
    data_list: Sequence[Any],
    *,
    device: torch.device,
    batch_size: int,
    encoder_chunk_size: Optional[int],
) -> Tuple[int, np.ndarray, np.ndarray]:
    model = load_torch_model(
        ckpt,
        config,
        device=device,
        encoder_chunk_size=encoder_chunk_size,
    )
    try:
        logits, _bad_logits, probs, _bad_probs = predict_data_list_torch(
            model,
            list(data_list),
            device=device,
            batch_size=batch_size,
        )
        return int(fold), logits.astype(np.float32, copy=False), probs.astype(np.float32, copy=False)
    finally:
        del model
        if device.type == "cuda":
            torch.cuda.empty_cache()


def load_badsegnet_models(
    *,
    weights_dir: Path = DEFAULT_BADSEGNET_WEIGHTS_DIR,
    folds: Sequence[int] = DEFAULT_FOLDS,
    device: torch.device,
    encoder_chunk_size: Optional[int] = None,
) -> List[Tuple[int, torch.nn.Module]]:
    """Load all BadSegNet fold models once for repeated-file inference."""
    models: List[Tuple[int, torch.nn.Module]] = []
    for fold, ckpt, cfg in _fold_paths(Path(weights_dir), list(folds)):
        model = load_torch_model(
            ckpt,
            cfg,
            device=device,
            encoder_chunk_size=encoder_chunk_size,
        )
        models.append((int(fold), model))
    return models


def _predict_loaded_one_fold(
    fold: int,
    model: torch.nn.Module,
    data_list: Sequence[Any],
    *,
    device: torch.device,
    batch_size: int,
) -> Tuple[int, np.ndarray, np.ndarray]:
    logits, _bad_logits, probs, _bad_probs = predict_data_list_torch(
        model,
        list(data_list),
        device=device,
        batch_size=batch_size,
    )
    return int(fold), logits.astype(np.float32, copy=False), probs.astype(np.float32, copy=False)


def predict_loaded_badsegnet_ensemble(
    models: Sequence[Tuple[int, torch.nn.Module]],
    data_list: Sequence[Any],
    *,
    device: torch.device,
    batch_size: int = 32,
    fold_workers: int = 5,
) -> Dict[str, np.ndarray]:
    loaded = list(models)
    workers = max(1, min(int(fold_workers), len(loaded)))
    results: List[Tuple[int, np.ndarray, np.ndarray]] = []
    if workers == 1:
        for fold, model in loaded:
            results.append(_predict_loaded_one_fold(fold, model, data_list, device=device, batch_size=batch_size))
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [
                ex.submit(_predict_loaded_one_fold, fold, model, data_list, device=device, batch_size=batch_size)
                for fold, model in loaded
            ]
            for fut in futs:
                results.append(fut.result())
    results.sort(key=lambda item: item[0])
    fold_ids = np.asarray([r[0] for r in results], dtype=np.int64)
    fold_logits = np.stack([r[1] for r in results], axis=0).astype(np.float32, copy=False)
    fold_probs = np.stack([r[2] for r in results], axis=0).astype(np.float32, copy=False)
    mean_probs = fold_probs.mean(axis=0).astype(np.float32, copy=False)
    return {
        "folds": fold_ids,
        "fold_logits": fold_logits,
        "fold_probs": fold_probs,
        "artifact_probs": mean_probs,
    }


def predict_badsegnet_ensemble(
    data_list: Sequence[Any],
    *,
    weights_dir: Path = DEFAULT_BADSEGNET_WEIGHTS_DIR,
    folds: Sequence[int] = DEFAULT_FOLDS,
    device: torch.device,
    batch_size: int = 0,
    encoder_chunk_size: Optional[int] = None,
    fold_workers: int = 5,
) -> Dict[str, np.ndarray]:
    paths = _fold_paths(Path(weights_dir), list(folds))
    workers = max(1, min(int(fold_workers), len(paths)))
    results: List[Tuple[int, np.ndarray, np.ndarray]] = []
    if workers == 1:
        for fold, ckpt, cfg in paths:
            results.append(
                _predict_one_fold(
                    fold,
                    ckpt,
                    cfg,
                    data_list,
                    device=device,
                    batch_size=batch_size,
                    encoder_chunk_size=encoder_chunk_size,
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
                    data_list,
                    device=device,
                    batch_size=batch_size,
                    encoder_chunk_size=encoder_chunk_size,
                )
                for fold, ckpt, cfg in paths
            ]
            for fut in futs:
                results.append(fut.result())
    results.sort(key=lambda item: item[0])
    fold_ids = np.asarray([r[0] for r in results], dtype=np.int64)
    fold_logits = np.stack([r[1] for r in results], axis=0).astype(np.float32, copy=False)
    fold_probs = np.stack([r[2] for r in results], axis=0).astype(np.float32, copy=False)
    mean_probs = fold_probs.mean(axis=0).astype(np.float32, copy=False)
    return {
        "folds": fold_ids,
        "fold_logits": fold_logits,
        "fold_probs": fold_probs,
        "artifact_probs": mean_probs,
    }
