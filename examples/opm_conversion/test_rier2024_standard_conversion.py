#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run and verify the Rier2024 standard OPM conversion demo."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import mne
import numpy as np
import pandas as pd
from mne.io.constants import FIFF


ROOT = Path("./")
DEMO = ROOT / "examples" / "quspin_rier2024_sub001"
OUTDIR = DEMO / "outputs"
CONVERTER = ROOT / "standard_opm_matrix_to_fif.py"
SFREQ = 1200.0
MEG_UNIT = "fT"

ARTICLE_TFR_CMAP = LinearSegmentedColormap.from_list(
    "article_blue_green_yellow",
    [
        (0.0, "#1f5aa6"),
        (0.5, "#2ca25f"),
        (1.0, "#f6d746"),
    ],
)


def _left_sensorimotor_roi(tfr: mne.time_frequency.EpochsTFR, raw: mne.io.BaseRaw) -> pd.DataFrame:
    rows = []
    for idx, ch_name in enumerate(tfr.ch_names):
        loc = raw.info["chs"][raw.ch_names.index(ch_name)]["loc"][:3]
        rows.append(
            {
                "index": idx,
                "channel": ch_name,
                "base": ch_name.rsplit(" ", 1)[0],
                "x": float(loc[0]),
                "y": float(loc[1]),
                "z": float(loc[2]),
            }
        )
    channels = pd.DataFrame(rows)
    bases = (
        channels.groupby("base", as_index=False)
        .agg(
            x=("x", "first"),
            y=("y", "first"),
            z=("z", "first"),
            channel_count=("channel", "count"),
        )
    )
    # MNE head/RAS coordinates: x<0 is left hemisphere. The y/z limits are
    # intentionally a search ROI, not a hard anatomical label: the article
    # reports the largest beta-modulation peak around left sensorimotor cortex,
    # and at sensor level that peak can project onto nearby post-central sensors.
    roi_bases = bases[
        (bases["x"] < 0.0)
        & (bases["y"] > -0.100)
        & (bases["y"] < 0.050)
        & (bases["z"] > 0.030)
        & (bases["z"] < 0.125)
    ]["base"]
    return channels[channels["base"].isin(roi_bases)].copy()


def _condition_tfr(raw_tfr: mne.io.BaseRaw, events: np.ndarray, event_name: str, event_id: int):
    if event_id not in events[:, 2]:
        raise AssertionError(f"Rier2024 demo expected {event_name} event_id={event_id}")

    epochs = mne.Epochs(
        raw_tfr,
        events,
        event_id={event_name: event_id},
        tmin=-1.0,
        tmax=3.5,
        baseline=None,
        picks="mag",
        preload=True,
        verbose="ERROR",
    )
    assert len(epochs) > 0

    freqs = np.arange(4.0, 41.0, 1.0)
    n_cycles = np.maximum(freqs / 2.0, 3.0)
    tfr = epochs.compute_tfr(
        method="morlet",
        freqs=freqs,
        n_cycles=n_cycles,
        average=True,
        return_itc=False,
        decim=2,
        n_jobs=1,
        verbose="ERROR",
    )
    tfr.apply_baseline((2.5, 3.0), mode="percent", verbose="ERROR")
    return epochs, tfr


def _select_roi_channel(tfr: mne.time_frequency.EpochsTFR, raw: mne.io.BaseRaw) -> dict:
    candidates = _rank_roi_channels(tfr, raw)
    selected = candidates.iloc[0]
    return {
        "index": int(selected["index"]),
        "channel": str(selected["channel"]),
        "base": str(selected["base"]),
        "x": float(selected["x"]),
        "y": float(selected["y"]),
        "z": float(selected["z"]),
        "beta_prestim_percent": float(selected["beta_prestim_percent"]),
        "beta_0p3_0p8_percent": float(selected["beta_0p3_0p8"]),
        "beta_delta_post_minus_pre_percent": float(selected["beta_delta_post_minus_pre"]),
        "paper_like_score": float(selected["paper_like_score"]),
        "roi_bases": sorted(candidates["base"].unique().tolist()),
    }


def _rank_roi_channels(tfr: mne.time_frequency.EpochsTFR, raw: mne.io.BaseRaw) -> pd.DataFrame:
    data_pct = tfr.data * 100.0
    beta_mask = (tfr.freqs >= 13.0) & (tfr.freqs <= 30.0)
    prestim_mask = (tfr.times >= -0.2) & (tfr.times < 0.0)
    response_mask = (tfr.times >= 0.3) & (tfr.times <= 0.8)
    beta_effect = data_pct[:, beta_mask][:, :, response_mask].mean(axis=(1, 2))
    beta_prestim = data_pct[:, beta_mask][:, :, prestim_mask].mean(axis=(1, 2))
    beta_delta = beta_effect - beta_prestim
    roi = _left_sensorimotor_roi(tfr, raw)
    if roi.empty:
        raise AssertionError("Left sensorimotor ROI did not contain any Rier2024 channels")
    roi_indices = roi["index"].to_numpy(dtype=int)
    roi = roi.assign(
        beta_prestim_percent=beta_prestim[roi_indices],
        beta_0p3_0p8=beta_effect[roi_indices],
        beta_delta_post_minus_pre=beta_delta[roi_indices],
    )
    # Lower score is better. This favors channels with post-onset beta decrease,
    # while penalizing channels that are already strongly blue before the trial.
    roi = roi.assign(
        paper_like_score=roi["beta_delta_post_minus_pre"] + 0.25 * np.abs(roi["beta_prestim_percent"])
    )
    return roi.sort_values("paper_like_score").reset_index(drop=True)


def _top_unique_sensor_positions(candidates: pd.DataFrame, top_n: int = 6) -> pd.DataFrame:
    return candidates.drop_duplicates("base", keep="first").head(top_n).reset_index(drop=True)


def _plot_candidate_tfrs(
    tfr: mne.time_frequency.EpochsTFR,
    candidates: pd.DataFrame,
    event_name: str,
    event_id: int,
    epochs_count: int,
    figdir: Path,
) -> tuple[str, list[dict]]:
    selected = _top_unique_sensor_positions(candidates, top_n=6)
    data_pct = tfr.data * 100.0
    plot_mask = (tfr.times >= -0.2) & (tfr.times <= 2.5)
    plot_times = tfr.times[plot_mask]
    images = [data_pct[int(row["index"]), :, :][:, plot_mask] for _, row in selected.iterrows()]
    beta_freqs = (tfr.freqs >= 13.0) & (tfr.freqs <= 30.0)
    common_vmax = max(float(np.nanpercentile(np.abs(np.stack([im[beta_freqs, :] for im in images])), 98)), 1.0)
    common_vmax = min(common_vmax, 80.0)

    fig, axes = plt.subplots(2, 3, figsize=(12.0, 6.2), constrained_layout=True, sharex=True, sharey=True)
    for ax, image, (_, row) in zip(axes.ravel(), images, selected.iterrows()):
        im = ax.imshow(
            image,
            aspect="auto",
            origin="lower",
            extent=[plot_times[0], plot_times[-1], tfr.freqs[0], tfr.freqs[-1]],
            cmap=ARTICLE_TFR_CMAP,
            vmin=-common_vmax,
            vmax=common_vmax,
        )
        ax.axvline(0.0, color="k", linestyle="--", linewidth=0.9)
        ax.axvline(0.5, color="k", linestyle=":", linewidth=0.9)
        ax.axhspan(13.0, 30.0, color="k", alpha=0.08, linewidth=0)
        ax.set_title(
            f"{row['channel']}  beta={row['beta_0p3_0p8']:.1f}%  "
            f"delta={row['beta_delta_post_minus_pre']:.1f}%",
            fontsize=10,
        )
    for ax in axes[:, 0]:
        ax.set_ylabel("Frequency (Hz)")
    for ax in axes[-1, :]:
        ax.set_xlabel("Time from trial onset (s)")
    cbar = fig.colorbar(im, ax=axes, fraction=0.03, pad=0.02)
    cbar.set_label("% power change vs 2.5-3.0 s baseline")
    fig.suptitle(f"Rier2024 {event_name} / event_id={event_id}: candidate sensor-level beta TFRs (Nave={epochs_count})")
    out = figdir / f"rier2024_{event_name.lower()}_candidate_beta_tfrs.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    candidate_records = [
        {
            "channel": str(row["channel"]),
            "base": str(row["base"]),
            "xyz_m": [float(row["x"]), float(row["y"]), float(row["z"])],
            "beta_prestim_percent": float(row["beta_prestim_percent"]),
            "beta_0p3_0p8_percent": float(row["beta_0p3_0p8"]),
            "beta_delta_post_minus_pre_percent": float(row["beta_delta_post_minus_pre"]),
            "paper_like_score": float(row["paper_like_score"]),
        }
        for _, row in selected.iterrows()
    ]
    return str(out), candidate_records


def _plot_sensor_selection(
    raw: mne.io.BaseRaw,
    selections: list[dict],
    figdir: Path,
) -> str:
    rows = []
    for ch_name in mne.pick_info(raw.info, mne.pick_types(raw.info, meg=True, exclude=[])).ch_names:
        loc = raw.info["chs"][raw.ch_names.index(ch_name)]["loc"][:3]
        rows.append(
            {
                "channel": ch_name,
                "base": ch_name.rsplit(" ", 1)[0],
                "x": float(loc[0]),
                "y": float(loc[1]),
                "z": float(loc[2]),
            }
        )
    channels = pd.DataFrame(rows)
    bases = channels.groupby("base", as_index=False).agg(x=("x", "first"), y=("y", "first"), z=("z", "first"))
    roi_bases = set()
    for selection in selections:
        roi_bases.update(selection["roi_bases"])
    fig, ax = plt.subplots(figsize=(5.8, 5.2), constrained_layout=True)
    ax.scatter(bases["x"], bases["y"], s=28, c="0.78", edgecolors="none", label="all sensor positions")
    roi = bases[bases["base"].isin(roi_bases)]
    ax.scatter(roi["x"], roi["y"], s=48, c="0.35", edgecolors="white", linewidths=0.5, label="left sensorimotor ROI")
    colors = {"Start_index": "#2166ac", "Start_pinky": "#b2182b"}
    edge_colors = {"Start_index": "#2ca25f", "Start_pinky": "#f6d746"}
    for selection in selections:
        base = bases[bases["base"].eq(selection["base"])].iloc[0]
        color = colors.get(selection["event_name"], "black")
        edge_color = edge_colors.get(selection["event_name"], "black")
        ax.scatter(base["x"], base["y"], s=150, c=color, edgecolors=edge_color, linewidths=1.8, zorder=5)
        ax.text(base["x"] + 0.004, base["y"] + 0.004, selection["channel"], color=color, fontsize=10, weight="bold")
    ax.axhline(0.0, color="0.85", linewidth=0.8)
    ax.axvline(0.0, color="0.85", linewidth=0.8)
    ax.set(
        title="Rier2024 sensor-level channel selection",
        xlabel="Head x / m (left < 0)",
        ylabel="Head y / m",
        aspect="equal",
    )
    ax.legend(loc="lower right", fontsize=8, frameon=False)
    out = figdir / "rier2024_sensor_level_tfr_channels.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return str(out)


def _plot_rier2024_sensor_tfr(raw: mne.io.BaseRaw, events: np.ndarray, figdir: Path) -> dict:
    raw_tfr = raw.copy().load_data(verbose="ERROR")
    raw_tfr.notch_filter(freqs=[50.0], picks="mag", verbose="ERROR")
    raw_tfr.filter(l_freq=1.0, h_freq=45.0, picks="mag", verbose="ERROR")

    channel = "KG Z"
    conditions = [("Start_index", 3, "D2"), ("Start_pinky", 4, "D5")]
    condition_results = []
    images = []
    plot_times = None
    for event_name, event_id, digit in conditions:
        epochs, tfr = _condition_tfr(raw_tfr, events, event_name, event_id)
        if channel not in tfr.ch_names:
            raise AssertionError(f"Expected Rier2024 demo channel {channel!r}")

        data_frac = tfr.data
        channel_idx = tfr.ch_names.index(channel)
        beta_mask = (tfr.freqs >= 13.0) & (tfr.freqs <= 30.0)
        prestim_mask = (tfr.times >= -0.2) & (tfr.times < 0.0)
        response_mask = (tfr.times >= 0.3) & (tfr.times <= 0.8)
        beta_prestim = float(data_frac[channel_idx, beta_mask][:, prestim_mask].mean())
        beta_response = float(data_frac[channel_idx, beta_mask][:, response_mask].mean())
        beta_delta = beta_response - beta_prestim
        loc = raw.info["chs"][raw.ch_names.index(channel)]["loc"][:3]
        selection = {
            "event_name": event_name,
            "event_id": event_id,
            "digit": digit,
            "epochs": int(len(epochs)),
            "channel": channel,
            "base": channel.rsplit(" ", 1)[0],
            "x": float(loc[0]),
            "y": float(loc[1]),
            "z": float(loc[2]),
            "beta_prestim_fraction": beta_prestim,
            "beta_0p3_0p8_fraction": beta_response,
            "beta_delta_post_minus_pre_fraction": beta_delta,
        }
        condition_results.append(selection)

        plot_mask = (tfr.times >= -0.2) & (tfr.times <= 2.5)
        plot_times = tfr.times[plot_mask]
        image = data_frac[channel_idx, :, :][:, plot_mask]
        images.append((tfr, image, selection))

    beta_limits = []
    for tfr, image, _selection in images:
        beta_freqs = (tfr.freqs >= 13.0) & (tfr.freqs <= 30.0)
        beta_limits.append(float(np.nanpercentile(np.abs(image[beta_freqs, :]), 98)))
    common_vmax = max(max(beta_limits), 0.05)
    common_vmax = min(common_vmax, 0.8)

    fig, axes = plt.subplots(2, 1, figsize=(4.6, 6.6), constrained_layout=True, sharex=True, sharey=True)
    for ax, (tfr, image, selection) in zip(axes, images):
        im = ax.imshow(
            image,
            aspect="auto",
            origin="lower",
            extent=[plot_times[0], plot_times[-1], tfr.freqs[0], tfr.freqs[-1]],
            cmap=ARTICLE_TFR_CMAP,
            vmin=-common_vmax,
            vmax=common_vmax,
            interpolation="bilinear",
        )
        ax.axvline(0.0, color="k", linestyle="--", linewidth=1.0)
        ax.axvline(0.5, color="k", linestyle=":", linewidth=1.0)
        ax.axhspan(13.0, 30.0, color="k", alpha=0.08, linewidth=0)
        ax.set(
            title=(
                f"{selection['digit']} {selection['channel']}  "
                f"beta={selection['beta_0p3_0p8_fraction']:.3f}  "
                f"delta={selection['beta_delta_post_minus_pre_fraction']:.3f}"
            ),
            ylabel="Frequency (Hz)",
        )
    axes[-1].set_xlabel("Time from trial onset (s)")
    cbar = fig.colorbar(im, ax=axes, fraction=0.046, pad=0.04)
    cbar.set_label("Fractional power change vs 2.5-3.0 s baseline")
    fig.suptitle("Rier2024 KG Z sensor-level beta TFRs")
    out = figdir / "rier2024_kg_z_d2_d5_beta_tfr.png"
    fig.savefig(out, dpi=320)
    plt.close(fig)

    return {
        "tfr_event_ids": {item["event_name"]: int(item["event_id"]) for item in condition_results},
        "tfr_epochs": {item["event_name"]: int(item["epochs"]) for item in condition_results},
        "tfr_fixed_channel": channel,
        "tfr_channel_metrics": {
            item["event_name"]: {
                "channel": item["channel"],
                "base": item["base"],
                "xyz_m": [item["x"], item["y"], item["z"]],
                "beta_prestim_fraction": item["beta_prestim_fraction"],
                "beta_0p3_0p8_fraction": item["beta_0p3_0p8_fraction"],
                "beta_delta_post_minus_pre_fraction": item["beta_delta_post_minus_pre_fraction"],
            }
            for item in condition_results
        },
        "tfr_figure": str(out),
    }


def _run_converter(out_fif: Path) -> None:
    cmd = [
        sys.executable,
        str(CONVERTER),
        "--meg",
        str(DEMO / "meg.mat"),
        "--meg-key",
        "meg",
        "--sensors",
        str(DEMO / "sensors.tsv"),
        "--events",
        str(DEMO / "events.tsv"),
        "--sfreq",
        str(SFREQ),
        "--meg-unit",
        MEG_UNIT,
        "--event-pulse-width",
        "1",
        "--out",
        str(out_fif),
        "--overwrite",
    ]
    subprocess.run(cmd, check=True)


def _verify(out_fif: Path) -> dict:
    raw = mne.io.read_raw_fif(out_fif, preload=False, verbose="ERROR")
    expected = pd.read_csv(DEMO / "events.tsv", sep="\t")
    events = mne.find_events(raw, stim_channel="STI101", shortest_event=1, verbose="ERROR")
    np.testing.assert_array_equal(events[:, 0], expected["sample"].to_numpy(dtype=np.int64))
    np.testing.assert_array_equal(events[:, 2], expected["event_id"].to_numpy(dtype=np.int64))

    mag_picks = mne.pick_types(raw.info, meg=True, stim=False, exclude=[])
    assert len(mag_picks) == 189
    for pick in mag_picks:
        ch = raw.info["chs"][pick]
        assert ch["coil_type"] == FIFF.FIFFV_COIL_POINT_MAGNETOMETER
        assert ch["coord_frame"] in (FIFF.FIFFV_COORD_HEAD, FIFF.FIFFV_COORD_DEVICE)
        assert np.isfinite(ch["loc"]).all()
        assert np.linalg.norm(ch["loc"][9:12]) > 0.99
    if raw.info["chs"][mag_picks[0]]["coord_frame"] == FIFF.FIFFV_COORD_DEVICE:
        assert raw.info["dev_head_t"] is not None
        np.testing.assert_allclose(raw.info["dev_head_t"]["trans"], np.eye(4), atol=1e-12)
    assert raw.info.get("dig") is None

    figdir = OUTDIR / "figures"
    figdir.mkdir(parents=True, exist_ok=True)
    raw_psd = raw.copy().crop(tmax=min(20.0, raw.times[-1])).load_data(verbose="ERROR")
    psd = raw_psd.compute_psd(picks="mag", fmax=100, n_fft=2048, verbose="ERROR")
    arr = psd.get_data()
    assert np.isfinite(arr).all()
    assert float(arr.mean()) > 0.0
    fig = psd.plot(show=False)
    fig.savefig(figdir / "rier2024_psd.png", dpi=150)
    fig = raw.plot_sensors(kind="3d", show=False)
    fig.savefig(figdir / "rier2024_sensors_3d.png", dpi=150)
    fig = raw.plot_sensors(kind="topomap", sphere=(0.0, 0.0, 0.0, 0.095), show=False)
    fig.savefig(figdir / "rier2024_sensors_2d.png", dpi=150)
    tfr_result = _plot_rier2024_sensor_tfr(raw, events, figdir)

    result = {
        "fif": str(out_fif),
        "nchan": int(raw.info["nchan"]),
        "n_times": int(raw.n_times),
        "events": int(len(events)),
        "dig_points": 0,
        "first_event": [int(v) for v in events[0]],
    }
    result.update(tfr_result)
    return result


def main() -> int:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    out_fif = OUTDIR / "rier2024_standard_events_raw.fif"
    _run_converter(out_fif)
    result = _verify(out_fif)
    (OUTDIR / "verification_summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
