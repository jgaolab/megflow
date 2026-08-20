# !/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import json
import os
import math
from numbers import Integral
import numpy as np
import mne
import joblib as jl
import matplotlib as mpl
import matplotlib.pyplot as plt

from pathlib import Path
from scipy.stats import kurtosis
from scipy.io import loadmat
from PIL import Image, ImageDraw, ImageFont
from mne.annotations import _annotations_starts_stops
from mne.preprocessing import ICA, read_ica
from utils import load_bad_chn_seg

mne.viz.set_browser_backend('matplotlib')
mpl.rcParams['figure.max_open_warning'] = 100


class ICAInputValidationError(RuntimeError):
    """An actionable, machine-readable ICA input validation failure."""

    def __init__(self, code, message, validation):
        super().__init__(message)
        self.code = code
        self.validation = validation


def _write_ica_input_validation(validation_path, validation):
    if validation_path is None:
        return
    validation_path = Path(validation_path)
    validation_path.parent.mkdir(parents=True, exist_ok=True)
    validation_path.write_text(
        json.dumps(validation, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _ica_picks(raw, modality):
    if modality == 'eeg':
        return mne.pick_types(raw.info, meg=False, eeg=True, eog=False,
                              stim=False, exclude='bads')
    if modality == 'meg':
        return mne.pick_types(raw.info, meg=True, eeg=False, eog=False,
                              stim=False, exclude='bads', ref_meg=False)
    if modality == 'meeg':
        return mne.pick_types(raw.info, meg=True, eeg=True, eog=False,
                              stim=False, exclude='bads')
    return None


def _merged_bad_sample_count(raw):
    starts, stops = _annotations_starts_stops(raw, ["BAD"])
    intervals = sorted(
        (max(0, int(start)), min(raw.n_times, int(stop)))
        for start, stop in zip(starts, stops)
        if int(stop) > int(start)
    )
    merged = []
    for start, stop in intervals:
        if stop <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], stop))
        else:
            merged.append((start, stop))
    return sum(stop - start for start, stop in merged)


def _fail_ica_input_validation(code, title, guidance, validation, validation_path):
    total_samples = validation.get("total_samples")
    bad_samples = validation.get("bad_samples")
    if total_samples is None or bad_samples is None:
        coverage = "Bad-sample coverage is unavailable because the sidecar could not be applied."
    else:
        coverage = (
            f"Bad-sample coverage: {bad_samples}/{total_samples} samples "
            f"({validation['bad_coverage_fraction']:.1%})."
        )
    message = (
        f"{title} [{code}]\n"
        f"Bad-segment sidecar: {validation['bad_segment_sidecar']}\n"
        f"{coverage}\n"
        f"How to fix: {guidance}"
    )
    validation.update(
        status="failed",
        error_code=code,
        error_message=message,
    )
    _write_ica_input_validation(validation_path, validation)
    raise ICAInputValidationError(code, message, validation)


def prepare_ica_input(
    fn_data,
    n_components,
    modality,
    fname_bad_channels,
    fname_bad_segments,
    validation_path=None,
):
    """Validate ICA input from FIF metadata and annotations without signal reads."""
    validation = {
        "status": "pending",
        "error_code": None,
        "error_message": None,
        "requested_components": n_components,
        "bad_channel_sidecar": str(fname_bad_channels),
        "bad_segment_sidecar": str(fname_bad_segments),
        "sidecars": {
            "bad_channels": str(fname_bad_channels),
            "bad_segments": str(fname_bad_segments),
        },
    }
    raw = mne.io.read_raw_fif(fn_data, preload=False, verbose=False)
    sfreq = float(raw.info["sfreq"])
    validation.update(
        total_samples=int(raw.n_times),
        total_seconds=float(raw.n_times / sfreq),
        bad_samples=None,
        bad_seconds=None,
        usable_samples=None,
        usable_seconds=None,
        bad_coverage_fraction=None,
        eligible_channel_count=None,
        bad_channel_count=None,
    )

    try:
        sidecar_annotations = mne.read_annotations(fname_bad_segments)
        raw = load_bad_chn_seg(raw, fname_bad_channels, fname_bad_segments)
    except Exception as exc:
        _fail_ica_input_validation(
            "invalid_bad_segment_sidecar",
            "INVALID_BAD_SEGMENT_SIDECAR",
            (
                "regenerate the bad-segment sidecar from this recording and check "
                f"its time origin. Original error: {exc}"
            ),
            validation,
            validation_path,
        )
    if len(raw.annotations) < len(sidecar_annotations):
        _fail_ica_input_validation(
            "invalid_bad_segment_sidecar",
            "INVALID_BAD_SEGMENT_SIDECAR",
            (
                "regenerate the bad-segment sidecar from this recording; one or "
                "more annotation times fall completely outside the data"
            ),
            validation,
            validation_path,
        )

    bad_samples = int(_merged_bad_sample_count(raw))
    usable_samples = int(raw.n_times - bad_samples)
    picks = _ica_picks(raw, modality)
    if picks is None:
        eligible_channel_count = len(raw.ch_names) - len(raw.info["bads"])
    else:
        eligible_channel_count = len(picks)
    validation.update(
        bad_samples=bad_samples,
        bad_seconds=float(bad_samples / sfreq),
        usable_samples=usable_samples,
        usable_seconds=float(usable_samples / sfreq),
        bad_coverage_fraction=(
            float(bad_samples / raw.n_times) if raw.n_times else 0.0
        ),
        eligible_channel_count=int(eligible_channel_count),
        bad_channel_count=len(raw.info["bads"]),
    )

    if eligible_channel_count == 0:
        _fail_ica_input_validation(
            "no_eligible_meg_channels",
            "NO_ELIGIBLE_MEG_CHANNELS",
            (
                "review the bad-channel list and restore valid MEG channels, then "
                "rerun artifact detection and ICA"
            ),
            validation,
            validation_path,
        )
    if usable_samples == 0:
        _fail_ica_input_validation(
            "no_usable_samples_after_bad_annotations",
            "ICA_INPUT_ALL_BAD",
            (
                "review the bad-segment annotations, correct intervals that cover "
                "valid data, and rerun artifact detection"
            ),
            validation,
            validation_path,
        )

    if isinstance(n_components, Integral) and not isinstance(n_components, bool):
        available = min(eligible_channel_count, usable_samples)
        if n_components > available:
            _fail_ica_input_validation(
                "requested_components_exceed_available_input",
                "REQUESTED_COMPONENTS_EXCEED_AVAILABLE_INPUT",
                (
                    f"request at most {available} components ({eligible_channel_count} "
                    f"eligible channels and {usable_samples} usable samples), or "
                    "provide more usable input"
                ),
                validation,
                validation_path,
            )
    elif isinstance(n_components, (float, np.floating)) and 0 < n_components < 1:
        if usable_samples < 2:
            _fail_ica_input_validation(
                "requested_components_exceed_available_input",
                "REQUESTED_COMPONENTS_EXCEED_AVAILABLE_INPUT",
                (
                    "a variance-threshold component request needs at least 2 usable "
                    "samples; correct the bad annotations or provide more data"
                ),
                validation,
                validation_path,
            )

    validation["status"] = "passed"
    _write_ica_input_validation(validation_path, validation)
    return raw, validation

def add_text(fig_path,exp_var):
    image1 = Image.open(fig_path)

    # Define the text and its formatting
    mag_ratio = exp_var.get("mag")
    if mag_ratio is None:
        return
    text = 'mag:{:.1f}'.format(mag_ratio * 100)+'%'
    # text += ' grad:{:.1f}'.format(exp_var['grad']*100)+'%'
    # font = ImageFont.load_default()  # You can specify a different font if needed    
    font_size = 24  # Set the desired font size
    # font = ImageFont.truetype("/usr/share/fonts/open-sans/OpenSans-Regular.ttf", font_size)
    font = ImageFont.load_default()
    
    # Split the text into words
    words = text.split()
    
    # Add text to the left-top corner of the first image with custom font colors
    draw1 = ImageDraw.Draw(image1)
    
    # Iterate through words and specify custom colors for specific words
    x, y = 10, 2  # Initial position
    for word in words:
        try:
            float_number = abs(float(word))
            if float_number>0.1 and float_number<1:
                text_color = (255, 0, 0)
            # elif float_number>k_thres:
            #     text_color = (255, 0, 0)
            else:
                text_color = (0, 0, 0)
        except ValueError:
            text_color = (0, 0, 0)    
            
        draw1.text((x, y), word, fill=text_color, font=font) 
        x += font.getlength(word) + 5  # Move x position for the next word    
   
    image1.save(fig_path)    
    image1.close()





def str_to_bool(value):
    if isinstance(value, bool):
        return value
    value = str(value).strip().lower()
    if value in {"true", "t", "1", "yes", "y"}:
        return True
    if value in {"false", "f", "0", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError(f"Expected boolean value, got: {value}")


def remove_stale_component_property_outputs(subj_res_path, subj_res_path_ica, compute_explained_variance):
    explained_var_file = Path(subj_res_path) / "ica_explained_var.jl"
    if not compute_explained_variance and explained_var_file.exists():
        explained_var_file.unlink()
    stale_pattern = "*.png" if compute_explained_variance else "*_evar_*.png"
    for file_path in Path(subj_res_path_ica).glob(stale_pattern):
        if compute_explained_variance and not file_path.stem.isdigit():
            continue
        file_path.unlink()


def save_component_property_figures(fig_list, subj_res_path_ica, raw, ica, compute_explained_variance):
    explained_var_list = []
    for component_idx, fig in enumerate(fig_list):
        if compute_explained_variance:
            explained_var_ratio = ica.get_explained_variance_ratio(raw, components=[component_idx], ch_type=["mag"])
            for channel_type, ratio in explained_var_ratio.items():
                print(f"Fraction of {channel_type} variance explained by IC {component_idx}: {ratio}")
            fig_path = Path(subj_res_path_ica) / f'{component_idx}_evar_{explained_var_ratio.get("mag", 0.0):.4f}.png'
            explained_var_list.append(explained_var_ratio)
        else:
            fig_path = Path(subj_res_path_ica) / f"{component_idx}.png"

        try:
            fig.savefig(fig_path)
            plt.close(fig)
            if compute_explained_variance:
                add_text(fig_path, explained_var_list[-1])
        except Exception as e:
            print(e)

    return explained_var_list


def run_ica(
    subj_tag,
    subj_res_path,
    subj_res_path_ica,
    fn_data,
    fn_ica,
    n_IC,
    modality,
    fname_bad_channels,
    fname_bad_segments,
    random_seed,
    compute_explained_variance=False,
):
    figs = []
    subj_res_path = Path(subj_res_path)
    subj_res_path.mkdir(parents=True, exist_ok=True)
    subj_res_path_ica = Path(subj_res_path_ica)
    subj_res_path_ica.mkdir(parents=True, exist_ok=True)
    compute_explained_variance = bool(compute_explained_variance)
    raw, _ = prepare_ica_input(
        fn_data=fn_data,
        n_components=n_IC,
        modality=modality,
        fname_bad_channels=fname_bad_channels,
        fname_bad_segments=fname_bad_segments,
        validation_path=subj_res_path / "ica_input_validation.json",
    )
    raw.load_data()
    raw_ = raw
    remove_stale_component_property_outputs(subj_res_path, subj_res_path_ica, compute_explained_variance)

    if not os.path.exists(os.path.join(subj_res_path, fn_ica)):
        ica = ICA(n_components=n_IC, 
                method='fastica',
                max_iter='auto', 
                random_state=random_seed)

        picks = _ica_picks(raw_, modality)

        ica.fit(raw_, picks=picks, reject_by_annotation=True)
        ica.save(os.path.join(subj_res_path, fn_ica))
    else:
        ica = read_ica(os.path.join(subj_res_path, fn_ica))
    
    fig_list = []
    try:
        fig_list = ica.plot_properties(raw_, picks=list(range(ica.n_components_)), reject_by_annotation=True, reject=None,
                                       show=False, verbose=False)
    except Exception as e:
        print(e)

    explained_var_list = save_component_property_figures(
        fig_list=fig_list,
        subj_res_path_ica=subj_res_path_ica,
        raw=raw,
        ica=ica,
        compute_explained_variance=compute_explained_variance,
    )

    # combine png
    # for t in range(ica.n_components_):
    #     img1 = Image.open(f'{subj_res_path_ica}/_{t}.png')
    #     img2 = Image.open(f'{subj_res_path_ica}/_{t}_overlay.png')
    #
    #     total_width = img1.width + img2.width
    #     max_height = max(img1.height, img2.height)
    #
    #     new_img = Image.new('RGBA', (total_width, max_height))
    #
    #     x_offset = 0
    #     for img in [img1, img2]:
    #         new_img.paste(img, (x_offset, 0))
    #         x_offset += img.width
    #
    #     # save and remove verbose png.
    #     new_img.save(f'{subj_res_path_ica}/{t}_evar_{explained_var_list[t]["mag"]:.4f}.png')
    #     os.remove(f'{subj_res_path_ica}/_{t}.png')
    #     os.remove(f'{subj_res_path_ica}/_{t}_overlay.png')
    
    if compute_explained_variance:
        # save explained var list
        fname_ica_explained_var = os.path.join(subj_res_path, 'ica_explained_var.jl')
        jl.dump(explained_var_list, fname_ica_explained_var)

    #save sources 
    fname_ica_sources = os.path.join(subj_res_path, "ica_sources.fif")
    ica_sources = ica.get_sources(raw)

    if 'ctf_head_t' in raw.info:
        info = mne.create_info(ch_names=ica_sources.ch_names, ch_types=ica_sources.get_channel_types(),
                               sfreq=raw.info['sfreq'])
        ica_sources = mne.io.RawArray(ica_sources.get_data(), info)

    ica_sources.save(fname_ica_sources,overwrite=True)


    N = len(ica.unmixing_matrix_)
    dn = 20
    n = math.ceil(N / dn)
    plot_window = 200


    # plot ica comp tc
    for i in range(n):
        if i < n - 1:
            fig = ica.plot_sources(raw_, show=False,
                                    picks=list(np.linspace(dn * i, dn * (i + 1) - 1, dn).astype(int)), start=0,
                                    stop=plot_window, show_scrollbars=False)
            fig.savefig(os.path.join(subj_res_path_ica,
                                        'ica_comp_' + str(dn * i) + '-' + str(dn * (i + 1) - 1) + '_tc.png'), dpi=120)
            plt.close('all')
        else:
            fig = ica.plot_sources(raw_, show=False, picks=list(np.linspace(dn * i, N - 1, N - dn * i).astype(int)),
                                    start=0, stop=plot_window, show_scrollbars=False)
            fig.savefig(os.path.join(subj_res_path_ica, 'ica_comp_' + str(dn * i) + '-' + str(N - 1) + '_tc.png'),
                        dpi=120)
            plt.close('all')

    # plot ica comp topo
    try:
        figs = ica.plot_components(show=False)
        for i in list(np.linspace(0, n - 1, n).astype(int)):
            if i < n - 1:
                figs[i].savefig(os.path.join(subj_res_path_ica,
                                                'ica_comp_' + str(dn * i) + '-' + str(dn * (i + 1) - 1) + '_topo.png'),
                                dpi=120)
            else:
                figs[i].savefig(
                    os.path.join(subj_res_path_ica, 'ica_comp_' + str(dn * i) + '-' + str(N - 1) + '_topo.png'),
                    dpi=120)
        plt.close('all')
    except Exception as e:
        print(e)

    return figs


def parse_arguments():
    parser = argparse.ArgumentParser(description="Generate ICA components and plots for MEG data.")
    parser.add_argument('--raw_file', required=True, help='Path to the raw MEG file')
    parser.add_argument('--num_IC', required=True, type=float, help='The number of ICA components to generate')
    parser.add_argument('--output_dir', required=True, help='Path to save ICA plots and related files')
    parser.add_argument('--fname_bad_channels', required=True, help='Path to the bad channels file')
    parser.add_argument('--fname_bad_segments', required=True, help='Path to the bad segments file')
    parser.add_argument('--seed', required=False, default=2025, help='Random seed for ICA')
    parser.add_argument(
        '--compute_explained_variance',
        type=str_to_bool,
        default=False,
        help='Whether to compute per-component explained variance. Disabled by default because it is slow for many datasets.',
    )

    return parser.parse_args()

def main():
    args = parse_arguments()

    subj_tag = f"{Path(args.raw_file).stem}"
    subj_res_path = os.path.join(args.output_dir, f"{Path(args.raw_file).parent.name}")
    subj_res_path_ica = os.path.join(subj_res_path, "ica_results")
    os.makedirs(subj_res_path_ica, exist_ok=True)

    subj_ica_file = f"{subj_tag}_ica.fif"
    if not os.path.exists(subj_res_path):
        os.mkdir(subj_res_path)

    num_IC = args.num_IC
    if num_IC.is_integer():
        num_IC = int(num_IC)

    try:
        random_seed = args.seed
        random_seed = int(random_seed)
    except Exception:
        random_seed = 2025

    run_ica(
        subj_tag=subj_tag,
        subj_res_path=subj_res_path,
        subj_res_path_ica=subj_res_path_ica,
        fn_data=args.raw_file,
        fn_ica=subj_ica_file,
        n_IC=num_IC,
        modality="meg",
        fname_bad_channels=args.fname_bad_channels,
        fname_bad_segments=args.fname_bad_segments,
        random_seed=random_seed,
        compute_explained_variance=args.compute_explained_variance,
    )


if __name__ == "__main__":
    main()
