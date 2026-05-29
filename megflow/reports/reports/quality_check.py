# !/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import json
import streamlit as st
import pandas as pd
import mne
from pathlib import Path
from reports.utils import in_docker, filter_files_by_keyword

# ==================== PATH CONFIGURATION ====================
if in_docker():
    report_root_dir = Path("/output")
else:
    report_root_dir = Path(st.session_state.get("dataset_report_path"))

preprocessed_dir = report_root_dir / "preprocessed"
ica_report_dir = preprocessed_dir / "ica_report"
artifact_report_dir = preprocessed_dir / "artifact_report"
trans_dir = preprocessed_dir / "trans"

# ==================== STYLING ====================
st.markdown("""
<style>
    /* Hide default elements */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    /* Main header */
    .main-header {
        color: white;
        padding: 20px;
        border-radius: 15px;
        text-align: center;
        font-weight: 700;
        margin-bottom: 30px;
    }

    /* Metric cards */
    .metric-card {
        background: linear-gradient(135deg, #667eea15 0%, #764ba215 100%);
        border-radius: 12px;
        padding: 1rem;
        border-left: 4px solid #667eea;
    }

    /* Section headers */
    .section-header {
        font-size: 1.3rem;
        font-weight: 600;
        color: #2c3e50;
        padding: 0.5rem 0;
        border-bottom: 2px solid #667eea;
        margin: 1.5rem 0 1rem 0;
    }

    /* Status badges */
    .status-pass {
        color: #28a745;
        font-weight: 600;
    }
    .status-warning {
        color: #ffc107;
        font-weight: 600;
    }
    .status-fail {
        color: #dc3545;
        font-weight: 600;
    }

    /* Buttons */
    .stButton > button {
        border-radius: 8px;
        font-weight: 500;
        transition: all 0.3s ease;
    }
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.15);
    }

    /* Sidebar */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #f8f9fa 0%, #e9ecef 100%);
    }
</style>
""", unsafe_allow_html=True)


# ==================== DATA LOADING FUNCTIONS ====================

def get_all_subjects():
    """
    Scan preprocessed directory to get all subject directories
    Returns list of subject directory names
    """
    subjects = []

    # Scan main preprocessed directory for subject folders
    if preprocessed_dir.exists():
        for item in preprocessed_dir.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                # Check if it's a valid subject directory (contains .fif file)
                fif_files = list(item.glob("*_preproc-raw.fif"))
                if fif_files:
                    subjects.append(item.name)

    return sorted(subjects)


def load_ica_data(subject_dir):
    """Load ICA component data"""
    ica_subject_dir = ica_report_dir / subject_dir
    data = {
        'has_ecg': False,
        'has_eog': False,
        'ecg_scores': [],
        'eog_scores': [],
        'marked_components': 0
    }

    # Load ECG/EOG scores
    score_file = ica_subject_dir / "ecg_eog_scores.json"
    if score_file.exists():
        try:
            with open(score_file, 'r') as f:
                scores = json.load(f)
                data['has_ecg'] = len(scores.get('ecg_indices', [])) > 0
                data['has_eog'] = len(scores.get('eog_indices', [])) > 0
                data['ecg_scores'] = scores.get('ecg', [])
                data['eog_scores'] = scores.get('eog', [])
        except Exception as e:
            st.warning(f"Error loading ICA scores for {subject_dir}: {e}")

    # Load marked components
    marked_file = ica_subject_dir / "marked_components.txt"
    if marked_file.exists():
        try:
            with open(marked_file, 'r') as f:
                components = [line.strip() for line in f.readlines() if line.strip()]
                data['marked_components'] = len(components)
        except Exception as e:
            st.warning(f"Error loading marked components for {subject_dir}: {e}")

    return data


def load_artifact_data(subject_dir):
    """Load bad channels and bad segments data"""
    artifact_subject_dir = artifact_report_dir / subject_dir
    data = {
        'total_channels': 306,  # Default for MEG
        'bad_channels': 0,
        'bad_channels_list': [],
        'total_segments(10s segments)': 0,
        'bad_segments': 0
    }

    # Load bad channels
    bad_ch_files = list(artifact_subject_dir.glob("*_bad_channels.txt"))
    if bad_ch_files:
        try:
            with open(bad_ch_files[0], 'r') as f:
                channels = [line.strip() for line in f.readlines() if line.strip()]
                data['bad_channels'] = len(channels)
                data['bad_channels_list'] = channels
        except Exception as e:
            st.warning(f"Error loading bad channels for {subject_dir}: {e}")

    # Load bad segments
    bad_seg_files = list(artifact_subject_dir.glob("*_bad_segments.txt"))
    if bad_seg_files:
        try:
            annotations = mne.read_annotations(bad_seg_files[0])
            data['bad_segments'] = len(annotations)

            # Get total segments from raw file
            raw_files = list((preprocessed_dir / subject_dir).glob("*_preproc-raw.fif"))
            if raw_files:
                raw = mne.io.read_raw_fif(raw_files[0], preload=False, verbose=False)
                duration = raw.times[-1]
                data['total_segments(10s segments)'] = int(duration / 10)  # Assuming 10s segments
        except Exception as e:
            st.warning(f"Error loading bad segments for {subject_dir}: {e}")

    return data


def load_coregistration_data(subject_dir):
    """Load coregistration quality data"""
    coreg_subject_dir = trans_dir / subject_dir
    data = {
        'dist_mean': None,
        'dist_max': None,
        'dist_min': None,
        'has_data': False
    }

    # Load distance data
    dists_file = coreg_subject_dir / "dists.csv"
    if dists_file.exists():
        try:
            df = pd.read_csv(dists_file)
            data['dist_mean'] = df['dist_mean(mm)'].values[0]
            data['dist_max'] = df['dist_max(mm)'].values[0]
            data['dist_min'] = df['dist_min(mm)'].values[0]
            data['has_data'] = True
        except Exception as e:
            st.warning(f"Error loading coregistration data for {subject_dir}: {e}")

    return data


def load_meg_data(subject_dir):
    """
    Load all MEG preprocessing data for a subject
    Returns comprehensive data dictionary
    """
    return {
        'subject': subject_dir,
        'ica': load_ica_data(subject_dir),
        'artifacts': load_artifact_data(subject_dir),
        'coregistration': load_coregistration_data(subject_dir)
    }


def check_meg_file(data, check_settings):
    """
    Check a single subject's data based on enabled check settings
    Returns list of alarms (category, description)
    """
    alarms = []
    subject = data['subject']

    # 1. ICA component checks
    ica_data = data['ica']

    if check_settings['check_ica_ecg']:
        if not ica_data['has_ecg']:
            alarms.append(("ICA", "No ECG-related components detected"))
        elif ica_data['marked_components'] == 0:
            alarms.append(("ICA", "ECG components detected but none marked"))

    if check_settings['check_ica_eog']:
        if not ica_data['has_eog']:
            alarms.append(("ICA", "No EOG-related components detected"))
        elif ica_data['marked_components'] == 0:
            alarms.append(("ICA", "EOG components detected but none marked"))

    # 2. Bad channels check
    if check_settings['check_bad_channels']:
        artifact_data = data['artifacts']
        bad_channels = artifact_data['bad_channels']
        threshold = check_settings['bad_channel_threshold']

        if bad_channels > threshold:
            alarms.append((
                "Artifacts",
                f"Excessive bad channels: {bad_channels}/{artifact_data['total_channels']} "
                f"(threshold: {threshold})"
            ))

    # 3. Bad segments check
    if check_settings['check_bad_segments']:
        artifact_data = data['artifacts']
        bad_segments = artifact_data['bad_segments']
        threshold = check_settings['bad_segment_threshold']

        if bad_segments > threshold:
            alarms.append((
                "Artifacts",
                f"Excessive bad segments: {bad_segments} (threshold: {threshold})"
            ))

    # 4. Coregistration check
    if check_settings['check_coregistration']:
        coreg_data = data['coregistration']

        if not coreg_data['has_data']:
            alarms.append(("Coregistration", "Coregistration data missing"))
        else:
            mean_dist = coreg_data['dist_mean']
            max_dist = coreg_data['dist_max']
            mean_threshold = check_settings['coreg_mean_threshold']
            max_threshold = check_settings['coreg_max_threshold']

            if mean_dist > mean_threshold:
                alarms.append((
                    "Coregistration",
                    f"Poor mean distance: {mean_dist:.2f}mm (threshold: {mean_threshold}mm)"
                ))

            if max_dist > max_threshold:
                alarms.append((
                    "Coregistration",
                    f"Poor max distance: {max_dist:.2f}mm (threshold: {max_threshold}mm)"
                ))

    return alarms


# ==================== MAIN APP ====================

st.markdown('<h2 class="main-header">🧠 MEG Preprocessing Quality Summary</h2>', unsafe_allow_html=True)

st.markdown("""
**Automated quality control for MEG preprocessing pipeline:**
- 📋 ICA component extraction completeness
- 🔍 Artifact detection thresholds
- 🎯 Coregistration quality metrics
""")

# ==================== SIDEBAR ====================
with st.sidebar:
    st.markdown("""
        <div style='text-align: center; padding: 0px;'>
            <h2>⚙️ Settings</h2>
        </div>
    """, unsafe_allow_html=True)

    # File Selection
    st.markdown('<div class="section-header">📁 Subject Selection</div>', unsafe_allow_html=True)

    # Get all subjects
    all_subjects = get_all_subjects()

    if not all_subjects:
        st.error("⚠️ No subjects found in preprocessed directory")
        st.stop()

    # Filter functionality
    if 'filter_keyword' not in st.session_state:
        st.session_state.filter_keyword = ""

    filter_keyword = st.text_input(
        "🔍 Filter subjects:",
        value=st.session_state.filter_keyword,
        placeholder="e.g., sub-01, task-aef",
        help="Filter subjects by keyword (case-insensitive)"
    )
    st.session_state.filter_keyword = filter_keyword

    # Apply filter
    filtered_subjects = filter_files_by_keyword(all_subjects, filter_keyword)

    # Select all or manual selection
    select_all = st.checkbox("Select All Subjects", value=True)

    if select_all:
        selected_subjects = filtered_subjects
    else:
        selected_subjects = st.multiselect(
            "Choose subjects:",
            filtered_subjects,
            default=filtered_subjects[:5] if len(filtered_subjects) >= 5 else filtered_subjects
        )

    st.caption(f"✓ Selected: {len(selected_subjects)} / {len(all_subjects)} subjects")

    st.markdown("---")

    # Check Settings
    st.markdown('<div class="section-header">🔍 Quality Checks</div>', unsafe_allow_html=True)

    # ICA Checks
    with st.expander("📋 ICA Components", expanded=True):
        check_ica_ecg = st.checkbox(
            "Check ECG Component",
            value=True,
            help="Flag if no ECG-related components detected or none marked"
        )
        check_ica_eog = st.checkbox(
            "Check EOG Component",
            value=True,
            help="Flag if no EOG-related components detected or none marked"
        )

    # Bad Channels Check
    with st.expander("🔴 Bad Channels", expanded=True):
        check_bad_channels = st.checkbox("Enable Bad Channels Check", value=True)
        bad_channel_threshold = st.number_input(
            "Maximum allowed bad channels",
            min_value=0,
            max_value=306,
            value=30,
            step=5,
            disabled=not check_bad_channels
        )

    # Bad Segments Check
    with st.expander("📊 Bad Segments", expanded=True):
        check_bad_segments = st.checkbox("Enable Bad Segments Check", value=True)
        bad_segment_threshold = st.number_input(
            "Maximum allowed bad segments",
            min_value=0,
            max_value=1000,
            value=50,
            step=10,
            disabled=not check_bad_segments
        )

    # Coregistration Check
    with st.expander("🎯 Coregistration Quality", expanded=True):
        check_coregistration = st.checkbox("Enable Coregistration Check", value=True)
        coreg_mean_threshold = st.number_input(
            "Mean distance threshold (mm)",
            min_value=0.0,
            max_value=10.0,
            value=5.0,
            step=0.5,
            disabled=not check_coregistration,
            help="Flag if mean distance > threshold"
        )
        coreg_max_threshold = st.number_input(
            "Max distance threshold (mm)",
            min_value=0.0,
            max_value=20.0,
            value=10.0,
            step=1.0,
            disabled=not check_coregistration,
            help="Flag if max distance > threshold"
        )

    # Collect settings
    check_settings = {
        'check_ica_ecg': check_ica_ecg,
        'check_ica_eog': check_ica_eog,
        'check_bad_channels': check_bad_channels,
        'bad_channel_threshold': bad_channel_threshold,
        'check_bad_segments': check_bad_segments,
        'bad_segment_threshold': bad_segment_threshold,
        'check_coregistration': check_coregistration,
        'coreg_mean_threshold': coreg_mean_threshold,
        'coreg_max_threshold': coreg_max_threshold,
    }

    st.markdown("---")

    # Display Settings
    st.markdown('<div class="section-header">⚙️ Display Options</div>', unsafe_allow_html=True)

    show_mode = st.selectbox(
        "Filter by status:",
        ["All Subjects", "With Alarms Only", "Passed Only"]
    )

    page_size = st.selectbox("Items per page:", [10, 20, 50, 100], index=1)

    # Active checks summary
    st.markdown("---")
    st.caption("**Active Checks:**")
    active_checks = []
    if check_ica_ecg: active_checks.append("✓ ICA ECG")
    if check_ica_eog: active_checks.append("✓ ICA EOG")
    if check_bad_channels: active_checks.append(f"✓ Bad Channels (≤{bad_channel_threshold})")
    if check_bad_segments: active_checks.append(f"✓ Bad Segments (≤{bad_segment_threshold})")
    if check_coregistration: active_checks.append(f"✓ Coregistration (mean≤{coreg_mean_threshold}mm)")

    for check in active_checks:
        st.caption(check)

# ==================== MAIN CONTENT ====================

if not selected_subjects:
    st.info("👈 Please select subjects in the sidebar")
    st.stop()

# Initialize cache
if 'check_results' not in st.session_state:
    st.session_state['check_results'] = {}

# Check if settings changed
settings_key = str(check_settings)
if 'last_settings' not in st.session_state or st.session_state['last_settings'] != settings_key:
    st.session_state['check_results'] = {}
    st.session_state['last_settings'] = settings_key

# Progress bar for batch processing
if len(selected_subjects) > 5:
    progress_bar = st.progress(0)
    status_text = st.empty()

# Process subjects
results_summary = []
for idx, subject in enumerate(selected_subjects):
    # Update progress
    if len(selected_subjects) > 5:
        progress = (idx + 1) / len(selected_subjects)
        progress_bar.progress(progress)
        status_text.text(f"Processing {idx + 1}/{len(selected_subjects)}: {subject}")

    # Check cache
    if subject not in st.session_state['check_results']:
        try:
            data = load_meg_data(subject)
            alarms = check_meg_file(data, check_settings)
            st.session_state['check_results'][subject] = {
                'data': data,
                'alarms': alarms
            }
        except Exception as e:
            st.warning(f"Error processing {subject}: {e}")
            continue

    result = st.session_state['check_results'][subject]
    alarm_count = len(result['alarms'])

    results_summary.append({
        'subject': subject,
        'alarm_count': alarm_count,
        'has_alarms': alarm_count > 0,
        'alarms': result['alarms'],
        'data': result['data']
    })

# Clear progress indicators
if len(selected_subjects) > 5:
    progress_bar.empty()
    status_text.empty()

# Calculate statistics
st.markdown("### 📊 Summary Statistics")

total_subjects = len(results_summary)
total_with_alarms = sum(1 for r in results_summary if r['has_alarms'])
total_passed = total_subjects - total_with_alarms
pass_rate = (total_passed / total_subjects * 100) if total_subjects > 0 else 0

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Subjects", total_subjects)
col2.metric("✅ Passed", total_passed, delta=None)
col3.metric("⚠️ With Alarms", total_with_alarms, delta=None)
col4.metric("Pass Rate", f"{pass_rate:.1f}%")

# Apply display filter
filtered_results = results_summary.copy()
if show_mode == "With Alarms Only":
    filtered_results = [r for r in filtered_results if r['has_alarms']]
elif show_mode == "Passed Only":
    filtered_results = [r for r in filtered_results if not r['has_alarms']]

if len(filtered_results) != total_subjects:
    st.info(f"📋 Showing {len(filtered_results)} of {total_subjects} subjects (filter: {show_mode})")

# Pagination
total_pages = max(1, (len(filtered_results) + page_size - 1) // page_size)

if total_pages > 1:
    page = st.selectbox(f"Page (Total: {total_pages})", range(1, total_pages + 1))
else:
    page = 1

start_idx = (page - 1) * page_size
end_idx = min(start_idx + page_size, len(filtered_results))
page_results = filtered_results[start_idx:end_idx]

# Display results
st.markdown("---")
st.markdown(f"### 📋 Quality Check Results (Page {page}/{total_pages})")

if not page_results:
    st.warning("No subjects match the current filter.")
else:
    for idx, result in enumerate(page_results, start=start_idx + 1):
        subject = result['subject']
        alarm_count = result['alarm_count']

        # Status styling
        if alarm_count == 0:
            status_icon = "✅"
            status_class = "status-pass"
        elif alarm_count <= 2:
            status_icon = "⚠️"
            status_class = "status-warning"
        else:
            status_icon = "❌"
            status_class = "status-fail"

        # Expandable card
        with st.expander(
                f"{status_icon} **{idx}. {subject}** - {alarm_count} alarm(s)",
                expanded=(alarm_count > 0 and idx <= start_idx + 3)
        ):
            if alarm_count == 0:
                st.success("✨ All quality checks passed!")
            else:
                st.error(f"⚠️ Detected {alarm_count} issue(s):")

                # Group alarms by category
                alarm_by_category = {}
                for category, description in result['alarms']:
                    if category not in alarm_by_category:
                        alarm_by_category[category] = []
                    alarm_by_category[category].append(description)

                for category, descriptions in alarm_by_category.items():
                    st.markdown(f"**{category}:**")
                    for desc in descriptions:
                        st.markdown(f"- {desc}")

            # Detailed metrics
            st.markdown("---")
            st.markdown("**📊 Detailed Metrics:**")

            data = result['data']

            # Create metrics display
            col1, col2, col3 = st.columns(3)

            with col1:
                st.markdown("**ICA:**")
                st.caption(f"ECG: {'✓' if data['ica']['has_ecg'] else '✗'}")
                st.caption(f"EOG: {'✓' if data['ica']['has_eog'] else '✗'}")
                st.caption(f"Marked: {data['ica']['marked_components']}")

            with col2:
                st.markdown("**Artifacts:**")
                st.caption(f"Bad Channels: {data['artifacts']['bad_channels']}/{data['artifacts']['total_channels']}")
                st.caption(f"Bad Segments: {data['artifacts']['bad_segments']}")

            with col3:
                st.markdown("**Coregistration:**")
                if data['coregistration']['has_data']:
                    st.caption(f"Mean: {data['coregistration']['dist_mean']:.2f}mm")
                    st.caption(f"Max: {data['coregistration']['dist_max']:.2f}mm")
                else:
                    st.caption("No data available")

            # Raw data toggle
            if st.toggle("View Raw Data", key=f"raw_{idx}_{subject}"):
                st.json(data)

# Export functionality
st.markdown("---")
st.markdown("### 📥 Export Report")

col1, col2 = st.columns([3, 1])
with col1:
    st.write(f"Export {len(filtered_results)} subject(s) based on current filter")
with col2:
    if st.button("📥 Download CSV", type="primary", use_container_width=True):
        # Prepare export data
        export_data = []
        for r in filtered_results:
            data = r['data']
            export_data.append({
                'Subject': r['subject'],
                'Status': 'Passed' if r['alarm_count'] == 0 else 'Failed',
                'Alarm Count': r['alarm_count'],
                'ICA ECG': '✓' if data['ica']['has_ecg'] else '✗',
                'ICA EOG': '✓' if data['ica']['has_eog'] else '✗',
                'ICA Marked': data['ica']['marked_components'],
                'Bad Channels': data['artifacts']['bad_channels'],
                'Bad Segments': data['artifacts']['bad_segments'],
                'Coreg Mean (mm)': f"{data['coregistration']['dist_mean']:.2f}" if data['coregistration'][
                    'has_data'] else 'N/A',
                'Coreg Max (mm)': f"{data['coregistration']['dist_max']:.2f}" if data['coregistration'][
                    'has_data'] else 'N/A',
                'Alarm Details': '; '.join([f"[{cat}] {desc}" for cat, desc in r['alarms']])
            })

        df_export = pd.DataFrame(export_data)
        csv = df_export.to_csv(index=False, encoding='utf-8-sig')

        st.download_button(
            label="💾 Download Complete Report",
            data=csv,
            file_name=f"meg_quality_summary_{len(filtered_results)}_subjects.csv",
            mime="text/csv",
            use_container_width=True
        )

# Footer
st.markdown("---")
st.caption(f"📁 Report Directory: `{report_root_dir}`")
st.caption(f"⏰ Last updated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}")
