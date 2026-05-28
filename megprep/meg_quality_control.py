# !/usr/bin/env python3
# -*- coding: utf-8 -*-
import mne
import argparse
import logging
import datetime

# 设置日志
parser = argparse.ArgumentParser()
parser.add_argument('--input', required=True, help="Input MEG file")
parser.add_argument('--output', required=True, help="QC output file")
parser.add_argument('--log', required=True, help="Log file path")
args = parser.parse_args()

logging.basicConfig(filename=args.log, level=logging.INFO)
logging.info(f"[{datetime.datetime.now()}] Starting QC for {args.input}")

raw = mne.io.read_raw_fif(args.input, preload=True)

# 伪迹检测和坏道识别
raw.info['bads'] = mne.preprocessing.find_bad_channels(raw)
annotations = mne.preprocessing.annotate_muscle_zscore(raw, threshold=4.0)
logging.info(f"Detected bad channels: {raw.info['bads']}")
logging.info(f"Annotations added: {annotations}")

raw.set_annotations(annotations)
raw.save(args.output, overwrite=True)
logging.info(f"[{datetime.datetime.now()}] QC completed for {args.input}")
