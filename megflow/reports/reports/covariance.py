# !/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import streamlit as st
from pathlib import Path
from reports.utils import in_docker,filter_files_by_keyword



# Custom CSS for better styling
st.markdown("""
    <style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        text-align: center;
        padding: 1rem;
    }
    .sub-header {
        font-size: 1.5rem;
        font-weight: 600;
        color: #2c3e50;
        margin-top: 2rem;
        margin-bottom: 1rem;
        padding: 0.5rem;
        border-left: 5px solid #1f77b4;
        padding-left: 1rem;
    }
    .stImage {
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        transition: transform 0.3s ease;
    }
    .stImage:hover {
        transform: scale(1.02);
    }
    </style>
""", unsafe_allow_html=True)

# Title with icon
st.markdown('<div class="main-header">🧠 Covariance Visualization</div>', unsafe_allow_html=True)

# Sidebar styling
st.sidebar.markdown("""
    <div style='text-align: center; padding: 0px;'>
        <h2 >⚙️ Settings</h2>
    </div>
""", unsafe_allow_html=True)

# Determine report directory
if in_docker():
    report_root_dir = Path("/output")
else:
    report_root_dir = Path(st.session_state.get("dataset_report_path"))

covar_report_dir = report_root_dir / "preprocessed" / "covariance"

# Directory input with help text
covar_report_dir = st.sidebar.text_input(
    "📁 Covariance Report Directory:",
    value=str(covar_report_dir),
    help="Path to the directory containing covariance reports"
)

# Check directory existence and list subdirectories
if os.path.exists(covar_report_dir):
    image_dirs = sorted([f for f in os.listdir(covar_report_dir)
                         if os.path.isdir(os.path.join(covar_report_dir, f))])

    if image_dirs:
        st.sidebar.success(f"✅ Found {len(image_dirs)} MEG file(s)")
    else:
        st.sidebar.warning("⚠️ No MEG files found in directory")
        image_dirs = []
else:
    st.sidebar.error("❌ Directory does not exist")
    image_dirs = []

st.sidebar.markdown("---")

# File selection
if image_dirs:

    # Initialize filter keyword in session state
    if 'filter_keyword' not in st.session_state:
        st.session_state.filter_keyword = ""

    filter_keyword = st.sidebar.text_input(
        "🔍 Filter files by keyword:",
        value=st.session_state.filter_keyword,
        placeholder="e.g., sub-01, task-rest, run-1, etc.",
        help="Enter any keyword to filter files (case-insensitive). Leave empty to show all files.",
        key="filter_input"
    )
    st.session_state.filter_keyword = filter_keyword

    # Filter files
    filtered_covar_dirs = filter_files_by_keyword(image_dirs, filter_keyword)

    selected_dir = st.sidebar.selectbox(
        "📄 Select a MEG File:",
        filtered_covar_dirs,
        help="Choose a MEG file to visualize its covariance data"
    )

    st.sidebar.markdown("---")
    st.sidebar.info(f"**Currently viewing:**\n\n`{selected_dir}`")

    # Main content area
    col1, col2 = st.columns([1, 20])
    with col2:
        st.markdown("---")

    # Image paths
    bl_cov_path = os.path.join(covar_report_dir, selected_dir, "bl_cov.png")
    bl_cov_spectra_path = os.path.join(covar_report_dir, selected_dir, "bl_cov_spectra.png")

    # Display images in organized sections
    with st.container():
        st.markdown('<div class="sub-header"> Baseline (Noise) Covariance</div>', unsafe_allow_html=True)

        if os.path.exists(bl_cov_path):
            col1, col2, col3 = st.columns([1, 10, 1])
            with col2:
                st.image(bl_cov_path, width='stretch')
        else:
            st.warning(f"⚠️ Image not found: `bl_cov.png`")

    st.markdown("---")

    with st.container():
        st.markdown('<div class="sub-header"> Baseline (Noise) Covariance Spectra</div>', unsafe_allow_html=True)

        if os.path.exists(bl_cov_spectra_path):
            col1, col2, col3 = st.columns([1, 10, 1])
            with col2:
                st.image(bl_cov_spectra_path, width='stretch')
        else:
            st.warning(f"⚠️ Image not found: `bl_cov_spectra.png`")

    # Footer with download info
    st.markdown("---")

else:
    # No files found - display helpful message
    st.info("👈 Please select a valid directory and MEG file from the sidebar to begin visualization.")

    with st.container():
        st.markdown("### 📋 Quick Start Guide")
        st.markdown("""
        1. **Set Directory**: Enter or verify the covariance report directory path in the sidebar
        2. **Select File**: Choose a MEG file from the dropdown menu
        3. **View Results**: The covariance visualizations will appear automatically
        """)

        st.markdown("### 📊 What you'll see:")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**🔍 Baseline Covariance**")
            st.markdown("- Matrix visualization of noise covariance")
            st.markdown("- Shows sensor-to-sensor relationships")
        with col2:
            st.markdown("**📈 Covariance Spectra**")
            st.markdown("- Frequency domain analysis")
            st.markdown("- Noise characteristics across frequencies")
