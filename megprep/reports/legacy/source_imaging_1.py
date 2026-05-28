import os
import numpy as np
import streamlit as st
from stpyvista import stpyvista
from stpyvista.utils import start_xvfb
import pyvista as pv
import mne

# --- 1. 设置环境变量 ---
os.environ["MESA_GLSL_VERSION_OVERRIDE"] = "150"
os.environ["MESA_GL_VERSION_OVERRIDE"] = "3.2"
os.environ["DISPLAY"] = ":99"  # 如果在无头环境中，需要 Xvfb 或指定 DISPLAY

# --- 2. 启动虚拟显示（无头环境） ---
if "IS_XVFB_RUNNING" not in st.session_state:
    start_xvfb()
    st.session_state.IS_XVFB_RUNNING = True

# --- 3. Streamlit 页面布局 ---
st.title("MNE Source Localization Visualization in Streamlit")
st.write("### Surface View")

# --- 4. 读取脑表面数据 ---
subjects_dir = mne.datasets.sample.data_path() / "subjects"
subject = "fsaverage"
surf = "white"  # 可选：'white', 'pial', 'inflated'

# 读取左半球和右半球的脑表面
hemispheres = ['lh', 'rh']
meshes = {}

for hemi in hemispheres:
    surface_path = subjects_dir / subject / "surf" / f"{hemi}.{surf}"
    coords, faces = mne.read_surface(surface_path)
    # PyVista 需要 faces 数组的前面多一个多边形的顶点数量（3）
    faces = np.hstack([np.full((faces.shape[0], 1), 3), faces]).astype(np.int64)
    mesh = pv.PolyData(coords, faces)
    meshes[hemi] = mesh
    st.write(f"{hemi.upper()} Hemisphere: {mesh.n_points} vertices, {mesh.n_faces} faces.")

# --- 5. 读取 SourceEstimate 数据并映射到网格顶点 ---
# 使用 MNE 的示例数据，您可以替换为自己的 stc 对象
stc_file_lh = mne.datasets.sample.data_path() / "MEG" / "sample" / "sample_audvis-meg-eeg-lh.stc"
stc_file_rh = mne.datasets.sample.data_path() / "MEG" / "sample" / "sample_audvis-meg-eeg-rh.stc"

stc_lh = mne.read_source_estimate(stc_file_lh, subject=subject)
stc_rh = mne.read_source_estimate(stc_file_rh, subject=subject)

# --- 6. 添加滑块选择时间点 ---
min_time = float(stc_lh.times[0])
max_time = float(stc_lh.times[-1])
initial_time = float(stc_lh.times[0])

time_point = st.slider(
    "选择时间点 (秒)",
    min_value=min_time,
    max_value=max_time,
    value=initial_time,
    step=0.01
)

# 将时间点转换为最近的索引
time_index_lh = np.argmin(np.abs(stc_lh.times - time_point))
time_index_rh = np.argmin(np.abs(stc_rh.times - time_point))


# --- 7. 映射 SourceEstimate 数据到网格顶点 ---
def map_stc_to_mesh(stc, mesh, hemi):
    """
    将 SourceEstimate 数据映射到 PyVista 网格的顶点上。

    Parameters:
    - stc: SourceEstimate 对象
    - mesh: PyVista PolyData 对象
    - hemi: 'lh' 或 'rh'

    Returns:
    - scalars: 映射后的标量数组
    """
    if hemi == 'lh':
        vertno = stc.lh_vertno
        data = stc.data[:len(vertno), time_index_lh]
    elif hemi == 'rh':
        vertno = stc.rh_vertno
        data = stc.data[:len(vertno), time_index_rh]
    else:
        raise ValueError("hemi must be 'lh' or 'rh'")

    scalars = np.zeros(mesh.n_points)
    for i, vtx_id in enumerate(vertno):
        if vtx_id < mesh.n_points:
            scalars[vtx_id] = data[i]
        else:
            st.write(f"Warning: Vertex ID {vtx_id} is out of bounds for the {hemi.upper()} mesh.")
    return scalars


# 映射数据到左半球和右半球
scalars_lh = map_stc_to_mesh(stc_lh, meshes['lh'], 'lh')
scalars_rh = map_stc_to_mesh(stc_rh, meshes['rh'], 'rh')

# 将标量数据添加到网格
meshes['lh']["source_activation"] = scalars_lh
meshes['rh']["source_activation"] = scalars_rh

# --- 8. 创建或获取 Plotter 对象 ---
if "plotter" not in st.session_state:
    # 创建 Plotter 并添加左半球和右半球网格
    plotter = pv.Plotter(window_size=[800, 600])

    plotter.add_mesh(
        meshes['lh'],
        scalars="source_activation",
        cmap="bwr",  # 颜色映射表
        clim=[np.min(scalars_lh), np.max(scalars_lh)],  # 颜色映射范围
        show_edges=False,
        opacity=0.8,
    )

    plotter.add_mesh(
        meshes['rh'],
        scalars="source_activation",
        cmap="bwr",
        clim=[np.min(scalars_rh), np.max(scalars_rh)],
        show_edges=False,
        opacity=0.8,
    )

    # 添加标量条
    plotter.add_scalar_bar(
        title="Source Activation",
        label_font_size=10,
        title_font_size=12,
    )

    # 设置背景颜色
    plotter.set_background("white")

    # 设置视角
    plotter.view_isometric()

    # 存储 Plotter 到 Session State
    st.session_state.plotter = plotter
else:
    # 获取已存在的 Plotter
    plotter = st.session_state.plotter

    # 更新标量数据
    plotter.clear()

    # 重新添加左半球网格
    plotter.add_mesh(
        meshes['lh'],
        scalars="source_activation",
        cmap="bwr",
        clim=[np.min(scalars_lh), np.max(scalars_lh)],
        show_edges=False,
        opacity=0.8,
    )

    # 重新添加右半球网格
    plotter.add_mesh(
        meshes['rh'],
        scalars="source_activation",
        cmap="bwr",
        clim=[np.min(scalars_rh), np.max(scalars_rh)],
        show_edges=False,
        opacity=0.8,
    )

    # 重新添加标量条
    plotter.add_scalar_bar(
        title="Source Activation",
        label_font_size=10,
        title_font_size=12,
    )

    # 设置背景颜色
    plotter.set_background("white")

    # 设置视角
    plotter.view_isometric()

# --- 9. 在 Streamlit 中渲染 Plotter ---
stpyvista(plotter, key="brain_plot")

# --- 10. 添加“关闭 Plotter”按钮 ---
if st.button("关闭 Plotter"):
    plotter.close()
    del st.session_state.plotter
    st.success("Plotter 已关闭。请刷新页面以重新加载。")
