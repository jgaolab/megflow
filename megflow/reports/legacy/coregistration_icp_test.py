# !/usr/bin/env python3
# -*- coding: utf-8 -*-
## ref: https://mne.tools/stable/auto_tutorials/forward/20_source_alignment.html#sphx-glr-auto-tutorials-forward-20-source-alignment-py

import os
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


# --- 1. 设置环境变量 (在无头环境中避免 GLSL 错误) ---
os.environ['PYVISTA_PLOT_THEME'] = 'document'
os.environ['PYVISTA_USE_PANEL'] = 'False'
os.environ["MESA_GLSL_VERSION_OVERRIDE"] = "150"
os.environ["MESA_GL_VERSION_OVERRIDE"] = "3.2"

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
                           background_color='white'):
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
    plotter = pv.Plotter(window_size=window_size, notebook=False)

    # Add the head mesh and different scalp surfaces to the plotter
    # plotter.add_mesh(mesh, color="gray", opacity=0.95)  # original MRI mesh
    # plotter.add_mesh(pv.PolyData(scalp_pts_in_meg_coord, faces), color="blue", opacity=0.95)  # scalp in MEG coords
    # plotter.add_mesh(pv.PolyData(scalp_pts_in_head_coord, faces), color="pink", opacity=0.95)  # scalp in head coords
    plotter.add_mesh(pv.PolyData(scalp_points_in_vox, faces), color="gray", opacity=0.95)  # scalp in voxel coords | green

    # brain
    plotter.add_mesh(meshes['lh'],color="gray",cmap="bwr",show_edges=False,opacity=1,name="lh_brain")
    plotter.add_mesh(meshes['rh'],color="gray",cmap="bwr",show_edges=False,opacity=1,name="rh_brain")

    # Set the background color and view settings
    plotter.set_background(background_color)
    plotter.view_isometric()
    plotter.add_scalar_bar()

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

    # Transform the nasion from head to MRI space
    nasion_mri = mne.transforms.apply_trans(trans, nasion, move=True)

    # Transform to voxel space (from meters to millimeters)
    nasion_vox = mne.transforms.apply_trans(mri_to_vox, nasion_mri * 1e3, move=True)

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
        p for p in raw.info["dig"] if p["kind"] == FIFF.FIFFV_POINT_HPI
    ]
    hpi_vox = []
    for hsp in hsp_points:
        assert hsp["coord_frame"] == FIFF.FIFFV_COORD_HEAD
        hsp_xyz = hsp["r"]  # Get just the XYZ values
        hsp_mri = mne.transforms.apply_trans(trans, hsp_xyz, move=True)
        hpi_vox.append(mne.transforms.apply_trans(mri_to_vox, hsp_mri * 1e3, move=True))

    # Create a PyVista plotter
    # plotter = pv.Plotter(window_size=(600, 600), notebook=False)

    # Function to add the scalp mesh to the plot
    # def add_head(points, color, opacity=0.95):
    #     mesh = pv.PolyData(points, seghead_tri)
    #     plotter.add_mesh(mesh, color=color, opacity=opacity)
    #
    # add_head(seghead_rr, "green")  # Scalp in voxel coordinates

    # Add the nasion point as a sphere
    plotter.add_mesh(pv.Sphere(center=nasion_vox, radius=10, theta_resolution=20, phi_resolution=20),
                     color="orange", opacity=1)

    # Add LPA and RPA points as spheres
    plotter.add_mesh(pv.Sphere(center=lpa_vox, radius=10, theta_resolution=20, phi_resolution=20),
                     color="blue", opacity=1)  # LPA in blue
    plotter.add_mesh(pv.Sphere(center=rpa_vox, radius=10, theta_resolution=20, phi_resolution=20),
                     color="red", opacity=1)  # RPA in red

    # Add HPI points as spheres
    for idx, hpi in enumerate(hpi_vox):
        color = "purple"  # Choose a distinct color for HPI points
        plotter.add_mesh(pv.Sphere(center=hpi, radius=5, theta_resolution=20, phi_resolution=20),
                         color=color, opacity=1)  # HPI points in purple

    return plotter

## Main Function

st.title("Coregistration")

# Sidebar for user inputs
st.sidebar.header("Configuration")

# Set a default FreeSurfer SUBJECTS_DIR
default_subjects_dir = Path("/data/liaopan/datasets/smn4lang_single2_smri")
default_meg_dir = Path("/data/liaopan/datasets/SMN4Lang_single2/sub-01/meg/")
default_trans_dir = Path("/data/liaopan/datasets/SMN4Lang_single/test_v3.5/preprocessed/trans/")


subjects_dir = st.sidebar.text_input("Freesurfer SUBJECTS_DIR", default_subjects_dir)
opacity = st.sidebar.slider("Opacity", min_value=0.0, max_value=1.0, value=1.0, step=0.1)

# Get available subjects
if os.path.exists(subjects_dir):
    subjects = sorted([f for f in os.listdir(subjects_dir) if os.path.isdir(os.path.join(subjects_dir, f))])
    selected_subject = st.sidebar.selectbox("Select Subject", subjects)
else:
    st.sidebar.warning(f"No valid SUBJECTS_DIR found at: {subjects_dir}")
    selected_subject = None

meg_dir = st.sidebar.text_input("MEG DIR", default_meg_dir)
if os.path.exists(meg_dir):
    meg_files = sorted([
        f for f in os.listdir(meg_dir)
        if os.path.isfile(os.path.join(meg_dir, f)) and f.endswith('.fif')
    ])
    selected_meg_file = st.sidebar.selectbox("Select a MEG File", meg_files)
    selected_meg_file = os.path.join(meg_dir, selected_meg_file)
else:
    st.sidebar.warning(f"No MEG directory found for subject: {selected_subject}")
    meg_files = []
    selected_meg_file = None

trans_dir = st.sidebar.text_input("Transform DIR", default_trans_dir)
trans_dirs = sorted([f for f in os.listdir(trans_dir)])
selected_trans = st.sidebar.selectbox("Select a Transform File:", trans_dirs)
selected_trans_file  = Path(trans_dir) / selected_trans / "coreg-trans.fif"

# Fit ICP

n_iterations = int(st.sidebar.text_input("Number of Iterations", value="200"))
lpa_weight = float(st.sidebar.text_input("LPA Weight", value="1.0"))
nasion_weight = float(st.sidebar.text_input("Nasion Weight", value="10.0"))
rpa_weight = float(st.sidebar.text_input("RPA Weight", value="1.0"))
hsp_weight = float(st.sidebar.text_input("HSP Weight", value="10.0"))
eeg_weight = float(st.sidebar.text_input("EEG Weight", value="0.0"))
hpi_weight = float(st.sidebar.text_input("HPI Weight", value="1.0"))

grow_hair = float(st.sidebar.text_input("Grow Hair", value="0.0"))
omit_head_shape_points =  float(st.sidebar.text_input("Omit Head Shape Points", value="5.0"))

print("Selected MEG:", selected_meg_file)
print("Selected Subject:", selected_subject)
print("Selected Transform:", selected_trans_file)

# Init
t1_mgh = load_t1(subject=selected_subject, subjects_dir=subjects_dir)
raw = mne.io.read_raw_fif(selected_meg_file)
coreg_trans = mne.read_trans(selected_trans_file)

print("coreg_trans",coreg_trans)
print("coreg_trans matrix:",coreg_trans['trans'])

plotter = pv.Plotter(window_size=[800, 600])

plotter = visualize_head_surface(subject=selected_subject,
                               subjects_dir=subjects_dir,
                               trans=coreg_trans,
                               raw=raw,
                               t1_mgh=t1_mgh)


plotter = visualize_nasion_and_scalp(plotter=plotter,subject=selected_subject,
                           subjects_dir=subjects_dir,
                           trans=coreg_trans,
                           raw=raw,
                           t1_mgh=t1_mgh)
# 设置背景 & 视角
plotter.set_background("white")
plotter.view_isometric()
plotter.add_scalar_bar()

# Set the view parameters (camera position, focal point, elevation, azimuth)
# plotter.camera.position = (0.0, -600.0, 250.0)
# plotter.camera.focal_point = (0.0, 125.0, 250.0)
# plotter.camera.elevation = 45
# plotter.camera.azimuth = 180


stpyvista(plotter, key="coregistration")

# ICP Algorithm.
st.write("### Configured Parameters:")
st.write(f"Number of Iterations: {n_iterations}")
st.write(f"LPA Weight: {lpa_weight}")
st.write(f"Nasion Weight: {nasion_weight}")
st.write(f"RPA Weight: {rpa_weight}")
st.write(f"HSP Weight: {hsp_weight}")
st.write(f"EEG Weight: {eeg_weight}")
st.write(f"HPI Weight: {hpi_weight}")


# fiducials = 'estimated'
# coreg = Coregistration(info=raw.info,
#                        subject=selected_subject,
#                        subjects_dir=subjects_dir,
#                        fiducials=fiducials)

# coreg.set_grow_hair(grow_hair)
# coreg.omit_head_shape_points(distance=(omit_head_shape_points / 1000))
# coreg.trans | mne.transforms.Transform
# mne.write_trans(coreg_trans_file, coreg.trans, overwrite=True)

# For TEST
import streamlit as st
import pyvista as pv
import numpy as np

st.title("3D Transformation using Streamlit and PyVista")
st.sidebar.header("Settings")

# Get user input
translation_x = st.sidebar.slider("Translation X-axis", -5.0, 5.0, 1.0)  # Translation along X-axis
translation_y = st.sidebar.slider("Translation Y-axis", -5.0, 5.0, 0.0)  # Translation along Y-axis
translation_z = st.sidebar.slider("Translation Z-axis", -5.0, 5.0, 0.0)  # Translation along Z-axis

rotation_x = st.sidebar.slider("Rotation around X-axis (°)", 0, 360, 0)  # Rotation around X-axis
rotation_y = st.sidebar.slider("Rotation around Y-axis (°)", 0, 360, 0)  # Rotation around Y-axis
rotation_z = st.sidebar.slider("Rotation around Z-axis (°)", 0, 360, 0)  # Rotation around Z-axis

# 创建基本的球体
sphere = pv.Sphere()

target_sphere = pv.Sphere(radius=1.0)

# 定义平移量和旋转角度
translation = np.array([translation_x, translation_y, translation_z])

# 自定义旋转矩阵函数
def rotation_matrix(axis, angle):
    """生成旋转矩阵"""
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
        raise ValueError("轴必须是 'x', 'y' 或 'z'")

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

# 显示齐次变换矩阵
st.write("齐次变换矩阵 (4x4):")
st.write(homogeneous_transform)

# 复制并变换球体
transformed_sphere = pv.Sphere(radius=1.0,center=(2, 3, -4.5))
transformed_sphere.rotate_z(rotation_z, inplace=True)
transformed_sphere.rotate_y(rotation_y, inplace=True)
transformed_sphere.rotate_x(rotation_x, inplace=True)
transformed_sphere.translate(translation)

# Fit ICP button with unique key
if st.button("Fit ICP", key="fit_icp_button"):
    # Use PyVista's align function to align the transformed sphere with the target sphere
    aligned, icp_matrix = transformed_sphere.align(target_sphere,return_matrix=True)

    st.write("ICP Transform Matrix:")
    st.write(icp_matrix)

    combined_transform = icp_matrix @ homogeneous_transform

    st.write("融合后的变换矩阵:")
    st.write(combined_transform)

    # Optionally, calculate distances to show how well they are aligned
    _, closest_points = aligned.find_closest_cell(target_sphere.points, return_closest_point=True)
    dist = np.linalg.norm(target_sphere.points - closest_points, axis=1)

    st.write("对齐成功！")
    st.write("距离 (最接近的点):", np.min(dist))

    dist = np.mean(dist)
    st.write("dist:",dist)

    plotter.add_mesh(aligned, color='blue', show_edges=True, label='对齐后的球体')

    # save transform matrix
    if st.button("Save Transform Matrix", key="save_button"):
        trans = mne.Transform('head', 'mri', icp_matrix)
        # mne.write_trans(selected_trans_file, trans, overwrite=True)
        mne.write_trans("demo-trans.fif", trans, overwrite=True)

    st.session_state.fit_icp_done = True
    st.session_state.aligned = aligned


# Create a PyVista plotter
plotter = pv.Plotter()
plotter.add_mesh(target_sphere, color='red', opacity=0.5, show_edges=True, label='目标球体')
if st.session_state.get("fit_icp_done", False):
    # If aligned state is stored, display it
    aligned = st.session_state.get("aligned")
    plotter.add_mesh(aligned, color='blue', show_edges=True, label='对齐后的球体')
else:
    plotter.add_mesh(transformed_sphere, color='orange', opacity=0.8 ,show_edges=True, label='变换后的球体')
plotter.add_legend()  # Show legend
plotter.add_axes()  # Show axes

# 在 Streamlit 中显示 PyVista 图像
stpyvista(plotter)



