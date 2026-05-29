import os
import numpy as np
import nibabel as nib
from brainspace.vtk_interface.wrappers.data_object import BSPolyData
from brainspace.plotting import plot_hemispheres
import streamlit as st


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


# --- 1. 配置 FreeSurfer 数据目录 ---
FS_SURF_DIR = "/data/liaopan/datasets/Holmes_cn/smri/sub-001/surf"
subject_id = "sub-001"

# --- 2. 加载 FreeSurfer 表面数据 ---
lh_white_path = os.path.join(FS_SURF_DIR, "lh.white")
rh_white_path = os.path.join(FS_SURF_DIR, "rh.white")

print("lh_white_path", lh_white_path)
print("rh_white_path", rh_white_path)

# 使用 nibabel 加载 FreeSurfer 数据
lh_vertices, lh_faces = nib.freesurfer.read_geometry(lh_white_path)
rh_vertices, rh_faces = nib.freesurfer.read_geometry(rh_white_path)

# --- 3. 创建 BSPolyData 对象 ---
surf_lh = BSPolyData()
surf_lh.SetPoints(lh_vertices)
surf_lh.SetPolys(lh_faces)

surf_rh = BSPolyData()
surf_rh.SetPoints(rh_vertices)
surf_rh.SetPolys(rh_faces)

# --- 4. 加载指标数据 ---
data_lh = np.random.rand(len(lh_vertices))  # 左半球数据
data_rh = np.random.rand(len(rh_vertices))  # 右半球数据

# 将数据附加到对应的半球表面
surf_lh.append_array(data_lh, name='array_name')
surf_rh.append_array(data_rh, name='array_name')

# --- 5. 使用 BrainSpace 进行绘图 ---
# 注意，这里删除了 `hemi='both'`，因为 BrainSpace 会根据提供的 `surf_lh` 和 `surf_rh` 自动识别
fig, _ = plot_hemispheres(
    surf_lh=surf_lh,
    surf_rh=surf_rh,
    array_name='array_name',
)

# --- 6. 保存图像 ---
screenshot_path = 'screenshot.png'
fig.savefig(screenshot_path)

print('Saving screenshot to {}'.format(screenshot_path))

# --- 7. 在 Streamlit 中显示截图 ---
st.image(screenshot_path, caption="BrainSpace Screenshot", use_column_width=True)

st.write("Below is the 2D projection generated using BrainSpace. It visualizes brain region data.")
