# !/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import time
import subprocess
import numpy as np
import pandas as pd
import streamlit as st
import mne
import tempfile
from packaging.version import parse
import altair as alt
from pathlib import Path
from reports.utils import in_docker,filter_files_by_keyword

# --- 1. Set environment variables to avoid GLSL/VTK errors in headless mode ---
os.environ["PYVISTA_PLOT_THEME"] = "document"
os.environ["PYVISTA_USE_PANEL"] = "False"
os.environ["MESA_GLSL_VERSION_OVERRIDE"] = "150"
os.environ["MESA_GL_VERSION_OVERRIDE"] = "3.2"
os.environ["LIBGL_ALWAYS_SOFTWARE"] = "1"
os.environ["QT_QPA_PLATFORM"] = "xcb"
os.environ["VTK_OFFSCREEN_RENDERING"] = "1"
os.environ["XDG_RUNTIME_DIR"] = "/tmp"

import pyvista as pv


def _find_free_xvfb_display(start=100, stop=2000):
    for display_number in range(start, stop):
        lock_path = Path(f"/tmp/.X{display_number}-lock")
        socket_path = Path(f"/tmp/.X11-unix/X{display_number}")
        if not lock_path.exists() and not socket_path.exists():
            return display_number
    raise RuntimeError("No free Xvfb display was found.")


def ensure_vtk_headless_context():
    """Start a private Xvfb display and pre-initialize VTK off-screen rendering."""
    if st.session_state.get("SOURCE_VTK_CONTEXT_READY"):
        pv.OFF_SCREEN = False
        return

    display_number = _find_free_xvfb_display()
    display = f":{display_number}"
    proc = subprocess.Popen(
        ["Xvfb", display, "-screen", "0", "1024x768x24"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    os.environ["DISPLAY"] = display

    socket_path = Path(f"/tmp/.X11-unix/X{display_number}")
    lock_path = Path(f"/tmp/.X{display_number}-lock")
    for _ in range(30):
        if proc.poll() is not None:
            raise RuntimeError(f"Xvfb failed to start on {display}.")
        if socket_path.exists() or lock_path.exists():
            break
        time.sleep(0.1)
    else:
        proc.terminate()
        raise RuntimeError(f"Timed out waiting for Xvfb on {display}.")

    pv.OFF_SCREEN = True
    dummy_plotter = pv.Plotter(off_screen=True)
    dummy_plotter.add_mesh(pv.Sphere())
    dummy_plotter.show(auto_close=False)
    dummy_plotter.close()
    # MNE's time_viewer/show_traces needs a live interactor; keep plotting interactive
    # after the off-screen warm-up, matching megprep/source_localization.py.
    pv.OFF_SCREEN = False

    st.session_state.SOURCE_XVFB_PROCESS = proc
    st.session_state.SOURCE_VTK_CONTEXT_READY = True


# --- 2. Start a virtual display and pre-initialize VTK ---
ensure_vtk_headless_context()

# --- Custom CSS Styling ---
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
        background: linear-gradient(90deg, #f0f2f6 0%, #ffffff 100%);
        padding: 1rem 1.5rem;
        border-radius: 10px;
        border-left: 5px solid #2E86DE;
        margin: 1.5rem 0 1rem 0;
        font-weight: 600;
        color: #1e3a8a;
    }

    /* Info boxes */
    .stAlert > div {
        border-radius: 10px;
        border-left: 5px solid #2E86DE;
    }

    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
    }

    [data-testid="stSidebar"] .stSelectbox label,
    [data-testid="stSidebar"] .stTextInput label,
    [data-testid="stSidebar"] .stSlider label,
    [data-testid="stSidebar"] .stRadio label,
    [data-testid="stSidebar"] .stMultiSelect label,
    [data-testid="stSidebar"] .stCheckbox label {
        font-weight: 600;
        # color: #1e3a8a;
        font-size: 0.95rem;
    }

    /* Expander styling */
    .streamlit-expanderHeader {
        background-color: #f8fafc;
        border-radius: 8px;
        font-weight: 600;
        color: #475569;
    }

    /* Image container */
    .stImage {
        border-radius: 12px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        overflow: hidden;
        margin: 1rem 0;
    }

    /* Code blocks */
    code {
        background-color: #f1f5f9;
        padding: 0.2rem 0.4rem;
        border-radius: 4px;
        font-size: 0.9em;
    }

    /* Sidebar section dividers */
    .sidebar-divider {
        height: 2px;
        background: linear-gradient(90deg, transparent 0%, #cbd5e1 50%, transparent 100%);
        margin: 1.5rem 0;
    }

    /* Parameter box */
    .param-box {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 1rem;
        margin: 0.5rem 0;
    }
</style>
""", unsafe_allow_html=True)

# Main title with custom styling
st.markdown('<h2 class="main-header">🧠 Source Localization</h2>', unsafe_allow_html=True)
st.markdown('---')

if in_docker():
    report_root_dir = Path("/output")
    subjects_dir = Path("/smri")
else:
    report_root_dir = Path(st.session_state.get("dataset_report_path"))
    subjects_dir = Path(st.session_state.get("subjects_dir"))

source_recon_report_dir = report_root_dir / "preprocessed" / "source_recon"

# --- Sidebar Configuration ---
st.sidebar.markdown("### 📁 Data Configuration")
source_report_dir = st.sidebar.text_input(
    "Source Recon Report Directory:",
    value=str(source_recon_report_dir)
)


# --- subject options ---
st.sidebar.markdown("### Subject Selection")
# List all available subjects (folders) in SUBJECTS_DIR
if subjects_dir and os.path.exists(subjects_dir):
    subject_choices = sorted(
        [d for d in os.listdir(subjects_dir) if os.path.isdir(os.path.join(subjects_dir, d))]
    )
else:
    st.warning("⚠️ SUBJECTS_DIR not found or does not exist!")
    subject_choices = []
subject = st.sidebar.selectbox("Select subject for surface visualization", subject_choices)


if os.path.exists(source_report_dir):
    image_dirs = sorted([f for f in os.listdir(source_report_dir) if os.path.isdir(os.path.join(source_report_dir, f))])
else:
    image_dirs = []

filtered_dirs = filter_files_by_keyword(image_dirs, subject)
selected_dir = st.sidebar.selectbox("Select a MEG File:", filtered_dirs)


st.sidebar.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)

## --- STC Source Estimate Visualization ---

stc_dir = Path(source_report_dir) / selected_dir if selected_dir else None
if stc_dir and stc_dir.exists():
    # Find all stc file prefixes (excluding hemi)
    stc_files = [f for f in os.listdir(stc_dir) if f.endswith('.stc')]
    prefixes = set()
    for f in stc_files:
        if f.endswith('-lh.stc') or f.endswith('-rh.stc'):
            prefixes.add(f[:-7])
    prefixes = sorted(list(prefixes))
else:
    prefixes = []

if prefixes:
    st.sidebar.markdown("### ⚙️ Visualization Settings")
    selected_prefix = st.sidebar.selectbox("Select STC file prefix", prefixes)
    stc_path = stc_dir / f"{selected_prefix}-lh.stc"  # -{selected_ori_hemi} # (auto matches lh/rh)

    selected_ori = st.sidebar.radio("Select Brain Hemisphere:",
                                    ["Left Hemisphere", "Right Hemisphere", "Whole Brain"],help="Get location and latency of peak amplitude.")

    if "Left" in selected_ori:
        selected_ori_hemi = "lh"
    elif "Right" in selected_ori:
        selected_ori_hemi = "rh"
    else:
        selected_ori_hemi = "split"

    # Load and display the STC, with interactive visualization controls
    if stc_path.exists():
        col1, col2 = st.columns([2, 1])

        stc = mne.read_source_estimate(str(stc_path), subject=subject)

        st.sidebar.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)
        st.sidebar.markdown("### ⏱️ Time Selection")

        # --- Time slider ---
        time_min, time_max = stc.times[0], stc.times[-1]

        # Get the peak vertex and time for the current hemisphere
        if selected_ori_hemi == "split":
            peak_hemi = None
        else:
            peak_hemi = selected_ori_hemi
        vertno_max, peak_vertex_time = stc.get_peak(hemi=peak_hemi)

        print("vertno_max, peak_vertex_time:", vertno_max, peak_vertex_time)
        default_time = peak_vertex_time

        time = st.sidebar.slider(
            "Display Time Point (s)", float(time_min), float(time_max),
            value=float(default_time), step=0.01, format="%.3f"
        )

        st.sidebar.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)
        st.sidebar.markdown("### 👁️ Display Options")

        # --- Views multi-select ---
        views_options = ["lateral", "medial", "dorsal", "ventral", "frontal", "parietal", "axial"]
        views_selected = st.sidebar.multiselect("Brain View(s)", views_options, default=["lateral"])
        views = views_selected if len(views_selected) > 1 else views_selected[0]

        # --- CLIM and display options ---
        background_color = st.sidebar.selectbox("Background", ["white", "black"])
        clim_kind = st.sidebar.selectbox("Clim kind", ["percent", "value"], index=0)
        pos_lims_input = st.sidebar.text_input("Clim pos_lims (comma-separated)", value="0, 97.5, 100")
        smoothing_steps = st.sidebar.slider("Smoothing steps", min_value=0, max_value=20, value=10)

        try:
            pos_lims = [float(x.strip()) for x in pos_lims_input.split(",")][:3]
            if len(pos_lims) != 3:
                raise ValueError
        except Exception:
            st.error("❌ clim pos_lims must be three comma-separated numbers!")
            st.stop()

        alpha = st.sidebar.slider("Alpha", 0.0, 1.0, value=1.0, format="%.2f")
        time_viewer = st.sidebar.checkbox("Time_viewer", True,help="display time viewer")
        show_traces = time_viewer

        if selected_ori_hemi == 'split':
            size = (1250, 500)
        else:
            size = (1000, 800)
        time_label = f"Time ({time:.3f}s)"

        brain_kwargs = dict(show=False)
        if parse(mne.__version__) < parse("1.11.0"):
            brain_kwargs['block'] = False

        surfer_kwargs = dict(
            subject=subject,
            hemi=selected_ori_hemi,
            subjects_dir=subjects_dir,  # supply fsaverage or subjects dir as needed
            clim=dict(kind=clim_kind, pos_lims=pos_lims),
            views=views,
            # initial_time=time,
            time_unit='s',
            time_label=time_label,
            alpha=alpha,
            time_viewer=time_viewer,
            show_traces=show_traces,
            size=size,
            background=background_color,
            smoothing_steps=smoothing_steps,
            brain_kwargs=brain_kwargs,
            verbose=True
        )

        with st.expander("🔧 Visualization parameters", expanded=False):
            st.write(f"```{surfer_kwargs}```")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpimg = os.path.join(tmpdir, f"brain_{selected_prefix}_{selected_ori_hemi}_{time:.3f}.png")

            with st.spinner('Generating brain visualization...'):
                brain = stc.plot(**surfer_kwargs)
                brain.set_time(time)

                try:
                    # For the PyVista backend
                    if hasattr(brain, '_renderer') and hasattr(brain._renderer, 'plotter'):
                        brain._renderer.plotter.render()
                except Exception as e:
                    print(f"Render update failed: {e}")
                brain.save_image(tmpimg)
                brain.close()

            # Display with enhanced styling
            caption_text = f"**{selected_prefix}** | Hemisphere: `{selected_ori_hemi}` | Time: `{time:.3f} s`"
            st.image(tmpimg, caption=caption_text, width='stretch')

            # Add metadata
            col1, col2, col3= st.columns([1,1,2])
            with col1:
                st.metric("Current Time", f"{peak_vertex_time:.3f} s")
            with col2:
                st.metric("Time Range", f"{time_max - time_min:.3f} s")
            with col3:
                st.metric("The vertex exhibiting the maximum response", f"{vertno_max}")


    else:
        st.warning(f"⚠️ STC file not found: `{stc_path}`")
else:
    st.info("ℹ️ No STC files found for interactive display in this MEG directory.")

