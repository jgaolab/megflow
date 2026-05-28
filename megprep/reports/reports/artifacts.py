#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import base64
import os
import time
from io import BytesIO
from pathlib import Path

import joblib as jl
import mne
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from PIL import Image
from streamlit_shortcuts import add_shortcuts
from reports.utils import filter_files_by_keyword
from reports.utils import in_docker

mne.viz.set_browser_backend("matplotlib")

# set report root dir.
# Determine report directory
if in_docker():
    report_root_dir = Path("/output")
else:
    report_root_dir = Path(st.session_state.get("dataset_report_path"))

DATA_DIR = os.path.join(report_root_dir, "preprocessed","artifact_report")

CONFIG = {
    "CHANNELS_PER_VIEW": 30,
    "TIME_PER_PLOT": 60,
    "DEFAULT_FREQ_RANGE": (1, 100),
    "WAVEFORM_HEIGHT": 950,
    "CHANNEL_WIDTH_RATIO": 0.12,
    "TIME_OVERVIEW_PLOT": 200,
    "OVERVIEW_WAVEFORM_HEIGHT": 400,
}

add_shortcuts(ch_prev="w", art_prev="a", art_next="d", ch_next="s")


def load_bad_segments(bad_segments_file):
    """Load bad segments from file and return annotations"""
    annotations = None
    if os.path.exists(bad_segments_file):
        annotations = mne.read_annotations(bad_segments_file)
    return annotations


def get_plot_path(plot_dir, onset_time, channel_group=0, plot_type="waveform"):
    plots_dir = Path(plot_dir) / plot_type / f"chn.{channel_group}"

    if plot_type == "waveform":
        filename = f"seg_{onset_time:.3f}.jpg"
    elif plot_type == "overview":
        filename = f"seg_{onset_time:.3f}.jpg"
    else:
        return None
    filepath = plots_dir / filename
    return filepath if filepath.exists() else None


def get_available_onsets(check_plots_dir):
    """获取可用的onset时间点列表"""
    plots_dir = Path(check_plots_dir) / "chn.0"
    if not plots_dir.exists():
        return []
    onsets = set()
    for img_file in plots_dir.glob("seg_*.jpg"):
        try:
            parts = img_file.stem.split("_")
            onset = float(parts[1])
            onsets.add(onset)
        except (ValueError, IndexError):
            continue

    return sorted(list(onsets))


def get_channel_groups_for_onset(plots_dir, onset_time):
    """获取某个onset时间点的可用通道组数量"""

    if not plots_dir.exists():
        return 0

    ch_groups = set()
    for chn_dir in plots_dir.glob("chn.*"):
        try:
            parts = chn_dir.name.split(".")
            ch_group = int(parts[1])
            ch_groups.add(ch_group)
        except (ValueError, IndexError):
            continue

    return len(ch_groups)


def image_to_base64(image_path):
    """将图片转换为base64编码"""
    img = Image.open(image_path)
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    return f"data:image/png;base64,{img_str}"


def get_current_channels(chn_jl, chn_group_id):
    """根据通道组名id来获取通道列表"""
    chn_info = jl.load(chn_jl)
    return chn_info[chn_group_id]


def get_info_dict(chn_jl, query_key):
    """通过关键词来获取raw info相关信息"""
    chn_info = jl.load(chn_jl)
    return chn_info.get(query_key, None)


def create_interactive_waveform_with_channels(
    image_path,
    onset_time,
    duration,
    bad_segments_list,
    first_time,
    channel_names,
    bad_channels,
    channels_to_toggle,
    segments_to_delete=None,
    drag_mode="pan",
):
    """
    创建带通道名标签的交互式波形图

    Parameters:
    -----------
    image_path : Path
        波形图图片路径
    onset_time : float
        当前显示的起始时间（相对时间）
    duration : float
        显示的时间长度
    bad_segments_list : list
        坏段列表 [(onset, duration, description), ...]
    first_time : float
        数据起始时间（绝对时间）
    channel_names : list
        当前显示的通道名列表
    bad_channels : list
        坏通道列表
    channels_to_toggle : set
        标记为切换的通道集合
    segments_to_delete : set
        标记为删除的坏段索引集合
    drag_mode : str
        交互模式：'pan' 或 'select'

    Returns:
    --------
    plotly.graph_objects.Figure
    """
    if segments_to_delete is None:
        segments_to_delete = set()

    # 读取图片尺寸
    img = Image.open(image_path)
    img_width, img_height = img.size

    # 创建图形
    fig = go.Figure()

    # ========== 计算真实坐标范围 ==========
    channel_width = duration * CONFIG["CHANNEL_WIDTH_RATIO"] / (1 - CONFIG["CHANNEL_WIDTH_RATIO"])
    x_min = onset_time - channel_width  # 通道区域在 onset_time 左侧
    x_max = onset_time + duration  # 波形区域到 onset_time + duration

    n_channels = len(channel_names)
    y_positions = np.linspace(0.98, 0.02, n_channels)

    # ========== 1. 添加通道区域背景 ==========
    fig.add_shape(
        type="rect",
        x0=x_min,
        x1=onset_time,
        y0=0,
        y1=1,
        fillcolor="rgba(245,245,245,0.95)",
        line=dict(width=0),
        layer="below",
    )

    # ========== 2. 创建通道按钮（作为单个 scatter trace） ==========
    channel_x = []
    channel_y = []
    channel_colors = []
    channel_sizes = []
    channel_symbols = []
    channel_texts = []
    channel_hovertexts = []
    channel_customdata = []

    for i, (ch_name, y_pos) in enumerate(zip(channel_names, y_positions)):
        # 判断通道状态
        is_bad = ch_name in bad_channels
        is_toggled = ch_name in channels_to_toggle

        # 通道按钮中心位置（相对于 onset_time）
        ch_x_center = onset_time - channel_width / 2

        # 确定显示样式
        if is_toggled:
            if is_bad:
                # 坏通道 → 待恢复为好通道
                marker_color = "rgb(135, 206, 250)"
                text_label = f"✓ {ch_name}"
                hover_text = f"<b>{ch_name}</b><br>BAD → GOOD<br><i>Click to cancel</i>"
                marker_symbol = "circle"
                bg_color = "rgba(135, 206, 250, 0.7)"
            else:
                # 好通道 → 待标记为坏通道
                marker_color = "rgb(255, 105, 180)"
                text_label = f"⚠ {ch_name}"
                hover_text = f"<b>{ch_name}</b><br>GOOD → BAD<br><i>Click to cancel</i>"
                marker_symbol = "x"
                bg_color = "rgba(255, 105, 180, 0.7)"
        else:
            if is_bad:
                # 坏通道
                marker_color = "rgb(220, 20, 60)"
                text_label = f"✗ {ch_name}"
                hover_text = f"<b>{ch_name}</b><br><b>BAD CHANNEL</b><br><i>Click to mark as good</i>"
                marker_symbol = "x"
                bg_color = "rgba(220, 20, 60, 0.8)"
            else:
                # 好通道
                marker_color = "rgb(70, 130, 180)"
                text_label = f"{ch_name}"
                hover_text = f"<b>{ch_name}</b><br><b>GOOD CHANNEL</b><br><i>Click to mark as bad</i>"
                marker_symbol = "circle"
                bg_color = "rgba(240, 248, 255, 0.7)"

        # 添加通道背景框（相对于 onset_time）
        ch_y_size = 0.018
        fig.add_shape(
            type="rect",
            x0=onset_time - channel_width * 0.95,
            x1=onset_time - channel_width * 0.05,
            y0=y_pos - ch_y_size,
            y1=y_pos + ch_y_size,
            fillcolor=bg_color,
            line=dict(color=marker_color, width=2),
            layer="below",
        )

        # 收集数据
        channel_x.append(ch_x_center)
        channel_y.append(y_pos)
        channel_colors.append(marker_color)
        channel_sizes.append(50)
        channel_symbols.append(marker_symbol)
        channel_texts.append(text_label)
        channel_hovertexts.append(hover_text)

        # customdata: [channel_name, 'channel']
        channel_customdata.append([ch_name, "channel"])

    # 创建单个 scatter trace 包含所有通道按钮
    fig.add_trace(
        go.Scatter(
            x=channel_x,
            y=channel_y,
            mode="markers+text",
            marker=dict(
                size=channel_sizes, color=channel_colors, symbol=channel_symbols, opacity=0.01, line=dict(width=0)
            ),
            text=channel_texts,
            textposition="middle center",
            textfont=dict(size=11, color="black", family="Courier New, monospace"),
            hovertext=channel_hovertexts,
            hoverinfo="text",
            customdata=channel_customdata,
            showlegend=False,
            name="channels",
        )
    )

    # ========== 3. 添加分隔线 ==========
    fig.add_vline(x=onset_time, line_width=3, line_dash="solid", line_color="rgba(100,100,100,0.6)", opacity=0.8)

    # ========== 4. 添加波形图片 ==========
    img_base64 = image_to_base64(image_path)
    fig.add_layout_image(
        dict(
            source=img_base64,
            xref="x",
            yref="y",
            x=onset_time,
            y=1,
            sizex=duration,
            sizey=1,
            sizing="stretch",
            opacity=1.0,
            layer="below",
        )
    )

    # ========== 5. 添加坏段标记 ==========
    segment_x = []
    segment_y = []
    segment_colors = []
    segment_sizes = []
    segment_symbols = []
    segment_hovertexts = []
    segment_customdata = []

    for idx, (seg_onset, seg_duration, seg_desc) in enumerate(bad_segments_list):
        seg_onset_rel = seg_onset - first_time

        # 判断坏段是否在当前显示范围内
        if seg_onset_rel < onset_time + duration and seg_onset_rel + seg_duration > onset_time:
            display_start = max(seg_onset_rel, onset_time)
            display_end = min(seg_onset_rel + seg_duration, onset_time + duration)

            # 判断是否标记为删除
            is_marked = idx in segments_to_delete

            if is_marked:
                fill_color = "rgba(255, 0, 0, 0.3)"
                line_color = "red"
                line_dash = "dash"
                marker_color = "red"
                marker_symbol = "x"
                marker_size = 20
                hover_text = f"<b>Segment #{idx}</b><br>⟲ Click to RESTORE<br>Time: {seg_onset_rel:.3f}s<br>Duration: {seg_duration:.3f}s"
                label_text = "✗ DELETE"
            else:
                fill_color = "rgba(255, 255, 0, 0.25)"
                line_color = "orange"
                line_dash = "solid"
                marker_color = "orange"
                marker_symbol = "circle"
                marker_size = 18
                hover_text = f"<b>Segment #{idx}</b><br>🗑️ Click to DELETE<br>Time: {seg_onset_rel:.3f}s<br>Duration: {seg_duration:.3f}s<br>Type: {seg_desc}"
                label_text = f"BAD #{idx}"

            # 添加矩形框
            fig.add_vrect(
                x0=display_start,
                x1=display_end,
                fillcolor=fill_color,
                layer="above",
                line_width=2,
                line_color=line_color,
                line_dash=line_dash,
            )

            # 收集数据
            mid_point = (display_start + display_end) / 2
            segment_x.append(mid_point)
            segment_y.append(0.96)
            segment_colors.append(marker_color)
            segment_sizes.append(marker_size)
            segment_symbols.append(marker_symbol)
            segment_hovertexts.append(hover_text)

            # customdata: [segment_index, 'segment']
            segment_customdata.append([idx, "segment"])

            # 添加标签
            fig.add_annotation(
                x=display_start + 1,
                y=0.98,
                text=f"<b>{label_text}</b>",
                showarrow=False,
                font=dict(size=10, color="white"),
                bgcolor=marker_color,
                bordercolor="white",
                borderwidth=1,
                borderpad=4,
            )

    # 添加坏段 scatter trace
    if segment_x:
        fig.add_trace(
            go.Scatter(
                x=segment_x,
                y=segment_y,
                mode="markers",
                marker=dict(
                    size=segment_sizes, color=segment_colors, symbol=segment_symbols, line=dict(width=2, color="white")
                ),
                hovertext=segment_hovertexts,
                hoverinfo="text",
                customdata=segment_customdata,
                showlegend=False,
                name="segments",
            )
        )

    # ========== 6. 添加框选辅助 trace ==========
    fig.add_trace(
        go.Scatter(
            x=[onset_time, onset_time + duration],
            y=[0.5, 0.5],
            mode="markers",
            marker=dict(size=1, opacity=0),
            hoverinfo="skip",
            showlegend=False,
            name="selection_helper",
        )
    )

    # ========== 布局设置 ==========
    if drag_mode == "pan":
        mode_hint = "Click MODE | 🎯 Click channels & segments | 🖱️ Drag to navigate"
    else:
        mode_hint = "SELECT MODE | 🖱️ Drag horizontally to mark bad segments"

    fig.update_layout(
        # title=dict(
        #     text=f"<b>MEG Waveform</b> (Time: {onset_time:.3f} - {onset_time + duration:.3f}s)<br>"
        #          f"<sub>{mode_hint}</sub>",
        #     font=dict(size=14),
        #     x=0.5,
        #     xanchor='center'
        # ),
        xaxis=dict(
            range=[x_min, x_max],
            title="Time (s)",
            showgrid=True,
            gridcolor="rgba(200,200,200,0.3)",
            zeroline=True,
            zerolinewidth=2,
            zerolinecolor="rgba(128,128,128,0.5)",
            tickmode="auto",
            nticks=10,
        ),
        yaxis=dict(range=[0, 1], showticklabels=False, showgrid=False, zeroline=False),
        height=CONFIG["WAVEFORM_HEIGHT"],
        dragmode=drag_mode,
        selectdirection="h",
        hovermode="closest",
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(l=10, r=30, t=80, b=50),
        clickmode="event+select",
    )

    return fig


def get_file_color(file_path):
    return "lightgrey" if file_path in processed_files else "white"


# ========== PAGE TITLE ==========
st.markdown('<h2 class="main-header">🧠 MEG Artifacts (FastView)</h2>', unsafe_allow_html=True)

# Check directories
if not os.path.exists(DATA_DIR):
    st.error(f"⚠️ Data directory not found: {DATA_DIR}")
    st.stop()


# ========== SIDEBAR ==========
with st.sidebar:
    st.sidebar.markdown(
        """
        <div style='text-align: center;'>
            <h2>⚙️ Settings</h2>
        </div>
    """,
        unsafe_allow_html=True,
    )
    st.header("📁 File Selection")

    subdirectories = sorted([
        d for d in os.listdir(DATA_DIR)
        if os.path.isdir(os.path.join(DATA_DIR, d))
    ])
    selected_dir = st.sidebar.selectbox("Select Dataset:", options=subdirectories, index=0)
    full_path = os.path.join(DATA_DIR, selected_dir)
    check_plot_dataset_dir = os.path.join(DATA_DIR, selected_dir)

    if not os.path.exists(check_plot_dataset_dir):
        st.error(f"⚠️ Check Plot directory not found: {check_plot_dataset_dir}")
        st.stop()

    processed_files_file = Path(DATA_DIR) / "processed_files.jl"
    if os.path.exists(processed_files_file):
        processed_files = jl.load(processed_files_file)
    else:
        processed_files = []

    files = sorted(
        [
            os.path.join(root, f)
            for root, dirs, _files in os.walk(full_path)
            for f in _files
            if f.endswith("_bad_segments.txt")
        ]
    )

    if not files:
        st.warning("⚠️ No files found")

    if "filter_keyword" not in st.session_state:
        st.session_state.filter_keyword = ""

    filter_keyword = st.text_input(
        "🔍 Filter:", value=st.session_state.filter_keyword, placeholder="e.g., sub-01", key="filter_input"
    )
    st.session_state.filter_keyword = filter_keyword

    filtered_files = filter_files_by_keyword(files, filter_keyword)
    selected_file = st.selectbox(
        "Select MEG File:",
        filtered_files,
        label_visibility="collapsed",
        format_func=lambda file_path: f"{'[Processed]' if file_path in processed_files else ''} {Path(file_path).stem}",
    )

    if selected_file:
        if "last_selected_file" not in st.session_state:
            st.session_state.last_selected_file = selected_file
        elif st.session_state.last_selected_file != selected_file:
            st.session_state.last_selected_file = selected_file
            st.session_state.current_artifact_index = 0
            st.session_state.current_channel_group = 0
            st.session_state.selected_regions = []
            st.session_state.segments_to_delete = set()
            st.session_state.channels_to_toggle = set()
            st.session_state.current_overview_index = 0

        st.markdown("---")

        # 初始化交互模式
        if "interaction_mode" not in st.session_state:
            st.session_state.interaction_mode = "pan"

        file_path = os.path.join(DATA_DIR, selected_file)
        # origin_raw = mne.io.read_raw_fif(file_path, preload=False)
        subject_id_dir = Path(selected_file).parent.name
        check_plots_dir = Path(check_plot_dataset_dir) / "check_imgs"
        check_plots_waveformdir = check_plots_dir / "waveform"
        check_plots_overviewdir = check_plots_dir / "overview"
        chn_info_jl = Path(check_plots_waveformdir) / "channels.jl"
        if not chn_info_jl.exists():
            st.error(f"{chn_info_jl} is not exists...")
            st.stop()

        # ========== DISPLAY SETTINGS ==========
        st.header("⚙️ Display")
        with st.expander("📊 Options", expanded=False):
            show_overview = st.checkbox("📈 Overview", value=False)
            show_info = st.checkbox("ℹ️ Info", value=False)
            show_stats = st.checkbox("📊 Stats", value=False)

        st.markdown("---")

        # ========== NAVIGATION ==========
        st.header("🧭 Navigation")
        first_time = get_info_dict(chn_info_jl, "first_time")
        last_time = get_info_dict(chn_info_jl, "last_time")
        total_duration = last_time - first_time

        # 加载数据
        artifact_dir = Path(DATA_DIR) / subject_id_dir
        selected_file_stem = Path(selected_file).stem.replace("_bad_segments", "")
        bad_segments_file = artifact_dir / f"{selected_file_stem}_bad_segments.txt"
        bad_channels_file = artifact_dir / f"{selected_file_stem}_bad_channels.txt"
        if not bad_segments_file.exists():
            st.error("bad segment file is not exists...")
        else:
            annotations = load_bad_segments(bad_segments_file)

        bad_channels = []
        if bad_channels_file.exists():
            with open(bad_channels_file, "r") as f:
                bad_channels = [ch.strip() for ch in f.read().splitlines() if ch.strip()]

        available_onsets = get_available_onsets(check_plots_waveformdir)
        available_onsets_overview = get_available_onsets(check_plots_overviewdir)

        if not available_onsets:
            st.error(f"⚠️ No plots found for {subject_id_dir}")
            st.stop()

        # 初始化
        for key, default in [
            ("current_artifact_index", 0),
            ("current_overview_index", 0),
            ("current_channel_group", 0),
            ("selected_regions", []),
            ("segments_to_delete", set()),
            ("channels_to_toggle", set()),
        ]:
            if key not in st.session_state:
                st.session_state[key] = default

        st.session_state.current_artifact_index = max(
            0, min(st.session_state.current_artifact_index, len(available_onsets) - 1)
        )
        st.session_state.current_overview_index = max(
            0, min(st.session_state.current_overview_index, len(available_onsets_overview) - 1)
        )
        current_onset = available_onsets[st.session_state.current_artifact_index]
        current_onset_overview = available_onsets_overview[st.session_state.current_overview_index]
        n_channel_groups = get_channel_groups_for_onset(check_plots_waveformdir, current_onset)
        st.session_state.current_channel_group = max(
            0, min(st.session_state.current_channel_group, n_channel_groups - 1)
        )

        # ========== QUICK NAVIGATION ==========
        # st.caption("Use w to go up a channel group, s to go down a channel group, a to go to the previous segment, and d to go to the next segment.")
        # st.markdown("### ⌨️ Quick Navigation") ['w',"arrowup"],hint=False
        if st.button("⬆️ Prev", disabled=(st.session_state.current_channel_group <= 0), key="ch_prev", width="stretch"):
            st.session_state.current_channel_group -= 1
            st.rerun()

        col1, col2 = st.columns(2)
        with col1:  # ['a',"arrowleft"],hint=False
            if st.button(
                "⏮️ Prev", disabled=(st.session_state.current_artifact_index <= 0), key="art_prev", width="stretch"
            ):
                st.session_state.current_artifact_index -= 1
                # st.session_state.current_channel_group = 0
                st.rerun()

        with col2:  # ['d', "arrowright"], hint=False
            if st.button(
                "Next ⏭️",
                disabled=(st.session_state.current_artifact_index >= len(available_onsets) - 1),
                key="art_next",
                width="stretch",
            ):
                st.session_state.current_artifact_index += 1
                # st.session_state.current_channel_group = 0
                st.rerun()
        # ['s',"arrowdown"],hint=False,
        if st.button(
            "⬇️ Next",
            disabled=(st.session_state.current_channel_group >= n_channel_groups - 1),
            key="ch_next",
            width="stretch",
        ):
            st.session_state.current_channel_group += 1
            st.rerun()

        # add_shortcuts(ch_prev="w",art_prev="a",art_next="d",ch_next="s")
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button(
                "ClickChn",
                type="primary" if st.session_state.interaction_mode == "pan" else "secondary",
                width="stretch",
                key="quick_pan",
            ):
                if st.session_state.interaction_mode != "pan":
                    st.session_state.interaction_mode = "pan"
                    st.rerun()

        with col2:
            if st.button(
                "SelectSeg",
                type="primary" if st.session_state.interaction_mode == "select" else "secondary",
                width="stretch",
                key="quick_select",
            ):
                if st.session_state.interaction_mode != "select":
                    st.session_state.interaction_mode = "select"
                    st.rerun()

        # Artifact Navigation
        with st.expander("🔴 Segments", expanded=True):
            st.caption(f"Total: {len(available_onsets)}")

            col1, col2 = st.columns(2)
            with col1:
                st.metric("Current", f"{st.session_state.current_artifact_index + 1}/{len(available_onsets)}")
            with col2:
                st.metric("Time", f"{current_onset:.3f}s")

        # Channel Navigation
        with st.expander("📡 Channels", expanded=True):
            st.caption(f"Groups: {n_channel_groups} (30 ch/group)")
            st.metric("Current", f"{st.session_state.current_channel_group + 1}/{n_channel_groups}")
            # st.caption(f"Showing: {start_ch}-{end_ch-1}")


# ========== MAIN CONTENT ==========
if selected_file:
    print("processed_files:", processed_files)
    if show_stats:
        col1, col2, col3 = st.columns(3)
        with col1:
            current_bad = set(bad_channels)
            for ch in st.session_state.channels_to_toggle:
                if ch in current_bad:
                    current_bad.remove(ch)
                else:
                    current_bad.add(ch)
            st.metric("🔴 Bad Ch", len(current_bad))
        with col2:
            st.metric("⚠️ Ch Changes", len(st.session_state.channels_to_toggle))
        with col3:
            st.metric(
                "📊 Seg Changes", len(st.session_state.segments_to_delete) + len(st.session_state.selected_regions)
            )
        st.markdown("---")

    if show_overview:
        st.markdown("### 📈 Overview")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("⬅️ Prev Overview", width="stretch", disabled=(st.session_state.current_overview_index <= 0)):
                st.session_state.current_overview_index -= 1
                st.rerun()
        with col2:
            if st.button(
                "Next ➡️",
                width="stretch",
                disabled=(st.session_state.current_overview_index >= len(available_onsets_overview) - 1),
            ):
                st.session_state.current_overview_index += 1
                st.rerun()

        # Timeline
        if available_onsets_overview:
            current_overview_onset = available_onsets_overview[st.session_state.current_overview_index]
            end_time = current_overview_onset + CONFIG["TIME_OVERVIEW_PLOT"]
            # Display the current time on the timeline
            st.markdown(f"**Time:** {current_overview_onset:.1f} s to {end_time:.1f} s")

            # Load and display the overview image
            overview_path = get_plot_path(
                check_plots_dir,
                available_onsets_overview[st.session_state.current_overview_index],
                plot_type="overview",
            )

            if overview_path:
                # Create the figure
                combined_fig = go.Figure()

                # Add the overview image to the figure
                combined_fig.add_layout_image(
                    dict(
                        source=Image.open(overview_path),
                        x=current_overview_onset,  # Left edge of image
                        y=0,  # Bottom edge of image (adjust if needed)
                        xref="x",
                        yref="y",
                        sizex=end_time - current_overview_onset,  # Width of the image
                        sizey=1,  # Height of the image (adjust based on your needs)
                        sizing="stretch",
                        opacity=1,
                        layer="below",  # Ensure it's below the axis
                    )
                )

                # Add a horizontal line for the time axis
                combined_fig.add_shape(
                    type="line",
                    x0=current_overview_onset,
                    x1=end_time,
                    y0=0,
                    y1=0,
                    line=dict(color="lightgrey", width=4),
                )

                # Add vertical ticks at every 10 seconds
                for t in np.arange(int(current_overview_onset), int(end_time) + 1, 10):
                    combined_fig.add_shape(
                        type="line", x0=t, x1=t, y0=-0.05, y1=0.05, line=dict(color="lightgrey", width=2)
                    )
                    combined_fig.add_annotation(
                        x=t, y=0.1, text=f"{t:.1f}", showarrow=False, font=dict(size=10, color="black"), align="center"
                    )

                # Set the layout for the combined figure
                combined_fig.update_layout(
                    xaxis=dict(
                        range=[current_overview_onset, end_time],
                        title="Time (s)",
                        showgrid=True,
                        gridcolor="rgba(200,200,200,0.3)",
                        zeroline=True,
                        zerolinewidth=2,
                        zerolinecolor="rgba(128,128,128,0.5)",
                        tickmode="auto",
                        nticks=10,
                    ),
                    yaxis=dict(showticklabels=False, range=[-1.0, 0.2]),  # Hide y-axis and adjust range
                    height=CONFIG["OVERVIEW_WAVEFORM_HEIGHT"],  # Adjust height for a better viewing experience|300
                    margin=dict(t=0, b=0, l=0, r=0),  # Remove margins for a cleaner appearance
                )

                # Display the combined figure
                st.plotly_chart(combined_fig, width='stretch')

        st.markdown("---")

    # ========== INTERACTIVE WAVEFORM ==========
    color = get_file_color(selected_file)
    st.markdown(
        f"### 📈MEG Waveform(Time: {(current_onset):.3f} - {(current_onset) + CONFIG['TIME_PER_PLOT']:.3f}s)"
    )

    current_channels = get_current_channels(chn_info_jl, st.session_state.current_channel_group)
    annotations_orig_time = get_info_dict(chn_info_jl, "raw.annotations.orig_time")
    waveform_path = get_plot_path(check_plots_dir,current_onset, st.session_state.current_channel_group, "waveform")
    if waveform_path:
        try:
            bad_segments_list = []
            if annotations and len(annotations) > 0:
                bad_segments_list = [
                    (o, d, desc) for o, d, desc in zip(annotations.onset, annotations.duration, annotations.description)
                ]

            fig = create_interactive_waveform_with_channels(
                waveform_path,
                current_onset,
                CONFIG["TIME_PER_PLOT"],
                bad_segments_list,
                first_time,
                current_channels,
                bad_channels,
                st.session_state.channels_to_toggle,
                st.session_state.segments_to_delete,
                drag_mode=st.session_state.interaction_mode,
            )

            plot_key = f"plot_{st.session_state.current_artifact_index}_{st.session_state.current_channel_group}_{st.session_state.interaction_mode}"

            event = st.plotly_chart(fig, width="stretch", key=plot_key, on_select="rerun")

            # ========== 处理事件 ==========
            if event and "selection" in event:
                sel = event["selection"]

                # 点击事件
                if "points" in sel and len(sel["points"]) > 0:
                    for point in sel["points"]:
                        if "customdata" in point and point["customdata"]:
                            cdata = point["customdata"]

                            if len(cdata) >= 2:
                                item_id = cdata[0]
                                item_type = cdata[1]

                                if item_type == "channel":
                                    ch_name = item_id
                                    if ch_name in st.session_state.channels_to_toggle:
                                        st.session_state.channels_to_toggle.remove(ch_name)
                                        st.success(f"✅ Cancelled: {ch_name}")
                                    else:
                                        st.session_state.channels_to_toggle.add(ch_name)
                                        is_bad = ch_name in bad_channels
                                        action = "→ GOOD" if is_bad else "→ BAD"
                                        st.success(f"🎯 {ch_name} {action}")
                                    st.rerun()

                                elif item_type == "segment":
                                    seg_idx = item_id
                                    if seg_idx in st.session_state.segments_to_delete:
                                        st.session_state.segments_to_delete.remove(seg_idx)
                                        st.success(f"✅ Restored #{seg_idx}")
                                    else:
                                        st.session_state.segments_to_delete.add(seg_idx)
                                        st.warning(f"🗑️ Delete #{seg_idx}")
                                    st.rerun()

                # 框选事件
                if "box" in sel and len(sel["box"]) > 0:
                    if st.session_state.interaction_mode == "select":
                        for box in sel["box"]:
                            if "x" in box and len(box["x"]) == 2:
                                x_range = box["x"]
                                onset_rel = current_onset - first_time
                                if min(x_range) >= onset_rel:
                                    sel_start = max(min(x_range), onset_rel)
                                    sel_end = max(x_range)
                                    duration_sel = sel_end - sel_start

                                    if duration_sel > 0.1:
                                        new_region = (round(sel_start, 3), round(duration_sel, 3))
                                        if new_region not in st.session_state.selected_regions:
                                            st.session_state.selected_regions.append(new_region)
                                            st.success(
                                                f"✅ Selected: {sel_start:.3f}s-{(sel_start + duration_sel):.3f}s ({duration_sel:.3f}s)"
                                            )
                                            st.rerun()
                    else:
                        st.warning("⚠️ Switch to **Select Mode** to mark new bad segments")

        except Exception as e:
            st.error(f"❌ Error: {e}")
            import traceback

            st.code(traceback.format_exc())
    else:
        st.error("⚠️ Waveform not found")

    st.markdown("---")

    # ========== PENDING CHANGES ==========
    if st.session_state.channels_to_toggle or st.session_state.segments_to_delete or st.session_state.selected_regions:
        st.markdown("### 📋 Pending Changes")

        col1, col2 = st.columns([1, 2])

        with col1:
            if st.session_state.channels_to_toggle:
                st.markdown("#### 📡 Channels")
                to_bad = [ch for ch in st.session_state.channels_to_toggle if ch not in bad_channels]
                to_good = [ch for ch in st.session_state.channels_to_toggle if ch in bad_channels]

                if to_bad:
                    st.markdown("**🔴 → Bad:**")
                    for ch in sorted(to_bad):
                        st.text(f"  • {ch}")
                if to_good:
                    st.markdown("**✅ → Good:**")
                    for ch in sorted(to_good):
                        st.text(f"  • {ch}")

                if st.button("♻️ Clear", width="stretch", key="clear_ch"):
                    st.session_state.channels_to_toggle = set()
                    st.rerun()

        with col2:
            if st.session_state.segments_to_delete or st.session_state.selected_regions:
                st.markdown("#### 📊 Segments")
                if st.session_state.segments_to_delete:
                    st.markdown("**🗑️ Delete:**")
                    _bad_seg_df = annotations.to_data_frame(time_format=None)
                    # 添加时间转换
                    _bad_seg_df["onset"] = _bad_seg_df["onset"] - first_time
                    drop = [i for i in st.session_state.segments_to_delete]
                    drop_seg_df = _bad_seg_df.iloc[drop].reset_index(drop=True)
                    # 重命名列以显示相对时间
                    drop_seg_df = drop_seg_df.rename(columns={"onset": "onset (rel)"})
                    st.dataframe(drop_seg_df)

                    # for idx in sorted(st.session_state.segments_to_delete):
                    #     if idx < len(annotations):
                    #         st.text(f"  • #{idx}")

                if st.session_state.selected_regions:
                    st.markdown("**🆕 New:**")
                    selected_df = pd.DataFrame(st.session_state.selected_regions, columns=["Onset", "Duration"])
                    st.dataframe(selected_df, width="stretch")
                    # st.data_editor(selected_df, width='stretch',num_rows="dynamic")

                if st.button("♻️ Clear", width="stretch", key="clear_seg"):
                    st.session_state.segments_to_delete = set()
                    st.session_state.selected_regions = []
                    st.rerun()

        st.markdown("---")

    # ========== SAVE ==========
    st.markdown("### ✏️ Save")
    with st.form("save_form"):
        col1, col2 = st.columns([1, 2])

        with col1:
            st.markdown("#### 🔴 Bad Channels")
            current_bad_channels = set(bad_channels)
            st.caption(f"Total bad channels: {len(current_bad_channels)}")
            for ch in st.session_state.channels_to_toggle:
                if ch in current_bad_channels:
                    current_bad_channels.remove(ch)
                else:
                    current_bad_channels.add(ch)

            bad_ch_df = st.data_editor(
                pd.DataFrame(sorted(current_bad_channels), columns=["Bad Channels"]),
                num_rows="dynamic",
                width="stretch",
                height=300,
            )
            bad_ch_df.dropna(inplace=True)

        with col2:
            st.markdown("#### 📊 Bad Segments")
            if annotations and len(annotations) > 0:
                bad_seg_df = annotations.to_data_frame(time_format=None)
                bad_seg_df["onset"] = bad_seg_df["onset"] - first_time
                print("debug:first_time",first_time)
                bad_seg_df = bad_seg_df.rename(
                    columns={"onset": "onset (rel)", "duration": "duration", "description": "desc"}
                )

                if st.session_state.segments_to_delete:
                    keep = [i for i in range(len(bad_seg_df)) if i not in st.session_state.segments_to_delete]
                    bad_seg_df = bad_seg_df.iloc[keep].reset_index(drop=True)
            else:
                bad_seg_df = pd.DataFrame(columns=["onset (rel)", "duration", "desc"])

            if st.session_state.selected_regions:
                new_df = pd.DataFrame(
                    [(o, d, "BAD_manual") for o, d in st.session_state.selected_regions],
                    columns=["onset (rel)", "duration", "desc"],
                )
                bad_seg_df = pd.concat([bad_seg_df, new_df], ignore_index=True)

            st.caption(f"Total bad segments: {len(bad_seg_df)}")

            bad_seg_df_edited = st.data_editor(bad_seg_df, num_rows="dynamic", width="stretch", height=300)
            bad_seg_df_edited.dropna(inplace=True)
            bad_seg_df_edited["onset"] = bad_seg_df_edited["onset (rel)"] + first_time

        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            save_btn = st.form_submit_button("💾 Save", width="stretch", type="primary")

        if save_btn:
            with st.spinner("💾 Saving..."):
                if len(bad_seg_df_edited) > 0:
                    annot = mne.Annotations(
                        onset=bad_seg_df_edited["onset"].tolist(),
                        duration=bad_seg_df_edited["duration"].tolist(),
                        description=bad_seg_df_edited["desc"].tolist(),
                        orig_time=annotations_orig_time,
                    )
                    annot.save(bad_segments_file, overwrite=True)
                else:
                    empty = mne.Annotations([], [], [], orig_time=annotations_orig_time)
                    empty.save(bad_segments_file, overwrite=True)

                bad_ch_df.to_csv(bad_channels_file, header=False, index=False, sep="\n")

                st.session_state.selected_regions = []
                st.session_state.segments_to_delete = set()
                st.session_state.channels_to_toggle = set()

                processed_files.append(selected_file)
                jl.dump(processed_files, processed_files_file)

            st.success("✅ Saved!")
            st.markdown(f"- **Bad channels:** `{bad_channels_file.name}` ({len(bad_ch_df)} channels)")
            st.markdown(f"- **Bad segments:** `{bad_segments_file.name}` ({len(annot)} segments)")
            st.balloons()
            time.sleep(1)
            st.rerun()

    if show_info:
        with st.expander("ℹ️ Info", expanded=False):
            st.json(
                {
                    "file": selected_file,
                    "bad segments file": bad_channels_file.name,
                    "bad channels files": bad_segments_file.name,
                    "subject": subject_id_dir,
                    "duration": f"{total_duration:.3f}s",
                    "n_bad_ch": len(bad_channels),
                    "n_bad_seg": len(annotations) if annotations else 0,
                }
            )
        st.markdown("---")
