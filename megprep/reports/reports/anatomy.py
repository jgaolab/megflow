import streamlit as st
import nibabel as nib
import os
import numpy as np
from surfer import Brain
from stpyvista import stpyvista
from stpyvista.utils import start_xvfb

# --- 1. 设置环境变量 (在无头环境中避免 GLSL 错误) ---
os.environ["MESA_GLSL_VERSION_OVERRIDE"] = "150"
os.environ["MESA_GL_VERSION_OVERRIDE"] = "3.2"

# 如果在无头环境，需要指定 DISPLAY
os.environ["DISPLAY"] = ":99"

# --- 2. 启动虚拟显示 (Xvfb) ---
if "IS_XVFB_RUNNING" not in st.session_state:
    start_xvfb()
    st.session_state.IS_XVFB_RUNNING = True

# --- 1. 设置 FreeSurfer 数据目录 ---
FS_SURF_DIR = "/data/liaopan/datasets/Holmes_cn/smri/sub-001/surf"

# Define paths to the surface files
lh_white_path = os.path.join(FS_SURF_DIR, "lh.white")
rh_white_path = os.path.join(FS_SURF_DIR, "rh.white")
lh_pial_path = os.path.join(FS_SURF_DIR, "lh.pial")
rh_pial_path = os.path.join(FS_SURF_DIR, "rh.pial")

# --- 2. Streamlit Page Setup ---
st.title("Interactive Visualization of FreeSurfer Recon-all Results with PySurfer")
st.write("This application loads FreeSurfer surface files and visualizes them interactively using `pysurfer`.")

# --- 3. Check if all required surface files exist ---
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

# --- 4. Sidebar for User Selections ---
st.sidebar.header("Select Surfaces to Display")
show_white = st.sidebar.checkbox("Display White Matter Surface (white)", value=True)
show_pial = st.sidebar.checkbox("Display Pial Surface (pial)", value=False)

# --- 5. Display Brain Visualization using PySurfer ---
st.write("Generating 3D brain visualization...")

# Load FreeSurfer data using `Brain` from pysurfer
brain = Brain("fsaverage",
              hemi="both",
              surf="inflated",
              subjects_dir=FS_SURF_DIR,
              title="FreeSurfer Brain Visualization")

# Show the selected surfaces
if show_white:
    brain.add_surface("lh.white", color="blue", opacity=0.5)
    brain.add_surface("rh.white", color="red", opacity=0.5)

if show_pial:
    brain.add_surface("lh.pial", color="green", opacity=0.5)
    brain.add_surface("rh.pial", color="yellow", opacity=0.5)

st.success("3D brain visualization displayed successfully.")
