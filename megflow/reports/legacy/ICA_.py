import os
import re
import streamlit as st

# 设置页面为宽屏模式
# st.set_page_config(page_title="Interactive ICA Viewer", layout="wide")

# 数据目录路径
IMAGE_DIR = "/data/liaopan/datasets/Holmes_cn/ica_results_new"  # 存储图片的目录
MARKED_FILE = os.path.join(IMAGE_DIR, "marked_components.txt")  # 保存标记的文件路径

# 添加 CSS 隐藏 Header 和 Footer，并增加样式美化
hide_streamlit_style = """
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        .delete-btn {
            background-color: #ff4b4b;
            color: white;
            border: none;
            padding: 5px 10px;
            border-radius: 5px;
            cursor: pointer;
        }
        .delete-btn:hover {
            background-color: #e63e3e;
        }
    </style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# Streamlit 页面标题
st.title("Interactive ICA Component Viewer and Marker")

# 初始化会话状态
if "ica_component" not in st.session_state:
    st.session_state["ica_component"] = 0  # 当前成分编号
if "source_group" not in st.session_state:
    st.session_state["source_group"] = 0  # 当前 source 成分组
if "marked_components" not in st.session_state:
    # 如果存在 marked_components.txt 文件，则加载其中的内容
    if os.path.exists(MARKED_FILE):
        with open(MARKED_FILE, "r") as f:
            st.session_state["marked_components"] = [int(line.strip()) for line in f.readlines()]
    else:
        st.session_state["marked_components"] = []  # 初始化为空列表
if "refresh" not in st.session_state:
    st.session_state["refresh"] = False  # 虚拟刷新变量

# 获取文件列表
if not os.path.exists(IMAGE_DIR):
    st.error(f"Image directory '{IMAGE_DIR}' does not exist. Please check the path and try again.")
else:
    files = [f for f in os.listdir(IMAGE_DIR) if f.endswith(".png")]

    if not files:
        st.warning("No image files found in the specified directory.")
    else:
        # 解析拓扑图文件（提取成分编号和附加信息）
        def parse_filename(filename):
            match = re.search(r"ica_(\d+)_k_([\d+\.\d+]+(?=\.png))", filename)
            if match:
                component_number = int(match.group(1))
                score = float(match.group(2))
                return {"filename": filename, "component": component_number, "score": score}
            return None

        # 解析 sources 文件（如 ica_comp_20-39_tc.png）
        def parse_source_group(filename):
            match = re.search(r"ica_comp_(\d+)-(\d+)_tc", filename)
            if match:
                start = int(match.group(1))
                end = int(match.group(2))
                return {"filename": filename, "start": start, "end": end}
            return None

        topo_files = [parse_filename(f) for f in files if parse_filename(f)]
        topo_files = sorted(topo_files, key=lambda x: x["component"])  # 按成分编号排序

        source_files = [parse_source_group(f) for f in files if parse_source_group(f)]
        source_files = sorted(source_files, key=lambda x: x["start"])  # 按编号范围排序

        # 获取当前成分编号
        component_idx = st.session_state["ica_component"]
        source_group_idx = st.session_state["source_group"]

        # 检查成分编号范围
        if component_idx < 0 or component_idx >= len(topo_files):
            st.error("Invalid component index. Please check the file structure.")
        elif source_group_idx < 0 or source_group_idx >= len(source_files):
            st.error("Invalid source group index. Please check the file structure.")
        else:
            # 当前 source 和 topo 信息
            current_topo = topo_files[component_idx]
            current_topo_filename = current_topo["filename"]
            current_topo_score = current_topo["score"]

            # print("\n 1.current_topo",current_topo, component_idx)

            current_source = source_files[source_group_idx]
            current_source_filename = current_source["filename"]
            current_source_start = current_source["start"]
            current_source_end = current_source["end"]

            # 页面布局：两列，左侧为 source 波形图，右侧为拓扑图
            col1, col2 = st.columns([1, 1])

            # 左侧展示 sources 波形图
            with col1:
                st.subheader(f"Source Components: {current_source_start}-{current_source_end}")
                st.image(
                    os.path.join(IMAGE_DIR, current_source_filename),
                    caption=f"Source Components {current_source_start}-{current_source_end}",
                    use_container_width=True,
                )

                # 左侧按钮布局
                left_col1, left_col2 = st.columns(2)
                with left_col1:
                    if st.button("Previous Sources Group"):
                        st.session_state["source_group"] = max(0, source_group_idx - 1)
                        st.rerun()
                with left_col2:
                    if st.button("Next Sources Group"):
                        st.session_state["source_group"] = min(len(source_files) - 1, source_group_idx + 1)
                        st.rerun()

            # 右侧展示拓扑图
            total_components = len(topo_files)
            with col2:
                st.subheader(f"Component {current_topo['component']}/{total_components-1} - Topography")
                st.image(
                    os.path.join(IMAGE_DIR, current_topo_filename),
                    caption=f"Score: {current_topo_score}",
                    use_container_width=True,
                )

                # 右侧按钮布局
                right_col1, right_col2, right_col3 = st.columns(3)
                with right_col1:
                    if st.button("Previous Component"):
                        st.session_state["ica_component"] = max(0, component_idx - 1)
                        st.rerun()
                        # st.session_state["refresh"] = not st.session_state["refresh"]  # 刷新页面
                with right_col2:
                    if st.button("Next Component"):
                        # print("component_idx",component_idx)
                        st.session_state["ica_component"] = min(len(topo_files) - 1, component_idx + 1)
                        st.rerun()
                        # st.session_state["refresh"] = not st.session_state["refresh"]  # 刷新页面
                with right_col3:
                    # Display "Mark Component" button
                    if st.button("Mark Component"):
                        # print("current_topo[component]", current_topo["component"])
                        # print("st.session_state[marked_components]", st.session_state["marked_components"])
                        if current_topo["component"] not in st.session_state["marked_components"]:
                            st.session_state["marked_components"].append(current_topo["component"])
                            st.success(f"Component {current_topo['component']} marked as artifact.")
                            # st.session_state["refresh"] = not st.session_state["refresh"]  # 刷新页面

            st.subheader("Marked ICA Components")

            if st.session_state["marked_components"]:
                # Each row can show up to 6 items
                items_per_row = 6

                # Custom card and button styles
                card_style = """
                    <style>
                        .marked-card {
                            background-color: #e8f9ee;
                            border: 1px solid #ddd;
                            border-radius: 10px;
                            padding: 10px;
                            margin: 5px;
                            box-shadow: 2px 2px 5px rgba(0, 0, 0, 0.1);
                            display: flex;
                            flex-direction: column;
                            align-items: center;
                            justify-content: center;
                            width: 120px;
                            text-align: center;
                            color: black;
                        }
                        .delete-btn {
                            background-color: #ff4b4b;
                            color: white;
                            border: none;
                            padding: 5px 10px;
                            border-radius: 5px;
                            cursor: pointer;
                            font-size: 12px;
                            margin-top: 10px;
                        }
                        .delete-btn:hover {
                            background-color: #e63e3e;
                        }
                    </style>
                """
                st.markdown(card_style, unsafe_allow_html=True)

                # Group marked components into rows
                rows = [
                    st.session_state["marked_components"][i: i + items_per_row]
                    for i in range(0, len(st.session_state["marked_components"]), items_per_row)
                ]

                # Iterate through each row
                for row in rows:
                    cols = st.columns(len(row))  # Dynamically create columns for each row
                    for i, comp in enumerate(row):
                        with cols[i]:
                            # Display card with delete button
                            st.markdown(
                                f"""
                                <div class="marked-card">
                                    <div>Component {comp}</div>
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )
                            # Button directly inside the card
                            if st.button(f"Delete", key=f"delete_{comp}"):
                                st.session_state["marked_components"].remove(comp)
                                st.success(f"Component {comp} removed.")
                                st.rerun()

            else:
                st.write("No components marked yet.")

            # Save button
            st.subheader("Save ICA Components")
            if st.button("Save Marked Components"):
                with open(MARKED_FILE, "w") as f:
                    f.write("\n".join(map(str, st.session_state["marked_components"])))
                st.success(f"Marked components saved to {MARKED_FILE}!")





