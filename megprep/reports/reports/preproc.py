# !/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import streamlit as st
import mne
import time
import pandas as pd
from reports.utils import in_docker, merge_and_deduplicate_annotations,filter_files_by_keyword
from pathlib import Path
from datetime import timedelta

mne.viz.set_browser_backend('matplotlib')

# Custom CSS for better styling
st.markdown("""
    <style>
        /* Main header styling */
        .main-header {
            # background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 15px;
            text-align: center;
            font-weight: 700;
            # box-shadow: 0 8px 16px rgba(102, 126, 234, 0.3);
            margin-bottom: 30px;
            animation: fadeInDown 0.6s ease-out;
        }
    .sub-header {
        font-size: 1.2rem;
        color: #666;
        margin-bottom: 2rem;
    }
    .info-box {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 1rem 0;
    }
    .metric-card {
        background-color: #ffffff;
        padding: 1rem;
        border-radius: 0.5rem;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    /* 统一按钮样式 */
    .stButton button {
        font-weight: 500;
        border-radius: 0.5rem;
        transition: all 0.3s ease;
    }
    .stButton button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.15);
    }
    /* 导航按钮特殊样式 */
    div[data-testid="column"] .stButton button {
        height: 2.5rem;
        font-size: 0.9rem;
    }
    /* 保存按钮样式 */
    .stForm button[kind="primaryFormSubmit"] {
        height: 3rem !important;
        font-size: 1rem !important;
        font-weight: 600 !important;
        white-space: nowrap !important;
        padding: 0.5rem 2rem !important;
    }
    </style>
""", unsafe_allow_html=True)

# set report root dir.
if in_docker():
    report_root_dir = "/output"
else:
    report_root_dir = st.session_state.get("dataset_report_path")

DATA_DIR = os.path.join(report_root_dir, "preprocessed")


# Cache filtered raw
@st.cache_data
def filter_data(_raw, freqrange):
    raw_filtered = _raw.copy().filter(*freqrange, n_jobs=8)
    raw_filtered.set_annotations(_raw.annotations)
    raw_filtered.info['bads'] = _raw.info['bads']
    return raw_filtered


@st.cache_data
def plot_psd(_raw, freqrange):
    psd_fig = _raw.compute_psd().plot(show=False)
    return psd_fig


def load_bad_segments(bad_segments_file, origin_raw):
    """Load bad segments from file and return onset list"""
    bad_segments = []
    if os.path.exists(bad_segments_file):
        annotations = mne.read_annotations(bad_segments_file)
        old_annot = origin_raw.annotations
        if old_annot != annotations:
            annotations = merge_and_deduplicate_annotations(
                annotations,
                old_annot,
                orig_time=origin_raw.annotations.orig_time
            )
        bad_segments = annotations.onset.tolist()
    return bad_segments




# Page Title
st.markdown('<h2 class="main-header">🧠 MEG Preprocessing Results</h2>', unsafe_allow_html=True)


# Check if data directory exists
if not os.path.exists(DATA_DIR):
    st.error(f"⚠️ Data directory '{DATA_DIR}' does not exist. Please create it and add .fif files.")
    DATA_DIR = st.text_input("📁 Please specify a new data directory:", "")

# List .fif files in directory
files = sorted(
    [os.path.join(root, f) for root, dirs, _files in os.walk(DATA_DIR) for f in _files if f.endswith("-raw.fif")])

if not files:
    st.warning("⚠️ No .fif files found in the data directory. Please add some MEG files.")
else:
    # ========== SIDEBAR ==========
    with st.sidebar:
        # Sidebar styling
        st.sidebar.markdown("""
            <div style='text-align: center; padding: 0px;'>
                <h2 >⚙️ Settings</h2>
            </div>
        """, unsafe_allow_html=True)
        st.header("📁 File Selection")
        # Custom filter
        st.markdown('<div class="filter-box">', unsafe_allow_html=True)

        # Initialize filter keyword in session state
        if 'filter_keyword' not in st.session_state:
            st.session_state.filter_keyword = ""

        filter_keyword = st.text_input(
            "🔍 Filter files by keyword:",
            value=st.session_state.filter_keyword,
            placeholder="e.g., sub-01, task-rest, run-1, etc.",
            help="Enter any keyword to filter files (case-insensitive). Leave empty to show all files.",
            key="filter_input"
        )
        st.session_state.filter_keyword = filter_keyword

        # Filter files
        filtered_files = filter_files_by_keyword(files, filter_keyword)

        selected_file = st.selectbox("Select a MEG File:", filtered_files, label_visibility="collapsed")

        if selected_file:
            # Cache management
            if "last_selected_file" not in st.session_state:
                st.session_state.last_selected_file = selected_file
            elif st.session_state.last_selected_file != selected_file:
                st.cache_data.clear()
                st.session_state.last_selected_file = selected_file

            st.markdown("---")

            # ========== VISUALIZATION SETTINGS ==========
            st.header("⚙️ Visualization Settings")

            with st.expander("🎚️ Signal Processing", expanded=True):
                freqrange = st.slider(
                    'Band-pass Filter (Hz)',
                    min_value=0,
                    max_value=300,
                    value=(1, 40),
                    help="Filter frequency range for visualization"
                )

            with st.expander("📊 Display Options", expanded=True):
                time_duration = st.selectbox(
                    '⏱️ Duration per View',
                    [10, 20, 30, 60],
                    index=2,
                    help="Time duration to display"
                )

                channel_range = st.selectbox(
                    '📡 Channels per View',
                    [10, 20, 30, 60],
                    help="Number of channels to display"
                )

            st.markdown("---")

            # ========== NAVIGATION ==========
            st.header("🧭 Navigation")

            # Load raw data info first
            file_path = os.path.join(DATA_DIR, selected_file)
            origin_raw = mne.io.read_raw_fif(file_path, preload=True)

            first_time = origin_raw.first_time
            last_time = origin_raw.last_samp / origin_raw.info['sfreq']

            # Load bad segments info
            subject_id_dir = Path(selected_file).parent.name
            artifact_dir = Path(selected_file).parent.parent / "artifact_report" / subject_id_dir
            bad_segments_file = artifact_dir / f"{subject_id_dir}_preproc-raw_bad_segments.txt"
            bad_segments = load_bad_segments(bad_segments_file, origin_raw)

            # Initialize navigation mode
            if 'navigation_mode' not in st.session_state:
                st.session_state.navigation_mode = 'manual' if not bad_segments else 'artifact'

            # Navigation mode selector (only show if artifacts exist)
            if bad_segments:
                nav_mode = st.radio(
                    "Navigation Mode",
                    options=['artifact','manual'],
                    format_func=lambda x: '⏰ Manual Time' if x == 'manual' else '🔴 Artifact Jump',
                    horizontal=True,
                    key='navigation_mode'
                )
            else:
                nav_mode = 'manual'

            # ========== MANUAL TIME NAVIGATION ==========
            if nav_mode == 'manual':
                with st.expander("⏰ Time Navigation", expanded=True):
                    st.caption(f"**Total Duration:** {(last_time - first_time):.2f} s")

                    # Initialize manual start time
                    if 'manual_start_time' not in st.session_state:
                        st.session_state.manual_start_time = 0.0

                    manual_start_time = st.number_input(
                        f'Start Time (s)',
                        min_value=0.,
                        max_value=(last_time - first_time - time_duration),
                        value=st.session_state.manual_start_time,
                        step=1.0,
                        format="%.2f",
                        help=f"Range: [0, {(last_time - first_time - time_duration):.2f}] s",
                        key='manual_time_input'
                    )
                    st.session_state.manual_start_time = manual_start_time
                    start_time = manual_start_time

            # Initialize channel navigation
            if 'start_channel' not in st.session_state:
                st.session_state.start_channel = 12

            with st.expander("📡 Channel Navigation", expanded=True):
                st.caption(f"**Total Channels:** {len(origin_raw.ch_names)}")
                start_channel = st.slider(
                    'Starting Channel',
                    min_value=0,
                    max_value=len(origin_raw.ch_names) - channel_range,
                    value=st.session_state.start_channel,
                    step=1,
                    help="Select the first channel to display"
                )
                st.session_state.start_channel = start_channel

                # Navigation buttons
                col1, col2 = st.columns(2)
                with col1:
                    prev_disabled = st.session_state.start_channel <= 0
                    if st.button('← Prev', width='stretch', disabled=prev_disabled, key="ch_prev"):
                        if st.session_state.start_channel > 0:
                            st.session_state.start_channel -= channel_range
                            st.rerun()

                with col2:
                    next_disabled = st.session_state.start_channel + channel_range >= len(origin_raw.ch_names)
                    if st.button('Next →', width='stretch', disabled=next_disabled, key="ch_next"):
                        if st.session_state.start_channel + channel_range < len(origin_raw.ch_names):
                            st.session_state.start_channel += channel_range
                            st.rerun()

                st.caption(
                    f"Showing channels {st.session_state.start_channel} - {st.session_state.start_channel + channel_range - 1}")

            # ========== ARTIFACT NAVIGATION ==========
            if bad_segments and nav_mode == 'artifact':
                st.markdown("---")
                st.header("🔴 Artifact Navigation")

                if 'current_bad_index' not in st.session_state:
                    st.session_state.current_bad_index = 0

                # Ensure index is within bounds
                if st.session_state.current_bad_index >= len(bad_segments):
                    st.session_state.current_bad_index = len(bad_segments) - 1
                if st.session_state.current_bad_index < 0:
                    st.session_state.current_bad_index = 0

                # Display current position info (显示相对时间)
                col1, col2 = st.columns([2, 1])
                with col1:
                    st.metric(
                        "Segment Position",
                        f"{st.session_state.current_bad_index + 1} / {len(bad_segments)}"
                    )
                with col2:
                    # 显示相对时间（去掉 first_time）
                    relative_onset = bad_segments[st.session_state.current_bad_index] - first_time
                    st.metric(
                        "Onset Time",
                        f"{relative_onset:.2f}s"
                    )

                # Navigation buttons
                col1, col2 = st.columns(2)
                with col1:
                    prev_artifact_disabled = st.session_state.current_bad_index <= 0
                    if st.button('← Prev', width='stretch', disabled=prev_artifact_disabled, key="art_prev"):
                        if st.session_state.current_bad_index > 0:
                            st.session_state.current_bad_index -= 1
                            st.rerun()

                with col2:
                    next_artifact_disabled = st.session_state.current_bad_index >= len(bad_segments) - 1
                    if st.button('Next →', width='stretch', disabled=next_artifact_disabled, key="art_next"):
                        if st.session_state.current_bad_index < len(bad_segments) - 1:
                            st.session_state.current_bad_index += 1
                            st.rerun()

                # Use artifact time
                current_segment_onset = bad_segments[st.session_state.current_bad_index]
                start_time = current_segment_onset - first_time

    # ========== MAIN CONTENT ==========
    if selected_file:
        # Select channels to display
        selected_channels = origin_raw.ch_names[
                            st.session_state.start_channel:st.session_state.start_channel + channel_range]

        # Filter data
        raw = origin_raw.copy().filter(*freqrange, n_jobs=8)

        # Load artifact files
        bad_channels_file = artifact_dir / f"{subject_id_dir}_preproc-raw_bad_channels.txt"

        # Load bad channels
        bad_channels = []
        if os.path.exists(bad_channels_file):
            with open(bad_channels_file, 'r') as f:
                bad_channels = [ch.strip() for ch in f.read().splitlines() if ch.strip()]
            raw.info['bads'].extend(origin_raw.info['bads'])
            raw.info["bads"].extend(bad_channels)

        # Load bad segments
        annotations = None
        if os.path.exists(bad_segments_file):
            annotations = mne.read_annotations(bad_segments_file)
            old_annot = origin_raw.annotations
            if old_annot != annotations:
                annotations = merge_and_deduplicate_annotations(
                    annotations,
                    old_annot,
                    orig_time=origin_raw.annotations.orig_time
                )
                raw.set_annotations(annotations)

        # ========== POWER SPECTRAL DENSITY ==========
        st.markdown("### 📊 Power Spectral Density (PSD)")
        with st.spinner("Computing PSD..."):
            psd_fig = plot_psd(raw, freqrange)
            st.pyplot(psd_fig)

        st.markdown("---")

        # ========== FILTERED WAVEFORM ==========
        st.markdown(f"### 📈 Filtered Waveform ({freqrange[0]}-{freqrange[1]} Hz)")

        # Show current view info with navigation mode indicator
        col1, col2, col3 = st.columns(3)
        with col1:
            nav_icon = "⏰" if st.session_state.navigation_mode == 'manual' else "🔴"
            st.info(f"{nav_icon} **Time:** {start_time:.2f} - {start_time + time_duration:.2f} s")
        with col2:
            st.info(
                f"📡 **Channels:** {st.session_state.start_channel} - {st.session_state.start_channel + channel_range - 1}")
        with col3:
            st.info(f"🎚️ **Filter:** {freqrange[0]}-{freqrange[1]} Hz")

        with st.spinner("Rendering waveform..."):
            fig_filtered = raw.plot(
                picks=selected_channels,
                n_channels=channel_range,
                duration=time_duration,
                start=start_time,
                show=False,
                block=False,
                show_scrollbars=False
            )
            st.pyplot(fig_filtered)

        st.markdown("---")

        # ========== ARTIFACT ANNOTATION EDITOR ==========
        st.markdown("### ✏️ Artifact Annotation Editor")

        # Initialize session states
        if "bad_segments" not in st.session_state:
            st.session_state.bad_segments = raw.annotations
        if "bad_channels" not in st.session_state:
            st.session_state.bad_channels = bad_channels
        if "save_triggered_s" not in st.session_state:
            st.session_state.save_triggered_s = False
        if "save_triggered_c" not in st.session_state:
            st.session_state.save_triggered_c = False
        if "save_triggered_r" not in st.session_state:
            st.session_state.save_triggered_r = False

        with st.form("edit_bad_channels"):
            col1, col2 = st.columns([1, 2])

            with col1:
                st.markdown("#### 🔴 Bad Channels")
                st.caption(f"Total bad channels: {len(bad_channels)}")
                raw.info["bads"] = bad_channels
                bad_ch_df = st.data_editor(
                    pd.DataFrame(raw.info['bads'], columns=['Bad Channels']),
                    num_rows="dynamic",
                    width='stretch',
                    height=300
                )
                bad_ch_df.dropna(inplace=True)

            with col2:
                st.markdown("#### 📊 Bad Segments")
                bad_segments_annot = raw.annotations
                st.caption(f"Total bad segments: {len(bad_segments_annot)}")

                # 转换为相对时间用于显示
                bad_seg_df_display = bad_segments_annot.to_data_frame(time_format=None)
                bad_seg_df_display['onset'] = bad_seg_df_display['onset'] - first_time

                # 重命名列以更清晰
                bad_seg_df_display = bad_seg_df_display.rename(columns={
                    'onset': 'onset (relative)',
                    'duration': 'duration',
                    'description': 'description'
                })

                bad_seg_df_edited = st.data_editor(
                    bad_seg_df_display,
                    num_rows="dynamic",
                    width='stretch',
                    height=300,
                    column_config={
                        "onset (relative)": st.column_config.NumberColumn(
                            "Onset (s)",
                            help="Time relative to waveform display (0-based)",
                            format="%.3f"
                        ),
                        "duration": st.column_config.NumberColumn(
                            "Duration (s)",
                            format="%.3f"
                        )
                    }
                )
                bad_seg_df_edited.dropna(inplace=True)

                # 转换回绝对时间用于保存
                bad_seg_df_edited['onset'] = bad_seg_df_edited['onset (relative)'] + first_time

                bad_seg_anat = mne.Annotations(
                    onset=bad_seg_df_edited['onset'].tolist(),
                    duration=bad_seg_df_edited['duration'].tolist(),
                    description=bad_seg_df_edited['description'].tolist(),
                    orig_time=origin_raw.annotations.orig_time
                )

            # 更新提示信息
            st.info(
                f"💡 **Tip:** The 'Onset' shown above matches the waveform time (0-based). "
                f"Actual stored value = Displayed value + {first_time:.3f}s | "
                f"Click outside the cell after editing to ensure changes are captured"
            )

            # Save button
            st.markdown("<br>", unsafe_allow_html=True)
            col1, col2, col3 = st.columns([1, 1, 1])
            with col2:
                save_changes = st.form_submit_button(
                    "💾 Save Changes",
                    width='stretch',
                    type="primary"
                )

            if save_changes:
                # ====== 新增：验证 bad segments 时间范围 ======
                total_duration = last_time - first_time
                invalid_segments = []

                for idx, row in bad_seg_df_edited.iterrows():
                    onset_rel = row['onset (relative)']
                    duration = row['duration']

                    # 检查是否超出范围
                    if onset_rel < 0:
                        invalid_segments.append(f"Segment {idx}: onset {onset_rel:.3f}s < 0")
                    elif onset_rel + duration > total_duration:
                        invalid_segments.append(
                            f"Segment {idx}: end time {onset_rel + duration:.3f}s exceeds duration {total_duration:.3f}s"
                        )

                if invalid_segments:
                    st.error("❌ **Invalid time ranges detected:**")
                    for msg in invalid_segments:
                        st.error(f"  • {msg}")
                    st.warning(f"⚠️ Please ensure all segments are within 0 - {total_duration:.3f}s")
                    st.stop()  # 阻止保存

                # ====== 新增：验证 bad channels 是否存在于 raw 中 ======
                invalid_channels = []
                valid_ch_names = set(origin_raw.ch_names)

                for idx, row in bad_ch_df.iterrows():
                    ch_name = row['Bad Channels']
                    if ch_name not in valid_ch_names:
                        invalid_channels.append(ch_name)

                if invalid_channels:
                    st.error("❌ **Invalid channel names detected:**")
                    for ch in invalid_channels:
                        st.error(f"  • Channel '{ch}' not found in raw data")
                    st.warning(f"⚠️ Please ensure all channels exist in the raw data")
                    with st.expander("📋 Available channels", expanded=False):
                        st.write(origin_raw.ch_names)
                    st.stop()  # 阻止保存
                # ====== 验证结束 ======

                with st.spinner("Saving changes..."):
                    st.session_state.save_triggered_s = True
                    st.session_state.save_triggered_c = True
                    st.session_state.save_triggered_r = True
                    st.session_state.bad_segments = bad_seg_anat
                    st.session_state.bad_channels = bad_ch_df

                    # Save files
                    bad_seg_anat.save(bad_segments_file, overwrite=True)
                    bad_ch_df.to_csv(bad_channels_file, header=False, index=False, sep='\n')

                    # Update raw data
                    origin_raw.set_annotations(bad_seg_anat)
                    bad_channels_list = bad_ch_df['Bad Channels'].tolist()
                    origin_raw.info['bads'] = bad_channels_list
                    origin_raw.save(file_path, overwrite=True)

                    # Reset navigation to first segment (or keep current if still valid)
                    new_bad_segments = load_bad_segments(bad_segments_file, origin_raw)
                    if 'current_bad_index' in st.session_state:
                        if st.session_state.current_bad_index >= len(new_bad_segments):
                            st.session_state.current_bad_index = 0

                st.success(f"✅ Successfully saved changes!")

                # Display saved files info with time conversion example
                with st.expander("📄 Saved Files Details", expanded=False):
                    st.markdown(f"- **Bad channels:** `{bad_channels_file.name}` ({len(bad_ch_df)} channels)")
                    st.markdown(f"- **Bad segments:** `{bad_segments_file.name}` ({len(bad_seg_anat)} segments)")
                    st.markdown(f"- **Raw data:** `{Path(file_path).name}`")
                    st.divider()
                    st.markdown("**Time Conversion:**")
                    st.markdown(f"- Display time (relative): 0-based")
                    st.markdown(f"- Stored time (absolute): Display time + {first_time:.3f}s")
                    if len(bad_seg_anat) > 0:
                        st.markdown(
                            f"- Example: Display `{bad_seg_anat[0]['onset'] - first_time:.3f}s` → Stored `{bad_seg_anat[0]['onset']:.3f}s`")

                time.sleep(1)
                st.rerun()
            else:
                st.session_state.save_triggered_s = False
                st.session_state.save_triggered_c = False
                st.session_state.save_triggered_r = False

        # ========== ADDITIONAL INFO ==========
        with st.expander("ℹ️ File Information", expanded=False):
            st.markdown(f"**Selected File:** `{selected_file}`")
            st.markdown(f"**Bad Channels File:** `{bad_channels_file}`")
            st.markdown(f"**Bad Segments File:** `{bad_segments_file}`")
            st.divider()
            st.markdown("**Measurement Info:**")
            st.json({
                "sfreq": origin_raw.info['sfreq'],
                "n_channels": len(origin_raw.ch_names),
                "duration": f"{(last_time - first_time):.2f} s",
                "first_time": f"{first_time:.3f} s",
                "n_bad_channels": len(raw.info['bads']),
                "n_bad_segments": len(raw.annotations)
            })
            st.divider()
            st.markdown("**Raw Data Info:**")
            st.write(origin_raw.info)

        # Status footer
        st.markdown("---")
        if st.session_state.save_triggered_c and st.session_state.save_triggered_s and st.session_state.save_triggered_r:
            st.info("✅ All changes have been saved successfully.")
        else:
            st.caption("💾 No unsaved changes")