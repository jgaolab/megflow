# MEG
export DATASET_REPORT_PATH=/data/liaopan/megflow_demo/cog_dataset/derivatives
export SUBJECTS_DIR=/data/liaopan/megflow_demo/cog_dataset/smri
#OPM
#export DATASET_REPORT_PATH=/data/liaopan/datasets/OPM-COG.v1/derivatives
#export SUBJECTS_DIR=/data/liaopan/datasets/OPM-COG.v1/smri

#Holmes_cn

#auditory_OPM_stationary
#export DATASET_REPORT_PATH=
#export SUBJECTS_DIR=/data/liaopan/datasets/auditory_OPM_stationary/smri

# SMN4Lang_single2
export DATASET_REPORT_PATH=/data/liaopan/datasets/SMN4Lang_single2/
export SUBJECTS_DIR=/data/liaopan/datasets/smn4lang_single_smri
# Interactive Reports
streamlit run reports.py --server.address=0.0.0.0 --server.port=8502 --server.headless=true

# Global Static Reports
# python static_html_report.py   --report_root /data/liaopan/datasets/WAND_Extracted/g_nx   --output_dir /data/liaopan/megprep/static_html_report_WAND
# python static_html_report.py  --report_root /data/liaopan/datasets/SMN4Lang_single2/preprocessed   --output_dir /data/liaopan/datasets/SMN4Lang_single2/test_nx/static_html_report
