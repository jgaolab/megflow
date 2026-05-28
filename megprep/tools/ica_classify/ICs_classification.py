# coding:utf-8
import time
import os
import mne
import numpy as np
import matplotlib.pyplot as plt
import joblib as jl
from collections import defaultdict
from scipy.signal import correlate, savgol_filter, find_peaks
from mne.preprocessing import peak_finder
from mne.epochs import make_fixed_length_epochs
from sleepecg import detect_heartbeats
from scipy.stats import linregress
from collections import defaultdict

from .brain_mapping import get_chan_mapping,get_brain_mapping


# ecg related
def calculate_heart_rate(peaks, fs, decimal=2):
    """
    Calculate the heart rate (BPM) based on R-peak positions.

    Parameters
    ----------
    peaks : array-like
        Positions (indices) of R-peaks in the ECG signal.
    fs : float
        Sampling frequency of the signal (in Hz).
    decimal : int, optional
        Number of decimal places to round the heart rate to (default: 2).

    Returns
    -------
    float
        Calculated heart rate in BPM. Returns 0 if the number of peaks is insufficient.
    """
    if len(peaks) > 1:
        peak_times = np.array(peaks) / fs
        rr_intervals = np.diff(peak_times)
        heart_rate = 60 / np.mean(rr_intervals)
        heart_rate = round(heart_rate, decimal)
    else:
        heart_rate = 0
    return heart_rate


def compute_autocorrelation(signal, fs=1000):
    """
    Compute the autocorrelation of the signal using a template from the end of the signal.

    Parameters
    ----------
    signal : array-like
        Input time-domain signal.
    fs : int, optional
        Sampling frequency of the signal (default: 1000 Hz).

    Returns
    -------
    np.ndarray
        Autocorrelation result (same length as the input signal).
    """
    template_signal = signal[-1 * fs:]
    return correlate(signal, template_signal, mode='same')


def template_matching(signal, fs=1000):
    """
    Perform template matching using normalized cross-correlation.

    Parameters
    ----------
    signal : array-like
        Input time-domain signal.
    fs : int, optional
        Sampling frequency of the signal (default: 1000 Hz).

    Returns
    -------
    np.ndarray
        Normalized cross-correlation between the signal and its first 4-second template.
    """
    template = signal[:4 * int(fs)]
    correlation = correlate(signal, template, mode='same')
    template_energy = np.sum(template ** 2)
    signal_energy = np.convolve(signal ** 2, np.ones(len(template)), mode='same')
    normalization = np.sqrt(signal_energy * template_energy + 1e-10)
    normalized_correlation = correlation / normalization
    return normalized_correlation


def compute_fft(signal, fs=1000):
    """
    Compute the magnitude spectrum of the signal using FFT and convert it to dB.

    Parameters
    ----------
    signal : array-like
        Input time-domain signal.
    fs : float, optional
        Sampling frequency of the signal (default: 1000 Hz).

    Returns
    -------
    freqs : np.ndarray
        Frequency array (Hz), only the positive frequencies.
    fft_db : np.ndarray
        FFT magnitude (in dB).
    """
    n = len(signal)
    freqs = np.fft.fftfreq(n, 1 / fs)
    fft_signal = np.fft.fft(signal)
    fft_magnitude = np.abs(fft_signal)[: n // 2]
    fft_db = 20 * np.log10(fft_magnitude + 1e-10)  # avoid log(0)
    return freqs[: n // 2], fft_db


def outlier_removal(data, method='iqr', z_threshold=1):
    """
    Remove outliers from a 1D array using either the IQR or z-score method.

    Parameters
    ----------
    data : array-like
        Input 1D data.
    method : {'iqr', 'zscore'}, optional
        Method to detect outliers (default: 'iqr').
    z_threshold : float, optional
        Only used when method='zscore'; data beyond this number of standard
        deviations from the mean is considered an outlier (default: 1).

    Returns
    -------
    np.ndarray
        Filtered data with outliers removed.
    """
    data = np.array(data)
    if method == 'iqr':
        Q1 = np.percentile(data, 25)
        Q3 = np.percentile(data, 75)
        IQR = Q3 - Q1
        lower_bound = Q1 - 1.5 * IQR
        upper_bound = Q3 + 1.5 * IQR
        filtered_data = data[(data >= lower_bound) & (data <= upper_bound)]
    elif method == 'zscore':
        mean_val = np.mean(data)
        std_val = np.std(data)
        z_scores = (data - mean_val) / std_val
        filtered_data = data[np.abs(z_scores) < z_threshold]
    else:
        filtered_data = data

    return filtered_data


def replace_outliers(data, z_threshold=1, fill_method="zero"):
    """
    Remove outliers from a 1D array using the Z-score method and fill in the outliers
    either with 0 or with the average of adjacent non-outlier values while maintaining the original array length.

    Parameters
    ----------
    data : array-like
        Input 1D data.
    z_threshold : float, optional
        Threshold for identifying outliers; values with a Z-score exceeding this threshold are considered outliers (default is 1).
    fill_method : str, optional
        Method to fill in the outliers; options are "zero" (fill with 0) or "neighbor" (fill with the average of adjacent non-outliers, default is "zero").

    Returns
    -------
    np.ndarray
        Data array with outliers replaced as specified by the fill_method.
    """
    data = np.array(data)

    mean_val = np.mean(data)  # Calculate the mean of the data
    std_val = np.std(data)  # Calculate the standard deviation of the data

    # Calculate the Z-scores of the data
    z_scores = (data - mean_val) / std_val

    # Identify indices of outliers
    outlier_indices = np.abs(z_scores) >= z_threshold

    # Create a copy of the original data to store output
    filtered_data = np.copy(data)

    if fill_method == "zero":
        # Fill outliers with 0
        filtered_data[outlier_indices] = 0
    elif fill_method == "neighbor":
        # Initialize an array to store the means of neighbors for outliers
        neighbor_means = np.full(data.shape, np.nan)

        # Get indices of non-outlier values
        non_outlier_indices = np.where(~outlier_indices)[0]

        # Iterate through each outlier and calculate the mean of adjacent non-outlier values
        for i in np.where(outlier_indices)[0]:
            # Find the last non-outlier index to the left
            if i > 0:
                left_indices = non_outlier_indices[non_outlier_indices < i]
                left_mean = data[left_indices].mean() if left_indices.size > 0 else np.nan
            else:
                left_mean = np.nan

            # Find the first non-outlier index to the right
            right_indices = non_outlier_indices[non_outlier_indices > i]
            right_mean = data[right_indices].mean() if right_indices.size > 0 else np.nan

            # Calculate the average of the adjacent non-outlier values
            if not np.isnan(left_mean) and not np.isnan(right_mean):
                neighbor_means[i] = (left_mean + right_mean) / 2
            elif not np.isnan(left_mean):
                neighbor_means[i] = left_mean
            elif not np.isnan(right_mean):
                neighbor_means[i] = right_mean

        # Replace outliers in the original data with the calculated neighbor means
        filtered_data[outlier_indices] = neighbor_means[outlier_indices]

    return filtered_data


def find_ecg_ics(ica_sources_raw,time_start=0, time_segment=10, time_segment_ratio=0.9, ts_ecg_num_max=20, l_freq=0.1, h_freq=10, savefig=False,
                 savefig_path=".", peak_threshod_coef=0.4, peak_std_threshold_coef=0.05, verbose=False):
    """
    Identify potential ECG (electrocardiogram) components from ICA sources
    within a given time segment.

    This function crops the provided MNE raw object to the desired time segment,
    applies a bandpass filter, and then computes a variety of metrics (R-peak
    detection, autocorrelation via template matching, etc.) to determine which
    Independent Components (ICs) are likely ECG-related. The function produces
    debug plots and prints out whether each IC is classified as periodic/ECG-like.

    Parameters
    ----------
    ica_sources_raw : mne.io.Raw
        The raw ICA sources loaded by MNE, which will be cropped and filtered
        in-place.
    time_start : float, optional
        Extract the start time of the ICA source.
    time_segment : float, optional
        Time duration in seconds to crop from the beginning of the raw data.
        Default is 10.
    time_segment_ratio: float, optional
        The proportional value of the number of peaks required within the time_segment duration.
    ts_ecg_num_max : int, optional
        Maximum number of heartbeats expected in the chosen time segment for
        a healthy individual (used as a cutoff in periodicity checks).
        Default is 20.
    l_freq : float, optional
        Lower cutoff frequency for the bandpass filter. Default is 0.1 Hz.
    h_freq : float, optional
        Upper cutoff frequency for the bandpass filter. Default is 10 Hz.
    savefig_path: str, optional
        Directory of figure.
    peak_threshod_coef: float,optional
        Indicates the threshold of the number of ecg signal peak interval (unit: index). (peak_threshod = 0.4 * fs)
    peak_std_threshold_coef: float, optional
        Standard deviation threshold of ecg signal peak interval (unit: index). (peak_std_threshold = peak_std_threshold_coef * fs)

    Notes
    -----
    - The function operates on the raw object in-place, meaning it crops and
      filters the data permanently.
    - It plots the results (ECG signal, autocorrelation) and saves the figure
      as "debug.png".
    - If a signal is found to be periodic, the function pauses for 6 seconds
      before continuing to the next IC.

    Returns
    -------
    ecg_list
        This function does not return a value. Results are displayed via
        console prints and saved plots.

    Examples
    --------
    >>> raw = mne.io.read_raw_fif('example_ica_sources.fif', preload=True)
    >>> find_ecg_ics(raw, time_segment=10, ts_ecg_num_max=20, l_freq=0.1, h_freq=10)
    """
    # peak_std_threshold = 50 #100
    # time_segment = 10 #10
    # ts_ecg_num_max = 20 # Normal person's maximum heartbeat count in 10s

    fs = ica_sources_raw.info['sfreq']
    peak_std_threshold = peak_std_threshold_coef * fs  # for 1 seconds

    is_periodics = []
    # ica_sources_raw.crop(0, time_segment)
    total_duration = ica_sources_raw.times[-1]

    # update parameters
    ts_ecg_num_max = (total_duration / time_segment) * ts_ecg_num_max
    # peak_std_threshold = (total_duration / time_segment) * peak_std_threshold
    time_segment = (total_duration / time_segment) * time_segment # 必须最后

    ica_sources_raw.filter(l_freq=l_freq, h_freq=h_freq)
    ica_sources_data = ica_sources_raw.get_data()
    ic_nums = ica_sources_data.shape[0]
    ecg_list = []  # Store indices of ICs considered ECG-like

    for ic_num in range(0, ic_nums):

        if verbose:
            print(f"[IC_classify]ICs num is:{ic_num}")

        _ic_signal = ica_sources_data[ic_num, :]

        # Outlier remove & fill
        _ic_signal = replace_outliers(_ic_signal, z_threshold=6, fill_method='neighbor')

        # Smooth signal
        ic_signal = savgol_filter(_ic_signal, window_length=11, polyorder=2) # window_length=20

        # Outlier remove & fill
        # ic_signal = replace_outliers(ic_signal, z_threshold=6, fill_method='neighbor')

        fs = ica_sources_raw.info['sfreq']
        t = ica_sources_raw.times

        # Square or fourth power operation to enhance QRS wave amplitude
        ecg_signal = ic_signal ** 4

        # R-peak detection using sleepecg
        peaks = detect_heartbeats(ecg_signal, fs)

        # Autocorrelation using template matching (normalized cross-correlation)
        autocorr = template_matching(ecg_signal,fs)
        autocorr /= np.max(autocorr)

        peak_corr, peak_amp = peak_finder(autocorr, verbose=verbose)
        mean_amp = np.mean(peak_amp)
        std_amp = np.std(peak_amp)
        # print(f"peak_corr:{peak_corr}, peak_amp:{peak_amp}")

        # Select peaks above threshold
        threshold = 0.01 * mean_amp
        filtered_peak_corr = peak_corr[peak_amp > threshold]
        if verbose:
            print("[IC_classify]corr threshold:", threshold,"peak_amp: ",peak_amp)
            print("[IC_classify]filtered_peak_corr:", filtered_peak_corr)

        # Simple periodicity check
        if len(peak_corr) != 1 and len(peaks) != 1:
            diff_peak = np.mean(outlier_removal(np.diff(peaks)))
            diff_peak_std = np.std(outlier_removal(np.diff(peaks)))
            diff_peak_corr = np.mean(outlier_removal(np.diff(peak_corr)))
            diff_peak_corr_std = np.std(outlier_removal(np.diff(peak_corr)))
            if verbose:
                print("######:peaks:", peaks)
                print("diff_peak_corr:", diff_peak_corr)
                print("diff_peak:", diff_peak)

                print(f"len(peaks)({len(peaks)}) >= time_segment({time_segment_ratio * time_segment}): {len(peaks) >= time_segment_ratio * time_segment}")

                print(f"len(peaks)({len(peaks)}) <= ts_ecg_num_max({ts_ecg_num_max}): {len(peaks) <= ts_ecg_num_max}" )

                print(f"len(peak_corr)({len(peak_corr)}) >= time_segment({time_segment_ratio * time_segment}): {len(peak_corr) >= time_segment_ratio * time_segment}")

        else:
            diff_peak = 0
            diff_peak_corr = 0
            diff_peak_std = 0
            diff_peak_corr_std = 0

        # default values.
        is_periodic = False
        if len(peaks) >= (time_segment_ratio * time_segment) and len(peaks) <= ts_ecg_num_max and len(peak_corr) >= (time_segment_ratio * time_segment):
            if diff_peak >= peak_threshod_coef * fs and diff_peak_corr >= peak_threshod_coef * fs:
                if verbose:
                    print("Judge periodic:")
                    print(f"     diff_peak({diff_peak}) >= {peak_threshod_coef} * fs({peak_threshod_coef * fs}): {diff_peak >= peak_threshod_coef * fs}")
                    print(f"     diff_peak std({diff_peak_std}) <= peak_std_threshold({peak_std_threshold}): {diff_peak_std <= peak_std_threshold}")
                if diff_peak_corr_std <= peak_std_threshold or diff_peak_std <= peak_std_threshold:
                    is_periodic = True
        else:
            is_periodic = False


        if savefig:
            # Plotting
            plt.figure(figsize=(12, 12))
            fig_num = 4
            cnt = 1

            plt.subplot(fig_num, 1, cnt)
            plt.plot(_ic_signal)
            plt.title(f"Signal-{ic_num}")
            plt.xlabel("Time")
            plt.ylabel("Au")

            cnt += 1
            plt.subplot(fig_num, 1, cnt)
            plt.plot(ic_signal)
            plt.title(f"Smooth_Signal-{ic_num}")
            plt.xlabel("Time")
            plt.ylabel("Au")

            cnt += 1
            plt.subplot(fig_num, 1, cnt)
            plt.plot(t, ecg_signal, label="ECG Signal")
            plt.plot(t[peaks], ecg_signal[peaks], 'rx', label="R-peaks (Heartbeats)")
            plt.title(f"ECG Signal with Detected R-peaks (Heartbeats:{calculate_heart_rate(peaks, fs)})-sleepecg")
            plt.xlabel("Time [s]")
            plt.ylabel("Amplitude")
            # plt.text(0, 8, f'Is ECG?: {is_periodic}', fontsize=24, color='red')

            cnt += 1
            plt.subplot(fig_num, 1, cnt)
            plt.plot(autocorr)
            plt.plot(t[filtered_peak_corr] * fs, autocorr[filtered_peak_corr], 'rx', label="peaks (Heartbeats)")
            plt.title('Autocorrelation of ECG Signal-autocorr')
            plt.xlabel('Position')
            plt.ylabel('Similarity Score')

            plt.tight_layout()
            if not os.path.exists(savefig_path):
                os.makedirs(savefig_path)

            print(f"[IC_classify]Is the IC-{ic_num} signal likely to be an ECG signal?:{is_periodic}")
            plt.savefig(os.path.join(savefig_path, f"fecg__visual_ic_{ic_num}.png"))
            plt.close()

        if is_periodic:
            ecg_list.append(ic_num)

    return ecg_list


# topomap related
def ics_topomap_distribution(ica_fit_file, ica_sources_raw, ic_nums_list=[], savefig=False, savefig_path='.',
                             verbose=False):
    # Get the ICA topomap data for the specified component
    ica = mne.preprocessing.read_ica(ica_fit_file)
    topomap_ic = ica.get_components()
    ica_data = ica_sources_raw.get_data()
    print("topomap_ic:",topomap_ic.shape,len(ica.ch_names))
    # **select ICA components**
    ic_nums = ica_data.shape[0]
    region_energies_dict = defaultdict()
    # for component_idx in [2]:
    if not ic_nums_list:
        ic_nums_list = list(range(0, ic_nums))

    chan_mapping = get_chan_mapping(ica.info)

    for component_idx in ic_nums_list:
        regions = get_brain_mapping(ica.info)
        all_channels = chan_mapping.keys()
        data = topomap_ic[:, component_idx]

        # Calculate energy for all channels (not just the selected regions)
        total_energy = np.square(data)  # The energy for all channels

        # 4. 计算每个脑区的总能量
        region_energies = {}

        for region, electrodes in regions.items():
            # 找到每个脑区对应的电极在数据中的索引
            region_indices = [chan_mapping[electrode]
                              for electrode in electrodes
                              if electrode in chan_mapping]
            region_energy = np.sum(total_energy[region_indices])  # 计算该脑区的总能量
            region_energies[region] = region_energy

        # 5. 输出结果：展示每个脑区的能量强度
        attention_region_frontal = 0
        attention_region_temporal = 0
        attention_region_occipital = 0
        for region, energy in region_energies.items():
            if 'temporal' in region.lower():
                attention_region_temporal += energy
            if 'frontal' in region.lower():
                attention_region_frontal += energy
            if 'occipital' in region.lower():
                attention_region_occipital += energy

        # Calculate energy for the remaining channels (outside of defined regions)
        remaining_channels = [chan for chan in all_channels if
                              chan not in [electrode for region in regions.values() for electrode in region]]

        # Get the indices for the remaining channels
        remaining_channel_indices = [chan_mapping[chan] for chan in remaining_channels if chan in chan_mapping]

        # Calculate the energy for the remaining channels
        remaining_channel_energy = np.sum(total_energy[remaining_channel_indices])

        # Combine region energies with the energy of the remaining channels
        region_energies['Remaining'] = remaining_channel_energy

        # 3. Output results
        if verbose:
            for region, energy in region_energies.items():
                print(f"[IC_classify]IC-{component_idx}_{region} Total energy：{energy:.2f}")

        flag = ''
        if attention_region_frontal > remaining_channel_energy:
            flag += 'frontal'
        if attention_region_temporal > remaining_channel_energy:
            flag += ' temporal'

        if savefig:
            #  Visualize: Bar chart with region energies and remaining channel energy
            plt.bar(region_energies.keys(), region_energies.values(),
                    color=['blue', 'green', 'red', 'purple', 'orange'])
            plt.title(f"Brain Power - IC:{component_idx} including Remaining Channels")
            plt.xlabel("Brain Area / Remaining")
            plt.ylabel("Power")
            plt.xticks(rotation=45)
            # plt.text(-1, -2, f'Attention!!!_{flag}', fontsize=24, color='red')

            plt.tight_layout()
            if not os.path.exists(savefig_path):
                os.makedirs(savefig_path)
            plt.savefig(os.path.join(savefig_path, "vis_topo_with_remaining.png"))
            plt.close()

        if verbose:
            for region, proportion in region_energies.items():
                print(f"[IC_classify]IC-{component_idx}_{region} Energy Proportion: {proportion:.2f}%")
        region_energies_dict[component_idx] = region_energies

    return region_energies_dict


# PSD related
# ECG typical band: 8-16 Hz
# EOG typical band: 1-10 Hz
# EMG typical band: 7-45 Hz
def compute_psd(data: np.ndarray, info: mne.Info) -> tuple:
    """
    Compute the PSD (Power Spectral Density) of a single ICA component.

    Parameters
    ----------
    data : numpy.ndarray
        One-dimensional array of shape (n_timepoints,) representing the ICA component signal.
    info : mne.Info
        MNE info structure containing sampling frequency and channel info.

    Returns
    -------
    psds : numpy.ndarray
        PSD values of shape (1, n_freq_bins).
    freqs : numpy.ndarray
        Frequency bins corresponding to the PSD values.
    """
    sfreq = info['sfreq']
    single_info = mne.create_info(ch_names=['ic'], sfreq=sfreq, ch_types=['mag'])
    data_2d = data[np.newaxis, :]
    raw_ic = mne.io.RawArray(data_2d, single_info)

    # Compute PSD using MNE's native method
    spectrum = raw_ic.compute_psd(picks=[0])
    psds, freqs = spectrum.get_data(return_freqs=True, picks="all", exclude=[])

    return psds, freqs


def analyze_psd_curve(frequencies: np.ndarray,
                      psd_values: np.ndarray,
                      ic_num: int,
                      attention_low_freq: float = 0.0,
                      attention_high_freq: float = 12.0,
                      savefig: bool = True,
                      savefig_path: str = '.',
                      verbose: bool = True) -> tuple:
    """
    Analyze the PSD curve in terms of overall slope, local sections, and any unusually high PSD.

    Specifically:
      1. Computes a linear regression over the entire frequency range to check if
         the PSD slope is ascending or descending.
      2. Splits the frequency range into segments and checks each segment's slope.
      3. Detects if there are PSD values exceeding the highest amplitude in the
         user-specified low-frequency subrange (default 0-5 Hz).

    Parameters
    ----------
    frequencies : numpy.ndarray
        Frequency bins for the PSD.
    psd_values : numpy.ndarray
        PSD amplitude values corresponding to each frequency bin.
    ic_num : int
        ICs number
    attention_low_freq : float, optional
        The low cutoff for checking unusually high PSD within this range, by default 0.0.
    attention_high_freq : float, optional
        The high cutoff for checking unusually high PSD within this range, by default 5.0.
    savefig : bool, optional
        Whether to save the figure showing the PSD curve analysis, by default True.
    savefig_path : str, optional
        Directory path to save the figure if savefig is True, by default '.'.
    verbose: bool, optional
        print log info.

    Returns
    -------
    abnormal_segments : list of tuple
        A list of tuples (start_freq, end_freq) for those segments whose slope > 0.
    exceeding_frequencies : numpy.ndarray
        Frequency values at which the PSD amplitude exceeds the maximum amplitude
        in the range [attention_low_freq, attention_high_freq].
    """
    # Local segmentation: define threshold for positive or near-zero slope
    threshold_slope_near_zero = 0.00
    abnormal_segments = []
    exceeding_frequencies = []
    overall_slope_abnormal = False

    # Overall slope
    slope, intercept, r_value, p_value, std_err = linregress(frequencies, psd_values)
    if verbose:
        print(f"Overall slope: {slope:.4f}, r_value: {r_value:.4f}")

    if verbose:
        if slope >= 0:
            print("Warning: Overall slope is non-negative (flat or ascending). Potential artifact.")
            overall_slope_abnormal = True
        else:
            print("Overall slope is negative (descending), which is generally expected for PSD.")

            # Segment size (split into roughly 3 segments, make sure at least 2 points)
    segment_size = max(2, len(frequencies) // 3)
    for i in range(0, len(frequencies) - segment_size, segment_size):
        segment_slope, _, _, _, _ = linregress(
            frequencies[i:i + segment_size],
            psd_values[i:i + segment_size]
        )
        freq_range = (frequencies[i], frequencies[i + segment_size - 1])
        if verbose:
            print(f"Segment slope: {segment_slope:.4f}, frequency range: {freq_range}")

        if segment_slope > threshold_slope_near_zero:
            abnormal_segments.append(freq_range)
    if verbose:
        if abnormal_segments:
            print("Local abnormal segments (near zero or positive slope):", abnormal_segments)
        else:
            print("No significant local abnormal segments found.")

            # Check for amplitude exceeding the max in [attention_low_freq, attention_high_freq]
    freq_mask = (frequencies >= attention_low_freq) & (frequencies <= attention_high_freq)
    if np.any(freq_mask):
        initial_max_value = np.max(psd_values[freq_mask])
    else:
        initial_max_value = 0  # If the mask is empty, fallback

    exceed_indices = np.where(psd_values > initial_max_value)[0]
    if len(exceed_indices) > 0:
        exceeding_frequencies = frequencies[exceed_indices]
        if verbose:
            print(f"Warning: Found frequencies where PSD amplitude exceeds the "
                  f"{attention_low_freq}-{attention_high_freq} Hz max amplitude.")
            print("Frequencies exceeding that threshold:", exceeding_frequencies)
    else:
        if verbose:
            print(f"No PSD amplitude exceeds the maximum in the "
                  f"{attention_low_freq}-{attention_high_freq} Hz range.")

            # Optionally save diagnostic figure
    if savefig:
        if not os.path.exists(savefig_path):
            os.makedirs(savefig_path)

        plt.figure(figsize=(8, 5))
        plt.plot(frequencies, psd_values, label='PSD Curve')
        plt.xlabel('Frequency (Hz)')
        plt.ylabel('PSD Amplitude')
        plt.title('PSD Curve Analysis')
        plt.axhline(y=initial_max_value, color='r', linestyle='--',
                    label=f'{attention_low_freq}-{attention_high_freq} Hz Max')
        plt.legend()
        plt.tight_layout()
        plt.savefig(os.path.join(savefig_path, f"ics_psd_line_{ic_num}.png"))
        plt.close()

    return abnormal_segments, exceeding_frequencies, overall_slope_abnormal


def analyze_curve(frequencies: np.ndarray, psd_values: np.ndarray, ic_num: int) -> None:
    """
    Perform slope analysis and generate diagnostic plots of a PSD curve for a single ICA component.

    1. Computes slope at each bin via finite differences to assess increasing/flat/descending segments.
    2. Plots the slope and the PSD for visual inspection.

    Parameters
    ----------
    frequencies : numpy.ndarray
        The frequency bins corresponding to the PSD data.
    psd_values : numpy.ndarray
        The PSD amplitude at each frequency bin.
    ic_num : int
        The ICA component index used to label the plot.

    Returns
    -------
    None
        This function does not return any values; it saves a plot to "debug_line.png".

    """
    # Calculate slopes via finite differences
    slopes = np.diff(psd_values) / np.diff(frequencies)

    # Visualization
    plt.figure(figsize=(10, 5))

    # Plot derivative (slopes)
    plt.subplot(2, 1, 1)
    plt.plot(frequencies[:-1], slopes, marker='o', label='Slopes')
    plt.axhline(0, color='gray', linestyle='--')
    plt.title(f'Slope Analysis of PSD Curve (IC-{ic_num})')
    plt.xlabel('Frequency (Hz)')
    plt.ylabel('Slope (ΔPSD / ΔFreq)')
    plt.legend()

    # Plot the PSD curve
    plt.subplot(2, 1, 2)
    plt.plot(frequencies, psd_values)
    plt.title('PSD Curve')
    plt.xlabel('Frequency (Hz)')
    plt.ylabel('PSD Amplitude')
    plt.grid()
    plt.tight_layout()
    plt.savefig("debug_line.png")
    plt.close()


def find_abnormal_psd_ics(
        ica_sources_raw: mne.io.Raw,
        low_freq_energy_threshold: float = 0.5,
        low_freq: float = 10.0,
        high_freq: float = 30.0,
        attention_low_freq: float = 0.0,
        attention_high_freq: float = 150.0,
        le_low_freq: float = 0.0,
        le_high_freq: float = 12.0,
        savefig: bool = False,
        save_fig_path: str = '.',
        verbose: bool = False
) -> list:
    """
    Identify abnormal ICA components based on PSD analyses.

    This function:
      1. Creates fixed-length epochs from the ICA source signal.
      2. Computes the PSD for each epoch and averages them.
      3. Assesses the ratio of low-frequency energy (< low_freq Hz) and high-frequency energy (> high_freq Hz).
      4. Flags components whose low-frequency energy ratio exceeds a threshold (default 0.5).
      5. Further analyzes the PSD curve for abnormal segments and PSD peaks.

    Parameters
    ----------
    ica_sources_raw : mne.io.Raw
        The raw object containing ICA sources as channels.
    low_freq_energy_threshold : float, optional
        Threshold above which the component is flagged by low-frequency energy ratio, by default 0.5.
    low_freq : float, optional
        Frequency cutoff for low-frequency energy evaluation, by default 10.0.
    high_freq : float, optional
        Frequency cutoff for high-frequency energy evaluation, by default 30.0.
    attention_low_freq : float, optional
        Minimum frequency for plotting and more detailed PSD checks, by default 0.0.
    attention_high_freq : float, optional
        Maximum frequency for plotting and more detailed PSD checks, by default 150.0.
    le_low_freq : float, optional
        Lower bound for local amplitude comparison in analyze_psd_curve, by default 0.0.
    le_high_freq : float, optional
        Upper bound for local amplitude comparison in analyze_psd_curve, by default 5.0.
    savefig : bool, optional
        If True, saves PSD figures to disk, by default True.
    save_fig_path : str, optional
        Directory path to save figures if savefig is True, by default '.'.
    verbose : bool, optional
        If True, prints out diagnostic information during processing, by default True.

    Returns
    -------
    list
        A list of ICA component indices that are identified as abnormal.

    Notes
    -----
    - The PSD is computed on epochs of duration 2 seconds.
    - The function uses a log scaling approach and applies some multipliers to PSD values
      to highlight differences.
    - The function calls `analyze_psd_curve` to check for local slope anomalies and PSD
      exceeding the baseline in a given frequency range.
    """

    # Storage for results
    psd_abnormal = []
    abnormal_segments_dict = {}
    exceeding_psds_dict = {}
    abnormal_psds_ics = []  # Collect final set of abnormal ICS
    lowfreqHz_ics = []
    # Create fixed-length epochs from the ICA source signals
    epochs_src = make_fixed_length_epochs(
        ica_sources_raw,
        duration=2,
        preload=True,
        reject_by_annotation=True,
        proj=False,
        verbose=False
    )

    # Extract data and metadata
    ica_sources_data = ica_sources_raw.get_data()
    sfreq = ica_sources_raw.info['sfreq']
    n_ics = ica_sources_data.shape[0]

    # Compute PSD across epochs using MNE
    psd_args = {}
    nyquist_freq = epochs_src.info["sfreq"] / 2.0
    lp_filter = epochs_src.info["lowpass"]
    psd_args["fmax"] = min(lp_filter * 1.25, nyquist_freq)
    specs = epochs_src.compute_psd(picks='all', **psd_args)
    epoch_psds, epoch_freqs = specs.get_data(return_freqs=True)

    for ic_num in range(n_ics):
        # Optionally, could compute PSD with Welch on the entire signal:
        # freqs, psds = welch(ica_sources_data[ic_num, :], sfreq, nperseg=int(sfreq * 2))

        # Take the average PSD for the chosen IC across all epochs
        mean_ic_psd = epoch_psds[:, ic_num, :].mean(axis=0)

        # Compute low-/high-frequency energy ratios
        # low_freq_energy = np.sum(psds[freqs < low_freq]) / np.sum(psds)
        # high_freq_energy = np.sum(psds[freqs > high_freq]) / np.sum(psds)

        low_freq_energy = np.sum(mean_ic_psd[epoch_freqs < low_freq]) / np.sum(mean_ic_psd)
        high_freq_energy = np.sum(mean_ic_psd[epoch_freqs > high_freq]) / np.sum(mean_ic_psd)

        if verbose:
            print(f"IC-{ic_num} | Low-frequency energy (<{low_freq} Hz) ratio: {low_freq_energy:.2f}")
            print(f"IC-{ic_num} | High-frequency energy (>{high_freq} Hz) ratio: {high_freq_energy:.2f}")

            # Flag as abnormal if low-frequency ratio is too high
        if low_freq_energy >= low_freq_energy_threshold:
            psd_abnormal.append(ic_num)

            # Optionally plot the PSD
        if savefig:
            if not os.path.exists(save_fig_path):
                os.makedirs(save_fig_path)

            # Scale and transform PSD (example approach)
            scaling = 1e15
            coef = 10
            epoch_psds *= scaling * scaling
            # Convert to log scale
            np.log10(np.maximum(epoch_psds, np.finfo(float).tiny), out=epoch_psds)
            epoch_psds *= coef

            plt.figure(figsize=(10, 5))
            plt.plot(epoch_freqs, mean_ic_psd)
            # plt.semilogy(epoch_freqs, mean_ic_psd)

            plt.title(f'Epoch-Averaged PSD (IC-{ic_num})')
            plt.xlabel('Frequency (Hz)')
            plt.ylabel('Log-Scaled Power')
            plt.grid()
            plt.xlim(attention_low_freq, attention_high_freq)
            plt.text(0, 0.5,
                     f'Low Freq ratio: {low_freq_energy:.2f} - IC: {ic_num}',
                     fontsize=12, color='red')
            plt.tight_layout()
            plt.savefig(os.path.join(save_fig_path, f"ics_psd_{ic_num}.png"))
            plt.close()

            # Filter frequency range for more detailed analysis
        freq_mask = (epoch_freqs >= attention_low_freq) & (epoch_freqs <= attention_high_freq)
        filtered_freqs = epoch_freqs[freq_mask]
        filtered_psd_vals = mean_ic_psd[freq_mask]

        # Detailed PSD analysis (overall slope, local segments, etc.)
        abn_segments, exceed_freqs, overall_slope_abnormal = analyze_psd_curve(
            filtered_freqs,
            filtered_psd_vals,
            ic_num=ic_num,
            attention_low_freq=le_low_freq,
            attention_high_freq=le_high_freq,
            savefig=False,  # Already saved above; or set True if you want separate figs
            savefig_path=save_fig_path,
            verbose=False,
        )

        if len(abn_segments) > 0:
            abnormal_segments_dict[ic_num] = abn_segments
            abnormal_psds_ics.append(ic_num)
        if len(exceed_freqs) > 0:
            exceeding_psds_dict[ic_num] = exceed_freqs
            abnormal_psds_ics.append(ic_num)
        if overall_slope_abnormal:
            abnormal_psds_ics.append(ic_num)

            # Final summary
    if verbose:
        print("\n=== Summary of Abnormal Findings ===")
        print("ICs with abnormal low-frequency ratio (>= 0.5):", psd_abnormal)
        print("ICs with local slope anomalies:", abnormal_segments_dict)
        print("ICs with PSD amplitude exceeding the 0-5 Hz max amplitude:", exceeding_psds_dict)

        # Combine all abnormal ICs and remove duplicates
    abnormal_psds_ics.extend(psd_abnormal)
    abnormal_psds_ics = sorted(list(set(abnormal_psds_ics)))

    return abnormal_psds_ics, psd_abnormal


def _config_enabled(config, key, default=True):
    value = config.get(key, default)
    if isinstance(value, dict):
        return value.get("enabled", default)
    return bool(value)


def _kwargs_without_enabled(value):
    if not isinstance(value, dict):
        return {}
    return {key: item for key, item in value.items() if key != "enabled"}


def classify_ics(ica_source_file,ica_fit_file,explained_var_file=None,config=None):
    config = config or {}
    ica_sources_raw = mne.io.read_raw_fif(ica_source_file, preload=True)
    meg_vendor = config.get('meg_vendor','auto')
    meg_vendor_by_dataset = config.get("meg_vendor_by_dataset") or config.get("meg_vendor_map") or {}
    if isinstance(meg_vendor, dict):
        meg_vendor_by_dataset = meg_vendor_by_dataset or meg_vendor
        meg_vendor = meg_vendor.get("default", "auto")
    collect_outlier_rules = bool(config.get("collect_outlier_rules", True))
    exclude_ics = []  # store all exclude ics
    exclude_ics_dict = defaultdict(list)   # store all exclude ics

    ## ECG ICs detection.
    ecg_ics = []
    try:
        ecg_ics = find_ecg_ics(ica_sources_raw.copy(),
                               **_kwargs_without_enabled(config.get("find_ecg_ics")),
                               savefig=False,
                               savefig_path='./figs_ics',
                               verbose=False)

        print("[IC_classify | First screening]ECG list:", ecg_ics)
        brain_areas_dict = ics_topomap_distribution(ica_fit_file, ica_sources_raw.copy(), ecg_ics)

        for _ic_num in ecg_ics:
            # case 1：颞枕叶脑区能量应大于其余脑区
            temporal_occip_power = 0
            for brain_name in ['temporal', 'occipital']:
                temporal_occip_power += brain_areas_dict[_ic_num][f'Left-{brain_name}'] + brain_areas_dict[_ic_num][
                    f'Right-{brain_name}']

            other_power = 0
            # for brain_name in ['Left-frontal', 'Right-frontal', 'Remaining']: //backup,old version.
            for brain_name in ['Remaining']:
                    other_power += brain_areas_dict[_ic_num][brain_name]

            # case 2： 枕叶额叶能量大于其余脑区
            occipital_frontal_power = 0
            for brain_name in ['occipital', 'frontal']:
                occipital_frontal_power += brain_areas_dict[_ic_num][f'Left-{brain_name}'] + brain_areas_dict[_ic_num][
                    f'Right-{brain_name}']

            other_power_2 = 0
            for brain_name in ['Remaining']: # oldversion: 'Left-temporal', 'Right-temporal','Remaining'
                other_power_2 += brain_areas_dict[_ic_num][brain_name]

            # case 1：颞枕叶脑区能量应大于其余脑区 or case 2： 枕叶额叶能量大于其余脑区
            print("brain_areas_dict：",brain_areas_dict)
            print(f"IC_num:{_ic_num}  temporal_occip_power:{temporal_occip_power}__other_power_brain:{other_power}")
            print(f"IC_num:{_ic_num}  fontal_occip_power:{occipital_frontal_power}__other_power_brain:{other_power_2}")
            if (temporal_occip_power > other_power) or (occipital_frontal_power > other_power_2):
                exclude_ics.append(_ic_num)
    except Exception as e:
        print("ECG rules error:", e)

    print("[IC_classify]ECG abnormal list:", exclude_ics)
    exclude_ics_dict['ic_ecg'].extend(exclude_ics)

    # 根据explained var的值来判断，纳入异常ICs
    exp_var_ics = []
    explained_var_config = config.get('explained_var') or {}
    if (
        collect_outlier_rules
        and explained_var_config.get("enabled", True)
        and explained_var_file
        and os.path.exists(explained_var_file)
    ):
        try:
            explained_var_threshold = explained_var_config.get('threshold',0.1)  # 即解释值应小于10%的解释程度，才归纳为正常值。| 调高阈值为10%
            explained_var_list = jl.load(explained_var_file)
            for ic_num, explained_var in enumerate(explained_var_list):
                ch_type = explained_var_config.get('ch_type','mag')
                value = explained_var.get(ch_type) if isinstance(explained_var, dict) else None
                if value is None:
                    continue
                if value > explained_var_threshold:
                    exclude_ics.append(ic_num)
                    exp_var_ics.append(ic_num)
                    print(f"Explained Var Threshold:{explained_var_threshold} < {value:.4f}-Ic_num:", ic_num)
        except Exception as e:
            print("Explained variance rules error:", e)
    else:
        print(f"Explained variance outlier rules skipped; disabled, not requested, or file is missing: {explained_var_file}")

    exclude_ics_dict['ic_outlier'].extend(exp_var_ics)

    # PSD来判断EOG等异常成分
    abnormal_psd_ics = []
    lowfreqHz_ics = []
    if _config_enabled(config, "find_abnormal_psd_ics", True):
        try:
            abnormal_psd_ics, lowfreqHz_ics = find_abnormal_psd_ics(ica_sources_raw, **_kwargs_without_enabled(config.get("find_abnormal_psd_ics")))
            print("[IC_classify]low_freq_psd_ics:", lowfreqHz_ics)
            if collect_outlier_rules:
                print("[IC_classify]abnormal_psd_ics:", abnormal_psd_ics)
                exclude_ics.extend(abnormal_psd_ics)
                exclude_ics_dict['ic_outlier'].extend(abnormal_psd_ics)
            else:
                print("[IC_classify]PSD outlier collection skipped because ic_outlier is disabled.")
        except Exception as e:
            print("PSD rules error:", e)

    # EOG # 双侧额颞能量高、且psd小于10Hz高占比
    try:
        brain_areas_dict = ics_topomap_distribution(ica_fit_file, ica_sources_raw.copy(), lowfreqHz_ics)
        # print("brain_areas_dict(low freq&EOG):",brain_areas_dict)
        eog_ics = []
        for ic_num in lowfreqHz_ics:
            _eog_power = 0
            other_power = 0
            for brain_name in ['Left-frontal', 'Right-frontal', 'Left-temporal', 'Right-temporal']:
                _eog_power += brain_areas_dict[ic_num][brain_name]
            for brain_name in ['Left-occipital', 'Right-occipital', 'Left-parietal', 'Right-parietal', 'Remaining']:
                other_power += brain_areas_dict[ic_num][brain_name]
            if _eog_power > other_power:
                print(f"[IC_classify]EOG ICs:{ic_num}")
                exclude_ics.append(ic_num)
                eog_ics.append(ic_num)
        exclude_ics_dict['ic_eog'].extend(eog_ics)

        exclude_ics_dict['ic_outlier'] = sorted(list(set(exclude_ics_dict['ic_outlier'])))
        exclude_ics = sorted(list(set(exclude_ics)))
    except Exception as e:
        print("ICs_topomap_distribution error:", e)

    # Newly: TopoMap Template Similarity of ECG&EOG.
    try:
        from .ICs_template_similarity import find_ecg_eog_ics, resolve_device_type_from_dataset_map
        mapped_vendor, matched_dataset = resolve_device_type_from_dataset_map(
            meg_vendor_by_dataset,
            [ica_fit_file, ica_source_file],
        )
        if mapped_vendor is not None:
            meg_vendor = mapped_vendor
            print(f"Template similarity MEG vendor from dataset map ({matched_dataset}): {meg_vendor}")
        ecg_eog_dict = find_ecg_eog_ics(ica_fit_file, device_type=meg_vendor)
        print("ECG&EOG Template Similarity Exclude ICs:", ecg_eog_dict)
        exclude_ics_dict["ic_eog"].extend(ecg_eog_dict["ic_eog"])
        exclude_ics_dict["ic_ecg"].extend(ecg_eog_dict["ic_ecg"])
        exclude_ics_dict["ic_eog"] = list(set(exclude_ics_dict["ic_eog"]))
        exclude_ics_dict["ic_ecg"] = list(set(exclude_ics_dict["ic_ecg"]))
    except Exception as e:
        print("TemplateSimilarity Error:", e)

    print("[IC_classify]Final Exclude ICs:", exclude_ics_dict)
    return exclude_ics,exclude_ics_dict


