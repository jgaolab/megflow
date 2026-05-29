# !/usr/bin/env python3
# -*- coding: utf-8 -*-
## ref: https://mne.tools/stable/auto_tutorials/forward/20_source_alignment.html#sphx-glr-auto-tutorials-forward-20-source-alignment-py

import os
import glob
import numpy as np
import pandas as pd
import nibabel as nib
import streamlit as st
from stpyvista import stpyvista
from stpyvista.utils import start_xvfb
import pyvista as pv
import mne
from pathlib import Path
from scipy import linalg
from mne import transforms
from mne.io.constants import FIFF
from mne.coreg import Coregistration
from reports.utils import in_docker

# --- 1. 设置环境变量 (在无头环境中避免 GLSL 错误) ---
os.environ['PYVISTA_PLOT_THEME'] = 'document'
os.environ['PYVISTA_USE_PANEL'] = 'False'
os.environ["MESA_GLSL_VERSION_OVERRIDE"] = "150"
os.environ["MESA_GL_VERSION_OVERRIDE"] = "3.2"
os.environ['VTK_OFFSCREEN_RENDERING'] = '1'

# 如果在无头环境，需要指定 DISPLAY
# virtual GUI |
# Xvfb :99 -screen 0 1920x1080x24 &
os.environ["DISPLAY"] = ":99"

# --- 2. 启动虚拟显示 (Xvfb) ---
if "IS_XVFB_RUNNING" not in st.session_state:
    start_xvfb()
    st.session_state.IS_XVFB_RUNNING = True



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
        # PyVista requires the faces array to include the number of vertices for each polygon (3 for triangles)
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
    # Load the T1 file
    t1w = nib.load(Path(subjects_dir) / subject / "mri" / "T1.mgz")

    # Create a new Nifti1 image to update the header
    t1w = nib.Nifti1Image(t1w.get_fdata(), t1w.affine)

    # Update the header to set the correct units
    t1w.header["xyzt_units"] = np.array(10, dtype="uint8")

    # Convert to MGHImage
    t1_mgh = nib.MGHImage(t1w.get_fdata().astype(np.float32), t1w.affine)

    return t1_mgh


def visualize_head_surface(subject, subjects_dir, trans, raw, t1_mgh, window_size=(800, 600),
                           background_color='white', opacity=0.95):
    """
    Visualize the head surface for a given subject in different coordinate frames.

    Parameters:
    - subject (str): Subject identifier.
    - subjects_dir (str): Path to the Freesurfer subjects directory.
    - trans (dict): Transformation dictionary containing MRI to head transforms.
    - raw (mne.io.Raw): Raw MNE data object to get the device head transformation.
    - t1_mgh (mne.MGHImage): T1-weighted MRI image in MGH format.
    - hemi (str): Hemisphere to visualize ('lh' or 'rh').
    - surf (str): Surface type to load (e.g., 'seghead').
    - window_size (tuple): Size of the plotting window (width, height).
    - background_color (str): Background color of the plot.

    Returns:
    - plotter (pyvista.Plotter): The PyVista plotter instance.
    """

    # scalp surface
    surface_path = Path(subjects_dir) / subject / "surf" / "lh.seghead"

    # Read the surface file for the specified hemisphere and surface type
    coords, faces = mne.read_surface(surface_path)

    # Ensure the faces array includes the number of vertices for each polygon (3 for triangles)
    faces = np.hstack([np.full((faces.shape[0], 1), 3), faces]).astype(np.int64)

    # Create a PyVista mesh from the coordinates and faces
    mesh = pv.PolyData(coords, faces)

    # Transform coordinates into head, MEG, and voxel coordinate frames
    mri_to_head = linalg.inv(trans["trans"])
    scalp_pts_in_head_coord = mne.transforms.apply_trans(mri_to_head, coords, move=True)

    head_to_meg = linalg.inv(raw.info["dev_head_t"]["trans"])
    scalp_pts_in_meg_coord = mne.transforms.apply_trans(head_to_meg, scalp_pts_in_head_coord, move=True)

    vox_to_mri = t1_mgh.header.get_vox2ras_tkr()
    mri_to_vox = linalg.inv(vox_to_mri)
    scalp_points_in_vox = mne.transforms.apply_trans(mri_to_vox, coords, move=True)

    # brain surface
    meshes = load_surface(subject, subjects_dir, trans=mri_to_vox)


    # Create a PyVista plotter
    # plotter = pv.Plotter(window_size=window_size, notebook=False,off_screen=True)
    plotter = pv.Plotter(window_size=window_size, notebook=False)

    # Add the head mesh and different scalp surfaces to the plotter
    # plotter.add_mesh(mesh, color="gray", opacity=0.95)  # original MRI mesh
    # plotter.add_mesh(pv.PolyData(scalp_pts_in_meg_coord, faces), color="blue", opacity=0.95)  # scalp in MEG coords
    # plotter.add_mesh(pv.PolyData(scalp_pts_in_head_coord, faces), color="pink", opacity=0.95)  # scalp in head coords
    plotter.add_mesh(pv.PolyData(scalp_points_in_vox, faces), color="gray", opacity=opacity)  # scalp in voxel coords | green

    # brain
    plotter.add_mesh(meshes['lh'],color="gray",cmap="bwr",show_edges=False,opacity=1,name="lh_brain")
    plotter.add_mesh(meshes['rh'],color="gray",cmap="bwr",show_edges=False,opacity=1,name="rh_brain")

    # Set the background color and view settings
    plotter.set_background(background_color)
    plotter.view_isometric()
    # plotter.add_scalar_bar()

    return plotter

def visualize_nasion_and_scalp(plotter, subject, subjects_dir, trans, raw, t1_mgh):
    # Read the surface file for the left hemisphere segmented head
    seghead_rr, seghead_tri = mne.read_surface(Path(subjects_dir) / subject / "surf" / "lh.seghead")

    # Create the MRI to voxel transform
    vox_to_mri = t1_mgh.header.get_vox2ras_tkr()
    mri_to_vox = linalg.inv(vox_to_mri)

    # Get the nasion point from the raw data
    nasion = [
        p
        for p in raw.info["dig"]
        if p["kind"] == FIFF.FIFFV_POINT_CARDINAL and p["ident"] == FIFF.FIFFV_POINT_NASION
    ][0]
    assert nasion["coord_frame"] == FIFF.FIFFV_COORD_HEAD
    nasion = nasion["r"]  # Get just the XYZ values

    print("nasion:",nasion)
    # Transform the nasion from head to MRI space
    nasion_mri = mne.transforms.apply_trans(trans, nasion, move=True)

    # Transform to voxel space (from meters to millimeters)
    nasion_vox = mne.transforms.apply_trans(mri_to_vox, nasion_mri * 1e3, move=True)

    print("nasion vox:",nasion_vox)

    # Get LPA and RPA points similarly
    lpa = [
        p
        for p in raw.info["dig"]
        if p["kind"] == FIFF.FIFFV_POINT_CARDINAL and p["ident"] == FIFF.FIFFV_POINT_LPA
    ][0]
    assert lpa["coord_frame"] == FIFF.FIFFV_COORD_HEAD
    lpa = lpa["r"]  # Get just the XYZ values
    lpa_mri = mne.transforms.apply_trans(trans, lpa, move=True)
    lpa_vox = mne.transforms.apply_trans(mri_to_vox, lpa_mri * 1e3, move=True)

    rpa = [
        p
        for p in raw.info["dig"]
        if p["kind"] == FIFF.FIFFV_POINT_CARDINAL and p["ident"] == FIFF.FIFFV_POINT_RPA
    ][0]
    assert rpa["coord_frame"] == FIFF.FIFFV_COORD_HEAD
    rpa = rpa["r"]  # Get just the XYZ values
    rpa_mri = mne.transforms.apply_trans(trans, rpa, move=True)
    rpa_vox = mne.transforms.apply_trans(mri_to_vox, rpa_mri * 1e3, move=True)

    # Extract and transform HSP and HPI points
    hsp_points = [
        p for p in raw.info["dig"] if p["kind"] == FIFF.FIFFV_POINT_EXTRA #FIFFV_POINT_HEAD
    ]

    hsp_vox = []
    for hsp in hsp_points:
        assert hsp["coord_frame"] == FIFF.FIFFV_COORD_HEAD
        hsp_xyz = hsp["r"]  # Get just the XYZ values
        hsp_mri = mne.transforms.apply_trans(trans, hsp_xyz, move=True)
        hsp_vox.append(mne.transforms.apply_trans(mri_to_vox, hsp_mri * 1e3, move=True))

    hpi_points = [
        p for p in raw.info["dig"] if p["kind"] == FIFF.FIFFV_POINT_HPI
    ]
    hpi_vox = []
    for hpi in hpi_points:
        assert hpi["coord_frame"] == FIFF.FIFFV_COORD_HEAD
        hpi_xyz = hpi["r"]  # Get just the XYZ values
        hpi_mri = mne.transforms.apply_trans(trans, hpi_xyz, move=True)
        hpi_vox.append(mne.transforms.apply_trans(mri_to_vox, hpi_mri * 1e3, move=True))

    # Add the nasion point as a sphere
    plotter.add_mesh(pv.Sphere(center=nasion_vox, radius=5, theta_resolution=20, phi_resolution=20),
                     color="orange", opacity=1)

    # Add LPA and RPA points as spheres
    plotter.add_mesh(pv.Sphere(center=lpa_vox, radius=5, theta_resolution=20, phi_resolution=20),
                     color="blue", opacity=1)  # LPA in blue
    plotter.add_mesh(pv.Sphere(center=rpa_vox, radius=5, theta_resolution=20, phi_resolution=20),
                     color="red", opacity=1)  # RPA in red

    # Add HPI points as spheres
    for idx, hpi in enumerate(hpi_vox):
        color = "purple"  # Choose a distinct color for HPI points
        plotter.add_mesh(pv.Sphere(center=hpi, radius=5, theta_resolution=20, phi_resolution=20),
                         color=color, opacity=1)  # HPI points in purple

    # Add HSP points as spheres
    for idx, hsp in enumerate(hsp_vox):
        color = "salmon"  # Choose a distinct color for HSP points
        plotter.add_mesh(pv.Sphere(center=hsp, radius=3, theta_resolution=20, phi_resolution=20),
                         color=color, opacity=1)  # HSP points in salmon

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
    angle = np.radians(angle)  # 转换为弧度
    c = np.cos(angle)
    s = np.sin(angle)
    if axis == 'x':
        return np.array([[1, 0, 0],
                         [0, c, -s],
                         [0, s, c]])
    elif axis == 'y':
        return np.array([[c, 0, s],
                         [0, 1, 0],
                         [-s, 0, c]])
    elif axis == 'z':
        return np.array([[c, -s, 0],
                         [s, c, 0],
                         [0, 0, 1]])
    else:
        raise ValueError("Axis must be 'x', 'y', or 'z'")

## Main Function

st.title("Coregistration")

# Sidebar for user inputs
st.sidebar.header("Configuration")

if in_docker():
    report_root_dir = Path("/output")
    default_subjects_dir = Path("/smri")
else:
    report_root_dir = Path(st.session_state.get("dataset_report_path"))
    default_subjects_dir = Path(st.session_state.get("subjects_dir"))

default_meg_dir = report_root_dir / "preprocessed"
default_trans_dir = report_root_dir / "preprocessed" / "trans"


# Set a default FreeSurfer SUBJECTS_DIR
# SQUID
# default_subjects_dir = Path("/data/liaopan/datasets/smn4lang_single2_smri")
# default_meg_dir = Path("/data/liaopan/datasets/SMN4Lang_single2/sub-01/meg/")
# default_trans_dir = Path("/data/liaopan/datasets/SMN4Lang_single/test_v3.5/preprocessed/trans/")

# CTF
# default_subjects_dir = Path("/data/liaopan/datasets/Holmes/smri/")
# default_meg_dir = Path("/data/liaopan/datasets/Holmes/sub-001/ses-001/meg/")
# default_trans_dir = Path("/data/liaopan/datasets/Holmes/preprocessed/preprocessed/trans/")


subjects_dir = st.sidebar.text_input("Freesurfer SUBJECTS_DIR", default_subjects_dir)
opacity = st.sidebar.slider("Opacity", min_value=0.0, max_value=1.0, value=0.95, step=0.1)

# Get available subjects
if os.path.exists(subjects_dir):
    # subjects = sorted([f for f in os.listdir(subjects_dir) if os.path.isdir(os.path.join(subjects_dir, f))])
    subjects = sorted([
        f for f in os.listdir(subjects_dir)
        if os.path.isdir(os.path.join(subjects_dir, f)) and not f.startswith('fsaverage')
    ])
    selected_subject = st.sidebar.selectbox("Select Subject", subjects)
else:
    st.sidebar.warning(f"No valid SUBJECTS_DIR found at: {subjects_dir}")
    selected_subject = None

pattern = os.path.join(default_meg_dir, f"{selected_subject}*")
matched_dirs = glob.glob(pattern)
if matched_dirs:
    default_meg_dir = matched_dirs[0]

meg_dir = st.sidebar.text_input("MEG DIR", default_meg_dir)
if os.path.exists(meg_dir):

    # meg_files = sorted([
    #     f for f in os.listdir(meg_dir)
    #     if any(f.lower().endswith(ext) for ext in ['.fif', '.ds', '.sqd', '.con'])
    # ])

    meg_files = []
    for root, dirs, files in os.walk(meg_dir):
        for f in files:
            if any(f.lower().endswith(ext) for ext in ['.fif', '.ds', '.sqd', '.con']):
                # Store the path relative to the main MEG directory
                rel_path = os.path.relpath(os.path.join(root, f), meg_dir)
                meg_files.append(rel_path)
    meg_files = sorted(meg_files)

    if meg_files:
        selected_meg_file = st.sidebar.selectbox("Select a MEG File", meg_files)
        selected_meg_file = os.path.join(meg_dir, selected_meg_file)
    else:
        st.sidebar.warning("No available MEG files in this directory.")
        selected_meg_file = None
else:
    st.sidebar.warning(f"No MEG directory found for subject: {selected_subject}")
    meg_files = []
    selected_meg_file = None

trans_dir = st.sidebar.text_input("Transform DIR", default_trans_dir)
trans_dirs = sorted([f for f in os.listdir(trans_dir)])
selected_trans = st.sidebar.selectbox("Select a Transform File:", trans_dirs)
selected_trans_file  = Path(trans_dir) / selected_trans / "coreg-trans.fif"


# Init
t1_mgh = load_t1(subject=selected_subject, subjects_dir=subjects_dir)
raw = mne.io.read_raw(selected_meg_file)
coreg_trans = mne.read_trans(selected_trans_file)

print("coreg_trans",coreg_trans)
print("coreg_trans matrix:",coreg_trans['trans'])


st.sidebar.markdown("---")

# Fit ICP
st.sidebar.header("Settings")
with st.sidebar.form(key='coreg-settings'):
    st.subheader("MNE ICP Iteration Parameters")
    n_iterations = int(st.text_input("Number of Iterations", value="20"))
    lpa_weight = float(st.text_input("LPA Weight", value="1.0"))
    nasion_weight = float(st.text_input("Nasion Weight", value="10.0"))
    rpa_weight = float(st.text_input("RPA Weight", value="1.0"))
    hsp_weight = float(st.text_input("HSP Weight", value="10.0"))
    eeg_weight = float(st.text_input("EEG Weight", value="0.0"))
    hpi_weight = float(st.text_input("HPI Weight", value="1.0"))

    grow_hair = float(st.text_input("Grow Hair", value="0.0"))
    omit_head_shape_points =  float(st.text_input("Omit Head Shape Points", value="5.0"))

    # Create a dictionary with the parameters
    data = {
        "Parameter": [
            "Number of Iterations",
            "LPA Weight",
            "Nasion Weight",
            "RPA Weight",
            "HSP Weight",
            "EEG Weight",
            "HPI Weight",
            "Grow Hair",
            "Omit Head Shape Points"
        ],
        "Value": [
            n_iterations,
            lpa_weight,
            nasion_weight,
            rpa_weight,
            hsp_weight,
            eeg_weight,
            hpi_weight,
            grow_hair,
            omit_head_shape_points
        ]
    }

    # Create a DataFrame
    config_df = pd.DataFrame(data)

    col1, col2, col3 = st.columns([1, 2, 1]) # center
    with col2:
        submitted_config_icp = st.form_submit_button("FitICP") #[MNE]


with st.sidebar.form(key="tran-ro-config"):
    # st.markdown("---")
    st.subheader("Translation & Rotation")

    translation_x = st.slider("Translation X-axis", -5.0, 5.0, 1.0)  # Translation along X-axis
    translation_y = st.slider("Translation Y-axis", -5.0, 5.0, 0.0)  # Translation along Y-axis
    translation_z = st.slider("Translation Z-axis", -5.0, 5.0, 0.0)  # Translation along Z-axis

    rotation_x = st.slider("Rotation around X-axis (°)", 0, 360, 0)  # Rotation around X-axis
    rotation_y = st.slider("Rotation around Y-axis (°)", 0, 360, 0)  # Rotation around Y-axis
    rotation_z = st.slider("Rotation around Z-axis (°)", 0, 360, 0)  # Rotation around Z-axis

    col1, col2, col3 = st.columns([1, 2, 1]) # center
    with col2:
        submitted_config_trano = st.form_submit_button("Apply")


print("Selected MEG:", selected_meg_file)
print("Selected Subject:", selected_subject)
print("Selected Transform:", selected_trans_file)


plotter = pv.Plotter(window_size=[800, 600])

if st.session_state.get('transform_changed_flag',False):
    coreg_trans_matrix = st.session_state.coreg.trans
    print("go cache....",coreg_trans_matrix)
else:
    coreg_trans_matrix = coreg_trans
    print("go init...",coreg_trans)

plotter = visualize_head_surface(subject=selected_subject,
                               subjects_dir=subjects_dir,
                               trans=coreg_trans_matrix,
                               raw=raw,
                               t1_mgh=t1_mgh,
                               opacity=opacity)


plotter = visualize_nasion_and_scalp(plotter=plotter,subject=selected_subject,
                           subjects_dir=subjects_dir,
                           trans=coreg_trans_matrix,
                           raw=raw,
                           t1_mgh=t1_mgh)

# Set background & camera view
plotter.set_background("white")
plotter.view_isometric()
# plotter.add_scalar_bar()
plotter.add_axes_at_origin()
# plotter.show(auto_close=True)
# plotter.update()
stpyvista(plotter, key="coregistration", panel_kwargs=dict(interactive_orientation_widget=False,orientation_widget=True))

if submitted_config_icp:
    fiducials = 'estimated'
    coreg = Coregistration(info=raw.info,
                           subject=selected_subject,
                           subjects_dir=subjects_dir,
                           fiducials=fiducials)

    coreg.set_grow_hair(grow_hair)
    coreg.omit_head_shape_points(distance=(omit_head_shape_points / 1000))

    icp_parameters = {
        "n_iterations": n_iterations,
        "lpa_weight": lpa_weight,
        "nasion_weight": nasion_weight,
        "rpa_weight": rpa_weight,
        "hsp_weight": hsp_weight,
        "eeg_weight": eeg_weight,
        "hpi_weight": hpi_weight
    }
    coreg.fit_icp(**icp_parameters)

    st.write("Coreg Transform (after ICP):")
    st.write(coreg.trans)

    # Compute distances between HSP and MRI
    dists = coreg.compute_dig_mri_distances() * 1e3  # Convert to mm
    st.write(f"Distances between HSP and MRI(mean): {np.mean(dists):.3f} mm")

    st.session_state.coreg = coreg
    st.session_state.transform_changed_flag = True

if submitted_config_trano:
    print("go translate....")
    # Define translation offset and rotation angle
    translation = np.array([translation_x, translation_y, translation_z])

    # 计算旋转矩阵
    rot_x = rotation_matrix('x', rotation_x)
    rot_y = rotation_matrix('y', rotation_y)
    rot_z = rotation_matrix('z', rotation_z)

    # 组合旋转矩阵（ZYX顺序）
    combined_rotation_matrix = rot_z @ rot_y @ rot_x

    # 创建齐次变换矩阵（4x4）
    homogeneous_transform = np.eye(4)
    homogeneous_transform[:3, :3] = combined_rotation_matrix  # 设置旋转部分
    homogeneous_transform[:3, 3] = translation  # 设置平移部分

    # trans = mne.Transform('head', 'mri', homogeneous_transform) ##_head_mri_t

    if st.session_state.get('coreg',None) is not None:
        print("go here T 1")
        st.session_state.coreg._head_mri_t = homogeneous_transform
    else:
        coreg = Coregistration(info=raw.info,
                               subject=selected_subject,
                               subjects_dir=subjects_dir,
                               fiducials='estimated')
        print("homogeneous_transform:",homogeneous_transform)
        coreg._head_mri_t = homogeneous_transform
        st.session_state.coreg = coreg

    st.session_state.transform_changed_flag = True
    print("Translation&Rotation Done!")


# Display the header
st.write("### Configured Parameters:")

# Display the DataFrame as a table
st.dataframe(config_df, use_container_width=True,hide_index=True)


# 显示齐次变换矩阵
st.write("Coregistration Transform (4x4):")
if st.session_state.get('coreg',None) is not None:
    print("go cache2....")
    st.write(st.session_state.coreg.trans['trans'])
else:
    st.write(coreg_trans_matrix)
    print("go init2....")

# save transform matrix
if st.button("Save Transform Matrix", key="save_button"):
    transform_matrix = st.session_state.coreg.trans['trans']
    trans = mne.Transform('head', 'mri', transform_matrix)
    # mne.write_trans(selected_trans_file, trans, overwrite=True)
    mne.write_trans("demo-trans.fif", trans, overwrite=True)
    st.success(f"Transform matrix saved!")






