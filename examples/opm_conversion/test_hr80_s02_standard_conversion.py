#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run and verify the HR80 S02 standard OPM conversion demo."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import mne
import numpy as np
import pandas as pd
from mne.io.constants import FIFF


ROOT = Path("./")
DEMO = ROOT / "examples" / "quanmag_hr80_s02"
OUTDIR = DEMO / "outputs"
CONVERTER = ROOT / "standard_opm_matrix_to_fif.py"


def _preprocess_for_evoked(raw: mne.io.BaseRaw) -> mne.io.BaseRaw:
    raw_evoked = raw.copy().load_data(verbose="ERROR")
    raw_evoked.notch_filter(freqs=[50.0], picks="mag", verbose="ERROR")
    raw_evoked.filter(l_freq=1.0, h_freq=40.0, picks="mag", verbose="ERROR")
    return raw_evoked


def _run_converter_events(out_fif: Path) -> None:
    cmd = [
        sys.executable,
        str(CONVERTER),
        "--meg",
        str(DEMO / "meg.npy"),
        "--sensors",
        str(DEMO / "sensors.tsv"),
        "--events",
        str(DEMO / "events.tsv"),
        "--sfreq",
        "1000",
        "--meg-unit",
        "T",
        "--event-pulse-width",
        "1",
        "--ply",
        str(DEMO / "face.ply"),
        "--ply-unit",
        "mm",
        "--out",
        str(out_fif),
        "--overwrite",
    ]
    subprocess.run(cmd, check=True)


def _run_converter_triggers(out_fif: Path) -> None:
    cmd = [
        sys.executable,
        str(CONVERTER),
        "--meg",
        str(DEMO / "meg.npy"),
        "--sensors",
        str(DEMO / "sensors.tsv"),
        "--triggers",
        str(DEMO / "triggers.tsv"),
        "--sfreq",
        "1000",
        "--meg-unit",
        "T",
        "--ply",
        str(DEMO / "face.ply"),
        "--ply-unit",
        "mm",
        "--out",
        str(out_fif),
        "--overwrite",
    ]
    subprocess.run(cmd, check=True)


def _verify(out_fif: Path, expected_events_path: Path, *, label: str, make_figures: bool) -> dict:
    raw = mne.io.read_raw_fif(out_fif, preload=False, verbose="ERROR")
    expected = pd.read_csv(expected_events_path, sep="\t")
    events = mne.find_events(raw, stim_channel="STI101", shortest_event=1, verbose="ERROR")
    np.testing.assert_array_equal(events[:, 0], expected["sample"].to_numpy(dtype=np.int64))
    np.testing.assert_array_equal(events[:, 2], expected["event_id"].to_numpy(dtype=np.int64))

    mag_picks = mne.pick_types(raw.info, meg=True, stim=False, exclude=[])
    assert len(mag_picks) == 80
    for pick in mag_picks:
        ch = raw.info["chs"][pick]
        assert ch["coil_type"] == FIFF.FIFFV_COIL_POINT_MAGNETOMETER
        assert ch["coord_frame"] in (FIFF.FIFFV_COORD_HEAD, FIFF.FIFFV_COORD_DEVICE)
        assert np.isfinite(ch["loc"]).all()
        assert np.linalg.norm(ch["loc"][9:12]) > 0.99
    if raw.info["chs"][mag_picks[0]]["coord_frame"] == FIFF.FIFFV_COORD_DEVICE:
        assert raw.info["dev_head_t"] is not None
        np.testing.assert_allclose(raw.info["dev_head_t"]["trans"], np.eye(4), atol=1e-12)
    assert raw.info.get("dig") is not None and len(raw.info["dig"]) >= 100

    result = {
        "label": label,
        "fif": str(out_fif),
        "nchan": int(raw.info["nchan"]),
        "n_times": int(raw.n_times),
        "events": int(len(events)),
        "dig_points": int(len(raw.info["dig"])),
        "first_event": [int(v) for v in events[0]],
    }

    if make_figures:
        figdir = OUTDIR / "figures"
        figdir.mkdir(parents=True, exist_ok=True)
        raw_psd = raw.copy().crop(tmax=min(20.0, raw.times[-1])).load_data(verbose="ERROR")
        psd = raw_psd.compute_psd(picks="mag", fmax=100, n_fft=2048, verbose="ERROR")
        arr = psd.get_data()
        assert np.isfinite(arr).all()
        assert float(arr.mean()) > 0.0
        sphere = (0.0, 0.0, 0.0, 0.095)
        fig = psd.plot(sphere=sphere, show=False)
        fig.savefig(figdir / f"{label}_psd.png", dpi=150)
        fig = raw.plot_sensors(kind="3d", sphere=sphere, show=False)
        fig.savefig(figdir / f"{label}_sensors_3d.png", dpi=150)
        fig = raw.plot_sensors(kind="topomap", sphere=sphere, show=False)
        fig.savefig(figdir / f"{label}_sensors_2d.png", dpi=150)
        raw_evoked = _preprocess_for_evoked(raw)
        epochs = mne.Epochs(
            raw_evoked,
            events,
            event_id=None,
            tmin=-0.2,
            tmax=0.5,
            baseline=(None, 0),
            picks="mag",
            preload=True,
            verbose="ERROR",
        )
        assert len(epochs) > 0
        evoked = epochs.average()
        fig = evoked.plot(spatial_colors=True, sphere=sphere, show=False)
        fig.savefig(figdir / f"{label}_evoked_all_events.png", dpi=150)
        result["evoked_event_id"] = "all"
        result["evoked_epochs"] = int(len(epochs))

    return result


def main() -> int:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    events_fif = OUTDIR / "S02_standard_events_raw.fif"
    triggers_fif = OUTDIR / "S02_standard_triggers_raw.fif"
    _run_converter_events(events_fif)
    _run_converter_triggers(triggers_fif)
    results = [
        _verify(events_fif, DEMO / "events.tsv", label="events", make_figures=True),
        _verify(triggers_fif, DEMO / "events.tsv", label="triggers", make_figures=False),
    ]
    (OUTDIR / "verification_summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
