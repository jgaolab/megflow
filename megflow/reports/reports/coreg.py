# !/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import streamlit as st
from pathlib import Path
import pandas as pd
from reports.utils import in_docker,filter_files_by_keyword

# Custom CSS styling
st.markdown("""
<style>
    /* Main title styling */
    .main-header {
            color: white;
            padding: 20px;
            border-radius: 15px;
            text-align: center;
            font-weight: 700;
            margin-bottom: 30px;
        }

    /* Section headers */
    .section-header {
        font-size: 1.8rem;
        font-weight: 600;
        color: #2c3e50;
        margin-top: 2rem;
        margin-bottom: 1rem;
        padding: 0.8rem 1rem;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border-radius: 8px;
        border-left: 5px solid #1f77b4;
    }

    /* Step card container */
    .step-card {
        background: linear-gradient(135deg, #667eea15 0%, #764ba215 100%);
        border-radius: 12px;
        padding: 1.2rem;
        margin: 1.5rem 0;
        border-left: 5px solid #667eea;
        box-shadow: 0 2px 8px rgba(102, 126, 234, 0.1);
        transition: all 0.3s ease;
    }
    
    .step-card:hover {
        box-shadow: 0 4px 16px rgba(102, 126, 234, 0.2);
        transform: translateX(5px);
    }
    
    /* Step title */
    .step-title {
        font-size: 1.4rem;
        font-weight: 700;
        color: #667eea;
        margin-bottom: 0.5rem;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    
    /* Step description */
    .step-description {
        font-size: 1rem;
        color: #5a6c7d;
        margin: 0;
        padding-left: 2rem;
        line-height: 1.5;
    }
    
    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #f8f9fa 0%, #e9ecef 100%);
    }
    
    [data-testid="stSidebar"] .stSelectbox label {
        font-size: 1.1rem;
        font-weight: 600;
        color: #2c3e50;
    }
    
    /* DataFrame styling */
    .dataframe {
        border-radius: 8px;
        overflow: hidden;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }
    
    /* Image styling */
    img {
        border-radius: 8px;
        box-shadow: 0 2px 12px rgba(0,0,0,0.08);
    }
    
    /* Divider */
    hr {
        margin: 2rem 0;
        border: none;
        height: 1px;
        background: linear-gradient(90deg, transparent, #ddd, transparent);
    }
</style>
""", unsafe_allow_html=True)

# Main title
st.markdown('<h2 class="main-header">🧠 MEG Preprocessing Results Viewer</h2>', unsafe_allow_html=True)

# Determine report directory
if in_docker():
    report_root_dir = Path("/output")
else:
    report_root_dir = Path(st.session_state.get("dataset_report_path"))

coreg_report_dir = report_root_dir / "preprocessed" / "trans"
image_dirs = sorted([f for f in os.listdir(coreg_report_dir)])

# Sidebar styling
st.sidebar.markdown("""
    <div style='text-align: center; padding: 0px;'>
        <h2 >⚙️ Settings</h2>
    </div>
""", unsafe_allow_html=True)

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
filtered_dirs = filter_files_by_keyword(image_dirs, filter_keyword)

# Sidebar
st.sidebar.markdown("### 📂 Select Data")
selected_dir = st.sidebar.selectbox("Select a MEG File:", filtered_dirs)
# st.sidebar.markdown(f"**Current Selection:** `{selected_dir}`")
st.sidebar.markdown("---")
# st.sidebar.info("💡 Select a subject to view their coregistration results")

coreg_dir = coreg_report_dir / selected_dir

# Load distance data
dists = pd.read_csv(coreg_dir / "dists.csv", index_col=None)

# Coregistration Distance Section
st.markdown('<div class="section-header">Coregistration Distance</div>', unsafe_allow_html=True)

# Display some metrics if available
if not dists.empty:
    cols = st.columns(3)
    if 'distance' in dists.columns or len(dists.columns) > 0:
        numeric_cols = dists.select_dtypes(include=['float64', 'int64']).columns
        for idx, col in enumerate(numeric_cols[:3]):
            with cols[idx]:
                st.metric(
                    label=col.replace('_', ' ').capitalize(),
                    value=f"{dists[col].mean():.3f}",
                )

# st.dataframe(dists, use_container_width=True)

# Coregistration Visualization Section
st.markdown('<div class="section-header">Coregistration Visualization</div>', unsafe_allow_html=True)

# Define image display information with keywords
# Note: Order matters! More specific keywords should come first
image_info = {
    "coreg_initial": {
        "title": "1️⃣ Initial Position",
        "desc": "Initial coregistration position"
    },
    "coreg_fiducials": {
        "title": "2️⃣ Fiducials",
        "desc": "Fiducial-based alignment"
    },
    "coreg_icp": {
        "title": "3️⃣ ICP Registration",
        "desc": "Iterative Closest Point algorithm registration result"
    },
    "coreg_icp_finetune": {
        "title": "4️⃣ ICP Fine-tuned",
        "desc": "Final result after ICP fine-tuning"
    },
}

# Configuration: Naming Convention
# 1. With Scalp (Left): e.g., sub-01_coreg_initial.png
# 2. Without Scalp (Right): e.g., sub-01_coreg_initial_brain.png


NO_SCALP_SUFFIX = "_brain"
processed_files = set()
all_pngs = list(coreg_dir.glob("*.png"))

for keyword, info in image_info.items():

    # 1. Find all files belonging to the current step
    step_files = []
    for img_path in all_pngs:
        fname = img_path.name
        if keyword in fname:
            # Prevention: Ensure we don't match a longer keyword
            # (e.g. prevent 'coreg_icp' from matching 'coreg_icp_finetune')
            is_more_specific = False
            for other_key in image_info.keys():
                if other_key != keyword and len(other_key) > len(keyword) and other_key in fname:
                    is_more_specific = True
                    break

            if not is_more_specific:
                step_files.append(img_path)

    if not step_files:
        continue

    # Mark files as processed
    for f in step_files:
        processed_files.add(f.name)

    # 2. Identify Left (Scalp) and Right (Brain/No Scalp) images based on suffix
    img_scalp = None  # Standard view
    img_noscalp = None  # Brain view

    for f in step_files:
        if NO_SCALP_SUFFIX in f.name:
            img_noscalp = f
        else:
            # If it doesn't have the specific suffix, treat it as the standard scalp image
            img_scalp = f

    # 3. Display the Step Card
    st.markdown(f'''
    <div class="step-card">
        <div class="step-title">{info["title"]}</div>
        <div class="step-description">{info["desc"]}</div>
    </div>
    ''', unsafe_allow_html=True)

    # 4. Display images side-by-side
    cols = st.columns(2)

    # --- Left Column: With Scalp ---
    with cols[0]:
        st.markdown(
            "<div style='text-align: center; color: #666; margin-bottom: 5px; font-size: 0.9em;'><b>With Scalp (Head)</b></div>",
            unsafe_allow_html=True)
        if img_scalp:
            st.image(img_scalp, use_container_width=True)
        else:
            st.warning("Standard image not found")

    # --- Right Column: Without Scalp ---
    with cols[1]:
        st.markdown(
            f"<div style='text-align: center; color: #666; margin-bottom: 5px; font-size: 0.9em;'><b>Without Scalp (Brain Surface)</b></div>",
            unsafe_allow_html=True)
        if img_noscalp:
            st.image(img_noscalp, use_container_width=True)
        else:
            # Info message if the specific suffix image is missing
            st.info(f"Brain view ({NO_SCALP_SUFFIX}) not available")

    st.markdown("---")

# (Optional) Display uncategorized images
for img in all_pngs:
    if img.name not in processed_files:
        st.markdown(f"**Uncategorized Image: {img.name}**")
        st.image(img, use_container_width=True)
        st.markdown("---")
