from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Set, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceBundle:
    data: np.ndarray
    original_sfreq: float
    sfreq: float
    n_times: int
    raw_first_samp: int
    source_first_samp: int
    source_mode: str
    source_file: Optional[str]


def read_raw_fif(path: Path, *, preload: bool):
    import mne

    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    if not (path.name.endswith(".fif") or path.name.endswith(".fif.gz")):
        raise ValueError(f"Only FIF raw files are supported, got: {path}")
    return mne.io.read_raw_fif(path, preload=preload, verbose="error")


def read_ica(ica_file: Path):
    import mne

    path = ica_file.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return mne.preprocessing.read_ica(path, verbose="error")


def source_verification_segments(
    n_times: int,
    segment_samples: int = 1000,
) -> List[Tuple[int, int]]:
    """Return deterministic start, middle, and end source-check windows."""
    n_times = int(n_times)
    segment_samples = int(segment_samples)
    if n_times <= 0 or segment_samples <= 0:
        raise ValueError("n_times and segment_samples must be positive")
    window = min(n_times, segment_samples)
    starts = sorted(
        {
            0,
            max(0, (n_times - window) // 2),
            max(0, n_times - window),
        }
    )
    return [(start, start + window) for start in starts]


def load_component_sources(
    raw,
    ica,
    *,
    ica_sources_file: Optional[Path],
    target_sfreq: float = 250.0,
) -> SourceBundle:
    raw_first_samp = int(raw.first_samp)
    if ica_sources_file is None:
        LOG.info("Computing ICA sources from raw + ICA")
        raw_sources = ica.get_sources(raw)
        raw_sources.load_data(verbose="error")
        source_mode = "computed_from_raw_and_ica"
        source_path: Optional[Path] = None
    else:
        source_path = ica_sources_file.expanduser().resolve()
        LOG.info("Loading precomputed ICA sources: %s", source_path)
        raw_sources = read_raw_fif(source_path, preload=True)
        source_mode = "precomputed_ica_sources"
        if raw_sources.n_times != raw.n_times:
            raise ValueError(
                "ica_sources.fif does not match raw file length: "
                f"{raw_sources.n_times} vs {raw.n_times} samples."
            )
        if not np.isclose(
            float(raw_sources.info["sfreq"]),
            float(raw.info["sfreq"]),
            atol=1e-6,
        ):
            raise ValueError(
                "ica_sources.fif does not match raw sampling rate: "
                f"{raw_sources.info['sfreq']} vs {raw.info['sfreq']} Hz."
            )
        if int(raw_sources.first_samp) != raw_first_samp:
            LOG.warning(
                "ica_sources.fif uses first_samp=%d while raw uses first_samp=%d; "
                "continuing because MEGFlow may reset the ICA-source time origin "
                "when saving CTF-derived sources. Source identity will be checked "
                "numerically.",
                int(raw_sources.first_samp),
                raw_first_samp,
            )

    source_first_samp = int(raw_sources.first_samp)

    expected_components = int(ica.n_components_)
    if len(raw_sources.ch_names) != expected_components:
        raise ValueError(
            f"ICA/source component mismatch: ICA has {expected_components}, "
            f"source file has {len(raw_sources.ch_names)} channels."
        )
    expected_names = list(
        getattr(
            ica,
            "_ica_names",
            [f"ICA{component_idx:03d}" for component_idx in range(expected_components)],
        )
    )
    if list(raw_sources.ch_names) != expected_names:
        raise ValueError(
            "ICA/source component names/order mismatch: "
            f"expected {expected_names[:5]}, got {list(raw_sources.ch_names)[:5]}."
        )

    if source_path is not None:
        verification_segments = source_verification_segments(raw_sources.n_times)
        for start, stop in verification_segments:
            expected_sources = ica.get_sources(
                raw,
                start=start,
                stop=stop,
            ).get_data()
            actual_sources = raw_sources.get_data(start=start, stop=stop)
            if expected_sources.shape != actual_sources.shape or not np.allclose(
                actual_sources,
                expected_sources,
                rtol=1e-5,
                atol=1e-6,
                equal_nan=False,
            ):
                max_abs_difference = (
                    float(np.max(np.abs(actual_sources - expected_sources)))
                    if expected_sources.shape == actual_sources.shape
                    else float("inf")
                )
                raise ValueError(
                    "ica_sources.fif does not match raw + ICA over verification "
                    f"segment [{start}:{stop}] "
                    f"(max abs difference={max_abs_difference:.6g})."
                )
        LOG.info(
            "Verified precomputed ICA source identity over segments: %s",
            ", ".join(
                f"[{start}:{stop}]" for start, stop in verification_segments
            ),
        )

    original_sfreq, source_sfreq = prepare_source_sampling(
        raw_sources,
        target_sfreq,
    )

    data = raw_sources.get_data().astype(np.float32, copy=False)
    data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
    return SourceBundle(
        data=data,
        original_sfreq=original_sfreq,
        sfreq=source_sfreq,
        n_times=int(data.shape[1]),
        raw_first_samp=raw_first_samp,
        source_first_samp=source_first_samp,
        source_mode=source_mode,
        source_file=str(source_path) if source_path is not None else None,
    )


def prepare_source_sampling(raw_sources, target_sfreq: float = 250.0) -> Tuple[float, float]:
    """Downsample an in-memory ICA source object only when it exceeds target."""
    target_sfreq = float(target_sfreq)
    if target_sfreq <= 0:
        raise ValueError(f"target_sfreq must be positive, got {target_sfreq}")

    original_sfreq = float(raw_sources.info["sfreq"])
    effective_sfreq = original_sfreq
    if original_sfreq > target_sfreq and not np.isclose(
        original_sfreq,
        target_sfreq,
        atol=1e-6,
    ):
        LOG.warning(
            "Resampling in-memory ICA sources from %.6g Hz to %.6g Hz",
            original_sfreq,
            target_sfreq,
        )
        raw_sources.resample(target_sfreq, npad="auto", verbose="error")
        effective_sfreq = float(raw_sources.info["sfreq"])
    return original_sfreq, effective_sfreq


def cart2sph(x, y, z):
    xy = np.sqrt(x * x + y * y)
    radius = np.sqrt(x * x + y * y + z * z)
    theta = np.arctan2(y, x)
    phi = np.arctan2(z, xy)
    return radius, theta, phi


def pol2cart(radius, phi):
    return radius * np.cos(phi), radius * np.sin(phi)


def make_head_outlines_new(sphere, pos, outlines, clip_origin):
    """Match the circular head mask used to build the clean-topomap H5 files."""
    assert isinstance(sphere, np.ndarray)
    x, y, _, radius = sphere
    angles = np.linspace(0, 2 * np.pi, 101)
    head_x = np.cos(angles) * radius * 1.01 + x
    head_y = np.sin(angles) * radius * 1.01 + y
    outlines_dict = {"head": (head_x, head_y)}
    mask_scale = max(1.0, np.linalg.norm(pos, axis=1).max() * 1.01 / radius)
    outlines_dict["mask_pos"] = (mask_scale * head_x, mask_scale * head_y)
    clip_radius = radius * mask_scale
    outlines_dict["clip_radius"] = (clip_radius,) * 2
    outlines_dict["clip_origin"] = clip_origin
    return outlines_dict


def _circle_positions_from_locs(channel_locations3d: np.ndarray) -> np.ndarray:
    from scipy.interpolate import interp1d
    from scipy.spatial import ConvexHull

    spherical = np.array([cart2sph(*row) for row in channel_locations3d])
    theta = spherical[:, 1]
    phi = spherical[:, 2]
    new_radius = 1.0 - phi / np.pi * 2.0
    x2, y2 = pol2cart(new_radius, theta)
    channel_locations_2d = np.column_stack((x2, y2))
    border = ConvexHull(channel_locations_2d).vertices
    border_scale = 1.0 / new_radius[border]
    func_theta = np.hstack([theta[border] - 2 * np.pi, theta[border], theta[border] + 2 * np.pi])
    func_scale = np.hstack((border_scale, border_scale, border_scale))
    radial_scale = interp1d(func_theta, func_scale, fill_value="extrapolate")(theta)
    final_radius = np.minimum(new_radius * radial_scale, 1.0)
    x_new, y_new = pol2cart(final_radius, theta)
    return np.column_stack((x_new, y_new))


def _channel_type(info, idx: int) -> str:
    try:
        from mne._fiff.pick import channel_type
    except Exception:
        from mne.io.pick import channel_type
    return channel_type(info, idx)


def _available_ica_channel_types(ica) -> Set[str]:
    picks = getattr(ica, "picks", None)
    if picks is None:
        picks = range(len(ica.info["chs"]))
    return {_channel_type(ica.info, pick) for pick in picks}


def _resolve_ch_type(ica, ch_type: str) -> str:
    if ch_type and ch_type.lower() != "auto":
        return ch_type
    types = _available_ica_channel_types(ica)
    if "mag" in types:
        return "mag"
    try:
        from mne.viz.utils import _get_plot_ch_type

        return _get_plot_ch_type(
            ica,
            None,
            allow_ref_meg=getattr(ica, "allow_ref_meg", False),
        )
    except Exception:
        for candidate in ("mag", "grad", "eeg", "seeg", "ecog"):
            if candidate in types:
                return candidate
        return "mag"


def ica_topo_vectors(
    ica,
    component_idx: int,
    ch_type: str,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Tuple[float, float], bool]:
    from mne.viz.topomap import _prepare_topomap_plot

    try:
        from mne.channels.layout import _merge_ch_data
    except Exception:
        try:
            from mne.viz.topomap import _merge_ch_data
        except Exception as exc:
            raise ImportError("Could not import MNE helper _merge_ch_data") from exc

    resolved_type = _resolve_ch_type(ica, ch_type)
    data = ica.get_components()[:, component_idx]
    data_picks, pos, merge_channels, names, _, sphere, clip_origin = _prepare_topomap_plot(
        ica,
        resolved_type,
        sphere=None,
    )
    data = data[data_picks]
    if merge_channels:
        data, names = _merge_ch_data(data, resolved_type, names)

    used_warp = False
    if not merge_channels and len(data_picks) == pos.shape[0]:
        locations = np.array(
            [ica.info["chs"][pick]["loc"][:3] for pick in data_picks],
            dtype=float,
        )
        if locations.shape[0] == data.size and np.isfinite(locations).all():
            pos = _circle_positions_from_locs(locations)
            used_warp = True
            sphere = np.array([0.0, 0.0, 0.0, 1.0], dtype=float)
            clip_origin = (0.0, 0.0)
    return data.ravel(), pos, np.asarray(sphere), clip_origin, used_warp


def render_clean_topomap(
    topo_data: np.ndarray,
    pos: np.ndarray,
    sphere: np.ndarray,
    clip_origin: Tuple[float, float],
    *,
    res: int = 128,
    figsize: Tuple[float, float] = (2.5, 2.5),
    dpi: int = 120,
) -> np.ndarray:
    import mne

    outlines = make_head_outlines_new(sphere, pos, "head", clip_origin)
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi, facecolor="black")
    ax.axis("off")
    ax.set_facecolor("black")
    mne.viz.plot_topomap(
        topo_data,
        pos,
        axes=ax,
        show=False,
        sensors=False,
        outlines=outlines,
        extrapolate="head",
        sphere=sphere,
        contours=0,
        res=res,
        border=0,
        cmap="bwr",
    )
    head_x, head_y = outlines["head"]
    ax.plot(head_x, head_y, color="white", linewidth=1.0)
    ax.set_aspect("equal")
    plt.subplots_adjust(left=0, right=1, bottom=0, top=1)
    fig.canvas.draw()
    rgba = np.asarray(fig.canvas.buffer_rgba())
    plt.close(fig)
    return rgba[..., :3].copy()


def prepare_clean_topomap_images(
    ica,
    *,
    n_components: int,
    ch_type: str = "auto",
    render_res: int = 128,
    save_dir: Optional[Path] = None,
) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    if save_dir is not None:
        save_dir.mkdir(parents=True, exist_ok=True)
    prepared: List[np.ndarray] = []
    rendered: List[np.ndarray] = []
    for component_idx in range(int(n_components)):
        topo_data, pos, sphere, clip_origin, _ = ica_topo_vectors(ica, component_idx, ch_type)
        image = render_clean_topomap(
            topo_data,
            pos,
            sphere,
            clip_origin,
            res=int(render_res),
        )
        if save_dir is not None:
            plt.imsave(save_dir / f"component_{component_idx:03d}.png", image)
            rendered.append(image)
        chw = np.moveaxis(image.astype(np.float32, copy=False), -1, 0)
        prepared.append(np.asarray(chw, dtype=np.float32))
        if component_idx == 0 or (component_idx + 1) % 20 == 0 or component_idx + 1 == n_components:
            LOG.info("Rendered clean topomaps: %d/%d", component_idx + 1, n_components)
    original = np.stack(rendered, axis=0) if save_dir is not None else None
    return np.stack(prepared, axis=0), original


def megnet2020_start_times(
    total_samples: int,
    *,
    model_len: int,
    overlap: int,
    include_final: bool,
) -> List[int]:
    total_samples = int(total_samples)
    model_len = int(model_len)
    overlap = int(overlap)
    if model_len <= 0:
        raise ValueError(f"model_len must be positive, got {model_len}")
    if overlap < 0 or overlap >= model_len:
        raise ValueError(f"overlap must be in [0, model_len), got {overlap}")
    if total_samples < model_len:
        return []
    starts: List[int] = []
    stride = model_len - overlap
    start = 0
    while start + model_len <= total_samples:
        starts.append(int(start))
        start += stride
    if include_final:
        final_start = int(total_samples - model_len)
        if final_start >= 0 and final_start not in starts:
            starts.append(final_start)
    return sorted(starts)


def megnet2020_vote_weights(
    total_samples: int,
    starts: Sequence[int],
    *,
    model_len: int,
) -> np.ndarray:
    starts = [int(start) for start in starts]
    if not starts:
        return np.zeros((0,), dtype=np.float32)
    events = sorted(
        set([0, int(total_samples)] + starts + [start + int(model_len) for start in starts])
    )
    weights = np.zeros((len(starts),), dtype=np.float64)
    intervals = [(start, start + int(model_len)) for start in starts]
    for left, right in zip(events[:-1], events[1:]):
        if right <= left:
            continue
        active = [
            index
            for index, (start, end) in enumerate(intervals)
            if start <= left and right <= end
        ]
        if not active:
            continue
        contribution = float(right - left) / float(len(active))
        for index in active:
            weights[index] += contribution
    return weights.astype(np.float32)


def temporal_window_plan(
    total_samples: int,
    *,
    epoch_samples: int = 15000,
    overlap_samples: int = 3750,
    max_epochs: int = 128,
) -> Tuple[List[int], np.ndarray]:
    starts = megnet2020_start_times(
        total_samples,
        model_len=epoch_samples,
        overlap=overlap_samples,
        include_final=True,
    )
    if not starts:
        raise ValueError(
            f"ICA source has {total_samples} samples, shorter than the required "
            f"{epoch_samples} samples."
        )
    if len(starts) > int(max_epochs):
        indices = np.linspace(0, len(starts) - 1, int(max_epochs))
        starts = [starts[int(index)] for index in np.round(indices).astype(np.int64)]
    weights = megnet2020_vote_weights(
        total_samples,
        starts,
        model_len=epoch_samples,
    )
    if weights.shape[0] != len(starts) or float(weights.sum()) <= 0.0:
        weights = np.ones((len(starts),), dtype=np.float32)
    return starts, weights
