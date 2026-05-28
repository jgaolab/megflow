import os
import streamlit as st
import mne
import pandas as pd

mne.viz.set_browser_backend('matplotlib')
# os.environ["DISPLAY"] = ":99"
# 设置数据目录路径
DATA_DIR = "/data/liaopan/datasets/SQUID-Artifacts/"
DATA_DIR = "/data/liaopan/datasets/Holmes_cn/preprocessed/sub-010_ses-001_tsss/"

# Streamlit 页面标题
st.title("MEG Preprocessing Results Viewer")

print(mne.viz.get_browser_backend())

# 缓存滤波raw
@st.cache_data
def filter_data(_raw, freqrange):
    raw_filtered = _raw.copy().filter(*freqrange, n_jobs=8)
    return raw_filtered

# @st.cache_data
def plot_psd(_raw):
    psd_fig = _raw.compute_psd().plot(show=False)
    return psd_fig

# 检查数据目录是否存在
if not os.path.exists(DATA_DIR):
    st.error(f"Data directory '{DATA_DIR}' does not exist. Please create it and add .fif files.")
else:
    # 列出目录下的 .fif 文件
    files = [f for f in os.listdir(DATA_DIR) if f.endswith(".fif")]

    if not files:
        st.warning("No .fif files found in the data directory. Please add some MEG files.")
    else:
        # 文件选择器：允许用户选择一个文件
        selected_file = st.sidebar.selectbox("Select a MEG File:", files)

        if selected_file:
            # 构造文件路径
            file_path = os.path.join(DATA_DIR, selected_file)
            st.write(f"Selected File: {selected_file}")

            # 加载 MEG 数据
            raw = mne.io.read_raw_fif(file_path, preload=True)
            with st.expander("Raw Data Info", expanded=False):
                st.write("Raw Data Info:", raw.info)

            # 显示功率谱密度 (PSD) 图
            st.subheader("Power Spectral Density (PSD)")
            # psd_fig = raw.compute_psd().plot(show=False)
            psd_fig = plot_psd(raw)
            st.pyplot(psd_fig)

            # 显示原始波形图
            # st.subheader("Raw Waveform")
            # fig_raw = raw.plot(n_channels=10, duration=5, show=False, block=False)
            # st.pyplot(fig_raw)

            # 显示滤波后的波形图
            freqrange = st.sidebar.slider('Band-pass frequency range (Hz)', min_value=0, max_value=300,
                                          value=(1, 40))

            time_duration = st.sidebar.selectbox('Duration (s)', [5, 10, 20, 30])

            channel_range = st.sidebar.selectbox('Channels', [10, 20, 30, len(raw.ch_names)])

            first_time = raw.first_time
            last_time = raw.last_samp / raw.info['sfreq']
            timerange = st.sidebar.slider('Time (s)', min_value=first_time, max_value=last_time,
                                          value=(first_time,))
            # start_time_ = st.sidebar.number_input('Start Time (s)', min_value=first_time, max_value=last_time)
            start_time = timerange[0] + time_duration

            st.subheader(f"Filtered Waveform ({freqrange} Hz)")
            # raw.filter(*freqrange, n_jobs=8)
            raw = filter_data(raw, freqrange)
            # st.write('debug2:', raw.annotations)


            # 对应坏道和坏段文件
            bad_channels_file = os.path.join(
                "/data/liaopan/megprep/megprep/sub-010_ses-001_tsss_preproc-raw_bad_channels.txt")
            bad_segments_file = os.path.join(
                "/data/liaopan/megprep/megprep/sub-010_ses-001_tsss_preproc-raw_bad_segments.csv")

            ###############################################################################
            # 1) 检查并加载坏道文件 (xxx_bad_channels.txt)
            ###############################################################################
            if os.path.exists(bad_channels_file):
                # st.write(f"Loading bad channels from: {bad_channels_file}")
                with open(bad_channels_file, 'r') as f:
                    # 每一行是一个坏道名称
                    bad_channels = [ch.strip() for ch in f.read().splitlines() if ch.strip()]
                raw.info["bads"] = bad_channels
            else:
                st.write("No bad channels file found.")

            ###############################################################################
            # 2) 检查并加载坏段文件 (xxx_bad_segments.csv)
            ###############################################################################
            if os.path.exists(bad_segments_file):
                # st.write(f"Loading bad segments from: {bad_segments_file}")
                # 直接用 mne.read_annotations 读取 csv 文件
                annotations = mne.read_annotations(bad_segments_file)

                old_annot = raw.annotations
                annotations._orig_time = old_annot.orig_time # need debug and remove
                if old_annot != annotations:
                    print(old_annot, annotations)
                    print(old_annot != annotations,"old_annot != annotations")
                    # annotations = annotations + old_annot
                    raw.set_annotations(annotations)
                # st.write("Bad segments loaded:", annotations.to_data_frame())
                # st.write("Bad segments loaded:", raw.annotations.to_data_frame())
                # st.write('debug:', raw.annotations)
            else:
                st.write("No bad segments file found.")

            fig_filtered = raw.plot(n_channels=channel_range, duration=time_duration, start=start_time,
                                    show_first_samp=True,
                                    show=False, block=False, show_scrollbars=False)
            st.pyplot(fig_filtered)

            # # 显示功率谱密度 (PSD) 图
            # st.subheader("Power Spectral Density (PSD)")
            # # psd_fig = raw.compute_psd().plot(show=False)
            # psd_fig = plot_psd(raw)
            # st.pyplot(psd_fig)

            if "bad_segments" not in st.session_state:
                st.session_state.bad_segments = raw.annotations

            if "bad_channels" not in st.session_state:
                st.session_state.bad_channels = bad_channels

            if "save_triggered_s" not in st.session_state:
                st.session_state.save_triggered_s = False

            if "save_triggered_c" not in st.session_state:
                st.session_state.save_triggered_c = False

            with st.form("edit_bad_channels"):
                # 显示坏道检测结果
                st.subheader("Bad Channels")
                raw.info["bads"] = bad_channels  # 示例坏道
                # st.write("Bad channels:", raw.info["bads"])
                bad_ch_df = st.data_editor(pd.DataFrame(raw.info['bads'], columns=['Bad channels']), num_rows="dynamic")
                # if st.button("Save Bad Channels"):
                #     bad_ch_df.to_csv(bad_channels_file, header=False, index=False, sep='\n')
                #     st.success(f"Saved:{bad_channels_file}")
                save_changes = st.form_submit_button("Save Bad Channels")

                if save_changes:
                    st.session_state.save_triggered_c = True
                    st.session_state.bad_channels = bad_ch_df
                    bad_ch_df.to_csv(bad_channels_file, header=False, index=False, sep='\n')
                    st.success(f"Saved:{bad_channels_file}")
                else:
                    st.session_state.save_triggered_c = False

            # 显示坏段检测结果
            with st.form("edit_bad_segments"):
                st.subheader("Bad Segments")
                # example：raw.annotations.append(onset=10, duration=5, description="Bad segment")
                bad_segments = raw.annotations
                if bad_segments:
                    # st.write("Bad Segments:", bad_segments.to_data_frame())
                    st.data_editor(bad_segments.to_data_frame(), num_rows="dynamic")
                else:
                    st.write("No bad segments detected.")

                # if st.button("Save Bad Segments"):
                #     bad_segments.save(bad_segments_file, overwrite=True)
                #     st.success(f"Saved:{bad_segments_file}")

                save_changes = st.form_submit_button("Save Bad Segments")

                if save_changes:
                    st.session_state.save_triggered_s = True
                    st.session_state.bad_segments = bad_segments
                    bad_segments.save(bad_segments_file, overwrite=True)
                    st.success(f"Saved:{bad_segments_file}")
                else:
                    st.session_state.save_triggered_s = False

            # 根据保存状态提供提示
            if st.session_state.save_triggered_c or st.session_state.save_triggered_s:
                st.info("Save operation completed.")
            else:
                st.info("No save operation performed.")

            # 可选：显示其他预处理结果
            st.subheader("Other Preprocessing Results")
            # 这里可以根据需求展示更多的预处理步骤，例如 ICA，信号去噪等
