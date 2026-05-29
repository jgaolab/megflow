import streamlit as st
import nibabel as nib
import pyvista as pv
import os
import numpy as np
from pathlib import Path
from stpyvista import stpyvista
from stpyvista.utils import start_xvfb
from reports.utils import in_docker

# --- 1. 设置环境变量 (在无头环境中避免 GLSL 错误) ---
os.environ['PYVISTA_PLOT_THEME'] = 'document'
os.environ['PYVISTA_USE_PANEL'] = 'False'
os.environ["MESA_GLSL_VERSION_OVERRIDE"] = "150"
os.environ["MESA_GL_VERSION_OVERRIDE"] = "3.2"
os.environ['VTK_OFFSCREEN_RENDERING'] = '1'

# 如果在无头环境，需要指定 DISPLAY
os.environ["DISPLAY"] = ":99"

# --- 2. 启动虚拟显示 (Xvfb) ---
if "IS_XVFB_RUNNING" not in st.session_state:
    start_xvfb()
    st.session_state.IS_XVFB_RUNNING = True



# -----------------------------------------------
# 1. Set the default FreeSurfer results directory
#    (Ensure the path exists and contains the necessary surface files)
# -----------------------------------------------
if in_docker():
    report_root_dir = Path("/output")
    default_subjects_dir = Path("/smri")
else:
    report_root_dir = Path(st.session_state.get("dataset_report_path"))
    default_subjects_dir = Path(st.session_state.get("subjects_dir"))
    default_subjects_dir = '/data/liaopan/datasets/Holmes_cn/smri/' # only test

subjects_dir = st.sidebar.text_input("Freesurfer SUBJECTS_DIR", default_subjects_dir)
# Get available subjects
if os.path.exists(subjects_dir):
    # subjects = sorted([f for f in os.listdir(subjects_dir) if os.path.isdir(os.path.join(subjects_dir, f))])
    subjects = sorted([
        f for f in os.listdir(subjects_dir)
        if os.path.isdir(os.path.join(subjects_dir, f)) and not f.startswith('fsaverage')
    ])
    selected_subject = st.sidebar.selectbox("Select Subject", subjects)
    FS_SURF_DIR = Path(subjects_dir, selected_subject,"surf")
else:
    st.sidebar.warning(f"No valid SUBJECTS_DIR found at: {subjects_dir}")
    selected_subject = None

# only test
# FS_SURF_DIR = "/data/liaopan/datasets/Holmes_cn/smri/sub-001/surf"

# Define paths to the surface files
lh_white_path = os.path.join(FS_SURF_DIR, "lh.white")
rh_white_path = os.path.join(FS_SURF_DIR, "rh.white")
lh_pial_path = os.path.join(FS_SURF_DIR, "lh.pial")
rh_pial_path = os.path.join(FS_SURF_DIR, "rh.pial")

# -----------------------------------------------
# 2. Streamlit Page Setup
# -----------------------------------------------
st.title("Interactive Visualization of FreeSurfer Recon-all Results")
# st.write("This application loads FreeSurfer surface files from a default directory and visualizes them.")

# -----------------------------------------------
# 3. Check if all required surface files exist
# -----------------------------------------------
required_files = {
    "Left White Matter (lh.white)": lh_white_path,
    "Right White Matter (rh.white)": rh_white_path,
    "Left Pial Surface (lh.pial)": lh_pial_path,
    "Right Pial Surface (rh.pial)": rh_pial_path,
}

missing_files = [name for name, path in required_files.items() if not os.path.exists(path)]

if missing_files:
    st.error(f"The following FreeSurfer surface files are missing: {', '.join(missing_files)}. Please check the `FS_SURF_DIR` path.")
    st.stop()
else:
    st.success("All required FreeSurfer surface files have been found.")

# -----------------------------------------------
# 4. Load FreeSurfer Surface Data
# -----------------------------------------------
# st.write("Loading FreeSurfer surface data... Please wait.")

try:
    # Load each surface using nibabel
    lh_white_vertices, lh_white_faces = nib.freesurfer.read_geometry(lh_white_path)
    rh_white_vertices, rh_white_faces = nib.freesurfer.read_geometry(rh_white_path)
    lh_pial_vertices, lh_pial_faces = nib.freesurfer.read_geometry(lh_pial_path)
    rh_pial_vertices, rh_pial_faces = nib.freesurfer.read_geometry(rh_pial_path)
except Exception as e:
    st.error(f"An error occurred while reading FreeSurfer surface files: {e}")
    st.stop()

st.success("Successfully loaded FreeSurfer surface data.")

# -----------------------------------------------
# 5. Sidebar for User Selections
# -----------------------------------------------
st.sidebar.header("Select Surfaces to Display")
show_white = st.sidebar.checkbox("Display White Matter Surface (white)", value=True)
show_pial = st.sidebar.checkbox("Display Pial Surface (pial)", value=False)
pial_opacity = st.sidebar.slider("Pial Opacity", min_value=0.0, max_value=1.0, value=0.8, step=0.1)
white_opacity = st.sidebar.slider("White Opacity", min_value=0.0, max_value=1.0, value=1.0, step=0.1)

# -----------------------------------------------
# 6. Function to Merge Multiple Surfaces
# -----------------------------------------------
def merge_surfaces(vertices_list, faces_list):
    """
    Merge multiple surfaces into a single PyVista mesh.
    """
    meshes = []
    for vertices, faces in zip(vertices_list, faces_list):
        faces_pv = faces.copy()
        faces_pv = faces_pv.flatten()
        faces_pv = faces_pv.reshape(-1, 3)
        faces_pv = np.hstack([np.full((faces_pv.shape[0], 1), 3), faces_pv]).flatten()
        mesh = pv.PolyData(vertices, faces_pv)
        meshes.append(mesh)

    if not meshes:
        return None

    merged = meshes[0]
    for mesh in meshes[1:]:
        merged = merged.merge(mesh)

    return merged

# -----------------------------------------------
# 7. Display 3D Brain Visualization
# -----------------------------------------------
# st.write("Generating 3D brain visualization...")

left_vertices = []
left_faces = []
right_vertices = []
right_faces = []

if show_white:
    left_vertices.append(lh_white_vertices)
    left_faces.append(lh_white_faces)
    right_vertices.append(rh_white_vertices)
    right_faces.append(rh_white_faces)

white_left_merged = merge_surfaces(left_vertices, left_faces)
white_right_merged = merge_surfaces(right_vertices, right_faces)

if show_pial:
    left_vertices.append(lh_pial_vertices)
    left_faces.append(lh_pial_faces)
    right_vertices.append(rh_pial_vertices)
    right_faces.append(rh_pial_faces)

pial_left_merged = merge_surfaces(left_vertices, left_faces)
pial_right_merged = merge_surfaces(right_vertices, right_faces)

if pial_left_merged is None or pial_right_merged is None:
    st.error("No surfaces(pial) selected for display.")
elif white_left_merged is None or white_right_merged is None:
    st.error("No surfaces(white) selected for display.")
else:
    # Create a PyVista plotter
    plotter = pv.Plotter()

    # Add the left and right hemisphere meshes
    if show_white:
        plotter.add_mesh(white_left_merged, color="gray", opacity=white_opacity)
        plotter.add_mesh(white_right_merged, color="gray", opacity=white_opacity)
    if show_pial:
        plotter.add_mesh(pial_left_merged, color="green", opacity=pial_opacity)
        plotter.add_mesh(pial_right_merged, color="yellow", opacity=pial_opacity)

    # Customize the view
    plotter.view_isometric()

    # Display the plot with Streamlit
    stpyvista(plotter, key="brain_plot")
    # st.success("3D brain visualization displayed successfully.")
