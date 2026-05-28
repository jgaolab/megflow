import os
import numpy as np
import pandas as pd
import streamlit as st
from stpyvista import stpyvista
from stpyvista.utils import start_xvfb
import pyvista as pv
import mne

# --- 1. 环境变量 (避免 GLSL 错误、指定 DISPLAY 等) ---
os.environ["MESA_GLSL_VERSION_OVERRIDE"] = "150"
os.environ["MESA_GL_VERSION_OVERRIDE"]   = "3.2"
os.environ["DISPLAY"] = ":99"  # 无头环境中要指定

# --- 2. 启动 Xvfb (若在无头环境) ---
if "IS_XVFB_RUNNING" not in st.session_state:
    start_xvfb()
    st.session_state.IS_XVFB_RUNNING = True

# --- 3. Streamlit 页面布局 ---
st.title("MNE Source Localization Visualization + RMS Curve")
st.write("### Surface View (Left & Right Hemispheres) + RMS time series")

# --- 4. 读取脑表面数据 ---
subjects_dir = mne.datasets.sample.data_path() / "subjects"
subject = "fsaverage"
surf = "white"  # 'white' / 'pial' / 'inflated' etc.

hemispheres = ['lh', 'rh']
meshes = {}
for hemi in hemispheres:
    surface_path = subjects_dir / subject / "surf" / f"{hemi}.{surf}"
    coords, faces = mne.read_surface(surface_path)
    # PyVista 需要在 faces 前插入三角形顶点数量 (3)
    faces = np.hstack([np.full((faces.shape[0], 1), 3), faces]).astype(np.int64)
    mesh = pv.PolyData(coords, faces)
    meshes[hemi] = mesh
    st.write(f"{hemi.upper()} Hemisphere: {mesh.n_points} vertices, {mesh.n_faces} faces.")

# --- 5. 读取 SourceEstimate (分别 lh & rh) ---
stc_file_lh = mne.datasets.sample.data_path() / "MEG" / "sample" / "sample_audvis-meg-eeg-lh.stc"
stc_file_rh = mne.datasets.sample.data_path() / "MEG" / "sample" / "sample_audvis-meg-eeg-rh.stc"

stc_lh = mne.read_source_estimate(stc_file_lh, subject=subject)
stc_rh = mne.read_source_estimate(stc_file_rh, subject=subject)

# --- 6. 预先计算 RMS 时间序列 ---
# 简单示例：把左、右半球数据拼起来, 做 RMS(t) = sqrt( mean( data^2 ) ) over all vertices
# data_lh.shape = (#lh_vertices, #times)
# data_rh.shape = (#rh_vertices, #times)
all_data = np.concatenate([stc_lh.data, stc_rh.data], axis=0)  # shape=(n_lh + n_rh, n_times)
# RMS over vertices:
rms_all = np.sqrt(np.mean(all_data**2, axis=0))  # shape=(n_times, )

# 也可以只做单侧 RMS，或更复杂的ROI，但这里演示简单全脑

# --- 7. 添加滑块选择时间点 ---
time_min = float(stc_lh.times[0])
time_max = float(stc_lh.times[-1])
time_init = float(stc_lh.times[0])

time_point = st.slider(
    "选择时间点 (秒)",
    min_value=time_min,
    max_value=time_max,
    value=time_init,
    step=0.01
)

# 找到最接近 slider 的索引 (分别 lh & rh)
time_idx_lh = np.argmin(np.abs(stc_lh.times - time_point))
time_idx_rh = np.argmin(np.abs(stc_rh.times - time_point))

# 获取当前 RMS 值
rms_current = rms_all[time_idx_lh]  # lh 与 rh 时间点相同,可取 time_idx_lh

# --- 8. 映射 stc 数据到网格 (lh / rh) ---
def map_stc_to_mesh(stc, mesh, hemi):
    if hemi == 'lh':
        vertno = stc.lh_vertno
        data   = stc.data[:len(vertno), time_idx_lh]
    elif hemi == 'rh':
        vertno = stc.rh_vertno
        data   = stc.data[:len(vertno), time_idx_rh]
    else:
        raise ValueError("hemi must be 'lh' or 'rh'")

    scalars = np.zeros(mesh.n_points)
    for i, vtx_id in enumerate(vertno):
        if vtx_id < mesh.n_points:
            scalars[vtx_id] = data[i]
    return scalars

scalars_lh = map_stc_to_mesh(stc_lh, meshes['lh'], 'lh')
scalars_rh = map_stc_to_mesh(stc_rh, meshes['rh'], 'rh')
meshes['lh']["source_activation"] = scalars_lh
meshes['rh']["source_activation"] = scalars_rh

# --- 9. 管理 PyVista Plotter ---
if "plotter" not in st.session_state:
    plotter = pv.Plotter(window_size=[800, 600])
    # 左半球
    plotter.add_mesh(
        meshes['lh'],
        scalars="source_activation",
        cmap="bwr",
        clim=[np.min(scalars_lh), np.max(scalars_lh)],
        show_edges=False,
        opacity=0.8,
    )
    # 右半球
    plotter.add_mesh(
        meshes['rh'],
        scalars="source_activation",
        cmap="bwr",
        clim=[np.min(scalars_rh), np.max(scalars_rh)],
        show_edges=False,
        opacity=0.8,
    )
    # 标量条
    plotter.add_scalar_bar(
        title="Source Activation",
        label_font_size=10,
        title_font_size=12,
    )
    plotter.set_background("white")
    plotter.view_isometric()
    st.session_state.plotter = plotter
else:
    plotter = st.session_state.plotter
    # 每次更新要先清空 plotter, 再重绘
    plotter.clear()

    plotter.add_mesh(
        meshes['lh'],
        scalars="source_activation",
        cmap="bwr",
        clim=[np.min(scalars_lh), np.max(scalars_lh)],
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
    plotter.add_scalar_bar(
        title="Source Activation",
        label_font_size=10,
        title_font_size=12,
    )
    plotter.set_background("white")
    plotter.view_isometric()

stpyvista(plotter, key="brain_plot")

# --- 10. 添加“关闭 Plotter”按钮 ---
if st.button("关闭 Plotter"):
    plotter.close()
    del st.session_state.plotter
    st.success("Plotter 已关闭。请刷新页面以重新加载。")

# --- 11. 显示 RMS 曲线图 + 当前时间点 RMS 值 ---
st.write("### RMS over time")

# 用 pandas DataFrame 来画 line_chart
df_rms = pd.DataFrame({
    "time (s)": stc_lh.times,
    "RMS": rms_all
})

# 只画曲线, 不带突出当前点(简易实现)
st.line_chart(df_rms.set_index("time (s)")["RMS"])

# 在文字层面告诉用户当前 RMS 值
st.write(f"**Current time**: {time_point:.3f} s,  **RMS**: {rms_current:.4f}")
