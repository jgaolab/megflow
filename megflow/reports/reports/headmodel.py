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

    .orientation-header {
        font-size: 1.5rem;
        font-weight: 600;
        color: #2c3e50;
        margin-top: 1.5rem;
        margin-bottom: 1rem;
        padding: 0.5rem;
        background: linear-gradient(90deg, #e8f4f8 0%, transparent 100%);
        border-left: 4px solid #1f77b4;
        padding-left: 1rem;
    }
    .info-box {
        background-color: #e8f4f8;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 1rem 0;
        border-left: 4px solid #1f77b4;
    }
    .sidebar-header {
        font-size: 1.1rem;
        font-weight: 600;
        # color: #1f77b4;
        margin-bottom: 0.5rem;
    }
    /* 图片容器样式 */
    .image-container {
        background-color: #ffffff;
        padding: 1.5rem;
        border-radius: 0.5rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        margin-bottom: 2rem;
    }
    /* 统一按钮样式 - 去掉悬浮效果 */
    .stButton button {
        font-weight: 500;
        border-radius: 0.5rem;
    }
    </style>
""", unsafe_allow_html=True)

# Page Title
st.markdown('<div class="main-header">Head Model Review</div>', unsafe_allow_html=True)


# Get report directory
if in_docker():
    report_root_dir = Path("/output")
else:
    report_root_dir = Path(st.session_state.get("dataset_report_path"))

fwd_report_dir = report_root_dir / "preprocessed" / "forward_solution"

# ========== SIDEBAR ==========
with st.sidebar:
    # Sidebar styling
    st.sidebar.markdown("""
        <div style='text-align: center; padding: 0px;'>
            <h2 >⚙️ Settings</h2>
        </div>
    """, unsafe_allow_html=True)
    st.markdown('<p class="sidebar-header">📁 Directory Settings</p>', unsafe_allow_html=True)

    fwd_report_dir = st.text_input(
        "Head Model Report Directory:",
        value=str(fwd_report_dir),
        help="Path to the forward solution directory"
    )


    # Check if directory exists
    if os.path.exists(fwd_report_dir):
        image_dirs = sorted([f for f in os.listdir(fwd_report_dir) if os.path.isdir(os.path.join(fwd_report_dir, f))])
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
        if filtered_dirs:
            st.markdown('<p class="sidebar-header">📂 Subject Selection</p>', unsafe_allow_html=True)
            st.caption(f"📊 Total subjects: {len(filtered_dirs)}")

            selected_dir = st.selectbox(
                "Select a Subject:",
                filtered_dirs,
                label_visibility="collapsed"
            )

            # Show full path in an expander
            with st.expander("📂 Full Path", expanded=False):
                st.code(os.path.join(fwd_report_dir, selected_dir), language=None)
        else:
            st.warning("⚠️ No subject directories found in the specified path.")
            selected_dir = None
            filtered_dirs = []
    else:
        st.error(f"⚠️ Directory does not exist:\n`{fwd_report_dir}`")
        st.info("💡 Please check the path or create the directory.")
        selected_dir = None
        filtered_dirs = []

# ========== MAIN CONTENT ==========
if selected_dir:
    # Display subject info
    col1, col2 = st.columns([2, 1])
    with col1:
        st.markdown(f"**Selected Subject:** `{selected_dir}`")
    with col2:
        st.markdown(f"**Total Views:** 3")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("---")

    # Display images in different orientations
    orientations = ['coronal', 'sagittal', 'axial']
    orientation_icons = {
        'coronal': '🔵',
        'sagittal': '🟢',
        'axial': '🟡'
    }
    orientation_descriptions = {
        'coronal': 'Front-to-back view (Coronal plane)',
        'sagittal': 'Left-to-right view (Sagittal plane)',
        'axial': 'Top-to-bottom view (Axial plane)'
    }

    for orientation in orientations:
        # Create header for each orientation
        icon = orientation_icons.get(orientation, '📊')
        st.markdown(
            f'<p class="orientation-header">{icon} {orientation.capitalize()}</p>',
            unsafe_allow_html=True
        )

        # Add description
        st.caption(orientation_descriptions[orientation])

        # Image path
        image_path = os.path.join(fwd_report_dir, selected_dir, f"headmodel_{orientation}.png")

        # Check if image exists
        if os.path.exists(image_path):
            # Display image in a container
            st.image(
                image_path,
                width='stretch',
                caption=f"{orientation.capitalize()} view - {selected_dir}"
            )
            st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.warning(f"⚠️ Image not found: `headmodel_{orientation}.png`")

        # Add spacing between images
        if orientation != orientations[-1]:
            st.markdown("<br>", unsafe_allow_html=True)

    # ========== ADDITIONAL INFO ==========
    st.markdown("---")
    with st.expander("ℹ️ Image Information", expanded=False):
        st.markdown(f"**Subject Directory:** `{selected_dir}`")
        st.markdown(f"**Report Directory:** `{fwd_report_dir}`")
        st.divider()
        st.markdown("**Available Orientations:**")
        for i, orientation in enumerate(orientations, 1):
            image_path = os.path.join(fwd_report_dir, selected_dir, f"headmodel_{orientation}.png")
            status = "✅ Found" if os.path.exists(image_path) else "❌ Missing"
            st.markdown(f"{i}. **{orientation.capitalize()}:** {status}")
        st.divider()
        st.markdown("**Image Details:**")
        st.json({
            "total_orientations": len(orientations),
            "subject_id": selected_dir,
            "directory": str(fwd_report_dir)
        })

elif image_dirs:
    st.info("👈 Please select a subject from the sidebar to view head model visualizations.")
else:
    st.warning("⚠️ No subject data available. Please check the directory path in the sidebar.")
    st.markdown("""
    ### 📝 How to use:
    1. Ensure the forward solution directory exists
    2. Check that subject directories contain head model images
    3. Required image naming format: `headmodel_{orientation}.png`
    4. Supported orientations: coronal, sagittal, axial
    """)

# Footer
st.markdown("---")
st.caption("Head Model Review - View MEG forward-solution head models in multiple orientations")
