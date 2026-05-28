# !/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import mne
import streamlit as st
import pandas as pd
import ast  # 用于解析文本中的列表
from pathlib import Path
from reports.utils import in_docker,filter_files_by_keyword

mne.viz.set_browser_backend('matplotlib')

# ===== 自定义样式 =====
st.markdown("""
<style>
    /* 全局样式 */
    .main {
        padding-top: 2rem;
    }
    
    /* Main header styling */
    .main-header {
        # background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 20px;
        border-radius: 15px;
        text-align: center;
        font-weight: 700;
        # box-shadow: 0 8px 16px rgba(102, 126, 234, 0.3);
        margin-bottom: 30px;
        # animation: fadeInDown 0.6s ease-out;
    }

    /* 卡片样式 */
    .stImage {
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        transition: transform 0.3s ease;
    }

    .stImage:hover {
        transform: scale(1.02);
    }

    /* 侧边栏样式 */
    .css-1d391kg, [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #f8f9fa 0%, #e9ecef 100%);
    }

    /* 数据框样式 */
    .dataframe {
        border-radius: 8px;
        overflow: hidden;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.08);
    }

    /* 警告和成功消息样式 */
    .stAlert {
        border-radius: 8px;
        padding: 1rem;
        margin: 1rem 0;
    }

    /* 图表容器 */
    .plot-container {
        background: white;
        padding: 1.5rem;
        border-radius: 10px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        margin: 1rem 0;
    }

    /* 统计卡片 */
    .stat-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 1.5rem;
        border-radius: 10px;
        text-align: center;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        margin: 0.5rem 0;
    }

    .stat-value {
        font-size: 2rem;
        font-weight: 700;
        margin: 0.5rem 0;
    }

    .stat-label {
        font-size: 0.9rem;
        opacity: 0.9;
    }

    /* 分隔线 */
    .divider {
        height: 2px;
        background: linear-gradient(90deg, transparent, #1f77b4, transparent);
        margin: 2rem 0;
    }

    /* 按钮样式优化 */
    .stButton>button {
        border-radius: 8px;
        padding: 0.5rem 2rem;
        font-weight: 600;
        transition: all 0.3s ease;
    }

    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
    }
    

</style>
""", unsafe_allow_html=True)

# 设置页面标题
st.markdown('<h2 class="main-header">🧠 MEG Epochs Viewer</h2>', unsafe_allow_html=True)
# 文件路径
if in_docker():
    report_root_dir = Path("/output")
else:
    report_root_dir = Path(st.session_state.get("dataset_report_path"))

DEFAULT_EPOCHS_DIR = report_root_dir / "preprocessed" / "epochs"

# 侧边栏配置
with st.sidebar:
    # Sidebar styling
    st.sidebar.markdown("""
        <div style='text-align: center; padding: 0px;'>
            <h2 >⚙️ Settings</h2>
        </div>
    """, unsafe_allow_html=True)
    epochs_base_path = Path(st.text_input(
        "Epochs Report Directory:",
        value=DEFAULT_EPOCHS_DIR
    ))

subjects_epochs_dirs = sorted([f for f in os.listdir(epochs_base_path)])

if not subjects_epochs_dirs:
    st.warning("⚠️ No epochs found in the data directory. Please change the data directory.")
else:
    with st.sidebar:
        st.markdown("---")
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
        filtered_epochs_dirs = filter_files_by_keyword(subjects_epochs_dirs, filter_keyword)

        selected_dir = st.selectbox("📁 Select a directory:", filtered_epochs_dirs)
        st.markdown("---")

    print("selected directory: ", selected_dir)

    reject_log_file = epochs_base_path / selected_dir / f"{selected_dir}_preproc-raw_clean_raw_reject_epoch_log.txt"
    epoch_file = epochs_base_path / selected_dir / f"{selected_dir}_preproc-raw_clean_raw-epo.fif"
    epochs = mne.read_epochs(epoch_file, preload=True)

    # Epochs Visualization
    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    st.subheader("Epochs Visualization")
    with st.container():
        fig_epochs = epochs.plot(show_scrollbars=False)
        st.pyplot(fig_epochs)

    # Plot Event Related Potential / Fields image
    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    st.subheader("Epochs ERF Visualization")
    with st.container():
        fig_erf = epochs.plot_image(picks='meg', combine="mean")
        col1, col2 = st.columns(2)
        with col1:
            st.pyplot(fig_erf[0])
        with col2:
            st.pyplot(fig_erf[1])

    # Evoked Visualization
    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    st.subheader("Evoked Visualization")
    with st.container():
        fig_evoked = epochs.average().plot()
        st.pyplot(fig_evoked)

    # PNG 文件路径
    png_files = [
        f"{selected_dir}_preproc-raw_clean_raw_epoch_onset_psd.png",
        f"{selected_dir}_preproc-raw_clean_raw_epoch_onset_topo_mag.png",

        f"{selected_dir}_preproc-raw_clean_raw_epoch_onset_sensors_2d.png",
        f"{selected_dir}_preproc-raw_clean_raw_epoch_onset_sensors_3d.png",
    ]

    # 展示 PNG 图片
    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    st.subheader("Visualization Epochs")

    # 使用两列布局展示图片
    cols = st.columns(2)
    for idx, png_file in enumerate(png_files):
        png_path = epochs_base_path / selected_dir / png_file
        with cols[idx % 2]:
            if png_path.exists():
                st.image(str(png_path), caption=png_file, width='stretch')
            else:
                st.warning(f"⚠️ File not found: {png_file}")

    # 读取 rejected epochs
    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    print("reject_log_file,", reject_log_file)
    if reject_log_file.exists():
        with open(reject_log_file, "r") as f:
            log_content = f.readlines()

        try:
            rejected_epochs = ast.literal_eval(log_content[0].strip())
            num_epochs = int(log_content[1].split(":")[-1].strip())
            if isinstance(rejected_epochs, list) and rejected_epochs:
                # 展示原始内容
                st.subheader("🚫 Epochs Reject Log")

                # 转换为 Pandas DataFrame
                df = pd.DataFrame(rejected_epochs, columns=["Rejected Epochs"])

                # 分页配置
                with st.sidebar:
                    st.markdown("### 📄 Pagination Settings")
                    page_size = st.slider("Set Page Size:", min_value=10, max_value=50, value=20)

                page_number = st.number_input(
                    "Select Page Number:",
                    min_value=1,
                    max_value=(len(df) // page_size) + 1,
                    value=1,
                    step=1,
                )

                start_index = (page_number - 1) * page_size
                end_index = start_index + page_size
                st.dataframe(df.iloc[start_index:end_index], width='stretch')

                # 数据分析
                st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
                st.subheader("📊 Statistics and Insights")

                # 使用三列布局展示统计信息
                col1, col2, col3 = st.columns(3)

                with col1:
                    st.markdown(f"""
                    <div class="stat-card">
                        <div class="stat-label">Total Rejected</div>
                        <div class="stat-value">{len(rejected_epochs)}</div>
                    </div>
                    """, unsafe_allow_html=True)

                with col2:
                    st.markdown(f"""
                    <div class="stat-card">
                        <div class="stat-label">Min Epoch</div>
                        <div class="stat-value">{min(rejected_epochs)}</div>
                    </div>
                    """, unsafe_allow_html=True)

                with col3:
                    st.markdown(f"""
                    <div class="stat-card">
                        <div class="stat-label">Max Epoch</div>
                        <div class="stat-value">{max(rejected_epochs)}</div>
                    </div>
                    """, unsafe_allow_html=True)

                # 可视化分布
                st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
                st.subheader("📉 Visualization of Rejected Epochs")
                full_range = pd.DataFrame({"Epoch": range(0, num_epochs + 1)})
                rejected_counts = df["Rejected Epochs"].value_counts().reset_index()
                rejected_counts.columns = ["Epoch", "Frequency"]
                full_df = full_range.merge(rejected_counts, on="Epoch", how="left").fillna(0)

                # 转换 Frequency 列为整数
                full_df["Frequency"] = full_df["Frequency"].astype(int)

                # 展示条形图
                st.bar_chart(full_df.set_index("Epoch")["Frequency"])

                # 搜索功能
                st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
                st.subheader("🔍 Search Specific Epoch")
                search_value = st.number_input(
                    "Search for an epoch:",
                    min_value=min(rejected_epochs),
                    max_value=max(rejected_epochs),
                    value=min(rejected_epochs)
                )
                if search_value in rejected_epochs:
                    st.success(f"✅ Epoch {search_value} is rejected.")
                else:
                    st.warning(f"ℹ️ Epoch {search_value} is not in the rejected list.")
            else:
                st.warning("⚠️ The log content is not a valid list.")
        except Exception as e:
            st.error(f"❌ Error parsing log content: {e}")
    else:
        st.warning(f"⚠️ Reject log file not found at {reject_log_file}.")
