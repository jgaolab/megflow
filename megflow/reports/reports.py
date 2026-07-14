# !/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
from pathlib import Path
import streamlit as st

from report_layout import infer_report_scope

st.set_page_config(page_title="MEGFlow Reports", layout="wide", page_icon="_static/favicon.png",)


def _discover_corpus_datasets(root: Path):
    datasets_root = root / "datasets"
    if not datasets_root.is_dir():
        return []
    candidates = []
    for item in sorted(datasets_root.iterdir(), key=lambda p: p.name.lower()):
        if item.is_dir() and (item / "preprocessed").is_dir():
            candidates.append(item)
    return candidates


base_report_path = Path(os.getenv("DATASET_REPORT_PATH", "/output")).resolve()
subjects_root = Path(os.getenv("SUBJECTS_DIR", "/smri")).resolve()
corpus_datasets = _discover_corpus_datasets(base_report_path)
st.session_state.run_report_root = str(base_report_path)
st.session_state.report_scope = infer_report_scope(base_report_path)

if corpus_datasets:
    dataset_names = [path.name for path in corpus_datasets]
    selected_name = st.sidebar.selectbox("Corpus dataset", dataset_names)
    selected_path = corpus_datasets[dataset_names.index(selected_name)]
    st.session_state.dataset_report_path = str(selected_path)
    dataset_subjects_dir = base_report_path / "smri" / selected_name
    st.session_state.subjects_dir = str(dataset_subjects_dir if dataset_subjects_dir.is_dir() else subjects_root)
    st.sidebar.caption(f"Dataset output: `{selected_path}`")
    corpus_index = base_report_path / "corpus_static_html_report" / "index.html"
    if corpus_index.is_file():
        st.sidebar.markdown(f"[Open corpus static report]({corpus_index.as_uri()})")
else:
    st.session_state.dataset_report_path = str(base_report_path)
    st.session_state.subjects_dir = str(subjects_root)

preproc_page = st.Page("reports/preproc.py", title="Preprocessing", icon=":material/dashboard:")
ica_page = st.Page("reports/ICA.py", title="ICA", icon=":material/dashboard:")
epochs_page = st.Page("reports/epochs.py", title="Epochs", icon=":material/dashboard:")
covar_page = st.Page("reports/covariance.py", title="Covariance", icon=":material/dashboard:")

headmodel_page = st.Page("reports/headmodel.py", title="Head Model - BEM Surfaces", icon=":material/dashboard:")

coreg_page = st.Page("reports/coreg.py", title="Coregistration", icon=":material/dashboard:")
coreg_page_3d = st.Page("reports/coregistration.py", title="Coregistration [3D]", icon=":material/dashboard:")

source_page = st.Page("reports/source_imaging.py", title="Source Localization", icon=":material/dashboard:")

nextflow_page = st.Page("reports/nextflow.py", title="Nextflow Resources", icon=":material/dashboard:")
nextflow_config_page = st.Page("reports/nx_config_online.py", title="Nextflow Configure", icon=":material/dashboard:")

artifacts_page = st.Page("reports/artifacts.py", title="Artifacts - QuickCheck", icon=":material/dashboard:")

quality_check_page = st.Page("reports/quality_check.py",title="Quality Summary", icon=":material/dashboard:")

demo_page = st.Page("reports/demo_video.py",title="MEGFlow Interaction Guide", icon=":material/videocam:")

# search_page = st.Page("tools/search.py", title="Search", icon=":material/search:")
# history = st.Page("tools/history.py", title="History", icon=":material/history:")

pg = st.navigation([demo_page,preproc_page,
                    artifacts_page,
                    ica_page,
                    epochs_page,
                    covar_page,
                    headmodel_page,
                    coreg_page, coreg_page_3d,
                    source_page,
                    quality_check_page,
                    nextflow_config_page, nextflow_page,
                    ])

pg.run()
