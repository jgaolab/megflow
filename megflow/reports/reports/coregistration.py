# !/usr/bin/env python3
# -*- coding: utf-8 -*-
## ref: https://mne.tools/stable/auto_tutorials/forward/20_source_alignment.html#sphx-glr-auto-tutorials-forward-20-source-alignment-py

import os
import glob
import time
import subprocess
import re
import gc
import numpy as np
import pandas as pd
import nibabel as nib
import streamlit as st
import mne
from pathlib import Path
from scipy import linalg
from mne.io.constants import FIFF
from mne.coreg import Coregistration
from reports.utils import in_docker

# --- 1. 设置环境变量 (在无头环境中避免 GLSL 错误) ---
os.environ['PYVISTA_PLOT_THEME'] = 'document'
os.environ['PYVISTA_USE_PANEL'] = 'False'
os.environ["MESA_GLSL_VERSION_OVERRIDE"] = "150"
os.environ["MESA_GL_VERSION_OVERRIDE"] = "3.2"
os.environ["LIBGL_ALWAYS_SOFTWARE"] = "1"
os.environ["QT_QPA_PLATFORM"] = "xcb"
os.environ['VTK_OFFSCREEN_RENDERING'] = '1'

from stpyvista import stpyvista
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
    if st.session_state.get("COREG_VTK_CONTEXT_READY"):
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

    st.session_state.COREG_XVFB_PROCESS = proc
    st.session_state.COREG_VTK_CONTEXT_READY = True


# --- 2. 启动虚拟显示并预初始化 VTK ---
ensure_vtk_headless_context()


# --- Custom CSS Styling ---
def apply_custom_styles():
    st.markdown("""
    <style>
        /* Main container styling */
        .main .block-container {
            padding-top: 2rem;
            padding-bottom: 2rem;
            max-width: 95%;
        }

        /* Title styling */
        h1 {
            color: #1f77b4;
            font-weight: 700;
            padding-bottom: 0.5rem;
            border-bottom: 3px solid #1f77b4;
            margin-bottom: 2rem;
        }

        /* Sidebar styling */
        .css-1d391kg, [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #f8f9fa 0%, #e9ecef 100%);
        }

        .css-1d391kg h1, .css-1d391kg h2, .css-1d391kg h3 {
            color: #2c3e50;
        }

        /* Section headers */
        .section-header {
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 0.75rem 1rem;
            border-radius: 8px;
            font-weight: 600;
            margin-top: 1rem;
            margin-bottom: 1rem;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }

        /* Info box styling */
        .info-box {
            background-color: #e8f4f8;
            border-left: 4px solid #1f77b4;
            padding: 1rem;
            border-radius: 4px;
            margin: 1rem 0;
        }

        .success-box {
            background-color: #d4edda;
            border-left: 4px solid #28a745;
            padding: 1rem;
            border-radius: 4px;
            margin: 1rem 0;
        }

        .warning-box {
            background-color: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 1rem;
            border-radius: 4px;
            margin: 1rem 0;
        }

        /* Metric cards */
        .metric-card {
            background: white;
            border-radius: 10px;
            padding: 1.5rem;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            margin: 0.5rem 0;
            border-left: 4px solid #667eea;
            height: 110px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            overflow: auto;
        }

        .metric-title {
            color: #6c757d;
            font-size: 0.875rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 0.5rem;
        }

        .metric-value {
            color: #2c3e50;
            font-size: 1.0rem;
            font-weight: 1000;
            line-height: 1.35;
            overflow-wrap: anywhere;
            word-break: break-word;
        }

        /* Transform matrix styling */
        .stTable {
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }

        /* Button styling */
        .stButton > button,
        .stFormSubmitButton > button {
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 6px;
            padding: 0.5rem 2rem;
            font-weight: 600;
            transition: all 0.3s ease;
        }

        .stButton > button:hover,
        .stFormSubmitButton > button:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
        }

        /* Selectbox styling */
        .stSelectbox > div > div {
            background-color: white;
            border-radius: 6px;
            border: 2px solid #e9ecef;
        }

        /* Divider */
        hr {
            margin: 2rem 0;
            border: none;
            border-top: 2px solid #e9ecef;
        }

        /* Legend items */
        .legend-item {
            display: inline-block;
            margin-right: 1.5rem;
            margin-bottom: 0.5rem;
        }

        .legend-color {
            display: inline-block;
            width: 20px;
            height: 20px;
            border-radius: 50%;
            margin-right: 0.5rem;
            vertical-align: middle;
            box-shadow: 0 2px 4px rgba(0,0,0,0.2);
        }

        .legend-text {
            vertical-align: middle;
            font-weight: 500;
            color: #2c3e50;
        }
    </style>
    """, unsafe_allow_html=True)


def load_surface(subject, subjects_dir, trans, surf='white'):
    """
    Load surface data for the left and right hemispheres of the brain.

    Parameters:
    - subject: str, name of the subject
    - surf: str, surface type (e.g., 'white', 'pial', 'inflated', etc.)

    Returns:
    - meshes: dict, contains PyVista PolyData objects for the left and right hemispheres
    """
    hemispheres = ['lh', 'rh']
    meshes = {}

    for hemi in hemispheres:
        surface_path = Path(subjects_dir) / subject / "surf" / f"{hemi}.{surf}"
        coords, faces = mne.read_surface(surface_path)
        coords = mne.transforms.apply_trans(trans, coords, move=True)
        faces = np.hstack([np.full((faces.shape[0], 1), 3), faces]).astype(np.int64)
        mesh = pv.PolyData(coords, faces)
        meshes[hemi] = mesh
    return meshes


def load_t1(subject, subjects_dir):
    """
    Load the T1 MRI file and change the header information to the correct units.

    Parameters:
    data_path (str or Path): The path to the directory containing the MRI file.

    Returns:
    nibabel.MGHImage: The updated T1 MRI image.
    """
    t1w = nib.load(Path(subjects_dir) / subject / "mri" / "T1.mgz")
    t1w = nib.Nifti1Image(t1w.get_fdata(), t1w.affine)
    t1w.header["xyzt_units"] = np.array(10, dtype="uint8")
    t1_mgh = nib.MGHImage(t1w.get_fdata().astype(np.float32), t1w.affine)
    return t1_mgh


def visualize_head_surface(subject, subjects_dir, trans, raw, t1_mgh, window_size=(800, 600),
                           background_color='white', opacity=0.95, show_scalp=True):
    """
    Visualize the head surface for a given subject in different coordinate frames.
    """
    surface_path = Path(subjects_dir) / subject / "surf" / "lh.seghead"
    coords, faces = mne.read_surface(surface_path)
    faces = np.hstack([np.full((faces.shape[0], 1), 3), faces]).astype(np.int64)
    mesh = pv.PolyData(coords, faces)

    mri_to_head = linalg.inv(trans["trans"])
    scalp_pts_in_head_coord = mne.transforms.apply_trans(mri_to_head, coords, move=True)

    head_to_meg = linalg.inv(raw.info["dev_head_t"]["trans"])
    scalp_pts_in_meg_coord = mne.transforms.apply_trans(head_to_meg, scalp_pts_in_head_coord, move=True)

    vox_to_mri = t1_mgh.header.get_vox2ras_tkr()
    mri_to_vox = linalg.inv(vox_to_mri)
    scalp_points_in_vox = mne.transforms.apply_trans(mri_to_vox, coords, move=True)

    meshes = load_surface(subject, subjects_dir, trans=mri_to_vox)

    plotter = pv.Plotter(window_size=window_size, notebook=False, off_screen=True)
    if show_scalp:
        plotter.add_mesh(pv.PolyData(scalp_points_in_vox, faces), color="gray", opacity=opacity)
    plotter.add_mesh(meshes['lh'], color="gray", cmap="bwr", show_edges=False, opacity=1, name="lh_brain")
    plotter.add_mesh(meshes['rh'], color="gray", cmap="bwr", show_edges=False, opacity=1, name="rh_brain")

    plotter.set_background(background_color)
    plotter.view_isometric()

    return plotter


def visualize_nasion_and_scalp(plotter, subject, subjects_dir, trans, raw, t1_mgh):
    seghead_rr, seghead_tri = mne.read_surface(Path(subjects_dir) / subject / "surf" / "lh.seghead")

    vox_to_mri = t1_mgh.header.get_vox2ras_tkr()
    mri_to_vox = linalg.inv(vox_to_mri)

    nasion = [
        p for p in raw.info["dig"]
        if p["kind"] == FIFF.FIFFV_POINT_CARDINAL and p["ident"] == FIFF.FIFFV_POINT_NASION
    ][0]
    assert nasion["coord_frame"] == FIFF.FIFFV_COORD_HEAD
    nasion = nasion["r"]

    print("nasion:", nasion)
    nasion_mri = mne.transforms.apply_trans(trans, nasion, move=True)
    nasion_vox = mne.transforms.apply_trans(mri_to_vox, nasion_mri * 1e3, move=True)
    print("nasion vox:", nasion_vox)

    lpa = [
        p for p in raw.info["dig"]
        if p["kind"] == FIFF.FIFFV_POINT_CARDINAL and p["ident"] == FIFF.FIFFV_POINT_LPA
    ][0]
    assert lpa["coord_frame"] == FIFF.FIFFV_COORD_HEAD
    lpa = lpa["r"]
    lpa_mri = mne.transforms.apply_trans(trans, lpa, move=True)
    lpa_vox = mne.transforms.apply_trans(mri_to_vox, lpa_mri * 1e3, move=True)

    rpa = [
        p for p in raw.info["dig"]
        if p["kind"] == FIFF.FIFFV_POINT_CARDINAL and p["ident"] == FIFF.FIFFV_POINT_RPA
    ][0]
    assert rpa["coord_frame"] == FIFF.FIFFV_COORD_HEAD
    rpa = rpa["r"]
    rpa_mri = mne.transforms.apply_trans(trans, rpa, move=True)
    rpa_vox = mne.transforms.apply_trans(mri_to_vox, rpa_mri * 1e3, move=True)

    hsp_points = [p for p in raw.info["dig"] if p["kind"] == FIFF.FIFFV_POINT_EXTRA]
    hsp_vox = []
    for hsp in hsp_points:
        assert hsp["coord_frame"] == FIFF.FIFFV_COORD_HEAD
        hsp_xyz = hsp["r"]
        hsp_mri = mne.transforms.apply_trans(trans, hsp_xyz, move=True)
        hsp_vox.append(mne.transforms.apply_trans(mri_to_vox, hsp_mri * 1e3, move=True))

    hpi_points = [p for p in raw.info["dig"] if p["kind"] == FIFF.FIFFV_POINT_HPI]
    hpi_vox = []
    for hpi in hpi_points:
        assert hpi["coord_frame"] == FIFF.FIFFV_COORD_HEAD
        hpi_xyz = hpi["r"]
        hpi_mri = mne.transforms.apply_trans(trans, hpi_xyz, move=True)
        hpi_vox.append(mne.transforms.apply_trans(mri_to_vox, hpi_mri * 1e3, move=True))

    plotter.add_mesh(pv.Sphere(center=nasion_vox, radius=3, theta_resolution=20, phi_resolution=20),
                     color="orange", opacity=1)
    plotter.add_mesh(pv.Sphere(center=lpa_vox, radius=3, theta_resolution=20, phi_resolution=20),
                     color="blue", opacity=1)
    plotter.add_mesh(pv.Sphere(center=rpa_vox, radius=3, theta_resolution=20, phi_resolution=20),
                     color="red", opacity=1)

    if hpi_vox:
        plotter.add_mesh(
            make_sphere_glyphs(hpi_vox, radius=3, theta_resolution=12, phi_resolution=12),
            color="purple",
            opacity=1,
        )

    if hsp_vox:
        plotter.add_mesh(
            make_sphere_glyphs(hsp_vox, radius=2, theta_resolution=8, phi_resolution=8),
            color="salmon",
            opacity=1,
        )

    return plotter


def rotation_matrix(axis, angle):
    """
    Generate a 3D rotation matrix for a specified axis and angle.

    Parameters:
    -----------
    axis : str
        Rotation axis, must be 'x', 'y', or 'z'
    angle : float
        Rotation angle in degrees

    Returns:
    --------
    numpy.ndarray
        3x3 rotation matrix representing rotation around the specified axis
    """
    angle = np.radians(angle)
    c = np.cos(angle)
    s = np.sin(angle)
    if axis == 'x':
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    elif axis == 'y':
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    elif axis == 'z':
        return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    else:
        raise ValueError("Axis must be 'x', 'y', or 'z'")


def make_head_mri_transform(matrix):
    """Create a fresh MNE head->MRI Transform from a 4x4 matrix."""
    return mne.Transform("head", "mri", np.array(matrix, dtype=float, copy=True))


def is_candidate_meg_file(file_path):
    """Return True for raw/preprocessed MEG files, excluding derived report outputs."""
    path = Path(file_path)
    excluded_dirs = {"covariance", "epochs", "ica_report", "trans"}
    if any(part.lower() in excluded_dirs for part in path.parts):
        return False
    return path.name.lower().endswith((".fif", ".ds", ".sqd", ".con"))


def extract_bids_subject(value):
    match = re.search(r"sub-[A-Za-z0-9]+", str(value))
    return match.group(0) if match else None


def initialize_transform_state(trans_file, transform):
    """Keep the editable transform scoped to the currently selected file."""
    state_key = str(Path(trans_file).resolve())
    if st.session_state.get("coreg_active_trans_file") != state_key:
        st.session_state.coreg_active_trans_file = state_key
        st.session_state.coreg_transform_matrix = np.array(transform["trans"], dtype=float, copy=True)
        st.session_state.coreg_last_distance_mm = None
        st.session_state.coreg_last_action = "Loaded from disk"


def get_current_transform():
    return make_head_mri_transform(st.session_state.coreg_transform_matrix)


def set_current_transform(matrix, action):
    st.session_state.coreg_transform_matrix = np.array(matrix, dtype=float, copy=True)
    st.session_state.coreg_last_action = action


def set_coregistration_transform(coreg, head_mri_t):
    """Seed MNE Coregistration with an existing head->MRI transform."""
    head_mri_t = np.array(head_mri_t, dtype=float, copy=True)
    rotation = mne.transforms.rotation_angles(head_mri_t[:3, :3].T)
    translation = -head_mri_t[:3, :3].T @ head_mri_t[:3, 3]
    coreg.set_rotation(rotation)
    coreg.set_translation(translation)
    return coreg


def translate_transform(matrix, axis, distance_mm):
    translated = np.array(matrix, dtype=float, copy=True)
    translated[axis, 3] += distance_mm / 1000.0
    return translated


def translate_visual_transform(matrix, axis, distance_mm):
    """Apply manual translation using the displayed axis convention."""
    if axis == 2:
        distance_mm = -distance_mm
    return translate_transform(matrix, axis, distance_mm)


def make_sphere_glyphs(points, radius, theta_resolution=10, phi_resolution=10):
    """Render many points as one mesh of small spheres."""
    points = np.asarray(points, dtype=float)
    sphere = pv.Sphere(
        radius=radius,
        theta_resolution=theta_resolution,
        phi_resolution=phi_resolution,
    )
    return pv.PolyData(points).glyph(scale=False, geom=sphere)


def add_labeled_axes(plotter, t1_mgh, axis_length=None):
    """Add visible MRI RAS XYZ axes in the voxel-space scene."""
    mri_to_vox = linalg.inv(t1_mgh.header.get_vox2ras_tkr())
    bounds = np.array(plotter.bounds, dtype=float)
    mins = bounds[[0, 2, 4]]
    maxs = bounds[[1, 3, 5]]
    spans = np.maximum(maxs - mins, 1.0)
    origin = mins + spans * 0.08
    if axis_length is None:
        axis_length = float(np.max(spans) * 0.18)

    axes = [
        ("X", np.array([1.0, 0.0, 0.0]), "red"),
        ("Y", np.array([0.0, 1.0, 0.0]), "yellow"),
        ("Z", np.array([0.0, 0.0, -1.0]), "green"),
    ]

    for label, ras_direction, color in axes:
        direction = mne.transforms.apply_trans(mri_to_vox, ras_direction, move=False)
        direction_norm = np.linalg.norm(direction)
        if direction_norm == 0:
            continue
        direction = direction / direction_norm
        endpoint = origin + direction * axis_length
        arrow = pv.Arrow(
            start=origin,
            direction=direction,
            scale=axis_length,
            tip_length=0.18,
            tip_radius=0.035,
            shaft_radius=0.012,
        )
        plotter.add_mesh(arrow, color=color, opacity=1)

        text_mesh = pv.Text3D(label, depth=0.4)
        text_scale = max(axis_length * 0.12, 3.0)
        text_mesh.scale([text_scale, text_scale, text_scale], inplace=True)
        if label == "Y":
            text_mesh.rotate_z(180, inplace=True)
        text_mesh.translate(endpoint + direction * axis_length * 0.12, inplace=True)
        plotter.add_mesh(text_mesh, color=color, opacity=1)

    return plotter


def set_upright_coregistration_view(plotter, t1_mgh):
    """Use a stable face-on view: eyes facing viewer, top of brain upward."""
    mri_to_vox = linalg.inv(t1_mgh.header.get_vox2ras_tkr())

    anterior = mne.transforms.apply_trans(
        mri_to_vox, np.array([0.0, 1.0, 0.0]), move=False
    )
    superior = mne.transforms.apply_trans(
        mri_to_vox, np.array([0.0, 0.0, 1.0]), move=False
    )

    anterior_norm = np.linalg.norm(anterior)
    superior_norm = np.linalg.norm(superior)

    if anterior_norm == 0 or superior_norm == 0:
        plotter.view_isometric()
        return plotter

    anterior = anterior / anterior_norm
    superior = superior / superior_norm

    # Camera in front of the face, looking posteriorly.
    # This should make the eyes face the viewer.
    camera_direction = anterior

    # Flip this if the top of the brain appears upside down.
    view_up = superior

    bounds = np.array(plotter.bounds, dtype=float)
    mins = bounds[[0, 2, 4]]
    maxs = bounds[[1, 3, 5]]
    center = (mins + maxs) / 2.0
    distance = float(np.linalg.norm(maxs - mins) * 1.8)

    plotter.camera_position = [
        center + camera_direction * distance,
        center,
        view_up,
    ]

    plotter.reset_camera_clipping_range()

    return plotter

def run_icp_fit(raw, subject, subjects_dir, initial_matrix, params):
    coreg = Coregistration(
        info=raw.info,
        subject=subject,
        subjects_dir=subjects_dir,
        fiducials="estimated",
    )
    set_coregistration_transform(coreg, initial_matrix)
    coreg.set_grow_hair(params["grow_hair"])
    coreg.omit_head_shape_points(distance=params["omit_head_shape_points_mm"] / 1000.0)
    coreg.fit_icp(
        n_iterations=params["n_iterations"],
        lpa_weight=params["lpa_weight"],
        nasion_weight=params["nasion_weight"],
        rpa_weight=params["rpa_weight"],
        hsp_weight=params["hsp_weight"],
        eeg_weight=params["eeg_weight"],
        hpi_weight=params["hpi_weight"],
    )
    distances_mm = coreg.compute_dig_mri_distances() * 1e3
    return coreg.trans["trans"], distances_mm


def make_coreg_from_transform(raw, subject, subjects_dir, transform):
    coreg = Coregistration(
        info=raw.info,
        subject=subject,
        subjects_dir=subjects_dir,
        fiducials="estimated",
    )
    set_coregistration_transform(coreg, transform["trans"])
    return coreg


def save_coregistration_outputs(
    raw,
    subject,
    subjects_dir,
    transform,
    output_dir,
    output_subject,
    t1_mgh,
    grow_hair,
    omit_head_shape_points_mm,
):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    coreg = make_coreg_from_transform(raw, subject, subjects_dir, transform)
    coreg.set_grow_hair(grow_hair)
    coreg.omit_head_shape_points(distance=omit_head_shape_points_mm / 1000.0)
    dists = coreg.compute_dig_mri_distances() * 1e3
    dists_df = pd.DataFrame({
        "dist_min(mm)": [f"{np.min(dists):.3f}"],
        "dist_max(mm)": [f"{np.max(dists):.3f}"],
        "dist_mean(mm)": [f"{np.mean(dists):.3f}"],
    })
    dists_path = output_dir / "dists.csv"
    dists_df.to_csv(dists_path, index=False)

    screenshot_configs = [(True, ""), (False, "_brain")]
    screenshot_paths = []
    for show_scalp, suffix in screenshot_configs:
        screenshot_plotter = None
        try:
            screenshot_plotter = visualize_head_surface(
                subject=subject,
                subjects_dir=subjects_dir,
                trans=transform,
                raw=raw,
                t1_mgh=t1_mgh,
                window_size=(400, 400),
                opacity=1.0,
                show_scalp=show_scalp,
            )
            screenshot_plotter = visualize_nasion_and_scalp(
                plotter=screenshot_plotter,
                subject=subject,
                subjects_dir=subjects_dir,
                trans=transform,
                raw=raw,
                t1_mgh=t1_mgh,
            )
            screenshot_path = output_dir / f"{output_subject}_coreg_icp_finetune{suffix}.png"
            screenshot_plotter.set_background("white")
            screenshot_plotter = set_upright_coregistration_view(screenshot_plotter, t1_mgh)
            screenshot_plotter.screenshot(screenshot_path)
            screenshot_paths.append(screenshot_path)
        finally:
            if screenshot_plotter is not None:
                screenshot_plotter.close()
            gc.collect()

    return dists_path, screenshot_paths, dists


## Main Function

# Apply custom styles
apply_custom_styles()

# Main title with icon
st.markdown('<h1>🧠 MEG Coregistration Visualization</h1>', unsafe_allow_html=True)

# Sidebar styling
st.sidebar.markdown("""
    <div style='text-align: center; padding: 0px;'>
        <h2 >⚙️ Settings</h2>
    </div>
""", unsafe_allow_html=True)

if in_docker():
    report_root_dir = Path("/output")
    default_subjects_dir = Path("/smri")
else:
    report_root_dir = Path(st.session_state.get("dataset_report_path"))
    default_subjects_dir = Path(st.session_state.get("subjects_dir"))

default_meg_dir = report_root_dir / "preprocessed"
default_trans_dir = report_root_dir / "preprocessed" / "trans"

# Directory Configuration
st.sidebar.markdown("#### 📁 Directory Paths")
subjects_dir = st.sidebar.text_input("FreeSurfer SUBJECTS_DIR", default_subjects_dir)

# Subject Selection
if os.path.exists(subjects_dir):
    subjects = sorted([
        f for f in os.listdir(subjects_dir)
        if os.path.isdir(os.path.join(subjects_dir, f)) and not f.startswith('fsaverage')
    ])
    selected_subject = st.sidebar.selectbox("Select Subject", subjects)
    st.sidebar.markdown(f'<div class="success-box">✅ Found {len(subjects)} subjects</div>', unsafe_allow_html=True)
else:
    st.sidebar.markdown(f'<div class="warning-box">⚠️ No valid SUBJECTS_DIR found at: {subjects_dir}</div>',
                        unsafe_allow_html=True)
    selected_subject = None

# MEG File Selection
pattern = os.path.join(default_meg_dir, f"{selected_subject}*")
matched_dirs = glob.glob(pattern)
if matched_dirs:
    default_meg_dir = matched_dirs[0]

meg_dir = st.sidebar.text_input("MEG Directory", default_meg_dir)

meg_subject = None
if os.path.exists(meg_dir):
    meg_files = []
    for root, dirs, files in os.walk(meg_dir):
        for f in files:
            rel_path = os.path.relpath(os.path.join(root, f), meg_dir)
            if is_candidate_meg_file(rel_path):
                meg_files.append(rel_path)
    meg_files = sorted(meg_files)

    if meg_files:
        selected_meg_file = st.sidebar.selectbox("📊 Select MEG File", meg_files)
        selected_meg_file = os.path.join(meg_dir, selected_meg_file)
        st.sidebar.markdown(f'<div class="success-box">✅ Found {len(meg_files)} MEG files</div>',
                            unsafe_allow_html=True)
        meg_subject = extract_bids_subject(selected_meg_file)
        if selected_subject and meg_subject and selected_subject != meg_subject:
            st.sidebar.markdown(
                f'<div class="warning-box">⚠️ Subject mismatch: selected subject is '
                f'<b>{selected_subject}</b>, but MEG file appears to be <b>{meg_subject}</b>.</div>',
                unsafe_allow_html=True,
            )
    else:
        st.sidebar.markdown('<div class="warning-box">⚠️ No MEG files found</div>', unsafe_allow_html=True)
        selected_meg_file = None
else:
    st.sidebar.markdown(f'<div class="warning-box">⚠️ MEG directory not found for subject: {selected_subject}</div>',
                        unsafe_allow_html=True)
    meg_files = []
    selected_meg_file = None

# Transform File Selection
trans_dir = st.sidebar.text_input("Transform Directory", default_trans_dir)
trans_dirs = sorted([f for f in os.listdir(trans_dir)])
selected_trans = st.sidebar.selectbox("🔄 Select Transform File", trans_dirs)
selected_trans_file = Path(trans_dir) / selected_trans / "coreg-trans.fif"

st.sidebar.markdown("---")

# Visualization Settings
st.sidebar.markdown('⚙️ Visualization Settings', unsafe_allow_html=True)
opacity = st.sidebar.slider("Scalp Opacity", min_value=0.0, max_value=1.0, value=1.0, step=0.1)

st.sidebar.markdown("---")

# Info Display
print("Selected MEG:", selected_meg_file)
print("Selected Subject:", selected_subject)
print("Selected Transform:", selected_trans_file)

# Display current configuration in main area
col1, col2= st.columns(2)

with col1:
    st.markdown('<div class="metric-card"><div class="metric-title">Subject</div><div class="metric-value">👤 ' + str(
        selected_subject) + '</div></div>', unsafe_allow_html=True)

with col2:
    meg_filename = Path(selected_meg_file).name if selected_meg_file else "N/A"
    st.markdown(
        '<div class="metric-card"><div class="metric-title">MEG File</div><div class="metric-value">📊 ' + meg_filename + '</div></div>',
        unsafe_allow_html=True)

if selected_subject and meg_subject and selected_subject != meg_subject:
    st.warning(
        f"Selected Subject ({selected_subject}) does not match the subject inferred from the MEG file ({meg_subject})."
    )



st.markdown("---")

# Legend for fiducial points
st.markdown('<div class="section-header">📍 Fiducial Point Legend</div>', unsafe_allow_html=True)

legend_html = """
<div style="padding: 1rem; background-color: white; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); margin-bottom: 1.5rem;">
    <div class="legend-item">
        <span class="legend-color" style="background-color: orange;"></span>
        <span class="legend-text">Nasion</span>
    </div>
    <div class="legend-item">
        <span class="legend-color" style="background-color: blue;"></span>
        <span class="legend-text">LPA (Left)</span>
    </div>
    <div class="legend-item">
        <span class="legend-color" style="background-color: red;"></span>
        <span class="legend-text">RPA (Right)</span>
    </div>
    <div class="legend-item">
        <span class="legend-color" style="background-color: purple;"></span>
        <span class="legend-text">HPI Points</span>
    </div>
    <div class="legend-item">
        <span class="legend-color" style="background-color: salmon;"></span>
        <span class="legend-text">HSP Points</span>
    </div>
    <div class="legend-item">
        <span class="legend-color" style="background-color: gray;"></span>
        <span class="legend-text">Brain/Scalp</span>
    </div>
</div>
"""
st.markdown(legend_html, unsafe_allow_html=True)

# Load data and create visualization
try:
    with st.spinner('🔄 Loading data and generating visualization...'):
        t1_mgh = load_t1(subject=selected_subject, subjects_dir=subjects_dir)
        raw = mne.io.read_raw(selected_meg_file)
        coreg_trans = mne.read_trans(selected_trans_file)
        initialize_transform_state(selected_trans_file, coreg_trans)

        print("coreg_trans", coreg_trans)
        print("coreg_trans matrix:", coreg_trans['trans'])

        with st.sidebar.expander("🛠️ ICP & Manual Adjustment", expanded=True):
            with st.form("coreg_icp_form"):
                st.markdown("#### ICP Iteration")
                n_iterations = st.number_input("Number of Iterations", min_value=1, max_value=200, value=20, step=1)
                lpa_weight = st.number_input("LPA Weight", min_value=0.0, value=1.0, step=0.5)
                nasion_weight = st.number_input("Nasion Weight", min_value=0.0, value=10.0, step=0.5)
                rpa_weight = st.number_input("RPA Weight", min_value=0.0, value=1.0, step=0.5)
                hsp_weight = st.number_input("HSP Weight", min_value=0.0, value=10.0, step=0.5)
                eeg_weight = st.number_input("EEG Weight", min_value=0.0, value=0.0, step=0.5)
                hpi_weight = st.number_input("HPI Weight", min_value=0.0, value=1.0, step=0.5)
                grow_hair = st.number_input("Grow Hair (mm)", value=0.0, step=1.0)
                omit_head_shape_points_mm = st.number_input(
                    "Omit Head Shape Points Within (mm)",
                    min_value=0.0,
                    value=5.0,
                    step=1.0,
                )
                run_icp = st.form_submit_button("Run ICP", use_container_width=True)

            with st.form("coreg_manual_translation_form"):
                st.markdown("#### Manual Translation")
                step_mm = st.number_input("Step Size (mm)", min_value=0.1, max_value=50.0, value=1.0, step=0.5)
                col_left, col_right = st.columns(2)
                with col_left:
                    move_x_neg = st.form_submit_button("X-", use_container_width=True)
                with col_right:
                    move_x_pos = st.form_submit_button("X+", use_container_width=True)
                col_back, col_forward = st.columns(2)
                with col_back:
                    move_y_neg = st.form_submit_button("Y-", use_container_width=True)
                with col_forward:
                    move_y_pos = st.form_submit_button("Y+", use_container_width=True)
                col_down, col_up = st.columns(2)
                with col_down:
                    move_z_neg = st.form_submit_button("Z-", use_container_width=True)
                with col_up:
                    move_z_pos = st.form_submit_button("Z+", use_container_width=True)

                reset_transform = st.form_submit_button("Reset From Disk", use_container_width=True)

        if reset_transform:
            set_current_transform(coreg_trans["trans"], "Reset from disk")
            st.sidebar.success("Transform reset from selected file.")

        manual_moves = [
            (move_x_neg, 0, -step_mm, "Moved X-"),
            (move_x_pos, 0, step_mm, "Moved X+"),
            (move_y_neg, 1, -step_mm, "Moved Y-"),
            (move_y_pos, 1, step_mm, "Moved Y+"),
            (move_z_neg, 2, -step_mm, "Moved Z-"),
            (move_z_pos, 2, step_mm, "Moved Z+"),
        ]
        for should_move, axis, distance_mm, action in manual_moves:
            if should_move:
                set_current_transform(
                    translate_visual_transform(st.session_state.coreg_transform_matrix, axis, distance_mm),
                    f"{action} by {step_mm:g} mm",
                )
                st.session_state.coreg_last_distance_mm = None
                st.sidebar.success(f"{action} by {step_mm:g} mm.")
                break

        if run_icp:
            icp_params = {
                "n_iterations": int(n_iterations),
                "lpa_weight": float(lpa_weight),
                "nasion_weight": float(nasion_weight),
                "rpa_weight": float(rpa_weight),
                "hsp_weight": float(hsp_weight),
                "eeg_weight": float(eeg_weight),
                "hpi_weight": float(hpi_weight),
                "grow_hair": float(grow_hair),
                "omit_head_shape_points_mm": float(omit_head_shape_points_mm),
            }
            with st.spinner("Running ICP fitting..."):
                fitted_matrix, distances_mm = run_icp_fit(
                    raw=raw,
                    subject=selected_subject,
                    subjects_dir=subjects_dir,
                    initial_matrix=st.session_state.coreg_transform_matrix,
                    params=icp_params,
                )
            set_current_transform(fitted_matrix, f"ICP fitted ({int(n_iterations)} iterations)")
            st.session_state.coreg_last_distance_mm = float(np.mean(distances_mm))
            st.sidebar.success(f"ICP complete. Mean dig-MRI distance: {np.mean(distances_mm):.3f} mm")

        current_transform = get_current_transform()

        plotter = visualize_head_surface(
            subject=selected_subject,
            subjects_dir=subjects_dir,
            trans=current_transform,
            raw=raw,
            t1_mgh=t1_mgh,
            opacity=opacity
        )

        plotter = visualize_nasion_and_scalp(
            plotter=plotter,
            subject=selected_subject,
            subjects_dir=subjects_dir,
            trans=current_transform,
            raw=raw,
            t1_mgh=t1_mgh
        )

        plotter.set_background("white")
        plotter = set_upright_coregistration_view(plotter, t1_mgh)
        plotter = add_labeled_axes(plotter, t1_mgh)

    # Display visualization
    st.markdown('<div class="section-header">🎯 3D Visualization</div>', unsafe_allow_html=True)
    stpyvista(
        plotter,
        key=f"coregistration_{time.time()}",
        panel_kwargs=dict(interactive_orientation_widget=False, orientation_widget=False)
    )

    # Display transformation matrix
    st.markdown("---")
    st.markdown('<div class="section-header">🔢 Coregistration Transform Matrix (4×4)</div>', unsafe_allow_html=True)

    st.markdown(
        '<div class="info-box">This homogeneous transformation matrix represents the spatial relationship between MRI and MEG head coordinates.</div>',
        unsafe_allow_html=True)

    # Format the matrix nicely
    if st.session_state.get("coreg_last_action"):
        st.info(f"Current transform state: {st.session_state.coreg_last_action}")
    if st.session_state.get("coreg_last_distance_mm") is not None:
        st.metric("Mean Dig-MRI Distance", f"{st.session_state.coreg_last_distance_mm:.3f} mm")

    transform_df = current_transform['trans']
    st.dataframe(
        transform_df,
        width='stretch',
        height=200
    )

    # Additional matrix info
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Matrix Shape", f"{transform_df.shape[0]} × {transform_df.shape[1]}")
    with col2:
        determinant = np.linalg.det(transform_df[:3, :3])
        st.metric("Rotation Determinant", f"{determinant:.6f}")

    if st.button("💾 Save Transform Matrix", key="save_transform_button", use_container_width=True):
        mne.write_trans(selected_trans_file, current_transform, overwrite=True)
        output_subject = extract_bids_subject(selected_trans_file.parent.name) or selected_subject
        with st.spinner("Saving transform, distance metrics, and final coregistration figures..."):
            dists_path, screenshot_paths, saved_dists = save_coregistration_outputs(
                raw=raw,
                subject=selected_subject,
                subjects_dir=subjects_dir,
                transform=current_transform,
                output_dir=selected_trans_file.parent,
                output_subject=output_subject,
                t1_mgh=t1_mgh,
                grow_hair=float(grow_hair),
                omit_head_shape_points_mm=float(omit_head_shape_points_mm),
            )
        st.session_state.coreg_last_distance_mm = float(np.mean(saved_dists))
        st.success(
            "Saved coregistration outputs: "
            f"{selected_trans_file}, {dists_path}, "
            f"{', '.join(str(path) for path in screenshot_paths)}"
        )

except Exception as e:
    st.error(f"❌ Error: {str(e)}")
    st.exception(e)

# Footer
st.markdown("---")
st.markdown(
    '<div style="text-align: center; color: #6c757d; padding: 1rem;">'
    'MEG Coregistration Visualization Tool | Built with Streamlit & PyVista'
    '</div>',
    unsafe_allow_html=True
)
