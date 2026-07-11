# -*- coding: utf-8 -*-
"""Standalone runtime for the final BadSegNet + BadChnNet models."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np
import torch

from .badchnnet_backend import infer_window_duration as infer_badchnnet_window_duration
from .badchnnet_backend import load_badchnnet_models, predict_badchnnet_ensemble, predict_loaded_badchnnet_ensemble
from .badsegnet_backend import infer_window_duration as infer_badsegnet_window_duration
from .badsegnet_backend import load_badsegnet_models, predict_badsegnet_ensemble, predict_loaded_badsegnet_ensemble
from .config import (
    BADCHNNET_POSTPROCESS,
    BADSEGNET_POSTPROCESS,
    DEFAULT_BADCHNNET_WEIGHTS_DIR,
    DEFAULT_BADSEGNET_WEIGHTS_DIR,
    DEFAULT_FOLDS,
)
from .postprocess import artifact_probs_to_bad_intervals
from .preprocessing import build_badchnnet_record, build_torch_data_list, load_single_fif_record


def _mask_record_bad_channels(record, bad_channels: Sequence[str]):
    """Return a shallow record copy with BadChnNet bad channels masked for BadSegNet."""
    bad_name_set = {str(name) for name in bad_channels or [] if str(name)}
    if not bad_name_set:
        return record

    ch_names = list(record.get("ch_names") or [])
    if not ch_names:
        return record

    n_channels = len(ch_names)
    node_valid = np.asarray(record.get("node_valid", np.ones(n_channels)), dtype=np.int64).reshape(-1)
    if node_valid.shape[0] != n_channels:
        node_valid = np.ones(n_channels, dtype=np.int64)

    bad_mask = np.asarray([1 if name in bad_name_set else 0 for name in ch_names], dtype=np.int64)
    if not bad_mask.any():
        return record

    masked_record = dict(record)
    masked_record["node_valid"] = (node_valid * (1 - bad_mask)).astype(np.int64, copy=False)

    y_bad_channel = np.asarray(record.get("y_bad_channel", np.zeros(n_channels)), dtype=np.int64).reshape(-1)
    if y_bad_channel.shape[0] == n_channels:
        masked_record["y_bad_channel"] = np.maximum(y_bad_channel, bad_mask).astype(np.int64, copy=False)

    return masked_record


@dataclass
class DeepRejectPrediction:
    """Prediction output from the final standalone runtime."""

    ch_names: List[str]
    bad_intervals: List[Tuple[float, float]]
    bad_channels: List[str]
    window_duration_sec: float
    artifact_probs: np.ndarray
    artifact_fold_probs: np.ndarray
    artifact_fold_logits: np.ndarray
    artifact_pred: np.ndarray
    bad_channel_probs: np.ndarray
    bad_channel_fold_probs: np.ndarray
    bad_channel_fold_std: np.ndarray
    bad_channel_lcb_score: np.ndarray
    bad_channel_pred: np.ndarray
    artifact_folds: np.ndarray
    bad_channel_folds: np.ndarray
    backend: str = "torch"

    @property
    def bad_channel_mean_probs(self) -> np.ndarray:
        return self.bad_channel_probs


class DeepRejectPredictor:
    """Reusable final BadSegNet + BadChnNet inference wrapper.

    The class name is kept for compatibility with the original standalone
    package, but the runtime now uses two finalized paper models:
    BadSegNet for bad-segment detection and BadChnNet for bad-channel detection.
    """

    def __init__(
        self,
        device: str = "auto",
        *,
        badsegnet_weights_dir: Path = DEFAULT_BADSEGNET_WEIGHTS_DIR,
        badchnnet_weights_dir: Path = DEFAULT_BADCHNNET_WEIGHTS_DIR,
        folds: Sequence[int] = DEFAULT_FOLDS,
        fold_workers: int = 5,
        cache_models: bool = True,
        cpu_threads: Optional[int] = 4,
        cpu_interop_threads: Optional[int] = 1,
        badsegnet_batch_size: int = 32,
        badsegnet_encoder_chunk_size: Optional[int] = None,
        badsegnet_edge_k: int = 6,
        badchnnet_chunk_windows: Optional[int] = None,
        badchnnet_chunk_stride: Optional[int] = None,
        badchnnet_min_chunk_windows: Optional[int] = None,
        badchnnet_chunk_prob_aggregation: str = "mean",
        badsegnet_hysteresis_high: float = BADSEGNET_POSTPROCESS["hysteresis_high"],
        badsegnet_hysteresis_low: float = BADSEGNET_POSTPROCESS["hysteresis_low"],
        badsegnet_merge_gap_sec: float = BADSEGNET_POSTPROCESS["merge_gap_sec"],
        badsegnet_min_duration_sec: float = BADSEGNET_POSTPROCESS["min_duration_sec"],
        badsegnet_short_keep_threshold: Optional[float] = BADSEGNET_POSTPROCESS["short_keep_threshold"],
        badchnnet_lambda_lcb: float = BADCHNNET_POSTPROCESS["lambda_lcb"],
        badchnnet_floor: float = BADCHNNET_POSTPROCESS["floor"],
        badchnnet_z: float = BADCHNNET_POSTPROCESS["z"],
        badchnnet_min_type_channels: int = BADCHNNET_POSTPROCESS["min_type_channels"],
    ):
        self.device = _resolve_device(device)
        if self.device.type == "cpu":
            _apply_torch_cpu_threads(cpu_threads, cpu_interop_threads)
        self.badsegnet_weights_dir = Path(badsegnet_weights_dir)
        self.badchnnet_weights_dir = Path(badchnnet_weights_dir)
        self.folds = tuple(int(fold) for fold in folds)
        self.fold_workers = int(fold_workers)
        self.cache_models = bool(cache_models)
        self.cpu_threads = cpu_threads
        self.cpu_interop_threads = cpu_interop_threads
        self.badsegnet_batch_size = int(badsegnet_batch_size)
        self.badsegnet_encoder_chunk_size = badsegnet_encoder_chunk_size
        self.badsegnet_edge_k = int(badsegnet_edge_k)
        self.badchnnet_chunk_windows = badchnnet_chunk_windows
        self.badchnnet_chunk_stride = badchnnet_chunk_stride
        self.badchnnet_min_chunk_windows = badchnnet_min_chunk_windows
        self.badchnnet_chunk_prob_aggregation = str(badchnnet_chunk_prob_aggregation)
        self.badsegnet_hysteresis_high = float(badsegnet_hysteresis_high)
        self.badsegnet_hysteresis_low = float(badsegnet_hysteresis_low)
        self.badsegnet_merge_gap_sec = float(badsegnet_merge_gap_sec)
        self.badsegnet_min_duration_sec = float(badsegnet_min_duration_sec)
        self.badsegnet_short_keep_threshold = (
            None if badsegnet_short_keep_threshold is None else float(badsegnet_short_keep_threshold)
        )
        self.badchnnet_lambda_lcb = float(badchnnet_lambda_lcb)
        self.badchnnet_floor = float(badchnnet_floor)
        self.badchnnet_z = float(badchnnet_z)
        self.badchnnet_min_type_channels = int(badchnnet_min_type_channels)
        self.badsegnet_window_duration_sec = infer_badsegnet_window_duration(self.badsegnet_weights_dir, self.folds)
        self.badchnnet_window_duration_sec = infer_badchnnet_window_duration(self.badchnnet_weights_dir, self.folds)
        self._badsegnet_models = None
        self._badchnnet_models = None

    def preload_models(self, *, run_bad_segments: bool = True, run_bad_channels: bool = True) -> None:
        """Load fold models into memory/GPU once for repeated-file inference."""
        if run_bad_segments and self._badsegnet_models is None:
            self._badsegnet_models = load_badsegnet_models(
                weights_dir=self.badsegnet_weights_dir,
                folds=self.folds,
                device=self.device,
                encoder_chunk_size=self.badsegnet_encoder_chunk_size,
            )
        if run_bad_channels and self._badchnnet_models is None:
            self._badchnnet_models = load_badchnnet_models(
                weights_dir=self.badchnnet_weights_dir,
                folds=self.folds,
                device=self.device,
            )

    def predict_fif(
        self,
        fif_path: Path,
        *,
        annot_root: Optional[Path] = None,
        category: Optional[str] = None,
        dataset: Optional[str] = None,
        meg_scale_mag: float = 1e15,
        meg_scale_grad: float = 1e13,
        pick_exclude_marked_bads: bool = False,
        filter_l_freq: Optional[float] = None,
        filter_h_freq: Optional[float] = None,
        resample_sfreq: Optional[float] = None,
        run_bad_segments: bool = True,
        run_bad_channels: bool = True,
    ) -> DeepRejectPrediction:
        if not run_bad_segments and not run_bad_channels:
            raise ValueError("At least one of run_bad_segments/run_bad_channels must be True")

        record = load_single_fif_record(
            Path(fif_path),
            annot_root,
            category,
            dataset,
            meg_scale_mag,
            meg_scale_grad,
            self.badsegnet_window_duration_sec,
            pick_exclude_marked_bads=pick_exclude_marked_bads,
            filter_l_freq=filter_l_freq,
            filter_h_freq=filter_h_freq,
            resample_sfreq=resample_sfreq,
        )
        ch_names = list(record.get("ch_names") or [])

        artifact_folds = np.asarray([], dtype=np.int64)
        artifact_fold_probs = np.empty((0, len(record["window_signals"])), dtype=np.float32)
        artifact_fold_logits = np.empty((0, len(record["window_signals"]), 2), dtype=np.float32)
        artifact_probs = np.zeros(len(record["window_signals"]), dtype=np.float32)
        artifact_pred = np.zeros(len(record["window_signals"]), dtype=np.int64)
        bad_intervals: List[Tuple[float, float]] = []

        bad_channel_folds = np.asarray([], dtype=np.int64)
        bad_channel_fold_probs = np.empty((0, len(ch_names)), dtype=np.float32)
        bad_channel_probs = np.zeros(len(ch_names), dtype=np.float32)
        bad_channel_fold_std = np.zeros(len(ch_names), dtype=np.float32)
        bad_channel_lcb_score = np.zeros(len(ch_names), dtype=np.float32)
        bad_channel_pred = np.zeros(len(ch_names), dtype=np.int64)

        if run_bad_channels:
            if abs(self.badchnnet_window_duration_sec - self.badsegnet_window_duration_sec) < 1e-9:
                ch_record_base = record
            else:
                ch_record_base = load_single_fif_record(
                    Path(fif_path),
                    annot_root,
                    category,
                    dataset,
                    meg_scale_mag,
                    meg_scale_grad,
                    self.badchnnet_window_duration_sec,
                    pick_exclude_marked_bads=pick_exclude_marked_bads,
                    filter_l_freq=filter_l_freq,
                    filter_h_freq=filter_h_freq,
                    resample_sfreq=resample_sfreq,
                )
            ch_record = build_badchnnet_record(ch_record_base)
            if self.cache_models:
                self.preload_models(run_bad_segments=False, run_bad_channels=True)
                chn = predict_loaded_badchnnet_ensemble(
                    self._badchnnet_models,
                    ch_record,
                    weights_dir=self.badchnnet_weights_dir,
                    folds=self.folds,
                    device=self.device,
                    fold_workers=self.fold_workers,
                    chunk_windows=self.badchnnet_chunk_windows,
                    chunk_stride=self.badchnnet_chunk_stride,
                    min_chunk_windows=self.badchnnet_min_chunk_windows,
                    chunk_prob_aggregation=self.badchnnet_chunk_prob_aggregation,
                    lambda_lcb=self.badchnnet_lambda_lcb,
                    floor=self.badchnnet_floor,
                    z=self.badchnnet_z,
                    min_type_channels=self.badchnnet_min_type_channels,
                )
            else:
                chn = predict_badchnnet_ensemble(
                    ch_record,
                    weights_dir=self.badchnnet_weights_dir,
                    folds=self.folds,
                    device=self.device,
                    fold_workers=self.fold_workers,
                    chunk_windows=self.badchnnet_chunk_windows,
                    chunk_stride=self.badchnnet_chunk_stride,
                    min_chunk_windows=self.badchnnet_min_chunk_windows,
                    chunk_prob_aggregation=self.badchnnet_chunk_prob_aggregation,
                    lambda_lcb=self.badchnnet_lambda_lcb,
                    floor=self.badchnnet_floor,
                    z=self.badchnnet_z,
                    min_type_channels=self.badchnnet_min_type_channels,
                )
            bad_channel_folds = chn["folds"]
            bad_channel_fold_probs = chn["fold_probs"]
            bad_channel_probs = chn["bad_channel_probs"]
            bad_channel_fold_std = chn["bad_channel_fold_std"]
            bad_channel_lcb_score = chn["bad_channel_lcb_score"]
            bad_channel_pred = chn["bad_channel_pred"]
            ch_names = list(ch_record["ch_names"])
            del ch_record

        bad_channels = [name for name, flag in zip(ch_names, bad_channel_pred, strict=False) if int(flag)]

        if run_bad_segments:
            segment_record = _mask_record_bad_channels(record, bad_channels)
            data_list = build_torch_data_list(segment_record, edge_k=self.badsegnet_edge_k)
            if self.cache_models:
                self.preload_models(run_bad_segments=True, run_bad_channels=False)
                seg = predict_loaded_badsegnet_ensemble(
                    self._badsegnet_models,
                    data_list,
                    device=self.device,
                    batch_size=self.badsegnet_batch_size,
                    fold_workers=self.fold_workers,
                )
            else:
                seg = predict_badsegnet_ensemble(
                    data_list,
                    weights_dir=self.badsegnet_weights_dir,
                    folds=self.folds,
                    device=self.device,
                    batch_size=self.badsegnet_batch_size,
                    encoder_chunk_size=self.badsegnet_encoder_chunk_size,
                    fold_workers=self.fold_workers,
                )
            artifact_folds = seg["folds"]
            artifact_fold_probs = seg["fold_probs"]
            artifact_fold_logits = seg["fold_logits"]
            artifact_probs = seg["artifact_probs"]
            artifact_pred = (artifact_probs >= self.badsegnet_hysteresis_high).astype(np.int64)
            bad_intervals = artifact_probs_to_bad_intervals(
                artifact_probs,
                duration_sec=self.badsegnet_window_duration_sec,
                hysteresis_high=self.badsegnet_hysteresis_high,
                hysteresis_low=self.badsegnet_hysteresis_low,
                merge_gap_sec=self.badsegnet_merge_gap_sec,
                min_duration_sec=self.badsegnet_min_duration_sec,
                short_keep_threshold=self.badsegnet_short_keep_threshold,
            )
            del data_list

        return DeepRejectPrediction(
            ch_names=ch_names,
            bad_intervals=bad_intervals,
            bad_channels=bad_channels,
            window_duration_sec=self.badsegnet_window_duration_sec,
            artifact_probs=artifact_probs.astype(np.float32, copy=False),
            artifact_fold_probs=artifact_fold_probs.astype(np.float32, copy=False),
            artifact_fold_logits=artifact_fold_logits.astype(np.float32, copy=False),
            artifact_pred=artifact_pred.astype(np.int64, copy=False),
            bad_channel_probs=bad_channel_probs.astype(np.float32, copy=False),
            bad_channel_fold_probs=bad_channel_fold_probs.astype(np.float32, copy=False),
            bad_channel_fold_std=bad_channel_fold_std.astype(np.float32, copy=False),
            bad_channel_lcb_score=bad_channel_lcb_score.astype(np.float32, copy=False),
            bad_channel_pred=bad_channel_pred.astype(np.int64, copy=False),
            artifact_folds=artifact_folds.astype(np.int64, copy=False),
            bad_channel_folds=bad_channel_folds.astype(np.int64, copy=False),
        )

    def save_prediction(
        self,
        prediction: DeepRejectPrediction,
        output_dir: Path,
        *,
        stem: str,
        segment_suffix: str = "_bad_seg.txt",
        channel_suffix: str = "_bad_chn.txt",
        save_probabilities: bool = True,
    ) -> None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        _write_mne_annot_txt(output_dir / f"{stem}{segment_suffix}", prediction.bad_intervals)
        _write_bad_channels_txt(output_dir / f"{stem}{channel_suffix}", prediction.bad_channels)
        if save_probabilities:
            _write_artifact_probs_tsv(
                output_dir / f"{stem}_artifact_probs.tsv",
                prediction.artifact_probs,
                prediction.artifact_pred,
                duration_sec=prediction.window_duration_sec,
            )
            _write_bad_channel_probs_tsv(
                output_dir / f"{stem}_bad_channel_probs.tsv",
                prediction.ch_names,
                prediction.bad_channel_probs,
                prediction.bad_channel_fold_std,
                prediction.bad_channel_lcb_score,
                prediction.bad_channel_pred,
            )


def _write_mne_annot_txt(path: Path, intervals: List[Tuple[float, float]], description: str = "bad_deepreject") -> None:
    lines = [
        "# MNE-Annotations",
        "# orig_time : 1970-01-01 00:00:00",
        "# onset, duration, description",
    ]
    for onset, end in intervals:
        duration = float(end) - float(onset)
        if duration > 0:
            lines.append(f"{float(onset)},{duration},{description}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_bad_channels_txt(path: Path, names: Sequence[str]) -> None:
    lines = [str(name) for name in names if str(name)]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _write_artifact_probs_tsv(path: Path, probs: np.ndarray, preds: np.ndarray, *, duration_sec: float) -> None:
    p = np.asarray(probs, dtype=np.float32).reshape(-1)
    pred_arr = np.asarray(preds).reshape(-1)
    lines = ["window_idx\tonset_sec\tend_sec\tartifact_prob\tinitial_pred"]
    dur = float(duration_sec)
    for i, prob in enumerate(p):
        initial_pred = str(int(pred_arr[i])) if i < pred_arr.shape[0] else ""
        lines.append(f"{i}\t{i * dur:.6f}\t{(i + 1) * dur:.6f}\t{float(prob):.8g}\t{initial_pred}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_bad_channel_probs_tsv(
    path: Path,
    ch_names: Sequence[str],
    probs: np.ndarray,
    fold_std: np.ndarray,
    lcb_score: np.ndarray,
    preds: np.ndarray,
) -> None:
    p = np.asarray(probs, dtype=np.float32).reshape(-1)
    sd = np.asarray(fold_std, dtype=np.float32).reshape(-1)
    score = np.asarray(lcb_score, dtype=np.float32).reshape(-1)
    pred_arr = np.asarray(preds).reshape(-1)
    lines = ["channel_idx\tchannel_name\tbad_channel_prob\tfold_std\tlcb_score\tinitial_pred"]
    for i, prob in enumerate(p):
        name = str(ch_names[i]) if i < len(ch_names) else ""
        pred = str(int(pred_arr[i])) if i < pred_arr.shape[0] else ""
        std = float(sd[i]) if i < sd.shape[0] else float("nan")
        lcb = float(score[i]) if i < score.shape[0] else float("nan")
        lines.append(f"{i}\t{name}\t{float(prob):.8g}\t{std:.8g}\t{lcb:.8g}\t{pred}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _resolve_device(device: str) -> torch.device:
    value = str(device or "auto").lower()
    if value == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if value == "gpu":
        return torch.device("cuda")
    return torch.device(str(device))


def _apply_torch_cpu_threads(cpu_threads: Optional[int], cpu_interop_threads: Optional[int]) -> None:
    if cpu_threads is None:
        return
    try:
        n = max(1, int(cpu_threads))
    except (TypeError, ValueError):
        return
    try:
        torch.set_num_threads(n)
        if cpu_interop_threads is not None:
            torch.set_num_interop_threads(max(1, int(cpu_interop_threads)))
    except RuntimeError:
        # PyTorch may reject interop changes after work has started.  Keep
        # inference usable rather than failing because of a tuning hint.
        pass
