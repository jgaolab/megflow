# -*- coding: utf-8 -*-
"""Post-processing helpers for standalone DeepReject inference."""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np


def predictions_to_bad_intervals(
    preds: np.ndarray,
    duration_sec: float = 1.0,
) -> List[Tuple[float, float]]:
    preds = np.asarray(preds).reshape(-1)
    if preds.size == 0:
        return []
    intervals: List[Tuple[float, float]] = []
    in_bad = False
    start = 0.0
    dur = float(duration_sec)
    for i, value in enumerate(preds):
        t_start = i * dur
        if int(value) == 1:
            if not in_bad:
                in_bad = True
                start = t_start
        elif in_bad:
            intervals.append((start, t_start))
            in_bad = False
    if in_bad:
        intervals.append((start, preds.size * dur))
    return intervals


def artifact_probs_to_bad_intervals(
    probs: np.ndarray,
    duration_sec: float = 1.0,
    threshold: Optional[float] = None,
    hysteresis_high: Optional[float] = None,
    hysteresis_low: Optional[float] = None,
    merge_gap_sec: float = 0.0,
    min_duration_sec: float = 0.0,
    short_keep_threshold: Optional[float] = None,
) -> List[Tuple[float, float]]:
    p = np.asarray(probs, dtype=np.float32).reshape(-1)
    if p.size == 0:
        return []
    high = float(hysteresis_high) if hysteresis_high is not None else float(threshold if threshold is not None else 0.5)
    low = float(hysteresis_low) if hysteresis_low is not None else high
    if low > high:
        raise ValueError(f"hysteresis low 阈值 ({low}) 不能高于 high 阈值 ({high})")

    segs: List[Tuple[int, int, float]] = []
    in_low_component = False
    start = 0
    has_high = False
    for i, prob in enumerate(p):
        prob_f = float(prob)
        if prob_f >= low:
            if not in_low_component:
                in_low_component = True
                start = i
                has_high = False
            if prob_f >= high:
                has_high = True
        elif in_low_component:
            if has_high and i > start:
                segs.append((start, i, float(p[start:i].max())))
            in_low_component = False
    if in_low_component and has_high:
        segs.append((start, p.size, float(p[start:].max())))

    dur = float(duration_sec)
    if merge_gap_sec > 0 and segs:
        max_gap_windows = int(np.floor(float(merge_gap_sec) / dur + 1e-9))
        merged: List[Tuple[int, int, float]] = []
        for s, e, m in segs:
            if merged and s - merged[-1][1] <= max_gap_windows:
                ps, pe, pm = merged[-1]
                merged[-1] = (ps, e, max(pm, m))
            else:
                merged.append((s, e, m))
        segs = merged

    intervals: List[Tuple[float, float]] = []
    min_dur = max(float(min_duration_sec), 0.0)
    keep_thr = None if short_keep_threshold is None else float(short_keep_threshold)
    for s, e, max_prob in segs:
        onset = float(s) * dur
        end = float(e) * dur
        seg_dur = end - onset
        if min_dur > 0 and seg_dur < min_dur and (keep_thr is None or max_prob < keep_thr):
            continue
        if seg_dur > 0:
            intervals.append((onset, end))
    return intervals
