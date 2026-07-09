# MEG
# export DATASET_REPORT_PATH=/data/liaopan/megprep_demo/cog_dataset/derivatives
# export SUBJECTS_DIR=/data/liaopan/megprep_demo/cog_dataset/smri

## source imaging display for paper
#OPM COG: sub-01 aef
# export DATASET_REPORT_PATH=/data/liaopan/datasets/OPM-COG.v1/derivatives
# export SUBJECTS_DIR=/data/liaopan/datasets/OPM-COG.v1/smri

#Holmes: sub-01 ses01
# export DATASET_REPORT_PATH=/data/liaopan/datasets/Holmes/g3
# export SUBJECTS_DIR=/data/liaopan/datasets/Holmes/smri

#auditory_OPM_stationary: sub-002 aef
# export DATASET_REPORT_PATH=/data/liaopan/datasets/auditory_OPM_stationary/derivatives
# export SUBJECTS_DIR=/data/liaopan/datasets/auditory_OPM_stationary/smri

#SMN4Lang: sub-02
export DATASET_REPORT_PATH=/data/liaopan/datasets/SMN4Lang/g_nx
export SUBJECTS_DIR=/data/liaopan/datasets/SMN4Lang_smri


#### 

# SMN4Lang_single2
# export DATASET_REPORT_PATH=/data/liaopan/datasets/SMN4Lang_single2/
# export SUBJECTS_DIR=/data/liaopan/datasets/smn4lang_single_smri


# Interactive Reports
streamlit run reports.py --server.address=0.0.0.0 --server.port=8502 --server.headless=true

# Global Static Reports
# python static_html_report.py   --report_root /data/liaopan/datasets/WAND_Extracted/g_nx   --output_dir /data/liaopan/megprep/static_html_report_WAND
# python static_html_report.py  --report_root /data/liaopan/datasets/SMN4Lang_single2/preprocessed   --output_dir /data/liaopan/datasets/SMN4Lang_single2/test_nx/static_html_report
