#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import yaml
import re
import os
import time
import getpass
import subprocess
import random
import socket
import redis
import mne
import cloudpickle
import joblib as jl
import matplotlib
import numpy as np
import logging
import argparse
import pyvista as pv
from pathlib import Path
from typing import Literal
from matplotlib import pyplot as plt
from mne.channels.channels import _divide_to_regions


def setup_logging(log_level="INFO"):
    """Configure logging system"""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger(__name__)


logger = setup_logging()


def handle_yaml_scientific_notation():
    # handle scientific notation.
    loader = yaml.SafeLoader
    loader.add_implicit_resolver(
        u'tag:yaml.org,2002:float',
        re.compile(u'''^(?:
         [-+]?(?:[0-9][0-9_]*)\\.[0-9_]*(?:[eE][-+]?[0-9]+)?
        |[-+]?(?:[0-9][0-9_]*)(?:[eE][-+]?[0-9]+)
        |\\.[0-9_]+(?:[eE][-+][0-9]+)?
        |[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\\.[0-9_]*
        |[-+]?\\.(?:inf|Inf|INF)
        |\\.(?:nan|NaN|NAN))$''', re.X),
        list(u'-+0123456789.'))
    return loader


def str2bool(value):
    if value.lower() in ('true', 't', '1'):
        return True
    elif value.lower() in ('false', 'f', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')


def set_random_seed(seed=None):
    """Set all random seeds.

    This includes Python's random module and NumPy.

    Parameters
    ----------
    seed : int
        Random seed.
    """
    if seed is None:
        seed = random.randint(0, 2 ** 32 - 1)

    print(f"Setting random seed to {seed}")

    random.seed(seed)
    np.random.seed(seed)
    return seed

def get_xvfb_processes():
    """Retrieve a list of all running Xvfb processes along with their owners."""
    xvfb_processes = []
    try:
        # Use ps command to get information about all Xvfb processes
        result = subprocess.run(['ps', 'aux'], stdout=subprocess.PIPE, text=True)
        for line in result.stdout.splitlines():
            if 'Xvfb' in line and 'grep' not in line:
                parts = line.split()
                pid = parts[1]  # Process ID
                user = parts[0]  # Owner of the process
                xvfb_processes.append((pid, user))
    except Exception as e:
        print(f"Unable to retrieve process information: {e}")

    return xvfb_processes


def kill_non_owning_processes(xvfb_processes, current_user):
    """Terminate Xvfb processes not owned by the current user."""
    for pid, user in xvfb_processes:
        if user != current_user:
            try:
                print(f"Killing process: PID={pid}, User={user}")
                subprocess.run(['kill', pid])
            except Exception as e:
                print(f"Unable to kill process {pid}: {e}")


def is_xvfb_running():
    try:
        current_user = getpass.getuser()

        result = subprocess.run(
            ['ps', '-u', current_user, '-o', 'pid,cmd'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )

        xvfb_running = False
        output_lines = result.stdout.strip().split('\n')[1:]

        for line in output_lines:
            if 'Xvfb' in line:
                print(f"Xvfb is running for the current user:{current_user}")
                print(line.strip())
                xvfb_running = True

        return xvfb_running

    except subprocess.CalledProcessError as e:
        print(f"Command failed with error: {e.stderr.strip()}")
        return False
    except Exception as e:
        print(f"An error occurred: {e}")
        return False


def find_free_display():
    """Find a free display number by checking port numbers."""
    while True:
        # Generate a random display number between 1000 and 65535
        display_number = random.randint(1000, 65535)
        # Check if the port is free
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex(('localhost', display_number)) != 0:
                return display_number


def start_xvfb(interactive=False):
    """Start Xvfb on a randomly chosen free display and set the DISPLAY environment variable."""
    # Find a free display number
    free_display = find_free_display()
    display_str = f":{free_display}"  # Create display string
    print(f"Starting Xvfb on {display_str}...")

    # Start Xvfb
    # subprocess.Popen(['Xvfb', display_str, '-screen', '0', '1920x1080x24'])
    proc = subprocess.Popen(
        ['Xvfb', display_str, '-screen', '0', '1024x768x24'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    os.environ["MESA_GLSL_VERSION_OVERRIDE"] = "150"
    os.environ["MESA_GL_VERSION_OVERRIDE"] = "3.2"
    os.environ["LIBGL_ALWAYS_SOFTWARE"] = "1"
    os.environ["QT_QPA_PLATFORM"] = "xcb"

    # Set the DISPLAY environment variable
    os.environ['DISPLAY'] = display_str
    print(f"DISPLAY environment variable set to {os.environ['DISPLAY']}")

    for _ in range(20):
        if proc.poll() is not None:
            raise RuntimeError(f"Xvfb failed to start on {display_str}")
        if Path(f"/tmp/.X{free_display}-lock").exists():
            break
        time.sleep(0.1)

    # REQUIRED: Pre-initialize the VTK off-screen rendering context to avoid segmentation fault in headless pyvistaqt.
    pv.OFF_SCREEN = True
    _dummy_pl = pv.Plotter(off_screen=True)
    _dummy_pl.add_mesh(pv.Sphere()) 
    _dummy_pl.show(auto_close=False) 
    _dummy_pl.close()
    pv.OFF_SCREEN = not interactive

    return free_display


def stop_xvfb(display_number, delay=3):
    """Stop the Xvfb process associated with the specified display number."""
    try:
        display_str = f":{display_number}"
        # Use pgrep to find the PID of running Xvfb
        pid = subprocess.check_output(["pgrep", "-f", f"Xvfb {display_str}"]).strip()
        pid_str = pid.decode("utf-8")
        if pid:
            # Let Qt/PyVista clients disconnect before the X server is stopped;
            # killing it immediately causes noisy XIO messages during shutdown.
            subprocess.Popen(
                ["bash", "-lc", f"sleep {delay}; kill {pid_str} >/dev/null 2>&1 || true"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            # print(f"Xvfb on {display_str} stopped.")
        else:
            print(f"No Xvfb process found for {display_str}.")
    except subprocess.CalledProcessError:
        print(f"No Xvfb process found for {display_str}.")


class RedisGlobalVariableManager:
    def __init__(self, host='localhost', port=6379, db=0):
        """Initialize the Redis connection."""
        self.r = redis.StrictRedis(host=host, port=port, db=db, decode_responses=True)

    def set_global_variable(self, key, value):
        """Set a global variable in Redis."""
        self.r.set(key, value)

    def get_global_variable(self, key):
        """Get a global variable from Redis."""
        value = self.r.get(key)
        return value

def pad_raw_data(raw, dura):
    sfreq = raw.info["sfreq"]
    n_samples = raw.n_times
    duration = n_samples / sfreq

    target_duration = np.ceil(duration / dura) * dura
    target_samples = int(target_duration * sfreq)

    if target_samples == n_samples:
        return raw.copy()

    n_pad = target_samples - n_samples

    data = raw.get_data()
    n_channels = data.shape[0]

    pad = np.zeros((n_channels, n_pad))
    data_padded = np.concatenate([data, pad], axis=1)

    raw_padded = mne.io.RawArray(data_padded, raw.info)

    raw_padded.set_meas_date(raw.info["meas_date"])

    # edited
    raw_padded.set_annotations(raw.annotations)
    raw_padded.info["bads"] = raw.info["bads"]

    return raw_padded

def load_bad_chn_seg(raw, fname_bad_chn, fname_bad_seg):
    """
    Load and apply bad MEG channel and segment information to a raw object.

    This function reads a list of bad channels and annotations of bad segments from
    files and applies them to a given raw MEG object. Only channels present in the
    raw data are retained.

    Parameters
    ----------
    raw : mne.io.Raw
        The raw MEG data object to update with bad channel and segment information.
    fname_bad_chn : str or Path
        File path containing the list of bad channels (one per line).
    fname_bad_seg : str or Path
        File path containing the annotations of bad segments in FIF format.

    Returns
    -------
    mne.io.Raw
        The raw object with updated `info['bads']` and annotations.

    Notes
    -----
    - Channels listed in `fname_bad_chn` that do not exist in `raw.ch_names` are ignored.
    - Existing annotations in `raw` are replaced with those loaded from `fname_bad_seg`.

    """

    bad_chn_info = Path(fname_bad_chn).open(encoding="utf-8").read().splitlines()
    bad_seg_info = mne.read_annotations(fname_bad_seg)

    raw.info["bads"] = [i for i in bad_chn_info if i in raw.ch_names]
    raw.set_annotations(bad_seg_info)

    return raw

def plot_snippets(
    fname_fif: str | Path,
    fname_bad_chn: str | Path,
    fname_bad_seg: str | Path,
    fname_img_out: str | Path,
    fname_chn_out: str | Path,
    device_type: Literal["elekta", "ctf", "opm", "kit", "4D"],
    segment_type: Literal["annotation", "segment", "summary"],
    n_chans: int = None,
    duration: float = None,
    n_jobs: int = None,
    lowpass: float = 45,
    dpi: int = 200,
    figsize: tuple[float, float] = (8, 4.5),
):
    """
    Generate segmented MEG time-series plots from a raw FIF file, with consistent channel counts and saved channel order.

    ! Before use, Change "path/to/python/Lib/site-packages/mne/viz/_mpl_figure.py" Line 550
    ! to `self.mne.trace_kwargs = dict(antialiased=True, linewidth=0.2)`

    This function loads a raw MEG recording, applies channel and segment exclusions, divides channels into regional groups,
    and plots time-series segments as images. When the total channel count is not divisible by the desired number of channels per plot,
    artificial placeholder channels (named “EEG…” in the implementation) filled with zeros are appended to maintain uniform channel
    counts across figures. These placeholder channels are rendered white and therefore invisible in the resulting images. After plotting,
    each saved image is automatically cropped to retain only the region containing the signal traces.

    Parameters
    ----------
    fname_fif : str or path-like
        Path to the input raw FIF file.
    fname_bad_chn : str or path-like
        Path to a text file listing bad channels.
    fname_bad_seg : str or path-like
        Path to an MNE annotation file marking bad segments.
    fname_img_out : str or path-like
        Output filename pattern for saving images.
        Supports placeholders `#` (channel group index) and `$` (segment onset time in seconds).
    fname_chn_out : str or path-like
        Output file path for saving the mapping from channel group index to channel names (Joblib `.jl` format).
    device_type : {'elekta', 'ctf', 'opm', 'kit', '4D'}
        Type of MEG device, used to determine appropriate plotting scaling parameters.
    segment_type : {'annotation', 'segment'}
        Method of segmentation.
        - "annotation": use onsets from annotations.
        - "segment": use fixed-length segments based on `duration` as onsets.
    n_chans : int
        Number of channels to display per figure.
    duration : float
        Length of each plotted segment in seconds.
    lowpass : float, optional
        Low-pass filter cutoff frequency (Hz) applied before plotting. Default is 45.
    n_jobs : int
        Number of parallel jobs to use for plotting.
    dpi : int, optional
        Image resolution (dots per inch). Default is 200.
    figsize : tuple of float, optional
        Figure size in inches (width, height). Default is (8, 4.5).

    Notes
    -----
    - Placeholder EEG channels are added only to make the total number of channels divisible by `n_chans`.
    These channels are filled with zeros and drawn in white, ensuring uniform layout across all figures.
    - The function adjusts MNE's visualization settings to produce clean figures without scrollbars or scalebars.
    - After saving each plot, the function detects and crops the region containing the time-series traces
    by analyzing pixel intensity.
    - The mapping of each figure's channel order is stored in a Joblib file for recording.

    Outputs
    -------
    - Image files (`.jpg`) saved according to `fname_img_out` pattern.
    - Channel mapping file (`fname_chn_out`, Joblib `.jl`) linking figure indices to corresponding channel names.

    Examples
    --------
    >>> plot_snippets(
    ...     fname_fif="subject_raw.fif",
    ...     fname_bad_chn="bad_channels.txt",
    ...     fname_bad_seg="bad_segments.txt",
    ...     fname_img_out="./plots/chn.#/seg.$.jpg",
    ...     fname_chn_out="./plots/channel_map.jl",
    ...     device_type="opm",
    ...     segment_type="segment",
    ...     n_chans=30,
    ...     duration=60,
    ...     lowpass=45,
    ...     n_jobs=2,
    ... )

    """

    def find_argmin(arr):
        n = len(arr)
        a1 = np.argmin(arr[: n // 2])
        a2 = n // 2 + np.argmin(arr[n // 2 :])
        return a1, a2

    if segment_type != "summary":
        if duration is None:
            raise ValueError("When plot in segment or annotation mode, duration must not be None.")

    fname_img_out = Path(fname_img_out)
    fname_chn_out = Path(fname_chn_out)

    plt.rcParams["font.size"] = 5
    plt.rcParams["axes.linewidth"] = 0.5
    plt.rcParams["xtick.major.width"] = 0.5
    plt.rcParams["ytick.major.width"] = 0.5
    plt.rcParams["xtick.minor.width"] = 0.5
    plt.rcParams["ytick.minor.width"] = 0.5

    raw = mne.io.read_raw_fif(fname_fif, preload=True)
    raw = load_bad_chn_seg(raw, fname_bad_chn, fname_bad_seg)
    raw.filter(None, lowpass)

    if "grad" in raw.info.get_channel_types():
        raw.pick(["mag", "grad"])
    else:
        raw.pick("mag")

    idx = _divide_to_regions(raw.info)
    idx = (
        idx["Left-frontal"]
        + idx["Right-frontal"]
        + idx["Right-parietal"]
        + idx["Left-parietal"]
        + idx["Left-temporal"]
        + idx["Right-temporal"]
        + idx["Right-occipital"]
        + idx["Left-occipital"]
    )
    mag = [i for i in idx if raw.info.get_channel_types()[int(i)] == "mag"]
    grad = [i for i in idx if raw.info.get_channel_types()[int(i)] == "grad"]

    if duration is None:
        duration = raw.times[-1] - raw.times[0]

    if n_chans is None:
        n_chans = raw.info["nchan"]

    if segment_type == "summary":
        # duration = raw.times[-1] - raw.times[0] #edited
        n_chans = raw.info["nchan"]

    # add raw info for reports.
    raw_info = {
        "raw.annotations.orig_time": raw.annotations.orig_time,
        "first_time": raw.first_time,
        "last_time": raw.last_samp / raw.info["sfreq"],
    }

    if segment_type in ["segment", "summary"]:
        raw = pad_raw_data(raw, duration) # warning: force first time=0.

    n_chn_old = raw.info["nchan"]
    if len(mag + grad) % n_chans != 0:
        n_chn_new = ((n_chn_old // n_chans) + 1) * n_chans

        eeg_info = mne.create_info([f"EEG{i}" for i in range(n_chn_new - n_chn_old)], raw.info["sfreq"], ch_types="eeg")
        raw.add_channels(
            [
                mne.io.RawArray(
                    np.zeros((n_chn_new - n_chn_old, raw.times.size)),
                    eeg_info,
                )
            ],
            force_update_info=True,
        )
    else:
        n_chn_new = n_chn_old

    order_list = mag + grad + list(range(n_chn_old, n_chn_new))

    kwarg = {}
    kwarg["n_channels"] = n_chans
    kwarg["color"] = dict(mag="#4E342E", grad="#0D47A1", eeg="#FFFFFF")
    kwarg["bad_color"] = "#F44336"
    kwarg["show_scrollbars"] = False
    kwarg["show_scalebars"] = False
    kwarg["block"] = False
    kwarg["show"] = False
    kwarg["proj"] = True
    kwarg["clipping"] = 1.5

    if device_type.lower() == "opm":
        kwarg["scalings"] = dict(mag=2.5e-12)
    elif device_type.lower() == "kit":
        kwarg["scalings"] = dict(mag=0.5e-12)
    else:
        kwarg["scalings"] = None

    if segment_type == "annotation":
        iterator = raw.annotations.onset
    elif segment_type == "segment":
        iterator = [i * duration for i in range(int(raw.times[-1] + duration - 1) // duration)]
    elif segment_type == "summary":
        # iterator = [0] #edited
        iterator = [i * duration for i in range(int(raw.times[-1] + duration - 1) // duration)]

    chn_list = {}
    for chn in range(n_chn_new // n_chans):
        chn_list[chn] = [raw.ch_names[i] for i in order_list[chn * n_chans : (chn + 1) * n_chans]]

    fname_chn_out.parent.mkdir(parents=True, exist_ok=True)
    chn_list.update(raw_info)
    jl.dump(chn_list, fname_chn_out)

    # clear annotations and bads chn
    raw.info['bads'] = []
    raw.set_annotations(None)

    raw_serialized = cloudpickle.dumps(raw)

    def worker(seg, chn, raw_serialized=raw_serialized):
        matplotlib.use("agg")
        mne.viz.set_browser_backend("matplotlib")

        raw = cloudpickle.loads(raw_serialized)

        kwarg["start"] = seg
        kwarg["order"] = order_list[chn * n_chans : (chn + 1) * n_chans]

        fname_out__ = Path(str(fname_img_out).replace("#", f"{chn}").replace("$", f"{seg:.3f}"))
        fname_out__.parent.mkdir(parents=True, exist_ok=True)
        if fname_out__.exists():
            return

        if seg + duration > raw.times[-1]:
            kwarg["duration"] = raw.times[-1] - seg
        else:
            kwarg["duration"] = duration

        fig = raw.copy().plot(**kwarg)

        fig.set_size_inches(*figsize)
        plt.savefig(fname_out__, dpi=dpi)
        plt.close()

        img = plt.imread(fname_out__)

        img_sum = np.sum(img, axis=2)
        w1, w2 = find_argmin(img_sum.mean(axis=0))
        h1, h2 = find_argmin(img_sum.mean(axis=1))

        img = img[h1:h2, w1:w2, :]
        plt.imsave(fname_out__, img)

    proc_list = [[seg, chn] for seg in iterator for chn in range(n_chn_new // n_chans)]

    jl.Parallel(n_jobs=n_jobs)(jl.delayed(worker)(seg, chn) for seg, chn in proc_list)

