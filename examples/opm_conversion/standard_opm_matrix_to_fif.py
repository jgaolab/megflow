#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Convert standardized OPM inputs into an MNE FIF file.

Standard inputs:
  * MEG matrix: shape (n_channels, n_samples)
  * sensors table: name,x,y,z,ox,oy,oz,pos_unit,status
  * optional events table: sample,event_id,event_type
  * optional sparse trigger-change table: sample,value
  * optional PLY headshape and fiducials table
"""
from __future__ import annotations

import argparse
import json
import struct
import warnings
from pathlib import Path
from typing import Iterable

import mne
import numpy as np
import pandas as pd
from mne.io.constants import FIFF
from mne.transforms import rotation3d_align_z_axis


UNIT_TO_M = {"m": 1.0, "cm": 1e-2, "mm": 1e-3}
MEG_UNIT_TO_T = {"T": 1.0, "nT": 1e-9, "pT": 1e-12, "fT": 1e-15}


def _read_delimited(path: Path, *, header: int | None = 0) -> pd.DataFrame:
    sep = "\t" if path.suffix.lower() in {".tsv", ".txt"} else ","
    return pd.read_csv(path, sep=sep, header=header, comment="#")


def _load_matrix(path: Path, *, key: str | None = None) -> np.ndarray:
    suffix = path.suffix.lower()
    if suffix == ".npy":
        return np.asarray(np.load(path))
    if suffix == ".npz":
        data = np.load(path)
        if key is not None:
            return np.asarray(data[key])
        keys = list(data.keys())
        if len(keys) != 1:
            raise ValueError(f"{path}: npz has multiple arrays; pass --meg-key")
        return np.asarray(data[keys[0]])
    if suffix in {".csv", ".tsv", ".txt"}:
        return _read_delimited(path, header=None).to_numpy()
    if suffix == ".mat":
        try:
            import scipy.io as sio
        except ImportError as exc:
            raise ImportError("Reading .mat requires scipy") from exc
        if key is None:
            raise ValueError("Reading .mat requires --meg-key")
        return np.asarray(sio.loadmat(path)[key])
    raise ValueError(f"Unsupported matrix file type: {path.suffix}")


def _require_columns(table: pd.DataFrame, required: Iterable[str], path: Path) -> None:
    missing = [c for c in required if c not in table.columns]
    if missing:
        raise ValueError(f"{path}: missing required columns: {missing}")


def _as_int_array(values: pd.Series, *, name: str) -> np.ndarray:
    arr_f = pd.to_numeric(values, errors="raise").to_numpy(dtype=float)
    if not np.all(np.isfinite(arr_f)):
        raise ValueError(f"{name} contains NaN or Inf")
    arr_i = arr_f.astype(np.int64)
    if not np.all(arr_f == arr_i):
        raise ValueError(f"{name} must contain integer values")
    return arr_i


def _orthonormal_rot_rows_ez_third(ez: np.ndarray) -> np.ndarray:
    ez = np.asarray(ez, dtype=np.float64).ravel()
    ez = ez / (np.linalg.norm(ez) + 1e-20)
    anchor = np.array([1.0, 0.0, 0.0], dtype=np.float64)
    if abs(float(np.dot(anchor, ez))) > 0.9:
        anchor = np.array([0.0, 1.0, 0.0], dtype=np.float64)
    ex = anchor - np.dot(anchor, ez) * ez
    n = np.linalg.norm(ex)
    if n < 1e-14:
        anchor = np.array([0.0, 0.0, 1.0], dtype=np.float64)
        ex = anchor - np.dot(anchor, ez) * ez
        n = np.linalg.norm(ex)
    ex = ex / n
    ey = np.cross(ez, ex)
    ey = ey / (np.linalg.norm(ey) + 1e-20)
    ex = np.cross(ey, ez)
    ex = ex / (np.linalg.norm(ex) + 1e-20)
    rot = np.stack([ex, ey, ez], axis=0)
    if float(np.linalg.det(rot)) < 0.0:
        ey = -ey
        rot = np.stack([ex, ey, ez], axis=0)
    return rot


def _meg_ch_loc_from_pos_ori(pos_m: np.ndarray, ori: np.ndarray) -> np.ndarray:
    loc = np.zeros(12, dtype=np.float64)
    loc[0:3] = np.asarray(pos_m, dtype=np.float64).ravel()
    o = np.asarray(ori, dtype=np.float64).ravel()
    n = np.linalg.norm(o)
    if n < 1e-15:
        raise ValueError("Sensor orientation vector has near-zero norm")
    o = o / n
    try:
        rot = rotation3d_align_z_axis(o).T
    except AssertionError:
        rot = _orthonormal_rot_rows_ez_third(o)
    loc[3:12] = rot.ravel(order="C")
    return loc


def _read_sensors(path: Path, n_channels: int) -> pd.DataFrame:
    sensors = _read_delimited(path, header=0)
    sensors.columns = [str(c).strip() for c in sensors.columns]
    required = ("name", "x", "y", "z", "ox", "oy", "oz", "pos_unit", "status")
    _require_columns(sensors, required, path)
    if len(sensors) != n_channels:
        raise ValueError(f"{path}: {len(sensors)} sensors != {n_channels} MEG channels")
    names = sensors["name"].astype(str).tolist()
    if len(set(names)) != len(names):
        raise ValueError(f"{path}: sensor names must be unique")
    bad_units = sorted(set(str(u) for u in sensors["pos_unit"]) - set(UNIT_TO_M))
    if bad_units:
        raise ValueError(f"{path}: unsupported pos_unit values: {bad_units}")
    bad_status = sorted(set(str(s).lower() for s in sensors["status"]) - {"good", "bad"})
    if bad_status:
        raise ValueError(f"{path}: status must be good or bad, got {bad_status}")
    return sensors


def _sensor_locs_m(sensors: pd.DataFrame) -> np.ndarray:
    locs = []
    for row in sensors.itertuples(index=False):
        factor = UNIT_TO_M[getattr(row, "pos_unit")]
        pos = np.array([row.x, row.y, row.z], dtype=np.float64) * factor
        ori = np.array([row.ox, row.oy, row.oz], dtype=np.float64)
        locs.append(_meg_ch_loc_from_pos_ori(pos, ori))
    return np.vstack(locs)


def _read_events_as_stim(path: Path, n_samples: int, pulse_width: int) -> np.ndarray:
    if pulse_width < 1:
        raise ValueError("--event-pulse-width must be >= 1")
    events = _read_delimited(path, header=0)
    events.columns = [str(c).strip() for c in events.columns]
    _require_columns(events, ("sample", "event_id"), path)
    samples = _as_int_array(events["sample"], name="events.sample")
    event_ids = _as_int_array(events["event_id"], name="events.event_id")
    if np.any(event_ids <= 0):
        raise ValueError("events.event_id must be positive")
    if np.any(samples < 0) or np.any(samples >= n_samples):
        raise ValueError("events.sample values must be in [0, n_samples)")
    if len(set(samples.tolist())) != len(samples):
        raise ValueError("events table has multiple rows at the same sample")
    order = np.argsort(samples)
    samples = samples[order]
    event_ids = event_ids[order]
    if len(samples) > 1 and np.any(np.diff(samples) <= pulse_width):
        raise ValueError(
            "events must leave at least one zero-valued sample between pulses; "
            "increase spacing or use --triggers for explicit reset samples"
        )

    stim = np.zeros((1, n_samples), dtype=np.float64)
    for sample, event_id in zip(samples, event_ids):
        stop = int(sample) + pulse_width
        if stop > n_samples:
            raise ValueError(f"event at sample {sample} exceeds n_samples with pulse width")
        if np.any(stim[0, sample:stop] != 0):
            raise ValueError(f"event pulse overlap at sample {sample}")
        stim[0, sample:stop] = event_id
    return stim


def _read_triggers_as_stim(path: Path, n_samples: int) -> np.ndarray:
    table = _read_delimited(path, header=None)
    if table.shape[1] < 2:
        raise ValueError(f"{path}: trigger table must have two columns: sample,value")
    table = table.iloc[:, :2].copy()
    first = [str(v).strip().lower() for v in table.iloc[0].tolist()]
    if first == ["sample", "value"]:
        table = table.iloc[1:].reset_index(drop=True)
    table.columns = ["sample", "value"]

    samples = _as_int_array(table["sample"], name="triggers.sample")
    values = _as_int_array(table["value"], name="triggers.value")
    if np.any(values < 0):
        raise ValueError("triggers.value must be non-negative")
    if np.any(samples < 0) or np.any(samples >= n_samples):
        raise ValueError("triggers.sample values must be in [0, n_samples)")
    if not np.all(np.diff(samples) > 0):
        raise ValueError("triggers.sample must be strictly increasing")

    stim = np.zeros((1, n_samples), dtype=np.float64)
    for idx, (sample, value) in enumerate(zip(samples, values)):
        stop = int(samples[idx + 1]) if idx + 1 < len(samples) else n_samples
        stim[0, int(sample):stop] = int(value)
    if len(values) and values[-1] != 0:
        warnings.warn("last trigger value is non-zero and will continue to the end", UserWarning)
    return stim


def _ply_numpy_dtype(prop_type: str, endian: str) -> np.dtype:
    mapping = {
        "char": "i1",
        "uchar": "u1",
        "int8": "i1",
        "uint8": "u1",
        "short": "i2",
        "ushort": "u2",
        "int16": "i2",
        "uint16": "u2",
        "int": "i4",
        "uint": "u4",
        "int32": "i4",
        "uint32": "u4",
        "float": "f4",
        "float32": "f4",
        "double": "f8",
        "float64": "f8",
    }
    if prop_type not in mapping:
        raise ValueError(f"Unsupported PLY property type: {prop_type}")
    code = mapping[prop_type]
    if code.endswith("1"):
        return np.dtype(code)
    return np.dtype(endian + code)


def _read_ply_points_fallback(path: Path) -> np.ndarray:
    with path.open("rb") as fid:
        header_lines = []
        while True:
            line = fid.readline()
            if not line:
                raise ValueError(f"{path}: missing end_header")
            header_lines.append(line.decode("ascii", errors="replace").strip())
            if header_lines[-1] == "end_header":
                break
        if header_lines[0] != "ply":
            raise ValueError(f"{path}: not a PLY file")
        fmt = header_lines[1].split()[1]
        vertex_count = None
        vertex_props: list[tuple[str, str]] = []
        in_vertex = False
        for line in header_lines:
            parts = line.split()
            if len(parts) >= 3 and parts[:2] == ["element", "vertex"]:
                vertex_count = int(parts[2])
                in_vertex = True
                continue
            if len(parts) >= 3 and parts[0] == "element" and parts[1] != "vertex":
                in_vertex = False
            if in_vertex and len(parts) == 3 and parts[0] == "property":
                vertex_props.append((parts[2], parts[1]))
        if vertex_count is None:
            raise ValueError(f"{path}: missing vertex element")
        names = [name for name, _ in vertex_props]
        for coord in ("x", "y", "z"):
            if coord not in names:
                raise ValueError(f"{path}: vertex properties must include x,y,z")

        if fmt == "ascii":
            rows = []
            for _ in range(vertex_count):
                vals = fid.readline().decode("ascii").split()
                rows.append([float(vals[names.index(c)]) for c in ("x", "y", "z")])
            return np.asarray(rows, dtype=np.float64)
        if fmt not in {"binary_little_endian", "binary_big_endian"}:
            raise ValueError(f"{path}: unsupported PLY format {fmt}")
        endian = "<" if fmt == "binary_little_endian" else ">"
        dtype = np.dtype([(name, _ply_numpy_dtype(ptype, endian)) for name, ptype in vertex_props])
        vertices = np.fromfile(fid, dtype=dtype, count=vertex_count)
        return np.column_stack([vertices["x"], vertices["y"], vertices["z"]]).astype(np.float64)


def _downsample_points(points: np.ndarray, max_points: int) -> np.ndarray:
    if max_points < 0:
        raise ValueError("--ply-max-points must be >= 0")
    if max_points == 0 or len(points) <= max_points:
        return points
    rng = np.random.default_rng(0)
    picks = np.sort(rng.choice(len(points), size=max_points, replace=False))
    return points[picks]


def _read_ply_points(path: Path, unit: str, max_points: int, decimate_factor: float) -> np.ndarray:
    if unit not in UNIT_TO_M:
        raise ValueError(f"Unsupported --ply-unit {unit!r}")
    if not 0.0 <= decimate_factor < 1.0:
        raise ValueError("--ply-decimate-factor must be in [0, 1)")
    try:
        import pyvista as pv
        from pyvista.core.errors import NotAllTrianglesError
    except ImportError:
        points = _read_ply_points_fallback(path)
    else:
        try:
            mesh = pv.read(path)
            if decimate_factor > 0.0:
                mesh = mesh.triangulate()
                mesh = mesh.decimate(decimate_factor)
            points = np.asarray(mesh.points, dtype=np.float64)
        except (NotAllTrianglesError, ValueError, RuntimeError):
            points = _read_ply_points_fallback(path)
    points = _downsample_points(points, max_points)
    return points * UNIT_TO_M[unit]


def _read_fiducials(path: Path) -> dict[str, np.ndarray]:
    table = _read_delimited(path, header=0)
    table.columns = [str(c).strip() for c in table.columns]
    _require_columns(table, ("name", "x", "y", "z", "unit"), path)
    out = {}
    for row in table.itertuples(index=False):
        name = str(row.name).strip().upper()
        if name not in {"NAS", "LPA", "RPA"}:
            raise ValueError(f"{path}: fiducial name must be NAS, LPA, or RPA")
        unit = str(row.unit).strip()
        if unit not in UNIT_TO_M:
            raise ValueError(f"{path}: unsupported fiducial unit {unit!r}")
        out[name] = np.array([row.x, row.y, row.z], dtype=np.float64) * UNIT_TO_M[unit]
    missing = {"NAS", "LPA", "RPA"} - set(out)
    if missing:
        raise ValueError(f"{path}: missing fiducials {sorted(missing)}")
    return out


def convert(args: argparse.Namespace) -> Path:
    meg = _load_matrix(Path(args.meg), key=args.meg_key).astype(np.float64, copy=False)
    if meg.ndim != 2:
        raise ValueError(f"MEG matrix must be 2D, got shape {meg.shape}")
    n_channels, n_samples = meg.shape
    if args.meg_unit not in MEG_UNIT_TO_T:
        raise ValueError(f"Unsupported --meg-unit {args.meg_unit!r}")
    meg = (meg * MEG_UNIT_TO_T[args.meg_unit]).astype(np.float32, copy=False)

    sensors = _read_sensors(Path(args.sensors), n_channels)
    ch_names = sensors["name"].astype(str).tolist()
    ch_types = ["mag"] * n_channels
    data = meg

    if args.events and args.triggers:
        raise ValueError("--events and --triggers are mutually exclusive")
    if args.events:
        stim = _read_events_as_stim(Path(args.events), n_samples, args.event_pulse_width)
        data = np.vstack([data, stim])
        ch_names.append("STI101")
        ch_types.append("stim")
    elif args.triggers:
        stim = _read_triggers_as_stim(Path(args.triggers), n_samples)
        data = np.vstack([data, stim])
        ch_names.append("STI101")
        ch_types.append("stim")

    info = mne.create_info(ch_names=ch_names, sfreq=float(args.sfreq), ch_types=ch_types, verbose="ERROR")

    if args.ply:
        hsp = _read_ply_points(
            Path(args.ply), args.ply_unit, args.ply_max_points, args.ply_decimate_factor
        )
        if args.fiducials:
            fid = _read_fiducials(Path(args.fiducials))
            montage = mne.channels.make_dig_montage(
                nasion=fid["NAS"], lpa=fid["LPA"], rpa=fid["RPA"], hsp=hsp, coord_frame="head"
            )
        else:
            montage = mne.channels.make_dig_montage(hsp=hsp, coord_frame="head")
        info.set_montage(montage)

    locs = _sensor_locs_m(sensors)
    for idx in range(n_channels):
        ch = info["chs"][idx]
        ch["loc"] = locs[idx]
        ch["coord_frame"] = FIFF.FIFFV_COORD_HEAD
        ch["coil_type"] = FIFF.FIFFV_COIL_POINT_MAGNETOMETER
        ch["kind"] = FIFF.FIFFV_MEG_CH
        ch["unit"] = FIFF.FIFF_UNIT_T

    if len(ch_names) > n_channels:
        stim_ch = info["chs"][-1]
        stim_ch["loc"] = np.zeros(12, dtype=np.float64)
        stim_ch["coord_frame"] = FIFF.FIFFV_COORD_UNKNOWN
        stim_ch["coil_type"] = FIFF.FIFFV_COIL_NONE
        stim_ch["kind"] = FIFF.FIFFV_STIM_CH
        stim_ch["unit"] = FIFF.FIFF_UNIT_NONE

    info["bads"] = sensors.loc[sensors["status"].str.lower() == "bad", "name"].astype(str).tolist()
    info["line_freq"] = args.line_freq
    info["description"] = "Standard OPM matrix-to-FIF conversion; point magnetometer loc from x,y,z,ox,oy,oz"

    raw = mne.io.RawArray(data, info, verbose="ERROR")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    raw.save(out, overwrite=args.overwrite, fmt=args.fif_fmt, verbose="ERROR")

    readback = mne.io.read_raw_fif(out, preload=False, verbose="ERROR")
    summary = {
        "out": str(out),
        "n_channels": int(readback.info["nchan"]),
        "n_samples": int(readback.n_times),
        "sfreq": float(readback.info["sfreq"]),
        "meg_channels": int(sum(t == "mag" for t in readback.get_channel_types())),
        "has_STI101": "STI101" in readback.ch_names,
        "dig_points": 0 if readback.info.get("dig") is None else len(readback.info["dig"]),
        "bads": list(readback.info["bads"]),
        "first_meg_loc": readback.info["chs"][0]["loc"].tolist(),
    }
    if "STI101" in readback.ch_names:
        events = mne.find_events(readback, stim_channel="STI101", shortest_event=1, verbose="ERROR")
        summary["find_events_count"] = int(len(events))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return out


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standard OPM matrix + sensors + events/triggers to FIF")
    parser.add_argument("--meg", required=True, help="MEG matrix file, shape (n_channels, n_samples)")
    parser.add_argument("--meg-key", default=None, help="Array key for .npz/.mat inputs")
    parser.add_argument("--sensors", required=True, help="sensors.tsv/csv with name,x,y,z,ox,oy,oz,pos_unit,status")
    parser.add_argument("--sfreq", required=True, type=float, help="Sampling frequency in Hz")
    parser.add_argument("--meg-unit", default="fT", choices=sorted(MEG_UNIT_TO_T), help="Unit of MEG matrix")
    parser.add_argument("--events", default=None, help="events.tsv/csv with sample,event_id,event_type")
    parser.add_argument("--event-pulse-width", type=int, default=1, help="Pulse width in samples for --events")
    parser.add_argument("--triggers", default=None, help="sparse trigger-change table with sample,value")
    parser.add_argument("--ply", default=None, help="Optional optical scan PLY")
    parser.add_argument("--ply-unit", default="mm", choices=sorted(UNIT_TO_M), help="Unit of PLY coordinates")
    parser.add_argument(
        "--ply-max-points",
        default=500,
        type=int,
        help="Maximum headshape points written from PLY; 0 keeps all points",
    )
    parser.add_argument(
        "--ply-decimate-factor",
        default=0.995,
        type=float,
        help="PyVista mesh decimation fraction before point capping, same meaning as opmpy._read_scan_ply(factor)",
    )
    parser.add_argument("--fiducials", default=None, help="Optional fiducials table: name,x,y,z,unit")
    parser.add_argument("--line-freq", default=None, type=float, help="Power line frequency")
    parser.add_argument("--out", required=True, help="Output FIF path")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite output FIF")
    parser.add_argument("--fif-fmt", default="single", choices=("single", "double"), help="FIF data precision")
    return parser


def main() -> int:
    parser = build_argparser()
    args = parser.parse_args()
    convert(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
