#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate a portable static HTML report package for MEGFlow outputs.

The generated directory keeps HTML pages, copied result files, and summary data
in one place so the whole folder can be zipped and viewed offline.
"""

from __future__ import annotations

import argparse
import ast
import csv
import html
import json
import math
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import mne
import pandas as pd

from workflow_diagram import (
    build_workflow_nodes,
    expect_coregistration_outputs_for_qc,
    expect_ica_outputs_for_qc,
    load_workflow_context,
    qc_completeness_scope_from_manifest,
    render_workflow_dataset_html,
    workflow_meta_for_json,
)

DEFAULT_THRESHOLDS = {
    "bad_channel_threshold": 30,
    "bad_segment_threshold": 50,
    "coreg_mean_threshold": 5.0,
    "coreg_max_threshold": 10.0,
    "epoch_reject_rate_threshold": 0.30,
    "artifact_overview_duration": 200.0,
    "megqc_alarm_score": 70.0,
}

STEP_DEFS = [
    ("quality_score", "QC score"),
    ("basic_preproc", "Basic preprocessing"),
    ("artifacts", "Artifacts"),
    ("ica", "ICA"),
    ("epochs", "Epochs"),
    ("covariance", "Covariance"),
    ("coregistration", "MEG-MRI coregistration"),
    ("headmodel", "Head model"),
    ("source", "Source localization"),
]
PROCESS_TO_STEP = {
    "import_mri_dataset": "anatomy import",
    "dcm2niix": "anatomy import",
    "run_freesurfer": "anatomy",
    "run_deepprep": "anatomy",
    "run_mkheadsurf": "headmodel",
    "generate_bem": "headmodel",
    "import_meg_dataset": "meg import",
    "score_meg_quality": "quality_score",
    "meg_basic_preproc": "basic_preproc",
    "detect_artifacts": "artifacts",
    "run_ica": "ica",
    "run_ic_label": "ica",
    "apply_ica": "ica",
    "coregistration": "coregistration",
    "forward_solution": "headmodel",
    "epochs": "epochs",
    "compute_covariance": "covariance",
    "compute_covariances": "covariance",
    "source_imaging": "source",
    "generate_static_html_report": "report",
    "generate_corpus_static_html_report": "report",
}
STEP_KEYS = {key for key, _ in STEP_DEFS}
SUCCESS_TRACE_STATUSES = {"COMPLETED", "CACHED", "SUBMITTED", "RUNNING"}

COREG_ASSET_STEPS = (
    "coreg_initial",
    "coreg_fiducials",
    "coreg_icp",
    "coreg_icp_finetune",
)
COREG_ASSET_VIEW_SUFFIXES = ("", "_brain")
COREG_STAGE_DETAILS = {
    "coreg_initial": {
        "title": "Initial alignment",
        "description": "Before fitting, showing the starting MEG-MRI alignment.",
    },
    "coreg_fiducials": {
        "title": "After fiducial fitting",
        "description": "Alignment after fitting nasion, LPA, and RPA fiducials.",
    },
    "coreg_icp": {
        "title": "After ICP registration",
        "description": "Alignment after the first ICP pass using head shape points.",
    },
    "coreg_icp_finetune": {
        "title": "Final result: fine-tuned ICP",
        "description": "Final coregistration result used for downstream analysis.",
    },
}
STATIC_DIR = Path(__file__).resolve().parent / "_static"
FAVICON_PATH = STATIC_DIR / "favicon.png"

REPORT_CSS = """
:root {
  --bg: #f5f7fb;
  --panel: #ffffff;
  --panel-soft: #f6f8fb;
  --text: #17212b;
  --muted: #667085;
  --line: #dbe4ee;
  --accent: #4267d5;
  --accent-2: #1f4acc;
  --accent-soft: #eef3ff;
  --warn: #b54708;
  --warn-soft: #fff4dd;
  --danger: #c4320a;
  --danger-soft: #ffe9e5;
  --good: #067647;
  --good-soft: #ddf9eb;
  --hero-top: #eef4ff;
  --hero-bottom: #e8f0ff;
  --shadow: 0 14px 40px rgba(15, 23, 42, 0.08);
  --radius: 20px;
  --radius-sm: 14px;
}

* {
  box-sizing: border-box;
}

html {
  scroll-behavior: smooth;
}

body {
  margin: 0;
  font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  background:
    radial-gradient(circle at top left, rgba(66, 103, 213, 0.12), transparent 24%),
    radial-gradient(circle at top right, rgba(66, 103, 213, 0.08), transparent 20%),
    var(--bg);
  color: var(--text);
}

a {
  color: var(--accent);
  text-decoration: none;
}

a:hover {
  text-decoration: underline;
}

.container {
  width: min(1500px, calc(100% - 48px));
  margin: 0 auto;
  padding: 28px 0 56px;
}

.hero {
  background:
    radial-gradient(circle at top right, rgba(66, 103, 213, 0.12), transparent 28%),
    linear-gradient(180deg, var(--hero-top), var(--hero-bottom));
  color: var(--text);
  border-radius: 28px;
  padding: 28px 32px;
  box-shadow: var(--shadow);
  margin-bottom: 24px;
  border: 1px solid rgba(66, 103, 213, 0.12);
}

.hero h1 {
  margin: 0 0 10px;
  font-size: 2.05rem;
  letter-spacing: -0.02em;
}

.hero p {
  margin: 6px 0;
  color: var(--muted);
}

.eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  padding: 6px 12px;
  border-radius: 999px;
  background: rgba(66, 103, 213, 0.08);
  color: var(--accent-2);
  font-size: 0.84rem;
  font-weight: 700;
  letter-spacing: 0.02em;
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  margin-top: 18px;
}

.toolbar input,
.toolbar select {
  background: #fff;
  border: 1px solid var(--line);
  color: var(--text);
  border-radius: 12px;
  padding: 10px 14px;
  min-width: 180px;
  outline: none;
  box-shadow: inset 0 1px 2px rgba(16, 24, 40, 0.04);
}

.toolbar input::placeholder {
  color: #98a2b3;
}

.filter-panel {
  margin-top: 20px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(66, 103, 213, 0.12);
  border-radius: 18px;
  padding: 16px;
  backdrop-filter: blur(8px);
}

.filter-grid {
  display: grid;
  grid-template-columns: minmax(0, 2.2fr) repeat(4, minmax(0, 1fr));
  gap: 12px;
  align-items: end;
}

.control-group {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.control-group.search-control {
  grid-column: span 1;
}

.quality-score-controls {
  grid-column: span 2;
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(96px, 0.65fr);
  gap: 12px;
  align-items: end;
}

.control-group label {
  color: var(--muted);
  font-size: 0.82rem;
  font-weight: 700;
  letter-spacing: 0.01em;
}

.control-group input,
.control-group select {
  width: 100%;
  min-width: 0;
  max-width: 100%;
  background: #fff;
  border: 1px solid rgba(66, 103, 213, 0.14);
  border-radius: 14px;
  padding: 11px 14px;
  color: var(--text);
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
}

.control-group input:focus,
.control-group select:focus {
  border-color: rgba(66, 103, 213, 0.55);
  box-shadow: 0 0 0 4px rgba(66, 103, 213, 0.10);
}

.hero-links {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 16px;
}

.hero-links a {
  color: var(--accent-2);
  background: #fff;
  padding: 9px 14px;
  border-radius: 999px;
  border: 1px solid rgba(66, 103, 213, 0.14);
}

.grid {
  display: grid;
  gap: 16px;
}

.grid.cards {
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  margin-bottom: 22px;
}

.card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 18px 18px 16px;
  position: relative;
  overflow: hidden;
}

.card::after {
  content: "";
  position: absolute;
  inset: auto auto 0 0;
  width: 100%;
  height: 4px;
  background: linear-gradient(90deg, var(--accent), rgba(66, 103, 213, 0.18));
}

.card .label {
  color: var(--muted);
  font-size: 0.92rem;
  margin-bottom: 10px;
}

.card .value {
  font-size: 1.9rem;
  font-weight: 700;
}

.card .subvalue {
  color: var(--muted);
  margin-top: 6px;
  font-size: 0.92rem;
}

.section {
  margin-top: 26px;
}

.section h2 {
  margin: 0 0 14px;
  font-size: 1.25rem;
}

.workflow-section {
  margin: 26px 0 44px;
}

.workflow-svg-wrap {
  overflow-x: auto;
  margin: 12px 0 10px;
  padding: 12px 14px;
  border-radius: 16px;
  background: linear-gradient(180deg, #fbfdff, #f6f8fc);
  border: 1px solid rgba(66, 103, 213, 0.12);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.75);
}

.workflow-section h2 {
  margin: 0 0 6px;
  font-size: 1.32rem;
  letter-spacing: 0;
  color: var(--text);
}

.workflow-subtitle {
  margin: 0 0 12px;
  color: var(--muted);
  font-size: 0.94rem;
  line-height: 1.45;
}

.workflow-panel {
  overflow: hidden;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(250, 252, 255, 0.98));
  border: 1px solid rgba(66, 103, 213, 0.14);
  box-shadow: var(--shadow);
}

.panel.workflow-panel {
  padding: 18px 20px 20px;
}

.workflow-footnote {
  margin: 0 0 10px !important;
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(66, 103, 213, 0.06);
  border: 1px solid rgba(66, 103, 213, 0.10);
}

.workflow-manifest-hint,
.workflow-details-hint {
  margin: 0;
  color: var(--muted);
  line-height: 1.45;
}

.workflow-manifest-hint {
  margin-top: 0;
}

.workflow-config-hint {
  margin: 0;
  color: var(--muted);
  line-height: 1.45;
}

.muted {
  color: var(--muted);
}

.workflow-link-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-top: 12px;
}

.workflow-link-row .workflow-manifest-hint,
.workflow-link-row .workflow-config-hint {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  max-width: 100%;
  min-height: 30px;
  padding: 6px 10px;
  border-radius: 999px;
  background: #ffffff;
  border: 1px solid rgba(66, 103, 213, 0.12);
}

.workflow-link-row .workflow-config-hint-missing {
  flex: 1 1 100%;
  align-items: flex-start;
  border-radius: 12px;
}

.workflow-details-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 16px;
}

.workflow-detail-group {
  min-width: 0;
  padding: 14px 16px 13px;
  border: 1px solid rgba(49, 51, 63, 0.10);
  border-radius: 12px;
  background: #ffffff;
}

.workflow-detail-group-paths {
  grid-column: 1 / -1;
}

.workflow-detail-group-normative-qc {
  grid-column: 1 / -1;
}

.workflow-detail-group-normative-qc .workflow-detail-list {
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 12px 18px;
}

.workflow-detail-group-normative-qc .workflow-detail-row {
  grid-template-columns: 1fr;
  gap: 4px;
  align-content: start;
  padding-bottom: 10px;
  border-bottom: 1px solid rgba(49, 51, 63, 0.08);
}

.workflow-detail-title {
  margin: 0 0 10px;
  color: var(--text);
  font-size: 0.9rem;
  font-weight: 800;
  letter-spacing: 0;
}

.workflow-detail-list {
  display: grid;
  gap: 9px;
  margin: 0;
}

.workflow-detail-row {
  display: grid;
  grid-template-columns: minmax(7rem, 0.32fr) minmax(0, 1fr);
  gap: 14px;
  align-items: start;
  min-width: 0;
}

.workflow-detail-group-paths .workflow-detail-row {
  grid-template-columns: 8.5rem minmax(0, 1fr);
}

.workflow-detail-row dt,
.workflow-detail-row dd {
  margin: 0;
}

.wf-detail-k {
  color: var(--muted);
  font-size: 0.8rem;
  font-weight: 700;
  line-height: 1.35;
}

.wf-detail-v {
  color: var(--text);
  font-size: 0.88rem;
  line-height: 1.35;
  min-width: 0;
  overflow-wrap: break-word;
  word-break: normal;
}

.wf-detail-help {
  margin-top: 4px;
  color: var(--muted);
  font-size: 0.78rem;
  line-height: 1.35;
  font-weight: 500;
}

.workflow-detail-group-paths .wf-detail-v {
  font-size: 0.86rem;
  overflow-wrap: anywhere;
}

.wf-detail-path-value {
  color: #1d2939;
  font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  font-weight: 600;
}

.wf-arrowhead {
  fill: rgba(66, 103, 213, 0.38);
}

.workflow-svg {
  min-width: 720px;
  max-width: none;
  height: auto;
  display: block;
  margin: 0 auto;
}

.wf-lane-bg {
  fill: rgba(255, 255, 255, 0.62);
  stroke: rgba(66, 103, 213, 0.10);
  stroke-width: 1;
}

.wf-lane-label {
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.08em;
  fill: #667085;
  font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
}

.wf-node-card {
  fill: #ffffff;
  stroke: rgba(49, 51, 63, 0.12);
  stroke-width: 1;
  filter: drop-shadow(0 7px 14px rgba(15, 23, 42, 0.08));
}

.wf-node-card.wf-done {
  fill: #ffffff;
  stroke: rgba(6, 118, 71, 0.20);
}

.wf-node-card.wf-partial {
  fill: #ffffff;
  stroke: rgba(181, 71, 8, 0.20);
}

.wf-node-card.wf-missing {
  fill: #ffffff;
  stroke: rgba(196, 50, 10, 0.22);
}

.wf-node-card.wf-skipped,
.wf-node-card.wf-na {
  fill: #ffffff;
  stroke: rgba(102, 112, 133, 0.18);
}

.wf-status-rail.wf-done {
  fill: var(--good);
}

.wf-status-rail.wf-partial {
  fill: var(--warn);
}

.wf-status-rail.wf-missing {
  fill: var(--danger);
}

.wf-status-rail.wf-skipped,
.wf-status-rail.wf-na {
  fill: #98a2b3;
}

.wf-node-pill.wf-done {
  fill: var(--good-soft);
}

.wf-node-pill.wf-partial {
  fill: var(--warn-soft);
}

.wf-node-pill.wf-missing {
  fill: var(--danger-soft);
}

.wf-node-pill.wf-skipped,
.wf-node-pill.wf-na {
  fill: #eef2f6;
}

.wf-text {
  font-size: 12.5px;
  font-weight: 700;
  fill: var(--text);
  font-family: "Source Sans Pro", "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
}

.wf-node-status {
  font-size: 10.5px;
  font-weight: 800;
  fill: #344054;
  font-family: "Source Sans Pro", "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
}

.wf-node-status.wf-done {
  fill: var(--good);
}

.wf-node-status.wf-partial {
  fill: var(--warn);
}

.wf-node-status.wf-missing {
  fill: var(--danger);
}

.wf-edge {
  fill: none;
  stroke: rgba(66, 103, 213, 0.26);
  stroke-width: 1.8;
  stroke-linecap: round;
}

.wf-edge-branch {
  stroke-dasharray: 4 4;
  stroke: rgba(102, 112, 133, 0.28);
}

/* Legacy fallback for older rectangular workflow SVG nodes. */
.wf-box.wf-done {
  fill: #f0f7ff;
  stroke: rgba(37, 99, 235, 0.35);
}

.wf-box.wf-partial {
  fill: #fffbeb;
  stroke: rgba(217, 119, 6, 0.35);
}

.wf-box.wf-missing {
  fill: #fef2f2;
  stroke: rgba(220, 38, 38, 0.32);
}

.wf-box.wf-skipped {
  fill: #f9fafb;
  stroke: rgba(107, 114, 128, 0.3);
  stroke-dasharray: 3 2;
}

.wf-box.wf-na {
  fill: #f9fafb;
  stroke: rgba(156, 163, 175, 0.28);
}

.workflow-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
  font-size: 0.76rem;
  align-items: center;
}

.wf-legend {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid rgba(49, 51, 63, 0.1);
  background: #ffffff;
  color: #31333f;
}

.wf-legend::before {
  content: "";
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #98a2b3;
}

.wf-legend.wf-done { background: var(--good-soft); border-color: rgba(6, 118, 71, 0.16); color: var(--good); }
.wf-legend.wf-partial { background: var(--warn-soft); border-color: rgba(181, 71, 8, 0.18); color: var(--warn); }
.wf-legend.wf-missing { background: var(--danger-soft); border-color: rgba(196, 50, 10, 0.18); color: var(--danger); }
.wf-legend.wf-skipped { background: #f2f4f7; border-color: rgba(102, 112, 133, 0.18); color: #475467; }
.wf-legend.wf-na { background: #f8fafc; border-color: rgba(102, 112, 133, 0.14); color: #667085; }

.wf-legend.wf-done::before { background: var(--good); }
.wf-legend.wf-partial::before { background: var(--warn); }
.wf-legend.wf-missing::before { background: var(--danger); }

.workflow-section + .grid.cards {
  margin-top: 4px;
}

.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 20px;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: 1.35fr 0.95fr;
  gap: 18px;
}

.dashboard-grid + .dashboard-grid {
  margin-top: 18px;
}

.panel h3 {
  margin: 0 0 14px;
  font-size: 1.02rem;
}

.panel-kicker {
  margin: 0 0 8px;
  color: var(--accent-2);
  font-size: 0.78rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.panel-title-row {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 14px;
}

.panel-title-group h3 {
  margin-bottom: 4px;
  font-size: 1.08rem;
}

.panel-subtitle {
  color: var(--muted);
  font-size: 0.92rem;
}

.subtle {
  color: var(--muted);
}

.table-wrap {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
}

th,
td {
  text-align: left;
  padding: 9px 10px;
  border-bottom: 1px solid var(--line);
  vertical-align: top;
}

th {
  font-size: 0.9rem;
  color: var(--muted);
  background: #fafcfd;
  position: sticky;
  top: 0;
}

th.sortable {
  padding: 0;
}

th.sortable.active-sort {
  background: #f7f9fd;
  box-shadow: inset 0 -1px 0 rgba(66, 103, 213, 0.18);
}

td.active-sort-cell {
  background: transparent;
  box-shadow: none;
}

.sort-header {
  width: 100%;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 9px 10px;
  cursor: pointer;
  font-weight: 700;
  text-align: left;
  line-height: 1.2;
}

.sort-header:hover {
  background: rgba(66, 103, 213, 0.06);
}

.sort-header:focus-visible {
  outline: 2px solid rgba(66, 103, 213, 0.35);
  outline-offset: -2px;
}

.sort-indicator {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 16px;
  color: #98a2b3;
  font-size: 0.78rem;
  font-weight: 700;
  opacity: 0.75;
}

.sort-header.active {
  color: var(--text);
  font-weight: 750;
}

.sort-header.active .sort-indicator {
  color: var(--accent-2);
  opacity: 0.85;
}

tr:hover td {
  background: #fbfdff;
}

tr.row-warn td {
  background: rgba(181, 71, 8, 0.045);
}

tr.row-fail td {
  background: rgba(196, 50, 10, 0.05);
}

tr.row-warn:hover td {
  background: rgba(181, 71, 8, 0.075);
}

tr.row-fail:hover td {
  background: rgba(196, 50, 10, 0.085);
}

tr.row-warn td.active-sort-cell {
  background: rgba(181, 71, 8, 0.045);
}

tr.row-fail td.active-sort-cell {
  background: rgba(196, 50, 10, 0.05);
}

tr:hover td.active-sort-cell {
  background: #fbfdff;
}

tr.row-warn:hover td.active-sort-cell {
  background: rgba(181, 71, 8, 0.075);
}

tr.row-fail:hover td.active-sort-cell {
  background: rgba(196, 50, 10, 0.085);
}

.pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: 999px;
  padding: 5px 12px;
  font-size: 0.84rem;
  font-weight: 600;
  border: 1px solid transparent;
}

.pill.good {
  color: var(--good);
  background: var(--good-soft);
  border-color: rgba(6, 118, 71, 0.10);
}

.pill.warn {
  color: var(--warn);
  background: var(--warn-soft);
  border-color: rgba(181, 71, 8, 0.12);
}

.pill.danger {
  color: var(--danger);
  background: var(--danger-soft);
  border-color: rgba(196, 50, 10, 0.12);
}

.pill.neutral {
  color: var(--muted);
  background: var(--panel-soft);
  border-color: var(--line);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.chip {
  display: inline-block;
  background: var(--panel-soft);
  border: 1px solid var(--line);
  color: var(--text);
  border-radius: 999px;
  padding: 6px 10px;
  font-size: 0.82rem;
}

.metric-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}

.metric-box {
  background: #fbfdff;
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 12px;
  min-width: 0;
}

.metric-box .k {
  color: var(--muted);
  font-size: 0.85rem;
  margin-bottom: 6px;
}

.metric-box .v {
  font-size: 1.15rem;
  font-weight: 700;
  min-width: 0;
}

.metric-box .v.smaller {
  font-size: 1rem;
}

.metric-box.wide {
  grid-column: 1 / -1;
}

.metric-box .v.wrap,
.mono-path {
  font-size: 0.95rem;
  font-weight: 600;
  word-break: break-word;
  overflow-wrap: anywhere;
  line-height: 1.45;
  font-family: "Consolas", "SFMono-Regular", "Liberation Mono", monospace;
}

.two-col {
  display: grid;
  grid-template-columns: 1.15fr 0.85fr;
  gap: 18px;
  align-items: start;
}

.quality-score-layout {
  grid-template-columns: minmax(0, 1.05fr) minmax(360px, 0.95fr);
  align-items: stretch;
}

.quality-summary-panel,
.quality-reference-panel {
  min-width: 0;
}

.quality-summary-panel {
  display: grid;
  gap: 14px;
  align-content: start;
}

.quality-summary-panel .info-note {
  margin-top: 0;
}

.quality-reference-panel {
  padding: 16px;
}

.quality-reference-panel .gallery {
  grid-template-columns: 1fr;
  gap: 0;
}

.quality-reference-figure img {
  box-sizing: border-box;
  padding: 8px 10px 2px;
}

.quality-reference-figure .caption {
  border-top: 1px solid var(--line);
  background: #fbfdff;
  color: var(--text);
  font-weight: 700;
}

.quality-detail-panel {
  margin-top: 16px;
}

.quality-components-details {
  margin-top: 16px;
}

.quality-components-details summary {
  cursor: pointer;
  list-style: none;
}

.quality-components-details summary::-webkit-details-marker {
  display: none;
}

.quality-components-details summary .panel-title-group {
  position: relative;
  padding-right: 90px;
}

.quality-components-details summary .panel-title-group::after {
  content: "Expand";
  position: absolute;
  right: 0;
  top: 2px;
  color: var(--accent-2);
  font-size: 0.82rem;
  font-weight: 800;
}

.quality-components-details[open] summary .panel-title-group::after {
  content: "Collapse";
}

.quality-components-body {
  margin-top: 14px;
}

.gallery {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 16px;
}

.artifact-gallery {
  display: grid;
  gap: 18px;
}

.artifact-group {
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 14px;
  background: linear-gradient(180deg, #fbfdff, #ffffff);
}

.artifact-group-title {
  font-weight: 800;
  margin-bottom: 4px;
}

.artifact-group-desc {
  color: var(--muted);
  font-size: 0.9rem;
  line-height: 1.45;
  margin-bottom: 12px;
}

.coreg-gallery {
  display: grid;
  gap: 18px;
}

.coreg-stage {
  background: linear-gradient(180deg, #fbfdff, #f7faff);
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 16px;
}

.coreg-stage.final {
  border-color: rgba(6, 118, 71, 0.32);
  box-shadow: 0 14px 32px rgba(6, 118, 71, 0.10);
  background: linear-gradient(180deg, #f1fff7, #fbfdff 42%);
}

.coreg-stage-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.coreg-stage-title {
  font-weight: 800;
  font-size: 1.02rem;
}

.coreg-stage-desc {
  color: var(--muted);
  font-size: 0.9rem;
  line-height: 1.5;
  margin-top: 4px;
}

.coreg-stage-images {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.coreg-stage .figure {
  background: #fff;
}

.coreg-stage .figure .caption {
  font-weight: 600;
}

.figure {
  background: #fbfdff;
  border: 1px solid var(--line);
  border-radius: 16px;
  overflow: hidden;
  position: relative;
}

.figure img {
  display: block;
  width: 100%;
  height: auto;
  background: #fff;
}

.figure .caption {
  padding: 10px 12px 12px;
  font-size: 0.9rem;
  color: var(--muted);
}

.figure-meta {
  margin-top: 5px;
  color: #475467;
  font-size: 0.8rem;
  line-height: 1.35;
  font-family: "Consolas", "SFMono-Regular", "Liberation Mono", monospace;
}

.figure.flagged {
  border-color: rgba(181, 71, 8, 0.28);
  box-shadow: 0 10px 24px rgba(181, 71, 8, 0.12);
  background: linear-gradient(180deg, #fffaf2, #fbfdff 22%);
}

.figure.wide {
  grid-column: 1 / -1;
}

.figure-badge {
  position: absolute;
  top: 12px;
  left: 12px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 800;
  letter-spacing: 0.01em;
  z-index: 1;
  border: 1px solid transparent;
  backdrop-filter: blur(6px);
}

.figure-badge.warn {
  color: var(--warn);
  background: rgba(255, 244, 221, 0.92);
  border-color: rgba(181, 71, 8, 0.18);
}

.figure-badge.neutral {
  color: var(--muted);
  background: rgba(246, 248, 251, 0.94);
  border-color: rgba(152, 162, 179, 0.18);
}

.figure-badge.good {
  color: var(--good);
  background: rgba(221, 249, 235, 0.94);
  border-color: rgba(6, 118, 71, 0.18);
}

.alarm-list {
  display: grid;
  gap: 10px;
}

.alarm-item {
  border: 1px solid var(--line);
  border-left: 5px solid var(--warn);
  border-radius: 14px;
  padding: 12px 14px;
  background: #fffdfa;
}

.alarm-item.danger {
  border-left-color: var(--danger);
  background: #fff8f7;
}

.alarm-item .category {
  font-weight: 700;
  margin-bottom: 4px;
}

.small {
  color: var(--muted);
  font-size: 0.9rem;
}

.path-list {
  display: grid;
  gap: 8px;
}

.path-row {
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 10px 12px;
  background: #fbfdff;
}

.scroll-box {
  max-height: 260px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: #fbfdff;
}

.detail-table {
  width: 100%;
  border-collapse: collapse;
}

.detail-table th,
.detail-table td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
  text-align: left;
  vertical-align: top;
}

.detail-table th {
  position: sticky;
  top: 0;
  background: #f7faff;
  color: var(--muted);
  font-size: 0.84rem;
}

.task-details summary {
  cursor: pointer;
  color: var(--accent-2);
  font-weight: 800;
}

.info-note {
  margin-top: 10px;
  color: var(--muted);
  font-size: 0.88rem;
}

.rule-list {
  display: grid;
  gap: 10px;
}

.rule-item {
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: #fbfdff;
}

.step-matrix-shell {
  display: grid;
  gap: 12px;
}

.step-matrix-meta {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.step-matrix-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.summary-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 10px;
  border-radius: 999px;
  border: 1px solid rgba(66, 103, 213, 0.12);
  background: var(--accent-soft);
  color: var(--accent-2);
  font-size: 0.82rem;
  font-weight: 700;
}

.step-matrix-wrap {
  max-height: 680px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: #fbfdff;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7);
}

.step-matrix-table {
  width: 100%;
  min-width: 760px;
  border-collapse: separate;
  border-spacing: 0;
}

.step-matrix-table th,
.step-matrix-table td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
  border-right: 1px solid rgba(219, 228, 238, 0.9);
  text-align: center;
  vertical-align: middle;
}

.step-matrix-table th:last-child,
.step-matrix-table td:last-child {
  border-right: 0;
}

.step-matrix-table thead th {
  position: sticky;
  top: 0;
  z-index: 2;
  background: #f6f9ff;
  color: var(--muted);
  font-size: 0.84rem;
}

.step-matrix-table .subject-col {
  position: sticky;
  left: 0;
  z-index: 1;
  min-width: 180px;
  text-align: left;
  background: #fbfdff;
  font-weight: 700;
  box-shadow: 14px 0 22px rgba(15, 23, 42, 0.06);
}

.step-matrix-table thead .subject-col {
  z-index: 3;
  background: #f6f9ff;
  box-shadow: 14px 0 22px rgba(15, 23, 42, 0.08);
}

.step-matrix-table tbody tr:hover td {
  background: rgba(66, 103, 213, 0.06);
}

.step-matrix-table tbody tr:hover .subject-col {
  background: #f3f7ff;
}

.step-cell {
  min-width: 84px;
  font-weight: 700;
  font-size: 0.8rem;
}

.step-cell.is-ready {
  color: var(--good);
  background: rgba(6, 118, 71, 0.10);
}

.step-cell.is-missing {
  color: var(--muted);
  background: rgba(152, 162, 179, 0.16);
}

.step-cell.is-failed {
  color: var(--danger);
  background: rgba(196, 50, 10, 0.12);
}

.step-cell.is-na {
  color: var(--muted);
  background: rgba(152, 162, 179, 0.10);
}

.step-cell .step-state {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 54px;
}

.inline-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.inline-controls label {
  color: var(--muted);
  font-size: 0.86rem;
  font-weight: 700;
}

.inline-controls select {
  background: #fff;
  border: 1px solid var(--line);
  color: var(--text);
  border-radius: 12px;
  padding: 8px 12px;
  min-width: 120px;
  max-width: 100%;
}

.segment-description {
  word-break: break-word;
  overflow-wrap: anywhere;
}

.footer {
  margin-top: 28px;
  color: var(--muted);
  font-size: 0.9rem;
}

.stat-bar-list {
  display: grid;
  gap: 12px;
}

.stat-bar-label {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 6px;
  font-size: 0.9rem;
}

.stat-bar-track {
  height: 10px;
  width: 100%;
  background: #edf2f7;
  border-radius: 999px;
  overflow: hidden;
}

.stat-bar-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--accent), #7b9cff);
}

.snapshot-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.snapshot-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: 999px;
  padding: 5px 9px;
  font-size: 0.76rem;
  font-weight: 700;
  white-space: nowrap;
}

.snapshot-item.good {
  background: var(--good-soft);
  color: var(--good);
}

.snapshot-item.missing {
  background: var(--panel-soft);
  color: var(--muted);
}

.snapshot-item.failed {
  background: var(--danger-soft);
  color: var(--danger);
}

.snapshot-item.neutral {
  background: #eef2f6;
  color: #667085;
}

.snapshot-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: currentColor;
}

.subject-table-controls {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.pager {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.pager button {
  border: 1px solid var(--line);
  background: #fff;
  color: var(--text);
  border-radius: 12px;
  padding: 8px 12px;
  cursor: pointer;
  font-weight: 600;
}

.pager button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.table-count {
  color: var(--muted);
  font-size: 0.9rem;
}

.table-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
}

.legend-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 10px;
  border-radius: 999px;
  font-size: 0.82rem;
  border: 1px solid var(--line);
  background: #fff;
  color: var(--muted);
}

.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
}

.legend-dot.warn {
  background: var(--warn);
}

.legend-dot.fail {
  background: var(--danger);
}

.top-subject-list {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}

.top-subject-item {
  border: 1px solid var(--line);
  background: #fbfdff;
  border-radius: 14px;
  padding: 12px 14px;
  min-width: 0;
}

.top-subject-item strong {
  display: block;
  margin-bottom: 6px;
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 12px;
}

.hide {
  display: none !important;
}

@media (max-width: 1024px) {
  .two-col {
    grid-template-columns: 1fr;
  }

  .dashboard-grid {
    grid-template-columns: 1fr;
  }

  .filter-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .control-group.search-control {
    grid-column: span 2;
  }
}

@media (max-width: 720px) {
  .container {
    width: min(100% - 24px, 1500px);
    padding-top: 18px;
  }

  .hero {
    padding: 22px 18px;
    border-radius: 22px;
  }

  .hero h1 {
    font-size: 1.55rem;
  }

  th,
  td {
    padding: 10px 8px;
  }

  .subject-table-controls {
    align-items: stretch;
  }

  .toolbar input,
  .toolbar select {
    min-width: 0;
    width: 100%;
  }

  .pager {
    width: 100%;
  }

  .step-matrix-meta {
    flex-direction: column;
  }

  .inline-controls {
    width: 100%;
  }

  .filter-grid {
    grid-template-columns: 1fr;
  }

  .control-group.search-control {
    grid-column: span 1;
  }

  .quality-score-controls {
    grid-column: span 1;
  }

  .coreg-stage-header {
    flex-direction: column;
  }

  .coreg-stage-images {
    grid-template-columns: 1fr;
  }

  .filter-panel {
    padding: 14px;
  }

  .panel.workflow-panel {
    padding: 14px;
  }

  .workflow-svg-wrap {
    padding: 10px;
  }

  .workflow-detail-group,
  .workflow-detail-group-paths {
    grid-column: 1 / -1;
  }

  .workflow-detail-row,
  .workflow-detail-group-paths .workflow-detail-row {
    grid-template-columns: 1fr;
    gap: 4px;
  }

  .workflow-detail-group-normative-qc .workflow-detail-list {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 440px) {
  .quality-score-controls {
    grid-template-columns: 1fr;
  }
}
"""

REPORT_JS = """
function normalizeText(value) {
  return (value || "").toString().toLowerCase();
}

function toNumber(value, fallback = -1) {
  if (value === undefined || value === null || value.toString().trim() === "") {
    return fallback;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function escapeHtml(value) {
  return (value || "").toString()
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatFixed(value, digits = 0, suffix = "") {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return "N/A";
  }
  return `${parsed.toFixed(digits)}${suffix}`;
}

function boolFromDataset(value) {
  return value === "1" || value === "true";
}

function getJsonScriptData(elementId) {
  const element = document.getElementById(elementId);
  if (!element) {
    return [];
  }
  try {
    return JSON.parse(element.textContent || "[]");
  } catch (error) {
    console.error(`Failed to parse JSON payload from ${elementId}`, error);
    return [];
  }
}

const STEP_MATRIX_DEFS = [
  { key: "quality_score", label: "QC score" },
  { key: "basic_preproc", label: "Basic preprocessing" },
  { key: "artifacts", label: "Artifacts" },
  { key: "ica", label: "ICA" },
  { key: "epochs", label: "Epochs" },
  { key: "covariance", label: "Cov" },
  { key: "coregistration", label: "MEG-MRI coregistration" },
  { key: "headmodel", label: "Head model" },
  { key: "source", label: "Source" },
];

function getStepDatasetValue(row, stepKey) {
  const datasetKey = `step${stepKey.charAt(0).toUpperCase()}${stepKey.slice(1)}`;
  return row.dataset[datasetKey];
}

function getSubjectTableState() {
  if (!window.__subjectTableState) {
    window.__subjectTableState = { page: 1, sortKey: "risk", sortDirection: "desc" };
  }
  return window.__subjectTableState;
}

function getBadSegmentTableState() {
  if (!window.__badSegmentTableState) {
    window.__badSegmentTableState = { page: 1 };
  }
  return window.__badSegmentTableState;
}

function updateStepMatrix(matchedRows, visibleRows) {
  const container = document.getElementById("stepCompletionMatrix");
  if (!container) {
    return;
  }

  const info = document.getElementById("stepMatrixInfo");
  const summary = document.getElementById("stepMatrixSummary");
  if (!matchedRows.length) {
    if (info) {
      info.textContent = "No subjects match the current homepage filters.";
    }
    if (summary) {
      summary.innerHTML = "";
    }
    container.innerHTML = '<div class="small">No subjects available for the current filter combination.</div>';
    return;
  }

  if (info) {
    info.textContent = `Heat matrix shows the current page slice (${visibleRows.length} of ${matchedRows.length} matched subjects).`;
  }

  if (summary) {
    summary.innerHTML = STEP_MATRIX_DEFS.map((step) => {
      const expectedRows = matchedRows.filter((row) => getStepDatasetValue(row, step.key) !== "na");
      if (!expectedRows.length) {
        return `<span class="summary-chip">${escapeHtml(step.label)} N/A</span>`;
      }
      const count = expectedRows.filter((row) => boolFromDataset(getStepDatasetValue(row, step.key))).length;
      return `<span class="summary-chip">${escapeHtml(step.label)} ${count}/${expectedRows.length}</span>`;
    }).join("");
  }

  const header = STEP_MATRIX_DEFS.map((step) => `<th>${escapeHtml(step.label)}</th>`).join("");
  const body = visibleRows.map((row) => {
    const subjectName = row.dataset.subject || "Unknown";
    const subjectUrl = row.dataset.subjectUrl || "#";
    const cells = STEP_MATRIX_DEFS.map((step) => {
      const stepValue = getStepDatasetValue(row, step.key);
      if (stepValue === "na") {
        return `<td class="step-cell is-na" title="${escapeHtml(`${subjectName}: ${step.label} N/A`)}"><span class="step-state">N/A</span></td>`;
      }
      if (stepValue === "failed") {
        return `<td class="step-cell is-failed" title="${escapeHtml(`${subjectName}: ${step.label} Failed`)}"><span class="step-state">Failed</span></td>`;
      }
      const isReady = boolFromDataset(stepValue);
      const label = isReady ? "READY" : "N/A";
      const cssClass = isReady ? "is-ready" : "is-missing";
      return `<td class="step-cell ${cssClass}" title="${escapeHtml(`${subjectName}: ${step.label} ${isReady ? "ready" : "N/A"}`)}"><span class="step-state">${label}</span></td>`;
    }).join("");
    return `<tr><td class="subject-col"><a href="${escapeHtml(subjectUrl)}">${escapeHtml(subjectName)}</a></td>${cells}</tr>`;
  }).join("");

  container.innerHTML = `
    <div class="step-matrix-wrap">
      <table class="step-matrix-table">
        <thead>
          <tr>
            <th class="subject-col">Subject</th>
            ${header}
          </tr>
        </thead>
        <tbody>
          ${body}
        </tbody>
      </table>
    </div>
  `;
}

function getDefaultSortDirection(sortKey) {
  return sortKey === "subject" || sortKey === "status" ? "asc" : "desc";
}

function getSortColumnIndex(sortKey) {
  const columnMap = {
    subject: 1,
    status: 2,
    quality_score: 3,
    alarm_count: 4,
    bad_channels: 5,
    bad_segments: 6,
    marked_ica: 7,
    coreg_mean: 8,
    coreg_max: 9,
    epoch_reject: 10,
  };
  return columnMap[sortKey] || null;
}

function statusRank(status) {
  const rankMap = { fail: 0, warn: 1, pass: 2 };
  return rankMap[normalizeText(status)] ?? 3;
}

function compareSubjectRows(a, b, sortKey, direction) {
  let result = 0;
  if (sortKey === "subject") {
    result = normalizeText(a.dataset.subject).localeCompare(normalizeText(b.dataset.subject));
  } else if (sortKey === "status") {
    result = statusRank(a.dataset.status) - statusRank(b.dataset.status);
  } else if (sortKey === "quality_score") {
    result = toNumber(a.dataset.qualityScore) - toNumber(b.dataset.qualityScore);
  } else if (sortKey === "alarm_count") {
    result = toNumber(a.dataset.alarmCount) - toNumber(b.dataset.alarmCount);
  } else if (sortKey === "bad_channels") {
    result = toNumber(a.dataset.badChannels) - toNumber(b.dataset.badChannels);
  } else if (sortKey === "bad_segments") {
    result = toNumber(a.dataset.badSegments) - toNumber(b.dataset.badSegments);
  } else if (sortKey === "marked_ica") {
    result = toNumber(a.dataset.markedIca) - toNumber(b.dataset.markedIca);
  } else if (sortKey === "coreg_mean") {
    result = toNumber(a.dataset.coregMean) - toNumber(b.dataset.coregMean);
  } else if (sortKey === "coreg_max") {
    result = toNumber(a.dataset.coregMax) - toNumber(b.dataset.coregMax);
  } else if (sortKey === "epoch_reject") {
    result = toNumber(a.dataset.epochReject) - toNumber(b.dataset.epochReject);
  } else if (sortKey === "missing_steps") {
    result = toNumber(a.dataset.missingCount) - toNumber(b.dataset.missingCount);
  } else {
    result = toNumber(a.dataset.riskScore) - toNumber(b.dataset.riskScore);
  }

  if (result === 0) {
    result = normalizeText(a.dataset.subject).localeCompare(normalizeText(b.dataset.subject));
  }
  return direction === "asc" ? result : -result;
}

function syncSubjectSortUI() {
  const state = getSubjectTableState();
  const select = document.getElementById("subjectSortBy");
  if (select && select.value !== state.sortKey) {
    select.value = state.sortKey;
  }

  const activeColumnIndex = getSortColumnIndex(state.sortKey);

  document.querySelectorAll("#subjectTable th.sortable").forEach((cell) => {
    const button = cell.querySelector("[data-sort-key]");
    const isActive = button && button.dataset.sortKey === state.sortKey;
    cell.classList.toggle("active-sort", Boolean(isActive));
  });

  document.querySelectorAll("#subjectTable tbody tr").forEach((row) => {
    row.querySelectorAll("td").forEach((cell, index) => {
      cell.classList.toggle("active-sort-cell", activeColumnIndex !== null && index + 1 === activeColumnIndex);
    });
  });

  document.querySelectorAll("#subjectTable [data-sort-key]").forEach((button) => {
    const isActive = button.dataset.sortKey === state.sortKey;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-sort", isActive ? state.sortDirection : "none");
    const indicator = button.querySelector(".sort-indicator");
    if (indicator) {
      indicator.textContent = !isActive ? "↕" : state.sortDirection === "asc" ? "↑" : "↓";
    }
  });
}

function setSubjectSort(sortKey) {
  const state = getSubjectTableState();
  if (state.sortKey === sortKey) {
    state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
  } else {
    state.sortKey = sortKey;
    state.sortDirection = getDefaultSortDirection(sortKey);
  }
  state.page = 1;
  syncSubjectSortUI();
  updateSubjectTable();
  updateAlarmBoard();
}

function setSubjectSortFromSelect() {
  const selectedKey = normalizeText(document.getElementById("subjectSortBy")?.value || "risk");
  const state = getSubjectTableState();
  state.sortKey = selectedKey;
  state.sortDirection = getDefaultSortDirection(selectedKey);
  state.page = 1;
  syncSubjectSortUI();
  updateSubjectTable();
  updateAlarmBoard();
}

function updateSubjectTable() {
  const table = document.getElementById("subjectTable");
  if (!table) {
    return;
  }

  const state = getSubjectTableState();
  const query = normalizeText(document.getElementById("subjectSearch")?.value);
  const status = normalizeText(document.getElementById("subjectStatusFilter")?.value || "all");
  const missingStep = normalizeText(document.getElementById("subjectMissingStepFilter")?.value || "all");
  const qualityMode = normalizeText(document.getElementById("qualityScoreMode")?.value || "all");
  const qualityThreshold = toNumber(document.getElementById("qualityScoreThreshold")?.value, 70);
  const pageSize = parseInt(document.getElementById("subjectPageSize")?.value || "20", 10);
  const rows = Array.from(table.querySelectorAll("tbody tr[data-search]"));
  const sortBy = state.sortKey || normalizeText(document.getElementById("subjectSortBy")?.value || "risk");
  const sortDirection = state.sortDirection || getDefaultSortDirection(sortBy);
  state.sortKey = sortBy;
  state.sortDirection = sortDirection;

  const matchedRows = rows.filter((row) => {
    const haystack = normalizeText(row.dataset.search);
    const rowStatus = normalizeText(row.dataset.status);
    const rowMissing = normalizeText(row.dataset.missingSteps || "");
    const rowQualityScore = toNumber(row.dataset.qualityScore, NaN);
    const queryMatch = !query || haystack.includes(query);
    const statusMatch = status === "all" || rowStatus === status;
    const missingMatch = missingStep === "all" || rowMissing.includes(missingStep);
    let qualityMatch = true;
    if (qualityMode === "gte") {
      qualityMatch = Number.isFinite(rowQualityScore) && rowQualityScore >= qualityThreshold;
    } else if (qualityMode === "lt") {
      qualityMatch = Number.isFinite(rowQualityScore) && rowQualityScore < qualityThreshold;
    } else if (qualityMode === "missing") {
      qualityMatch = !Number.isFinite(rowQualityScore);
    }
    return queryMatch && statusMatch && missingMatch && qualityMatch;
  });

  matchedRows.sort((a, b) => {
    return compareSubjectRows(a, b, sortBy, sortDirection);
  });

  const totalPages = Math.max(1, Math.ceil(matchedRows.length / pageSize));
  if (state.page > totalPages) {
    state.page = totalPages;
  }
  if (state.page < 1) {
    state.page = 1;
  }

  rows.forEach((row) => row.classList.add("hide"));
  const tbody = table.querySelector("tbody");
  if (tbody) {
    matchedRows.forEach((row) => tbody.appendChild(row));
  }
  const start = (state.page - 1) * pageSize;
  const end = start + pageSize;
  const visibleRows = matchedRows.slice(start, end);
  visibleRows.forEach((row) => row.classList.remove("hide"));

  const pageInfo = document.getElementById("subjectPageInfo");
  if (pageInfo) {
    pageInfo.textContent = `Page ${state.page} / ${totalPages}`;
  }

  const countInfo = document.getElementById("subjectCountInfo");
  if (countInfo) {
    countInfo.textContent = `Showing ${matchedRows.length === 0 ? 0 : start + 1}-${Math.min(end, matchedRows.length)} of ${matchedRows.length} matched subjects`;
  }

  const prevBtn = document.getElementById("subjectPrevBtn");
  const nextBtn = document.getElementById("subjectNextBtn");
  if (prevBtn) {
    prevBtn.disabled = state.page <= 1;
  }
  if (nextBtn) {
    nextBtn.disabled = state.page >= totalPages;
  }

  syncSubjectSortUI();
  updateStepMatrix(matchedRows, visibleRows);
}

function setSubjectPage(delta) {
  const state = getSubjectTableState();
  state.page += delta;
  updateSubjectTable();
  updateAlarmBoard();
}

function resetSubjectPage() {
  const state = getSubjectTableState();
  state.page = 1;
  updateSubjectTable();
  updateAlarmBoard();
}

function filterAlarmRows(inputId, listId) {
  updateAlarmBoard();
}

function updateAlarmBoard() {
  const list = document.getElementById("alarmBoard");
  if (!list) {
    return;
  }
  const query = normalizeText(document.getElementById("alarmSearch")?.value);
  const limit = parseInt(document.getElementById("subjectPageSize")?.value || "20", 10);
  const rows = Array.from(list.querySelectorAll(".alarm-row[data-search]"));
  const matchedRows = rows.filter((row) => {
    const haystack = normalizeText(row.dataset.search);
    return !query || haystack.includes(query);
  });

  rows.forEach((row) => row.classList.add("hide"));
  matchedRows.slice(0, limit).forEach((row) => row.classList.remove("hide"));

  const countInfo = document.getElementById("alarmCountInfo");
  if (countInfo) {
    countInfo.textContent = `Showing ${Math.min(limit, matchedRows.length)} of ${matchedRows.length} QC alerts`;
  }
}

function renderBadSegmentTable() {
  const body = document.getElementById("badSegmentTableBody");
  if (!body) {
    return;
  }

  const rows = getJsonScriptData("badSegmentRows").slice().sort((a, b) => {
    const onsetDelta = toNumber(a.onset_sec, 0) - toNumber(b.onset_sec, 0);
    if (onsetDelta !== 0) {
      return onsetDelta;
    }
    return toNumber(a.duration_sec, 0) - toNumber(b.duration_sec, 0);
  });
  const pageSize = parseInt(document.getElementById("badSegmentPageSize")?.value || "20", 10);
  const state = getBadSegmentTableState();
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  if (state.page > totalPages) {
    state.page = totalPages;
  }
  if (state.page < 1) {
    state.page = 1;
  }

  const start = (state.page - 1) * pageSize;
  const end = start + pageSize;
  const visibleRows = rows.slice(start, end);

  if (!visibleRows.length) {
    body.innerHTML = '<tr><td colspan="4" class="small">No bad segments listed.</td></tr>';
  } else {
    body.innerHTML = visibleRows.map((row) => `
      <tr>
        <td>${escapeHtml(row.index)}</td>
        <td>${formatFixed(row.onset_sec, 3, " s")}</td>
        <td>${formatFixed(row.duration_sec, 3, " s")}</td>
        <td class="segment-description">${escapeHtml(row.description)}</td>
      </tr>
    `).join("");
  }

  const countInfo = document.getElementById("badSegmentCountInfo");
  if (countInfo) {
    countInfo.textContent = `Showing ${rows.length === 0 ? 0 : start + 1}-${Math.min(end, rows.length)} of ${rows.length} bad segments`;
  }

  const pageInfo = document.getElementById("badSegmentPageInfo");
  if (pageInfo) {
    pageInfo.textContent = `Page ${state.page} / ${totalPages}`;
  }

  const prevBtn = document.getElementById("badSegmentPrevBtn");
  const nextBtn = document.getElementById("badSegmentNextBtn");
  if (prevBtn) {
    prevBtn.disabled = state.page <= 1;
  }
  if (nextBtn) {
    nextBtn.disabled = state.page >= totalPages;
  }
}

function setBadSegmentPage(delta) {
  const state = getBadSegmentTableState();
  state.page += delta;
  renderBadSegmentTable();
}

function resetBadSegmentPage() {
  const state = getBadSegmentTableState();
  state.page = 1;
  renderBadSegmentTable();
}

document.addEventListener("DOMContentLoaded", () => {
  syncSubjectSortUI();
  updateSubjectTable();
  updateAlarmBoard();
  renderBadSegmentTable();
});
"""


@dataclass
class AssetRecord:
    title: str
    rel_path: str
    category: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a portable static HTML report package from MEGFlow outputs."
    )
    parser.add_argument(
        "--report_root",
        required=True,
        help="Root report directory that contains the preprocessed outputs.",
    )
    parser.add_argument(
        "--output_dir",
        default=None,
        help="Directory to write the static report package. Defaults to <report_root>/static_html_report.",
    )
    parser.add_argument(
        "--bad_channel_threshold",
        type=int,
        default=DEFAULT_THRESHOLDS["bad_channel_threshold"],
        help="Alarm threshold for bad channels.",
    )
    parser.add_argument(
        "--bad_segment_threshold",
        type=int,
        default=DEFAULT_THRESHOLDS["bad_segment_threshold"],
        help="Alarm threshold for bad segments.",
    )
    parser.add_argument(
        "--coreg_mean_threshold",
        type=float,
        default=DEFAULT_THRESHOLDS["coreg_mean_threshold"],
        help="Alarm threshold for coregistration mean distance in mm.",
    )
    parser.add_argument(
        "--coreg_max_threshold",
        type=float,
        default=DEFAULT_THRESHOLDS["coreg_max_threshold"],
        help="Alarm threshold for coregistration max distance in mm.",
    )
    parser.add_argument(
        "--epoch_reject_rate_threshold",
        type=float,
        default=DEFAULT_THRESHOLDS["epoch_reject_rate_threshold"],
        help="Alarm threshold for epoch rejection rate, 0-1.",
    )
    parser.add_argument(
        "--megqc_alarm_score",
        type=float,
        default=DEFAULT_THRESHOLDS["megqc_alarm_score"],
        help="Alarm threshold for Normative Reference MEG QC score, 0-100; lower scores are flagged.",
    )
    parser.add_argument(
        "--artifact_overview_duration",
        type=float,
        default=DEFAULT_THRESHOLDS["artifact_overview_duration"],
        help="Seconds represented by the single Artifact Review overview plot in the static report.",
    )
    parser.add_argument(
        "--zip_output",
        type=str,
        default="false",
        help="Whether to create a zip archive next to the output directory. true/false.",
    )
    parser.add_argument(
        "--task_log_mode",
        choices=["failed", "all-command-log", "none"],
        default="failed",
        help=(
            "How much Nextflow .command* log content to bundle for Task Details. "
            "failed: copy .command.err/.command.log/.command.out only for failed or ignored tasks. "
            "all-command-log: also copy .command.log for successful tasks. "
            "none: do not copy .command* logs."
        ),
    )
    return parser.parse_args()


def str_to_bool(value: str) -> bool:
    value = str(value).strip().lower()
    if value in {"true", "t", "1", "yes", "y"}:
        return True
    if value in {"false", "f", "0", "no", "n"}:
        return False
    raise ValueError(f"Unsupported boolean value: {value}")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def sanitize_name(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip())
    return safe.strip("._") or "subject"


def html_text(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(v) for v in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        try:
            return json_ready(value.item())
        except Exception:
            pass
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return str(value)


def json_script_text(value: Any) -> str:
    return json.dumps(json_ready(value), ensure_ascii=False, allow_nan=False).replace("</", "<\\/")


def fmt_float(value: Any, digits: int = 2, suffix: str = "") -> str:
    if value is None or value == "":
        return "N/A"
    try:
        return f"{float(value):.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return html_text(value)


def fmt_metric_value(value: Any, digits: int = 4) -> str:
    if value is None or value == "":
        return "N/A"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return html_text(value)
    if not math.isfinite(number):
        return "N/A"
    abs_number = abs(number)
    if number != 0 and (abs_number < 10 ** -digits or abs_number >= 10 ** (digits + 2)):
        return f"{number:.{digits}e}"
    return f"{number:.{digits}g}"


def fmt_int(value: Any) -> str:
    if value is None or value == "":
        return "N/A"
    try:
        return f"{int(value)}"
    except (TypeError, ValueError):
        return html_text(value)


def pick_evenly_spaced(items: list[Path], max_items: int) -> list[Path]:
    if len(items) <= max_items:
        return items
    if max_items <= 1:
        return [items[0]]
    indexes = []
    last_index = len(items) - 1
    for i in range(max_items):
        idx = round(i * last_index / (max_items - 1))
        if idx not in indexes:
            indexes.append(idx)
    return [items[idx] for idx in indexes]


def read_lines(file_path: Path) -> list[str]:
    if not file_path.exists():
        return []
    with open(file_path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f.readlines() if line.strip()]


def safe_json(file_path: Path) -> dict[str, Any]:
    if not file_path.exists():
        return {}
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def coreg_asset_sort_key(file_path: Path) -> tuple[int, int, str]:
    stem = file_path.stem
    for step_idx, step in enumerate(COREG_ASSET_STEPS):
        for view_idx, view_suffix in enumerate(COREG_ASSET_VIEW_SUFFIXES):
            token = f"{step}{view_suffix}"
            if stem == token or stem.endswith(f"_{token}"):
                return (step_idx, view_idx, stem)
    return (len(COREG_ASSET_STEPS), len(COREG_ASSET_VIEW_SUFFIXES), stem)


def copy_asset(src: Path, output_root: Path, subject_slug: str, category: str) -> str:
    ext = src.suffix.lower()
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".json", ".csv", ".txt", ".jl", ".html"}:
        category_dir = ensure_dir(output_root / "files" / subject_slug / category)
        dest = category_dir / src.name
        shutil.copy2(src, dest)
        return dest.relative_to(output_root).as_posix()
    raise ValueError(f"Unsupported asset type for copy: {src}")


def copy_asset_as(src: Path, output_root: Path, subject_slug: str, category: str, file_name: str) -> str:
    ext = src.suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".json", ".csv", ".txt", ".jl", ".html"}:
        raise ValueError(f"Unsupported asset type for copy: {src}")
    category_dir = ensure_dir(output_root / "files" / subject_slug / category)
    safe_name = sanitize_name(Path(file_name).stem) + ext
    dest = category_dir / safe_name
    shutil.copy2(src, dest)
    return dest.relative_to(output_root).as_posix()


def copy_text_blob(text: str, output_root: Path, rel_path: Path) -> str:
    dest = output_root / rel_path
    ensure_dir(dest.parent)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(text)
    return dest.relative_to(output_root).as_posix()


def finite_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if pd.notna(out) else None


def direction_label(mode: str, direction: str = "") -> str:
    text = f"{mode} {direction}".lower()
    if "lower" in text:
        return "Lower is better"
    if "higher" in text:
        return "Higher is better"
    return "Closer to reference median is better"


def find_quality_score_files(qc_dir: Path) -> tuple[Path | None, Path | None, Path | None]:
    summary_file = next(iter(sorted(qc_dir.glob("*.summary.json"))), None)
    component_file = next(iter(sorted(qc_dir.glob("*.component_scores.csv"))), None)
    reference_plot = next(iter(sorted(qc_dir.glob("*.reference_position.png"))), None)
    return summary_file, component_file, reference_plot


def read_quality_components(component_file: Path | None, max_rows: int = 24) -> list[dict[str, Any]]:
    if not component_file or not component_file.is_file():
        return []
    try:
        df = pd.read_csv(component_file)
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for _, row in df.head(max_rows).iterrows():
        mode = str(row.get("mode", ""))
        direction = str(row.get("direction", ""))
        rows.append(
            {
                "family": row.get("family", ""),
                "domain": row.get("domain", ""),
                "metric": row.get("metric", ""),
                "raw_value": finite_float(row.get("raw_value")),
                "q05": finite_float(row.get("q05")),
                "q50": finite_float(row.get("q50")),
                "q95": finite_float(row.get("q95")),
                "reference_scope_used": row.get("reference_scope_used", ""),
                "reference_device": row.get("reference_device", ""),
                "reference_category": row.get("reference_category", ""),
                "component_score_0_1": finite_float(row.get("component_score_0_1")),
                "status": row.get("status", ""),
                "mode": mode,
                "direction": direction,
                "direction_label": direction_label(mode, direction),
                "interpretation": row.get("interpretation", ""),
            }
        )
    return rows


def collect_quality_score_data(
    subject: str,
    preprocessed_dir: Path,
    output_root: Path,
    subject_slug: str,
) -> dict[str, Any]:
    qc_dir = preprocessed_dir / "quality_control" / subject
    summary_file, component_file, reference_plot = find_quality_score_files(qc_dir)
    summary_json = safe_json(summary_file) if summary_file else {}
    score = finite_float(summary_json.get("score_0_100"))
    component_rows = read_quality_components(component_file)
    quality_data: dict[str, Any] = {
        "exists": bool(summary_file or component_file or reference_plot),
        "raw_file": summary_json.get("raw_file", ""),
        "score_0_100": score,
        "score_scale": summary_json.get("score_scale", "0-100; higher is better"),
        "score_higher_is_better": bool(summary_json.get("score_higher_is_better", True)),
        "model": summary_json.get("model", ""),
        "device_type": summary_json.get("device_type", ""),
        "category": summary_json.get("category", ""),
        "reference_scope": summary_json.get("reference_scope", ""),
        "processing_min_score": summary_json.get("processing_min_score"),
        "alarm_score_threshold": summary_json.get("alarm_score_threshold"),
        "passed_processing_threshold": summary_json.get("passed_processing_threshold"),
        "quality_alarm": summary_json.get("quality_alarm"),
        "status": summary_json.get("status", ""),
        "error": summary_json.get("error", ""),
        "reference_preprocessing": summary_json.get("reference_preprocessing", []),
        "bad_channel_policy": summary_json.get("bad_channel_policy", ""),
        "bad_annotation_policy": summary_json.get("bad_annotation_policy", ""),
        "family_scores": summary_json.get("family_scores", []),
        "components": component_rows,
        "files": {},
    }
    if summary_file and summary_file.is_file():
        quality_data["files"]["summary_json"] = copy_asset(summary_file, output_root, subject_slug, "quality_score")
    if component_file and component_file.is_file():
        quality_data["files"]["component_scores_csv"] = copy_asset(component_file, output_root, subject_slug, "quality_score")
    if reference_plot and reference_plot.is_file():
        quality_data["reference_plot_rel"] = copy_asset(reference_plot, output_root, subject_slug, "quality_score")
    return quality_data


def find_subjects(preprocessed_dir: Path) -> list[str]:
    subjects: set[str] = set()

    if preprocessed_dir.exists():
        for item in preprocessed_dir.iterdir():
            if item.is_dir() and list(item.glob("*_preproc-raw.fif")):
                subjects.add(item.name)

    for step_name in [
        "quality_control",
        "artifact_report",
        "ica_report",
        "trans",
        "epochs",
        "covariance",
        "source_recon",
        "forward_solution",
    ]:
        step_dir = preprocessed_dir / step_name
        if step_dir.exists():
            for item in step_dir.iterdir():
                if item.is_dir():
                    subjects.add(item.name)

    return sorted(subjects)


def parse_trace_task_name(name: str) -> tuple[str, str | None]:
    match = re.match(r"^(?P<process>.+?)\s+\((?P<tag>.+)\)$", name.strip())
    if match:
        return match.group("process").strip(), match.group("tag").strip()
    return name.strip(), None


def trace_task_failed(row: dict[str, str]) -> bool:
    status = (row.get("status") or "").strip().upper()
    exit_value = (row.get("exit") or "").strip()
    if exit_value not in {"", "-", "0"}:
        return True
    return bool(status and status not in SUCCESS_TRACE_STATUSES)


def filter_retried_trace_failures(tasks_by_subject: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """Hide failed attempts when the same process/tag later completed after retry."""
    for subject, tasks in tasks_by_subject.items():
        successful_identities = {
            (task.get("process") or "", task.get("tag") or "")
            for task in tasks
            if not task.get("failed")
        }
        if not successful_identities:
            continue
        tasks_by_subject[subject] = [
            task
            for task in tasks
            if not (task.get("failed") and (task.get("process") or "", task.get("tag") or "") in successful_identities)
        ]
    return tasks_by_subject


def trace_tag_dataset_and_subject(tag: str | None) -> tuple[str | None, str | None]:
    if not tag:
        return None, None
    if ":" not in tag:
        return None, tag
    dataset_name, subject_tag = tag.split(":", 1)
    return dataset_name.strip() or None, subject_tag.strip() or None


def manifest_dataset_name(manifest: dict[str, Any] | None) -> str | None:
    params_snapshot = manifest.get("params_snapshot") if isinstance(manifest, dict) else None
    if not isinstance(params_snapshot, dict):
        return None
    dataset_name = params_snapshot.get("dataset_name")
    if dataset_name in (None, ""):
        return None
    return str(dataset_name)


def trace_tag_matches_dataset(tag: str | None, dataset_name: str | None) -> bool:
    if not dataset_name:
        return True
    tag_dataset, _ = trace_tag_dataset_and_subject(tag)
    if not tag_dataset:
        return True
    return sanitize_name(tag_dataset) == sanitize_name(dataset_name)


def match_task_subject(tag: str | None, subjects: list[str], dataset_name: str | None = None) -> str | None:
    if not tag:
        return None
    if not trace_tag_matches_dataset(tag, dataset_name):
        return None
    _, subject_tag = trace_tag_dataset_and_subject(tag)
    tag_norm = sanitize_name(subject_tag or tag)
    for subject in subjects:
        subject_norm = sanitize_name(subject)
        if tag_norm == subject_norm or tag_norm.startswith(subject_norm) or subject_norm in tag_norm:
            return subject
    return None


def find_trace_files(report_root: Path, preprocessed_dir: Path, manifest: dict[str, Any] | None = None) -> list[Path]:
    candidates: list[Path] = []
    launch_candidates: list[Path] = []
    for base in [report_root, report_root.parent, preprocessed_dir / "logs"]:
        if base.exists():
            candidates.extend(base.glob("trace*.txt"))
            candidates.extend(base.glob("trace*.tsv"))
    params_snapshot = manifest.get("params_snapshot") if isinstance(manifest, dict) else None
    if isinstance(params_snapshot, dict) and params_snapshot.get("output_dir"):
        output_dir = Path(str(params_snapshot["output_dir"]))
        for base in [
            output_dir,
            output_dir.parent,
            output_dir.parent.parent,
        ]:
            if base.exists():
                candidates.extend(base.glob("trace*.txt"))
                candidates.extend(base.glob("trace*.tsv"))
                candidates.extend(base.glob("*trace*.txt"))
                candidates.extend(base.glob("*trace*.tsv"))
    workflow_meta = manifest.get("workflow_meta") if isinstance(manifest, dict) else None
    if isinstance(workflow_meta, dict) and workflow_meta.get("launch_dir"):
        launch_dir = Path(str(workflow_meta["launch_dir"]))
        if launch_dir.exists():
            launch_candidates.extend(launch_dir.glob("trace*.txt"))
            launch_candidates.extend(launch_dir.glob("trace*.tsv"))
    if not candidates:
        candidates.extend(launch_candidates)
    seen: set[Path] = set()
    trace_files: list[Path] = []
    for path in sorted(candidates):
        resolved = path.resolve()
        if resolved not in seen and path.is_file():
            trace_files.append(path)
            seen.add(resolved)
    return trace_files


def infer_work_roots(report_root: Path, preprocessed_dir: Path, manifest: dict[str, Any] | None) -> list[Path]:
    roots = [
        report_root / "work",
        report_root.parent / "work",
        report_root.parent.parent / "work" / report_root.name,
        preprocessed_dir.parent / "work",
    ]
    params_snapshot = manifest.get("params_snapshot") if isinstance(manifest, dict) else None
    if isinstance(params_snapshot, dict) and params_snapshot.get("output_dir"):
        output_dir = Path(str(params_snapshot["output_dir"]))
        roots.append(output_dir / "work")
        roots.append(output_dir.parent.parent / "work")
        roots.append(output_dir.parent.parent / "work" / "corpus_driver")
        roots.append(output_dir.parent.parent / "work" / "cohort_driver")
        roots.append(output_dir.parent.parent / "work" / output_dir.name)
    workflow_meta = manifest.get("workflow_meta") if isinstance(manifest, dict) else None
    if isinstance(workflow_meta, dict) and workflow_meta.get("launch_dir"):
        roots.append(Path(str(workflow_meta["launch_dir"])) / "work")
    seen: set[Path] = set()
    result: list[Path] = []
    for root in roots:
        resolved = root.resolve()
        if resolved not in seen and root.exists():
            result.append(root)
            seen.add(resolved)
    return result


def resolve_work_dir(task_hash: str, work_roots: list[Path]) -> Path | None:
    if "/" not in task_hash:
        return None
    prefix, suffix = task_hash.split("/", 1)
    for root in work_roots:
        parent = root / prefix
        direct = parent / suffix
        if direct.exists():
            return direct
        matches = sorted(parent.glob(f"{suffix}*")) if parent.exists() else []
        if matches:
            return matches[0]
    return None


def tail_text(path: Path, max_chars: int = 12000) -> str:
    if not path.is_file() or path.stat().st_size == 0:
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-max_chars:]


def first_error_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if any(token in lowered for token in ["error", "exception", "traceback", "failed", "killed", "no such file"]):
            return stripped[-500:]
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if stripped:
            return stripped[-500:]
    return ""


def task_log_names_for_mode(failed: bool, task_log_mode: str) -> list[str]:
    if task_log_mode == "none":
        return []
    if failed:
        return [".command.err", ".command.log", ".command.out"]
    if task_log_mode == "all-command-log":
        return [".command.log"]
    return []


def collect_nextflow_task_details(
    report_root: Path,
    preprocessed_dir: Path,
    output_root: Path,
    subjects: list[str],
    manifest: dict[str, Any] | None,
    task_log_mode: str = "failed",
) -> dict[str, list[dict[str, Any]]]:
    tasks_by_subject: dict[str, list[dict[str, Any]]] = {subject: [] for subject in subjects}
    trace_files = find_trace_files(report_root, preprocessed_dir, manifest)
    work_roots = infer_work_roots(report_root, preprocessed_dir, manifest)
    dataset_name = manifest_dataset_name(manifest)

    for trace_file in trace_files:
        with open(trace_file, "r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                process_name, tag = parse_trace_task_name(row.get("name", ""))
                subject = match_task_subject(tag, subjects, dataset_name=dataset_name)
                if subject is None:
                    continue
                subject_slug = sanitize_name(subject)
                failed = trace_task_failed(row)
                task_hash = row.get("hash", "")
                work_dir = resolve_work_dir(task_hash, work_roots)
                log_records = []
                message_candidates = []
                if work_dir:
                    for log_name in task_log_names_for_mode(failed, task_log_mode):
                        src = work_dir / log_name
                        excerpt = tail_text(src)
                        if not excerpt:
                            continue
                        log_category = "errors" if failed else "tasks"
                        rel_path = copy_text_blob(
                            excerpt,
                            output_root,
                            Path("files") / subject_slug / log_category / f"{sanitize_name(process_name)}_{sanitize_name(task_hash)}_{log_name[1:]}.txt",
                        )
                        log_records.append({"label": log_name, "path": rel_path})
                        if failed:
                            message = first_error_line(excerpt)
                            if message:
                                message_candidates.append(message)

                status = row.get("status", "")
                exit_value = row.get("exit", "")
                message = message_candidates[0] if message_candidates else f"Task status {status or 'unknown'}, exit {exit_value or 'unknown'}."
                tasks_by_subject[subject].append(
                    {
                        "process": process_name,
                        "step": PROCESS_TO_STEP.get(process_name, "unknown"),
                        "tag": tag,
                        "status": status,
                        "exit": exit_value,
                        "hash": task_hash,
                        "duration": row.get("duration", ""),
                        "realtime": row.get("realtime", ""),
                        "cpu": row.get("%cpu", ""),
                        "peak_rss": row.get("peak_rss", ""),
                        "peak_vmem": row.get("peak_vmem", ""),
                        "submit": row.get("submit", ""),
                        "trace_file": trace_file.name,
                        "work_dir": str(work_dir) if work_dir else "",
                        "failed": failed,
                        "task_log_mode": task_log_mode,
                        "message": message,
                        "logs": log_records,
                    }
                )

    return filter_retried_trace_failures(tasks_by_subject)


def resolve_report_dirs(report_root: Path) -> tuple[Path, Path]:
    report_root = report_root.resolve()
    direct_preprocessed = report_root / "preprocessed"
    if direct_preprocessed.exists() and direct_preprocessed.is_dir():
        return report_root, direct_preprocessed

    if report_root.name == "preprocessed" and report_root.is_dir():
        return report_root.parent, report_root

    candidate_children = []
    if report_root.exists() and report_root.is_dir():
        for child in sorted(report_root.iterdir()):
            child_preprocessed = child / "preprocessed"
            if child_preprocessed.exists() and child_preprocessed.is_dir():
                candidate_children.append(str(child))

    message = (
        f"Could not locate a 'preprocessed' directory under report_root: {report_root}. "
        f"Please pass either the MEGFlow output root or the preprocessed directory itself."
    )
    if candidate_children:
        message += " Available sibling output roots with preprocessed results: " + ", ".join(candidate_children[:8])
    raise ValueError(message)


def _nextflow_config_source_for_bundle(
    report_root: Path, preprocessed_dir: Path, manifest: dict[str, Any] | None
) -> tuple[Path | None, str | None]:
    """Pick nextflow.config (or run_nextflow.config) to embed as static_html data/nextflow.config.txt.

    The .txt suffix forces browsers to treat the bundle as plain text (Nextflow configs often start
    with '//' which triggers XML parse errors when the path ends in .config).

    Priority: preprocessed/logs (pipeline snapshot), then dataset report root, then manifest launch_dir.
    Within each location, run_nextflow.config is preferred because the workflow stores custom
    or Docker-adjusted configs under that name.
    Run-details table omits covariance/source params unless manifest meg_stage >= 3.
    """
    logs_dir = preprocessed_dir / "logs"
    for name in ("run_nextflow.config", "nextflow.config"):
        candidate = logs_dir / name
        if candidate.is_file():
            return candidate, f"{name} (preprocessed/logs, pipeline snapshot)"
    for name in ("run_nextflow.config", "nextflow.config"):
        candidate = report_root / name
        if candidate.is_file():
            return candidate, f"{name} (dataset / report root)"
    if isinstance(manifest, dict):
        wf = manifest.get("workflow_meta")
        if isinstance(wf, dict):
            ld = wf.get("launch_dir") or wf.get("launchDir")
            if ld:
                base = Path(str(ld))
                for name in ("run_nextflow.config", "nextflow.config"):
                    candidate = base / name
                    if candidate.is_file():
                        return candidate, f"{name} (manifest launch_dir)"
    return None, None


def read_raw_info(raw_file: Path) -> dict[str, Any]:
    try:
        generic_reader = getattr(mne.io, "read_raw", None)
        if generic_reader is not None:
            try:
                raw = generic_reader(str(raw_file), preload=False, verbose="ERROR")
            except Exception:
                if not str(raw_file).lower().endswith((".fif", ".fif.gz")):
                    raise
                raw = mne.io.read_raw_fif(str(raw_file), preload=False, verbose="ERROR")
        else:
            raw = mne.io.read_raw_fif(str(raw_file), preload=False, verbose="ERROR")
        sfreq = float(raw.info["sfreq"])
        n_channels = int(len(raw.ch_names))
        duration = float(raw.n_times / sfreq) if sfreq else None
        return {
            "raw_file": str(raw_file),
            "sfreq": sfreq,
            "n_channels": n_channels,
            "duration_sec": duration,
            "first_time": float(getattr(raw, "first_time", 0.0) or 0.0),
        }
    except Exception as exc:
        return {
            "raw_file": str(raw_file),
            "sfreq": None,
            "n_channels": None,
            "duration_sec": None,
            "error": str(exc),
        }


def parse_epochs_log(log_file: Path) -> dict[str, Any]:
    data = {
        "log_file": str(log_file) if log_file.exists() else None,
        "rejected_epochs": [],
        "remaining_epochs": None,
        "total_epochs_est": None,
        "reject_rate": None,
    }
    if not log_file.exists():
        return data

    with open(log_file, "r", encoding="utf-8") as f:
        log_content = [line.strip() for line in f.readlines() if line.strip()]

    if not log_content:
        return data

    try:
        rejected_epochs = ast.literal_eval(log_content[0])
        if not isinstance(rejected_epochs, list):
            rejected_epochs = []
        remaining_epochs = None
        if len(log_content) > 1 and ":" in log_content[1]:
            remaining_epochs = int(log_content[1].split(":")[-1].strip())
        total_epochs_est = None
        reject_rate = None
        if remaining_epochs is not None:
            total_epochs_est = remaining_epochs + len(rejected_epochs)
            if total_epochs_est > 0:
                reject_rate = len(rejected_epochs) / total_epochs_est
        data.update(
            {
                "rejected_epochs": rejected_epochs,
                "remaining_epochs": remaining_epochs,
                "total_epochs_est": total_epochs_est,
                "reject_rate": reject_rate,
            }
        )
    except Exception as exc:
        data["error"] = str(exc)

    return data


def artifact_segment_time(file_path: Path) -> str:
    stem = file_path.stem
    if stem.startswith("seg_"):
        return stem[4:]
    return stem


def artifact_segment_caption(segment_time: str) -> str:
    value = str(segment_time).strip()
    try:
        return f"Start time {float(value):g} s"
    except ValueError:
        return f"Start time {value}"


def artifact_overview_caption(start_time: Any = 0, duration: Any | None = None) -> str:
    start = fmt_float(start_time, 1, " s")
    if duration is None:
        return f"Start time {start}"
    return f"Start time {start} · Duration {fmt_float(duration, 1, ' s')}"


def artifact_segment_sort_key(file_path: Path) -> tuple[float, str]:
    value = artifact_segment_time(file_path)
    try:
        return (float(value), file_path.name)
    except ValueError:
        return (float("inf"), file_path.name)


def expected_steps_for_scope(scope: dict[str, Any] | None) -> dict[str, bool]:
    scope = scope if scope is not None else qc_completeness_scope_from_manifest(None)
    if not scope.get("run_meg"):
        return {key: False for key, _ in STEP_DEFS}
    try:
        meg_stage = int(scope.get("meg_stage", 3))
    except (TypeError, ValueError):
        meg_stage = 3
    return {
        "quality_score": bool(scope.get("megqc_enabled", True)),
        "basic_preproc": True,
        "artifacts": True,
        "ica": bool(meg_stage >= 1 and not scope.get("skip_ica")),
        "epochs": bool(meg_stage >= 2),
        "covariance": bool(meg_stage >= 3),
        "coregistration": bool(meg_stage >= 3),
        "headmodel": bool(meg_stage >= 3),
        "source": bool(meg_stage >= 3),
    }


def infer_qc_scope_from_task_details(task_details_by_subject: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
    seen_steps = {
        str(task.get("step") or "")
        for tasks in task_details_by_subject.values()
        for task in tasks
    }
    if not seen_steps:
        return None
    if seen_steps.intersection({"source", "headmodel", "coregistration", "covariance"}):
        meg_stage = 3
    elif "epochs" in seen_steps:
        meg_stage = 2
    elif "ica" in seen_steps:
        meg_stage = 1
    elif seen_steps.intersection({"artifacts", "basic_preproc", "meg import"}):
        meg_stage = 0
    else:
        return None
    return {"meg_stage": meg_stage, "skip_ica": False, "run_meg": True, "inferred_from_trace": True}


def steps_raw_for_scope(scope: dict[str, Any]) -> str:
    try:
        meg_stage = int(scope.get("meg_stage", 3))
    except (TypeError, ValueError):
        meg_stage = 3
    if meg_stage <= 0:
        return "meg_artifacts"
    if meg_stage == 1:
        return "meg_ica"
    if meg_stage == 2:
        return "meg_epochs"
    return "meg_all"


def apply_inferred_workflow_scope(ctx: dict[str, Any], scope: dict[str, Any]) -> dict[str, Any]:
    steps_raw = steps_raw_for_scope(scope)
    manifest = dict(ctx.get("manifest") or {})
    parsed = {
        "primary": steps_raw,
        "megStage": int(scope.get("meg_stage", 3)),
        "meg_stage": int(scope.get("meg_stage", 3)),
        "runAnatomy": False,
        "run_anatomy": False,
        "runMeg": True,
        "run_meg": True,
        "skipIca": bool(scope.get("skip_ica")),
        "skip_ica": bool(scope.get("skip_ica")),
    }
    manifest["parsed"] = parsed
    manifest["steps_raw"] = steps_raw
    manifest["report_only"] = True
    manifest["pipeline_steps_raw"] = steps_raw
    nodes, footnote = build_workflow_nodes(manifest, "trace")
    updated = dict(ctx)
    updated["manifest"] = manifest
    updated["steps_raw"] = steps_raw
    updated["nodes"] = nodes
    updated["footnote"] = f"steps inferred from Nextflow trace because the latest manifest is report-only: {steps_raw}"
    return updated


def select_artifact_images(artifact_dir: Path, overview_duration: float = 200.0) -> dict[str, list[dict[str, Any]]]:
    result = {"overview": []}
    check_imgs_dir = artifact_dir / "check_imgs"
    if not check_imgs_dir.exists():
        return result

    plot_dir = check_imgs_dir / "overview"
    if not plot_dir.exists():
        return result
    channel_dirs = sorted(
        [item for item in plot_dir.iterdir() if item.is_dir() and item.name.startswith("chn.")]
    )
    if not channel_dirs:
        return result
    target_dir = next((candidate for candidate in channel_dirs if candidate.name == "chn.0"), channel_dirs[0])
    files = sorted(target_dir.glob("seg_*.jpg"), key=artifact_segment_sort_key)
    if not files:
        return result

    duration = max(float(overview_duration or 0), 0.0)
    first_file = files[0]
    for file_path in files:
        sort_value, _ = artifact_segment_sort_key(file_path)
        if sort_value <= 0 or (duration and sort_value < duration):
            first_file = file_path
            break
    result["overview"] = [
        {
            "path": first_file,
            "channel_group": target_dir.name,
            "segment_time": artifact_segment_time(first_file),
            "duration": duration,
        }
    ]

    return result


def generate_static_artifact_overview(
    raw_file: Path,
    bad_channels: list[str],
    bad_segment_rows: list[dict[str, Any]],
    output_root: Path,
    subject_slug: str,
    overview_duration: float,
) -> dict[str, Any] | None:
    try:
        import matplotlib
        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception:
        return None

    try:
        raw = mne.io.read_raw_fif(str(raw_file), preload=False, verbose="ERROR")
        picks = list(mne.pick_types(raw.info, meg=True, eeg=False, ref_meg=False, exclude=[]))
        if not picks:
            return None

        duration = max(float(overview_duration or 0), 0.0)
        data_end = float(raw.times[-1]) if len(raw.times) else 0.0
        raw_first_time = float(getattr(raw, "first_time", 0.0) or 0.0)
        end_time = min(duration, data_end) if duration > 0 else data_end
        if end_time <= 0:
            return None
        plot_start = raw_first_time
        plot_stop = raw_first_time + end_time

        raw_window = raw.copy().pick(picks).crop(tmin=0.0, tmax=end_time, include_tmax=True)
        raw_window.load_data(verbose="ERROR")
        data, times = raw_window.get_data(return_times=True)
        if data.size == 0:
            return None

        times = times + raw_first_time

        ch_names = [raw_window.ch_names[idx] for idx in range(len(raw_window.ch_names))]
        ch_types = [mne.channel_type(raw_window.info, idx) for idx in range(len(ch_names))]
        raw_plot_scalings = {
            "mag": 1e-12,
            "grad": 4e-11,
            "ref_meg": 1e-12,
            "eeg": 20e-6,
        }
        scale = np.asarray([raw_plot_scalings.get(ch_type, 1.0) for ch_type in ch_types], dtype=float)
        for ch_type in sorted(set(ch_types)):
            type_idx = np.asarray([idx for idx, item in enumerate(ch_types) if item == ch_type], dtype=int)
            if type_idx.size == 0:
                continue
            default_scale = raw_plot_scalings.get(ch_type)
            if default_scale is None or not np.isfinite(default_scale) or default_scale <= 0:
                finite_abs = np.abs(data[type_idx][np.isfinite(data[type_idx])])
                type_scale = np.nanpercentile(finite_abs, 95) if finite_abs.size else 1.0
                scale[type_idx] = type_scale if np.isfinite(type_scale) and type_scale > 0 else 1.0
        scale[~np.isfinite(scale) | (scale <= 0)] = 1.0
        # Match raw.plot's visual contract more closely: channels of the same type
        # share a scale, so unusually large channels remain visibly large.
        display_data = data / scale[:, None]
        max_full_plot_samples = 60000
        max_plot_bins = 5000
        if display_data.shape[1] > max_full_plot_samples:
            n_samples = display_data.shape[1]
            print(
                "Static artifact overview uses min/max envelope downsampling "
                f"for {raw_file}: {n_samples} samples > {max_full_plot_samples} sample threshold."
            )
            edges = np.linspace(0, n_samples, max_plot_bins + 1, dtype=int)
            centers = np.empty(max_plot_bins, dtype=float)
            envelope = np.empty((display_data.shape[0], max_plot_bins * 3), dtype=float)
            for bin_idx, (start_idx, stop_idx) in enumerate(zip(edges[:-1], edges[1:])):
                stop_idx = max(stop_idx, start_idx + 1)
                chunk = display_data[:, start_idx:stop_idx]
                centers[bin_idx] = 0.5 * (times[start_idx] + times[min(stop_idx - 1, n_samples - 1)])
                envelope[:, bin_idx * 3] = np.nanmin(chunk, axis=1)
                envelope[:, bin_idx * 3 + 1] = np.nanmax(chunk, axis=1)
                envelope[:, bin_idx * 3 + 2] = np.nan
            plot_times = np.repeat(centers, 3)
            plot_data = envelope
        else:
            plot_times = times
            plot_data = display_data
        bad_set = set(bad_channels)
        offsets = np.arange(len(ch_names), dtype=float)[::-1]
        fig_height = max(5.2, min(28.0, 1.5 + 0.10 * len(ch_names)))
        fig, ax = plt.subplots(figsize=(12.5, fig_height), dpi=150)

        for row in bad_segment_rows:
            try:
                onset = float(row.get("onset_sec", row.get("onset")))
                duration_row = float(row.get("duration_sec", row.get("duration")))
            except (TypeError, ValueError):
                continue
            start = max(plot_start, onset)
            stop = min(plot_stop, onset + max(duration_row, 0.0))
            if stop > start:
                ax.axvspan(start, stop, color="#f97066", alpha=0.18, lw=0)

        for idx, ch_name in enumerate(ch_names):
            color = "#c4320a" if ch_name in bad_set else "#27364a"
            lw = 0.9 if ch_name in bad_set else 0.5
            alpha = 0.90 if ch_name in bad_set else 0.76
            ax.plot(plot_times, plot_data[idx] * 0.42 + offsets[idx], color=color, lw=lw, alpha=alpha)

        ax.set_xlim(plot_start, plot_stop)
        ax.set_ylim(-0.8, len(ch_names) - 0.2)
        tick_step = max(1, len(ch_names) // 28)
        tick_positions = offsets[::tick_step]
        tick_labels = ch_names[::tick_step]
        ax.set_yticks(tick_positions)
        ax.set_yticklabels(tick_labels, fontsize=7)
        ax.set_xlabel("Time (s)", fontsize=9)
        ax.set_ylabel("Channels (MNE-style shared scaling)", fontsize=9)
        ax.grid(axis="x", color="#dbe4ee", lw=0.6, alpha=0.85)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        fig.tight_layout(pad=0.45)

        rel_path = Path("assets") / "subjects" / subject_slug / "artifacts" / "static_overview.jpg"
        output_path = output_root / rel_path
        ensure_dir(output_path.parent)
        fig.savefig(output_path, format="jpg", dpi=150, bbox_inches="tight", pil_kwargs={"quality": 92})
        plt.close(fig)
        return {
            "rel_path": rel_path.as_posix(),
            "start_time": plot_start,
            "duration": end_time,
            "n_channels": len(ch_names),
        }
    except Exception:
        try:
            plt.close("all")
        except Exception:
            pass
        return None


def collect_qa_images(search_roots: list[Path]) -> dict[str, Path]:
    qa_files: dict[str, Path] = {}
    wanted = [
        "ica_overlay_mag.png",
        "ica_overlay_grad.png",
        "raw_psd.png",
        "ica_psd.png",
    ]
    for file_name in wanted:
        for root in search_roots:
            if root and root.exists():
                matches = list(root.rglob(file_name))
                if matches:
                    qa_files[file_name] = matches[0]
                    break
    return qa_files


def parse_ica_topographies(ica_results_dir: Path) -> list[dict[str, Any]]:
    topo_files = []
    if not ica_results_dir.exists():
        return topo_files
    evar_pattern = re.compile(r"^(?P<component>\d+)_evar_(?P<evar>-?\d+\.?\d*)$")
    plain_pattern = re.compile(r"^(?P<component>\d+)$")
    for file_path in ica_results_dir.glob("*.png"):
        match = evar_pattern.search(file_path.stem)
        explained_var = None
        if match:
            explained_var = float(match.group("evar"))
        else:
            match = plain_pattern.search(file_path.stem)
        if not match:
            continue
        topo_files.append(
            {
                "path": file_path,
                "component": int(match.group("component")),
                "explained_var": explained_var,
            }
        )
    topo_files.sort(key=lambda item: item["component"])
    return topo_files


def parse_ica_sources(ica_results_dir: Path) -> list[dict[str, Any]]:
    source_files = []
    if not ica_results_dir.exists():
        return source_files
    pattern = re.compile(r"ica_comp_(?P<start>\d+)-(?P<end>\d+)_tc")
    for file_path in ica_results_dir.glob("*.png"):
        match = pattern.search(file_path.stem)
        if not match:
            continue
        source_files.append(
            {
                "path": file_path,
                "start": int(match.group("start")),
                "end": int(match.group("end")),
            }
        )
    source_files.sort(key=lambda item: item["start"])
    return source_files


def render_status_pill(status: str) -> str:
    status_map = {
        "PASS": ("good", "Passed"),
        "WARN": ("warn", "Warning"),
        "FAIL": ("danger", "Failed"),
        "MISSING": ("neutral", "N/A"),
    }
    css_class, label = status_map.get(status, ("neutral", status))
    return f'<span class="pill {css_class}">{html_text(label)}</span>'


def collect_subject_data(
    subject: str,
    report_root: Path,
    output_root: Path,
    thresholds: dict[str, float],
    *,
    qc_scope: dict[str, Any] | None = None,
    task_details: list[dict[str, Any]] | None = None,
    artifact_overview_duration: float = DEFAULT_THRESHOLDS["artifact_overview_duration"],
) -> dict[str, Any]:
    preprocessed_dir = report_root / "preprocessed"
    subject_slug = sanitize_name(subject)
    subject_dir = preprocessed_dir / subject
    artifact_dir = preprocessed_dir / "artifact_report" / subject
    ica_dir = preprocessed_dir / "ica_report" / subject
    trans_dir = preprocessed_dir / "trans" / subject
    epochs_dir = preprocessed_dir / "epochs" / subject
    covariance_dir = preprocessed_dir / "covariance" / subject
    source_dir = preprocessed_dir / "source_recon" / subject
    fwd_dir = preprocessed_dir / "forward_solution" / subject

    raw_files = sorted(subject_dir.glob("*_preproc-raw.fif")) if subject_dir.exists() else []
    raw_info = read_raw_info(raw_files[0]) if raw_files else {}
    quality_score_data = collect_quality_score_data(subject, preprocessed_dir, output_root, subject_slug)
    if not raw_info and quality_score_data.get("raw_file"):
        raw_path = Path(str(quality_score_data["raw_file"]))
        raw_info = read_raw_info(raw_path) if raw_path.is_file() else {"raw_file": str(raw_path)}

    summary: dict[str, Any] = {
        "subject": subject,
        "subject_slug": subject_slug,
        "raw_info": raw_info,
        "files": [],
        "steps": {},
        "alarms": [],
        "thresholds": thresholds,
        "preproc_done": bool(raw_files),
        "task_details": task_details or [],
        "task_errors": [task for task in (task_details or []) if task.get("failed")],
        "failed_steps": {},
    }
    summary["quality_score"] = quality_score_data
    summary["steps"]["quality_score"] = quality_score_data["exists"]
    for label, rel_path in quality_score_data.get("files", {}).items():
        summary["files"].append({"label": f"Quality score {label.replace('_', ' ')}", "path": rel_path})

    # Artifacts
    artifact_data = {
        "bad_channels": [],
        "bad_segments": 0,
        "bad_duration_sec": None,
        "bad_ratio": None,
        "assets": [],
        "bad_segment_rows": [],
    }
    summary["steps"]["basic_preproc"] = summary["preproc_done"]
    bad_channels_file = next(iter(sorted(artifact_dir.glob("*_bad_channels.txt"))), None)
    bad_segments_file = next(iter(sorted(artifact_dir.glob("*_bad_segments.txt"))), None)
    deepreject_summary_file = artifact_dir / "deepreject_summary.json"

    if bad_channels_file:
        artifact_data["bad_channels"] = read_lines(bad_channels_file)
        rel = copy_asset(bad_channels_file, output_root, subject_slug, "artifacts")
        artifact_data["bad_channels_rel"] = rel
        summary["files"].append({"label": "Bad channels", "path": rel})

    if bad_segments_file:
        rel = copy_asset(bad_segments_file, output_root, subject_slug, "artifacts")
        artifact_data["bad_segments_rel"] = rel
        summary["files"].append({"label": "Bad segments", "path": rel})
        try:
            annotations = mne.read_annotations(str(bad_segments_file))
            artifact_data["bad_segments"] = int(len(annotations))
            artifact_data["bad_duration_sec"] = float(sum(annotations.duration))
            artifact_data["bad_segment_rows"] = [
                {
                    "index": idx + 1,
                    "onset_sec": float(onset),
                    "duration_sec": float(duration),
                    "description": str(description),
                }
                for idx, (onset, duration, description) in enumerate(
                    zip(annotations.onset, annotations.duration, annotations.description)
                )
            ]
            artifact_data["bad_segment_rows"].sort(
                key=lambda row: (float(row["onset_sec"]), float(row["duration_sec"]))
            )
            duration_sec = raw_info.get("duration_sec")
            if duration_sec and duration_sec > 0:
                artifact_data["bad_ratio"] = artifact_data["bad_duration_sec"] / duration_sec
        except Exception as exc:
            artifact_data["error"] = str(exc)

    if deepreject_summary_file.is_file():
        rel = copy_asset(deepreject_summary_file, output_root, subject_slug, "artifacts")
        artifact_data["deepreject_summary_rel"] = rel
        artifact_data["deepreject"] = safe_json(deepreject_summary_file)
        summary["files"].append({"label": "DeepReject summary", "path": rel})

    heatmap_file = next(
        (
            candidate
            for candidate in [
                artifact_dir / "check_imgs" / "artifact_mask_heatmap.jpg",
                artifact_dir / "check_imgs" / "artifact_mask_heatmap.jpeg",
                artifact_dir / "check_imgs" / "artifact_mask_heatmap.png",
            ]
            if candidate.is_file()
        ),
        None,
    )
    if heatmap_file:
        rel = copy_asset(heatmap_file, output_root, subject_slug, "artifacts")
        raw_first_time = raw_info.get("first_time", 0.0)
        artifact_data["assets"].append(
            {
                "title": "Artifact mask heatmap",
                "rel_path": rel,
                "category": "Artifacts",
                "artifact_group": "mask",
                "figure_class": "wide",
                "details": f"Time axis starts at {fmt_float(raw_first_time, 3, ' s')}",
            }
        )

    static_overview = None
    if raw_files:
        static_overview = generate_static_artifact_overview(
            raw_files[0],
            artifact_data["bad_channels"],
            artifact_data["bad_segment_rows"],
            output_root,
            subject_slug,
            artifact_overview_duration,
        )
    if static_overview:
        artifact_data["assets"].append(
            {
                "title": "Overview view 1",
                "rel_path": static_overview["rel_path"],
                "category": "Artifacts",
                "artifact_group": "overview",
                "start_time": static_overview.get("start_time", 0),
                "duration": static_overview.get("duration", artifact_overview_duration),
                "n_channels": static_overview.get("n_channels"),
                "details": artifact_overview_caption(
                    static_overview.get("start_time", 0),
                    static_overview.get("duration", artifact_overview_duration),
                ),
            }
        )
    else:
        selected_artifact_images = select_artifact_images(artifact_dir, artifact_overview_duration)
        for label, image_records in selected_artifact_images.items():
            for idx, image_record in enumerate(image_records, start=1):
                file_path = image_record["path"]
                channel_group = image_record["channel_group"]
                segment_time = image_record["segment_time"]
                rel = copy_asset_as(
                    file_path,
                    output_root,
                    subject_slug,
                    "artifacts",
                    f"{label}_{channel_group}_{file_path.name}",
                )
                artifact_data["assets"].append(
                    {
                        "title": f"Overview view {idx}",
                        "rel_path": rel,
                        "category": "Artifacts",
                        "artifact_group": label,
                        "channel_group": channel_group,
                        "segment_time": segment_time,
                        "duration": image_record.get("duration"),
                        "details": artifact_overview_caption(segment_time, image_record.get("duration")),
                    }
                )

    artifact_data["bad_channels_count"] = len(artifact_data["bad_channels"])
    artifact_data["exists"] = artifact_dir.exists() and (
        bool(bad_channels_file) or bool(bad_segments_file) or bool(artifact_data["assets"])
    )
    summary["artifacts"] = artifact_data
    summary["steps"]["artifacts"] = artifact_data["exists"]

    # ICA
    ica_data = {
        "marked_components": [],
        "marked_count": 0,
        "ecg_indices": [],
        "eog_indices": [],
        "ecg_scores": [],
        "eog_scores": [],
        "topographies": [],
        "sources": [],
        "qa_assets": [],
    }
    marked_file = ica_dir / "marked_components.txt"
    scores_file = ica_dir / "ecg_eog_scores.json"
    ica_results_dir = ica_dir / "ica_results"
    if marked_file.exists():
        marked_components = []
        for line in read_lines(marked_file):
            try:
                marked_components.append(int(line))
            except ValueError:
                continue
        ica_data["marked_components"] = sorted(marked_components)
        ica_data["marked_count"] = len(ica_data["marked_components"])
        rel = copy_asset(marked_file, output_root, subject_slug, "ica")
        summary["files"].append({"label": "ICA marked components", "path": rel})

    if scores_file.exists():
        scores = safe_json(scores_file)
        ica_data["ecg_indices"] = ensure_list(scores.get("ecg_indices", []))
        ica_data["eog_indices"] = ensure_list(scores.get("eog_indices", []))
        ica_data["ecg_scores"] = ensure_list(scores.get("ecg", []))
        ica_data["eog_scores"] = ensure_list(scores.get("eog", []))
        rel = copy_asset(scores_file, output_root, subject_slug, "ica")
        summary["files"].append({"label": "ICA ECG/EOG scores", "path": rel})

    topo_files = parse_ica_topographies(ica_results_dir)
    source_files = parse_ica_sources(ica_results_dir)
    marked_set = set(ica_data["marked_components"])
    marked_topos = [item for item in topo_files if item["component"] in marked_set]
    remaining_topos = [item for item in topo_files if item["component"] not in marked_set]
    remaining_topos.sort(
        key=lambda item: (
            item["explained_var"] is not None,
            item["explained_var"] if item["explained_var"] is not None else -1.0,
            -item["component"],
        ),
        reverse=True,
    )
    selected_topos = marked_topos[:6]
    for topo in remaining_topos:
        if len(selected_topos) >= 6:
            break
        selected_topos.append(topo)

    for topo in selected_topos:
        rel = copy_asset(topo["path"], output_root, subject_slug, "ica")
        ica_data["topographies"].append(
            {
                "component": topo["component"],
                "explained_var": topo["explained_var"],
                "rel_path": rel,
            }
        )

    for source_item in pick_evenly_spaced([item["path"] for item in source_files], 3):
        match = next((item for item in source_files if item["path"] == source_item), None)
        rel = copy_asset(source_item, output_root, subject_slug, "ica")
        title = "ICA source group"
        if match:
            title = f"ICA sources {match['start']}-{match['end']}"
        ica_data["sources"].append({"title": title, "rel_path": rel})

    qa_images = collect_qa_images([subject_dir, ica_dir])
    for name, file_path in qa_images.items():
        rel = copy_asset(file_path, output_root, subject_slug, "preproc")
        ica_data["qa_assets"].append({"title": name, "rel_path": rel})
        summary["files"].append({"label": name, "path": rel})

    ica_data["has_ecg"] = len(ica_data["ecg_indices"]) > 0
    ica_data["has_eog"] = len(ica_data["eog_indices"]) > 0
    ica_data["n_components"] = len(topo_files)
    ica_data["exists"] = ica_dir.exists() and (
        marked_file.exists() or scores_file.exists() or bool(topo_files) or bool(source_files)
    )
    summary["ica"] = ica_data
    summary["steps"]["ica"] = ica_data["exists"]

    # Coregistration
    coreg_data = {
        "dist_mean": None,
        "dist_max": None,
        "dist_min": None,
        "assets": [],
        "exists": False,
    }
    dists_file = trans_dir / "dists.csv"
    if dists_file.exists():
        try:
            df = pd.read_csv(dists_file)
            if not df.empty:
                row = df.iloc[0]
                coreg_data["dist_mean"] = row.get("dist_mean(mm)")
                coreg_data["dist_max"] = row.get("dist_max(mm)")
                coreg_data["dist_min"] = row.get("dist_min(mm)")
            rel = copy_asset(dists_file, output_root, subject_slug, "coreg")
            summary["files"].append({"label": "Coregistration distances", "path": rel})
        except Exception as exc:
            coreg_data["error"] = str(exc)

    for file_path in sorted(trans_dir.glob("*.png"), key=coreg_asset_sort_key):
        rel = copy_asset(file_path, output_root, subject_slug, "coreg")
        coreg_data["assets"].append({"title": file_path.stem, "rel_path": rel})
    coreg_data["exists"] = trans_dir.exists() and (dists_file.exists() or bool(coreg_data["assets"]))
    summary["coregistration"] = coreg_data
    summary["steps"]["coregistration"] = coreg_data["exists"]

    # Head model
    headmodel_data = {"assets": [], "exists": False}
    for file_path in sorted(fwd_dir.glob("headmodel_*.png")):
        rel = copy_asset(file_path, output_root, subject_slug, "headmodel")
        headmodel_data["assets"].append({"title": file_path.stem, "rel_path": rel})
    headmodel_data["exists"] = bool(headmodel_data["assets"])
    summary["headmodel"] = headmodel_data
    summary["steps"]["headmodel"] = headmodel_data["exists"]

    # Covariance
    covariance_data = {"assets": [], "exists": False}
    for file_name in ["bl_cov.png", "bl_cov_spectra.png"]:
        file_path = covariance_dir / file_name
        if file_path.exists():
            rel = copy_asset(file_path, output_root, subject_slug, "covariance")
            covariance_data["assets"].append({"title": file_name, "rel_path": rel})
    covariance_data["exists"] = bool(covariance_data["assets"])
    summary["covariance"] = covariance_data
    summary["steps"]["covariance"] = covariance_data["exists"]

    # Epochs
    epochs_data = {"assets": [], "exists": False}
    reject_log = next(iter(sorted(epochs_dir.glob("*reject_epoch_log.txt"))), None)
    epochs_data.update(parse_epochs_log(reject_log) if reject_log else parse_epochs_log(Path("__missing__")))
    if reject_log and reject_log.exists():
        rel = copy_asset(reject_log, output_root, subject_slug, "epochs")
        summary["files"].append({"label": "Epoch reject log", "path": rel})
        epochs_data["log_rel_path"] = rel
    epoch_pngs = sorted(epochs_dir.glob("*.png"))
    for file_path in epoch_pngs:
        rel = copy_asset(file_path, output_root, subject_slug, "epochs")
        epochs_data["assets"].append({"title": file_path.name, "rel_path": rel})
    epochs_data["exists"] = epochs_dir.exists() and (bool(epoch_pngs) or bool(reject_log))
    summary["epochs"] = epochs_data
    summary["steps"]["epochs"] = epochs_data["exists"]

    # Source localization
    source_data = {"assets": [], "exists": False}
    png_files = sorted(source_dir.glob("*.png"))
    for file_path in pick_evenly_spaced(png_files, 8):
        rel = copy_asset(file_path, output_root, subject_slug, "source")
        source_data["assets"].append({"title": file_path.name, "rel_path": rel})
    source_data["exists"] = bool(png_files)
    summary["source"] = source_data
    summary["steps"]["source"] = source_data["exists"]

    scope = qc_scope if qc_scope is not None else qc_completeness_scope_from_manifest(None)
    summary["expected_steps"] = expected_steps_for_scope(scope)
    if quality_score_data.get("passed_processing_threshold") is False:
        for step_key in summary["expected_steps"]:
            if step_key != "quality_score":
                summary["expected_steps"][step_key] = False
    expected_steps = summary["expected_steps"]
    for task_error in summary["task_errors"]:
        failed_step = task_error.get("step")
        if failed_step in STEP_KEYS:
            summary["steps"][failed_step] = False
            summary["failed_steps"][failed_step] = True
    alarms: list[dict[str, str]] = []

    for task_error in summary["task_errors"]:
        process = task_error.get("process") or "task"
        exit_value = task_error.get("exit") or "unknown"
        message = task_error.get("message") or "No stderr/stdout excerpt was available."
        alarms.append(
            {
                "category": f"Nextflow: {process}",
                "severity": "danger",
                "message": f"Task failed or was ignored (exit {exit_value}): {message}",
            }
        )

    qc_score = quality_score_data.get("score_0_100")
    qc_alarm_threshold = thresholds.get("megqc_alarm_score", DEFAULT_THRESHOLDS["megqc_alarm_score"])
    if not quality_score_data.get("exists"):
        alarms.append({"category": "QC Score", "severity": "warn", "message": "Normative Reference QC score is missing."})
    elif qc_score is None:
        error = quality_score_data.get("error") or "Score could not be computed."
        alarms.append({"category": "QC Score", "severity": "danger", "message": f"Normative Reference QC score failed: {error}"})
    elif float(qc_score) < float(qc_alarm_threshold):
        alarms.append(
            {
                "category": "QC Score",
                "severity": "warn",
                "message": (
                    f"Normative Reference score {fmt_float(qc_score, 1)} is below "
                    f"the warning threshold {fmt_float(qc_alarm_threshold, 1)}. Higher is better."
                ),
            }
        )
    if quality_score_data.get("passed_processing_threshold") is False:
        min_score = quality_score_data.get("processing_min_score")
        if min_score not in (None, ""):
            alarms.append(
                {
                    "category": "QC Gate",
                    "severity": "danger",
                    "message": (
                        f"Downstream processing was skipped because score {fmt_float(qc_score, 1)} "
                        f"is below required minimum {fmt_float(min_score, 1)}."
                    ),
                }
            )

    if expected_steps.get("artifacts", True) and not artifact_data["exists"]:
        alarms.append({"category": "Completeness", "severity": "warn", "message": "Artifact outputs are missing."})
    else:
        if artifact_data["bad_channels_count"] > thresholds["bad_channel_threshold"]:
            alarms.append(
                {
                    "category": "Artifacts",
                    "severity": "warn",
                    "message": (
                        f"Excessive bad channels: {artifact_data['bad_channels_count']} "
                        f"(threshold: {int(thresholds['bad_channel_threshold'])})"
                    ),
                }
            )
        if artifact_data["bad_segments"] > thresholds["bad_segment_threshold"]:
            alarms.append(
                {
                    "category": "Artifacts",
                    "severity": "warn",
                    "message": (
                        f"Excessive bad segments: {artifact_data['bad_segments']} "
                        f"(threshold: {int(thresholds['bad_segment_threshold'])})"
                    ),
                }
            )

    if expected_steps.get("ica", True) and expect_ica_outputs_for_qc(scope) and not ica_data["exists"]:
        alarms.append({"category": "Completeness", "severity": "warn", "message": "ICA outputs are missing."})
    elif ica_data["exists"]:
        if not ica_data["has_ecg"]:
            alarms.append({"category": "ICA", "severity": "warn", "message": "No ECG-related components detected."})
        elif ica_data["marked_count"] == 0:
            alarms.append(
                {
                    "category": "ICA",
                    "severity": "warn",
                    "message": "ECG-related components detected but none marked.",
                }
            )

        if not ica_data["has_eog"]:
            alarms.append({"category": "ICA", "severity": "warn", "message": "No EOG-related components detected."})
        elif ica_data["marked_count"] == 0:
            alarms.append(
                {
                    "category": "ICA",
                    "severity": "warn",
                    "message": "EOG-related components detected but none marked.",
                }
            )

    if expected_steps.get("coregistration", True) and expect_coregistration_outputs_for_qc(scope) and not coreg_data["exists"]:
        alarms.append({"category": "Completeness", "severity": "warn", "message": "Coregistration outputs are missing."})
    elif coreg_data["exists"]:
        if coreg_data["dist_mean"] is not None and float(coreg_data["dist_mean"]) > thresholds["coreg_mean_threshold"]:
            alarms.append(
                {
                    "category": "Coregistration",
                    "severity": "danger",
                    "message": (
                        f"Mean coreg distance {fmt_float(coreg_data['dist_mean'], 2, ' mm')} "
                        f"exceeds threshold {fmt_float(thresholds['coreg_mean_threshold'], 2, ' mm')}."
                    ),
                }
            )
        if coreg_data["dist_max"] is not None and float(coreg_data["dist_max"]) > thresholds["coreg_max_threshold"]:
            alarms.append(
                {
                    "category": "Coregistration",
                    "severity": "danger",
                    "message": (
                        f"Max coreg distance {fmt_float(coreg_data['dist_max'], 2, ' mm')} "
                        f"exceeds threshold {fmt_float(thresholds['coreg_max_threshold'], 2, ' mm')}."
                    ),
                }
            )

    if epochs_data["exists"] and epochs_data.get("reject_rate") is not None:
        if float(epochs_data["reject_rate"]) > thresholds["epoch_reject_rate_threshold"]:
            alarms.append(
                {
                    "category": "Epochs",
                    "severity": "warn",
                    "message": (
                        f"Epoch rejection rate {fmt_float(epochs_data['reject_rate'] * 100, 1, '%')} "
                        f"exceeds threshold {fmt_float(thresholds['epoch_reject_rate_threshold'] * 100, 1, '%')}."
                    ),
                }
            )
    summary["alarms"] = alarms
    summary["alarm_count"] = len(alarms)
    if len(alarms) >= 3 or any(alarm["severity"] == "danger" for alarm in alarms):
        summary["status"] = "FAIL"
    elif len(alarms) >= 1:
        summary["status"] = "WARN"
    else:
        summary["status"] = "PASS"

    for task_error in summary["task_errors"]:
        process = task_error.get("process") or "task"
        for log_record in task_error.get("logs", []):
            summary["files"].append({"label": f"{process} {log_record.get('label', 'log')}", "path": log_record["path"]})

    subject_json_rel = copy_text_blob(
        json.dumps(json_ready(summary), ensure_ascii=False, indent=2, allow_nan=False),
        output_root,
        Path("data") / "subjects" / f"{subject_slug}.json",
    )
    summary["summary_json"] = subject_json_rel
    summary["files"].append({"label": "Subject summary JSON", "path": subject_json_rel})

    return summary


def build_dataset_summary(
    report_root: Path,
    output_root: Path,
    subject_summaries: list[dict[str, Any]],
    thresholds: dict[str, float],
    *,
    workflow_html: str = "",
    workflow_meta: dict[str, Any] | None = None,
    qc_scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    step_names = [key for key, _ in STEP_DEFS]
    expected_steps = expected_steps_for_scope(qc_scope)
    total_subjects = len(subject_summaries)
    pass_count = sum(1 for item in subject_summaries if item["status"] == "PASS")
    warn_count = sum(1 for item in subject_summaries if item["status"] == "WARN")
    fail_count = sum(1 for item in subject_summaries if item["status"] == "FAIL")

    def avg(values: list[float | None]) -> float | None:
        cleaned = [float(v) for v in values if v is not None]
        if not cleaned:
            return None
        return sum(cleaned) / len(cleaned)

    dataset_summary = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "report_root": str(report_root),
        "output_root": str(output_root),
        "thresholds": thresholds,
        "total_subjects": total_subjects,
        "pass_count": pass_count,
        "warn_count": warn_count,
        "fail_count": fail_count,
        "alarm_count": sum(item["alarm_count"] for item in subject_summaries),
        "averages": {
            "megqc_score": avg([item["quality_score"].get("score_0_100") for item in subject_summaries]),
            "bad_channels": avg([item["artifacts"]["bad_channels_count"] for item in subject_summaries]),
            "bad_segments": avg([item["artifacts"]["bad_segments"] for item in subject_summaries]),
            "coreg_mean_mm": avg([item["coregistration"]["dist_mean"] for item in subject_summaries]),
            "coreg_max_mm": avg([item["coregistration"]["dist_max"] for item in subject_summaries]),
            "epoch_reject_rate": avg([item["epochs"].get("reject_rate") for item in subject_summaries]),
        },
        "step_completion": {
            step: sum(1 for item in subject_summaries if item["steps"].get(step)) for step in step_names
        },
        "expected_steps": expected_steps,
        "workflow_html": workflow_html,
        "workflow_meta": workflow_meta or {},
        "subjects": [
            {
                "subject": item["subject"],
                "subject_slug": item["subject_slug"],
                "status": item["status"],
                "alarm_count": item["alarm_count"],
                "megqc_score": item["quality_score"].get("score_0_100"),
                "bad_channels": item["artifacts"]["bad_channels_count"],
                "bad_segments": item["artifacts"]["bad_segments"],
                "marked_ica": item["ica"]["marked_count"],
                "coreg_mean": item["coregistration"]["dist_mean"],
                "coreg_max": item["coregistration"]["dist_max"],
                "epoch_reject_rate": item["epochs"].get("reject_rate"),
            }
            for item in subject_summaries
        ],
    }

    dataset_json_path = output_root / "data" / "dataset_summary.json"
    ensure_dir(dataset_json_path.parent)
    with open(dataset_json_path, "w", encoding="utf-8") as f:
        json.dump(json_ready(dataset_summary), f, ensure_ascii=False, indent=2, allow_nan=False)

    csv_path = output_root / "data" / "subjects.csv"
    ensure_dir(csv_path.parent)
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "subject",
                "status",
                "alarm_count",
                "megqc_score",
                "bad_channels",
                "bad_segments",
                "marked_ica",
                "coreg_mean_mm",
                "coreg_max_mm",
                "epoch_reject_rate",
                "quality_score",
                "artifacts",
                "ica",
                "coregistration",
                "headmodel",
                "epochs",
                "covariance",
                "source",
            ]
        )
        for item in subject_summaries:
            writer.writerow(
                [
                    item["subject"],
                    item["status"],
                    item["alarm_count"],
                    item["quality_score"].get("score_0_100"),
                    item["artifacts"]["bad_channels_count"],
                    item["artifacts"]["bad_segments"],
                    item["ica"]["marked_count"],
                    item["coregistration"]["dist_mean"],
                    item["coregistration"]["dist_max"],
                    item["epochs"].get("reject_rate"),
                    item["steps"].get("quality_score"),
                    item["steps"].get("artifacts"),
                    item["steps"].get("ica"),
                    item["steps"].get("coregistration"),
                    item["steps"].get("headmodel"),
                    item["steps"].get("epochs"),
                    item["steps"].get("covariance"),
                    item["steps"].get("source"),
                ]
            )

    return dataset_summary


def render_file_rows(file_items: list[dict[str, str]], prefix: str = "") -> str:
    if not file_items:
        return '<div class="small">No packaged sidecar files for this section.</div>'
    rows = []
    for item in file_items:
        rows.append(
            f"""
            <div class="path-row">
              <div><strong>{html_text(item['label'])}</strong></div>
              <div class="small"><a href="{prefix}{html_text(item['path'])}" target="_blank">{html_text(item['path'])}</a></div>
            </div>
            """
        )
    return '<div class="path-list">' + "".join(rows) + "</div>"


def render_quality_family_scores(family_scores: list[dict[str, Any]]) -> str:
    if not family_scores:
        return '<div class="small">No family scores available.</div>'
    rows = []
    for item in family_scores:
        rows.append(
            f"""
            <tr>
              <td>{html_text(item.get('domain', ''))}</td>
              <td>{html_text(item.get('family', ''))}</td>
              <td>{fmt_float(item.get('score_0_100'), 1)}</td>
              <td>{fmt_int(item.get('n_components'))}</td>
            </tr>
            """
        )
    return f"""
    <table>
      <thead><tr><th>Domain</th><th>Metric family</th><th>Family score</th><th>Components</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    """


def render_quality_preprocessing_steps(steps: list[dict[str, Any]]) -> str:
    if not steps:
        return '<div class="small">No reference preprocessing metadata available.</div>'
    rows = []
    for step in steps:
        if step.get("step") == "filter":
            detail = f"{fmt_float(step.get('l_freq'), 1, ' Hz')} - {fmt_float(step.get('h_freq'), 1, ' Hz')}"
        elif step.get("step") == "notch_filter":
            freqs = [freq for freq in ensure_list(step.get("freqs")) if finite_float(freq) is not None]
            detail = " ".join(f"{fmt_float(freq, 0, ' Hz')}" for freq in freqs) if freqs else html_text(step.get("reason", "auto"))
        else:
            detail = html_text(step.get("reason", ""))
        rows.append(
            f"""
            <tr>
              <td>{html_text(step.get('step', ''))}</td>
              <td>{html_text(detail)}</td>
              <td>{html_text(step.get('method', step.get('status', 'applied')))}</td>
            </tr>
            """
        )
    return f"""
    <table>
      <thead><tr><th>Step</th><th>Parameters</th><th>Method / status</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    """


def render_quality_component_table(components: list[dict[str, Any]]) -> str:
    if not components:
        return '<div class="small">No component scores available.</div>'
    rows = []
    for item in components:
        score = item.get("component_score_0_1")
        rows.append(
            f"""
            <tr>
              <td class="mono-path">{html_text(item.get('metric', ''))}</td>
              <td>{html_text(item.get('domain', ''))}</td>
              <td>{fmt_metric_value(item.get('raw_value'), 4)}</td>
              <td>{fmt_metric_value(item.get('q05'), 4)} / {fmt_metric_value(item.get('q50'), 4)} / {fmt_metric_value(item.get('q95'), 4)}</td>
              <td>{html_text(item.get('direction_label', ''))}</td>
              <td>{fmt_float((float(score) * 100) if score is not None else None, 1)}</td>
              <td>{html_text(item.get('status', ''))}</td>
              <td>{html_text(item.get('reference_scope_used', ''))} · {html_text(item.get('reference_device', ''))} · {html_text(item.get('reference_category', ''))}</td>
              <td>{html_text(item.get('interpretation', ''))}</td>
            </tr>
            """
        )
    return f"""
    <table>
      <thead>
        <tr>
          <th>Metric</th>
          <th>Domain</th>
          <th>Raw</th>
          <th>q05 / q50 / q95</th>
          <th>Direction</th>
          <th>Score</th>
          <th>Status</th>
          <th>Normative Reference</th>
          <th>Meaning</th>
        </tr>
      </thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    """


def render_gallery(assets: list[dict[str, Any]], prefix: str = "") -> str:
    if not assets:
        return '<div class="small">No images packaged for this section.</div>'
    blocks = []
    for asset in assets:
        title = html_text(asset.get("title", "Figure"))
        rel = html_text(prefix + asset["rel_path"])
        figure_class = html_text(asset.get("figure_class", "")).strip()
        badge = asset.get("badge")
        badge_html = ""
        if isinstance(badge, dict) and badge.get("text"):
            badge_text = html_text(badge.get("text", ""))
            badge_class = html_text(badge.get("class", "neutral"))
            badge_html = f'<div class="figure-badge {badge_class}">{badge_text}</div>'
        blocks.append(
            f"""
            <div class="figure {figure_class}">
              {badge_html}
              <a href="{rel}" target="_blank"><img src="{rel}" alt="{title}"></a>
              <div class="caption">{title}{f'<div class="figure-meta">{html_text(asset.get("details", ""))}</div>' if asset.get("details") else ''}</div>
            </div>
            """
        )
    return '<div class="gallery">' + "".join(blocks) + "</div>"


def render_artifact_gallery(assets: list[dict[str, Any]], prefix: str = "") -> str:
    if not assets:
        return '<div class="small">No images packaged for this section.</div>'
    groups = [
        ("mask", "Bad channel / bad segment mask", "Compact mask overview of detected bad channels and bad segments."),
        ("overview", "Overview plot", ""),
    ]
    blocks = []
    for group_key, title, desc in groups:
        group_assets = [asset for asset in assets if asset.get("artifact_group") == group_key]
        if not group_assets:
            continue
        blocks.append(
            f"""
            <div class="artifact-group">
              <div class="artifact-group-title">{html_text(title)}</div>
              {f'<div class="artifact-group-desc">{html_text(desc)}</div>' if desc else ''}
              {render_gallery(group_assets, prefix=prefix)}
            </div>
            """
        )
    other_assets = [asset for asset in assets if asset.get("artifact_group") not in {group[0] for group in groups}]
    if other_assets:
        blocks.append(
            f"""
            <div class="artifact-group">
              <div class="artifact-group-title">Additional artifact figures</div>
              {render_gallery(other_assets, prefix=prefix)}
            </div>
            """
        )
    return '<div class="artifact-gallery">' + "".join(blocks) + "</div>"


def coreg_asset_stage_and_view(asset: dict[str, Any]) -> tuple[str | None, str | None]:
    title = str(asset.get("title", ""))
    for step in COREG_ASSET_STEPS:
        for view_suffix in COREG_ASSET_VIEW_SUFFIXES:
            token = f"{step}{view_suffix}"
            if title == token or title.endswith(f"_{token}"):
                return step, view_suffix
    return None, None


def render_coreg_gallery(assets: list[dict[str, Any]], prefix: str = "") -> str:
    if not assets:
        return '<div class="small">No coregistration images packaged for this section.</div>'

    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = {step: [] for step in COREG_ASSET_STEPS}
    extras: list[dict[str, Any]] = []
    for asset in assets:
        step, view_suffix = coreg_asset_stage_and_view(asset)
        if step is None or view_suffix is None:
            extras.append(asset)
            continue
        grouped[step].append((COREG_ASSET_VIEW_SUFFIXES.index(view_suffix), asset))

    stage_blocks = []
    view_labels = {
        "": "Head surface view",
        "_brain": "Brain surface view",
    }
    for step in COREG_ASSET_STEPS:
        stage_assets = sorted(grouped[step], key=lambda item: (item[0], str(item[1].get("title", ""))))
        if not stage_assets:
            continue
        details = COREG_STAGE_DETAILS[step]
        is_final = step == "coreg_icp_finetune"
        final_badge = '<span class="pill good">Final result</span>' if is_final else ""
        figure_blocks = []
        for view_idx, asset in stage_assets:
            title = html_text(asset.get("title", "Figure"))
            rel = html_text(prefix + asset["rel_path"])
            view_suffix = COREG_ASSET_VIEW_SUFFIXES[view_idx]
            view_label = html_text(view_labels.get(view_suffix, "Coregistration view"))
            figure_blocks.append(
                f"""
                <div class="figure">
                  <a href="{rel}" target="_blank"><img src="{rel}" alt="{title}"></a>
                  <div class="caption">{view_label}<div class="small">{title}</div></div>
                </div>
                """
            )
        stage_blocks.append(
            f"""
            <div class="coreg-stage {'final' if is_final else ''}">
              <div class="coreg-stage-header">
                <div>
                  <div class="coreg-stage-title">{html_text(details['title'])}</div>
                  <div class="coreg-stage-desc">{html_text(details['description'])}</div>
                </div>
                {final_badge}
              </div>
              <div class="coreg-stage-images">{''.join(figure_blocks)}</div>
            </div>
            """
        )

    if extras:
        stage_blocks.append(
            f"""
            <div class="coreg-stage">
              <div class="coreg-stage-header">
                <div>
                  <div class="coreg-stage-title">Additional coregistration figures</div>
                  <div class="coreg-stage-desc">Extra images that do not match the standard coregistration stage names.</div>
                </div>
              </div>
              {render_gallery(extras, prefix=prefix)}
            </div>
            """
        )

    return '<div class="coreg-gallery">' + "".join(stage_blocks) + "</div>"


def render_alarm_items(alarms: list[dict[str, str]]) -> str:
    if not alarms:
        return '<div class="small">No QC alerts. This subject passed the current static thresholds.</div>'
    items = []
    for alarm in alarms:
        css_class = "danger" if alarm["severity"] == "danger" else ""
        items.append(
            f"""
            <div class="alarm-item {css_class}">
              <div class="category">{html_text(alarm['category'])}</div>
              <div>{html_text(alarm['message'])}</div>
            </div>
            """
        )
    return '<div class="alarm-list">' + "".join(items) + "</div>"


def render_step_snapshot(summary: dict[str, Any], compact: bool = False) -> str:
    parts = []
    expected_steps = summary.get("expected_steps") or {}
    failed_steps = summary.get("failed_steps") or {}
    for key, label in STEP_DEFS:
        if not expected_steps.get(key, True):
            css = "neutral"
            text = label if compact else f"{label}: N/A"
            parts.append(
                f'<span class="snapshot-item {css}"><span class="snapshot-dot"></span>{html_text(text)}</span>'
            )
            continue
        if failed_steps.get(key):
            css = "failed"
            text = label if compact else f"{label}: Failed"
            parts.append(
                f'<span class="snapshot-item {css}"><span class="snapshot-dot"></span>{html_text(text)}</span>'
            )
            continue
        is_ready = bool(summary["steps"].get(key))
        css = "good" if is_ready else "missing"
        text = label if compact else f"{label}: {'ready' if is_ready else 'missing'}"
        parts.append(
            f'<span class="snapshot-item {css}"><span class="snapshot-dot"></span>{html_text(text)}</span>'
        )
    return '<div class="snapshot-grid">' + "".join(parts) + "</div>"


def render_bad_channel_block(channels: list[str], max_inline: int = 18) -> str:
    if not channels:
        return '<div class="small">No bad channels listed.</div>'
    inline = channels[:max_inline]
    chips = "".join(f'<span class="chip">{html_text(ch)}</span>' for ch in inline)
    extra_note = ""
    if len(channels) > max_inline:
        extra_note = f'<div class="info-note">Showing first {max_inline} of {len(channels)} bad channels. Full list is scrollable below.</div>'
    table_rows = "".join(
        f"<tr><td>{idx + 1}</td><td>{html_text(ch)}</td></tr>" for idx, ch in enumerate(channels)
    )
    return (
        f'<div class="chips">{chips}</div>'
        f"{extra_note}"
        f'<div class="scroll-box" style="margin-top:10px"><table class="detail-table"><thead><tr><th>#</th><th>Channel</th></tr></thead><tbody>{table_rows}</tbody></table></div>'
    )


def render_bad_segment_block(rows: list[dict[str, Any]], page_size: int = 20) -> str:
    if not rows:
        return '<div class="small">No bad segments listed.</div>'
    controls_html = ""
    if len(rows) > 5:
        controls_html = (
            '<div class="subject-table-controls" style="margin-top:10px">'
            '  <div class="table-count" id="badSegmentCountInfo">Showing 0 of 0 bad segments</div>'
            '  <div class="inline-controls">'
            '    <label for="badSegmentPageSize">Page Size</label>'
            f'    <select id="badSegmentPageSize" onchange="resetBadSegmentPage()">'
            f'      <option value="5">5 / page</option>'
            f'      <option value="{page_size}" selected>{page_size} / page</option>'
            '      <option value="50">50 / page</option>'
            '      <option value="100">100 / page</option>'
            '    </select>'
            '    <div class="pager">'
            '      <button id="badSegmentPrevBtn" onclick="setBadSegmentPage(-1)">Previous</button>'
            '      <span id="badSegmentPageInfo" class="table-count">Page 1 / 1</span>'
            '      <button id="badSegmentNextBtn" onclick="setBadSegmentPage(1)">Next</button>'
            '    </div>'
            '  </div>'
            '</div>'
        )
    return (
        f"{controls_html}"
        '<div class="info-note">Bad segments are sorted by onset from earliest to latest.</div>'
        '<div class="scroll-box">'
        '  <table class="detail-table">'
        '    <thead><tr><th>#</th><th>Onset</th><th>Duration</th><th>Description</th></tr></thead>'
        '    <tbody id="badSegmentTableBody"></tbody>'
        '  </table>'
        '</div>'
        f'<script id="badSegmentRows" type="application/json">{json_script_text(rows)}</script>'
    )


def render_task_error_block(task_errors: list[dict[str, Any]], prefix: str = "") -> str:
    if not task_errors:
        return '<div class="small">No failed or ignored Nextflow tasks were found for this subject in the packaged trace files.</div>'
    items = []
    for error in task_errors:
        log_links = "".join(
            f'<a href="{html_text(prefix + log["path"])}" target="_blank">{html_text(log.get("label", "log"))}</a>'
            for log in error.get("logs", [])
        )
        if not log_links:
            log_links = '<span class="small">No command log excerpt found.</span>'
        items.append(
            f"""
            <div class="alarm-item danger">
              <div class="category">{html_text(error.get('process', 'task'))} · {html_text(error.get('status', 'unknown'))} · exit {html_text(error.get('exit', 'unknown'))}</div>
              <div>{html_text(error.get('message', 'No error excerpt available.'))}</div>
              <div class="small mono-path" style="margin-top:6px">work: {html_text(error.get('work_dir', 'N/A'))}</div>
              <div class="hero-links" style="margin-top:8px">{log_links}</div>
            </div>
            """
        )
    return '<div class="alarm-list">' + "".join(items) + "</div>"


def render_task_details_block(task_details: list[dict[str, Any]], prefix: str = "") -> str:
    if not task_details:
        return '<div class="small">No Nextflow task trace details were found for this subject.</div>'

    rows = []
    for task in task_details:
        failed = bool(task.get("failed"))
        status = task.get("status") or "unknown"
        status_class = "danger" if failed else "good"
        step = dict(STEP_DEFS).get(task.get("step"), str(task.get("step") or "unknown").replace("_", " "))
        log_links = "".join(
            f'<a href="{html_text(prefix + log["path"])}" target="_blank">{html_text(log.get("label", "log"))}</a> '
            for log in task.get("logs", [])
        )
        if not log_links:
            log_links = '<span class="small">-</span>'
        rows.append(
            f"""
            <tr>
              <td>{html_text(task.get('process', 'task'))}<div class="small">{html_text(step)}</div></td>
              <td><span class="pill {status_class}">{html_text(status)}</span></td>
              <td>{html_text(task.get('exit') or '-')}</td>
              <td>{html_text(task.get('duration') or task.get('realtime') or '-')}</td>
              <td>{html_text(task.get('peak_rss') or '-')}</td>
              <td class="mono-path">{html_text(task.get('hash') or '-')}</td>
              <td>{log_links}</td>
            </tr>
            """
        )

    failed_count = sum(1 for task in task_details if task.get("failed"))
    summary = f"{len(task_details)} task{'s' if len(task_details) != 1 else ''}"
    if failed_count:
        summary += f", {failed_count} failed/ignored"

    return (
        '<details class="task-details">'
        f'<summary>{html_text(summary)}</summary>'
        '<div class="scroll-box" style="margin-top:10px;max-height:360px">'
        '<table class="detail-table">'
        '<thead><tr><th>Process</th><th>Status</th><th>Exit</th><th>Duration</th><th>Peak RSS</th><th>Hash</th><th>Logs</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        '</table>'
        '</div>'
        '</details>'
    )


def build_subject_html(summary: dict[str, Any], output_root: Path) -> None:
    subject = summary["subject"]
    status_html = render_status_pill(summary["status"])
    raw_info = summary.get("raw_info", {})
    marked_component_set = set(summary["ica"].get("marked_components", []))
    quality_score = summary.get("quality_score", {})
    quality_score_value = quality_score.get("score_0_100")

    step_chips = []
    subject_step_labels = {
        "quality_score": "QC Score",
        "basic_preproc": "Basic preprocessing",
        "artifacts": "Artifacts",
        "ica": "ICA",
        "coregistration": "MEG-MRI coregistration",
        "headmodel": "Head model",
        "epochs": "Epochs",
        "covariance": "Covariance",
        "source": "Source",
    }
    for key, _ in STEP_DEFS:
        label = subject_step_labels[key]
        if not (summary.get("expected_steps") or {}).get(key, True):
            css = "neutral"
            state = "N/A"
        elif (summary.get("failed_steps") or {}).get(key):
            css = "danger"
            state = "Failed"
        else:
            css = "good" if summary["steps"].get(key) else "neutral"
            state = "ready" if summary["steps"].get(key) else "missing"
        step_chips.append(f'<span class="pill {css}">{label}: {state}</span>')

    qa_assets = []
    qa_assets.extend(summary["ica"]["qa_assets"])
    ica_topography_assets = [
        {
            "title": (
                f"Marked abnormal IC {item['component']}"
                + (f" | EVAR {fmt_float(item['explained_var'], 3)}" if item.get("explained_var") is not None else "")
                if item["component"] in marked_component_set
                else f"Reference IC {item['component']}"
                + (f" | EVAR {fmt_float(item['explained_var'], 3)}" if item.get("explained_var") is not None else "")
            ),
            "rel_path": item["rel_path"],
            "figure_class": "flagged" if item["component"] in marked_component_set else "",
            "badge": (
                {"text": "Detected abnormal component", "class": "warn"}
                if item["component"] in marked_component_set
                else {"text": "Reference component", "class": "neutral"}
            ),
        }
        for item in summary["ica"]["topographies"]
    ]
    task_failure_section = ""
    if summary.get("task_errors"):
        task_failure_section = f"""
    <div class="section">
      <h2>Task Failure Details</h2>
      <div class="panel">
        {render_task_error_block(summary.get('task_errors', []), prefix="../")}
      </div>
    </div>
"""

    content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html_text(subject)} - MEGFlow Static Report</title>
  <link rel="icon" type="image/png" href="../assets/favicon.png">
  <link rel="stylesheet" href="../assets/report.css">
  <script src="../assets/report.js"></script>
</head>
<body>
  <div class="container">
    <a class="back-link" href="../index.html">&larr; Back to dataset summary</a>
    <div class="hero">
      <div class="eyebrow">Subject-Level QC Report</div>
      <h1>{html_text(subject)}</h1>
      <p>Self-contained subject-level report with bundled QC figures and derivative sidecars.</p>
      <div class="hero-links">
        {status_html}
        <span class="pill neutral">QC alerts: {summary['alarm_count']}</span>
        <span class="pill neutral">Raw duration: {fmt_float(raw_info.get('duration_sec'), 1, ' s')}</span>
        <span class="pill neutral">Channels: {fmt_int(raw_info.get('n_channels'))}</span>
        <span class="pill neutral">Sampling rate: {fmt_float(raw_info.get('sfreq'), 1, ' Hz')}</span>
      </div>
      <div class="hero-links">
        {''.join(step_chips)}
      </div>
    </div>

    <div class="grid cards">
      <div class="card">
        <div class="label">Normative Reference QC score</div>
        <div class="value">{fmt_float(quality_score_value, 1)}</div>
        <div class="subvalue">0-100, higher is better; warning below {fmt_float(summary['thresholds'].get('megqc_alarm_score'), 1)}</div>
      </div>
      <div class="card">
        <div class="label">Bad-channel count</div>
        <div class="value">{fmt_int(summary['artifacts']['bad_channels_count'])}</div>
        <div class="subvalue">Threshold {fmt_int(summary['thresholds']['bad_channel_threshold'])} in static QC</div>
      </div>
      <div class="card">
        <div class="label">Bad-segment count</div>
        <div class="value">{fmt_int(summary['artifacts']['bad_segments'])}</div>
        <div class="subvalue">Annotated bad duration {fmt_float(summary['artifacts'].get('bad_duration_sec'), 1, ' s')}</div>
      </div>
      <div class="card">
        <div class="label">Marked ICA Components</div>
        <div class="value">{fmt_int(summary['ica']['marked_count'])}</div>
        <div class="subvalue">ECG: {'yes' if summary['ica']['has_ecg'] else 'no'} | EOG: {'yes' if summary['ica']['has_eog'] else 'no'}</div>
      </div>
      <div class="card">
        <div class="label">Mean / maximum coregistration distance (mm)</div>
        <div class="value">{fmt_float(summary['coregistration']['dist_mean'], 2, ' mm')}</div>
        <div class="subvalue">Max {fmt_float(summary['coregistration']['dist_max'], 2, ' mm')}</div>
      </div>
      <div class="card">
        <div class="label">Epoch rejection rate</div>
        <div class="value">{fmt_float((summary['epochs'].get('reject_rate') * 100) if summary['epochs'].get('reject_rate') is not None else None, 1, '%')}</div>
        <div class="subvalue">Rejected {len(summary['epochs'].get('rejected_epochs', []))} / Estimated total {fmt_int(summary['epochs'].get('total_epochs_est'))}</div>
      </div>
    </div>

    <div class="section">
      <h2>QC alerts</h2>
      <div class="panel">
        {render_alarm_items(summary['alarms'])}
      </div>
    </div>

{task_failure_section}

    <div class="section">
      <h2>Task Details</h2>
      <div class="panel">
        {render_task_details_block(summary.get('task_details', []), prefix="../")}
      </div>
    </div>

    <div class="section">
      <h2>Key Metrics</h2>
      <div class="panel">
        <div class="metric-list">
          <div class="metric-box wide"><div class="k">Raw File</div><div class="v wrap mono-path">{html_text(raw_info.get('raw_file', 'N/A'))}</div></div>
          <div class="metric-box"><div class="k">Bad-channel proportion</div><div class="v">{fmt_float((summary['artifacts']['bad_channels_count'] / raw_info['n_channels'] * 100) if raw_info.get('n_channels') else None, 1, '%')}</div></div>
          <div class="metric-box"><div class="k">Bad-segment proportion</div><div class="v">{fmt_float((summary['artifacts'].get('bad_ratio') * 100) if summary['artifacts'].get('bad_ratio') is not None else None, 1, '%')}</div></div>
          <div class="metric-box"><div class="k">ICA Components</div><div class="v">{fmt_int(summary['ica']['n_components'])}</div></div>
          <div class="metric-box"><div class="k">Epochs Remaining</div><div class="v">{fmt_int(summary['epochs'].get('remaining_epochs'))}</div></div>
          <div class="metric-box"><div class="k">Summary JSON</div><div class="v"><a href="../{html_text(summary['summary_json'])}" target="_blank">Open</a></div></div>
        </div>
      </div>
    </div>

    <div class="section">
      <h2>Normative Reference QC Score</h2>
      <div class="two-col quality-score-layout">
        <div class="panel quality-summary-panel">
          <div class="metric-list">
            <div class="metric-box"><div class="k">Score</div><div class="v">{fmt_float(quality_score_value, 1)}</div></div>
            <div class="metric-box"><div class="k">Processing Minimum</div><div class="v">{fmt_float(quality_score.get('processing_min_score'), 1)}</div></div>
            <div class="metric-box"><div class="k">Warning Threshold</div><div class="v">{fmt_float(summary['thresholds'].get('megqc_alarm_score'), 1)}</div></div>
            <div class="metric-box"><div class="k">Model</div><div class="v wrap">{html_text(quality_score.get('model', 'N/A'))}</div></div>
            <div class="metric-box"><div class="k">Device Reference</div><div class="v">{html_text(quality_score.get('device_type', 'N/A'))}</div></div>
            <div class="metric-box"><div class="k">Category</div><div class="v">{html_text(quality_score.get('category', 'N/A'))}</div></div>
            <div class="metric-box wide"><div class="k">Bad-channel policy</div><div class="v wrap">{html_text(quality_score.get('bad_channel_policy', 'N/A'))}</div></div>
            <div class="metric-box wide"><div class="k">Bad-annotation policy</div><div class="v wrap">{html_text(quality_score.get('bad_annotation_policy', 'N/A'))}</div></div>
          </div>
          <div class="info-note">Final score uses a 0-100 scale where higher is better. Before scoring, raw data is aligned to the reference space with the QC preprocessing below. The 1-100 Hz band-pass is fixed for Normative Reference scoring and should not be changed. Bad channels and BAD annotations are kept by default to match the normative reference.</div>
          {render_quality_preprocessing_steps(quality_score.get('reference_preprocessing', []))}
        </div>
        <div class="panel quality-reference-panel">
          {render_gallery([{'title': 'Reference-relative metric positions', 'rel_path': quality_score.get('reference_plot_rel'), 'figure_class': 'quality-reference-figure'}] if quality_score.get('reference_plot_rel') else [], prefix="../")}
        </div>
      </div>
      <div class="panel quality-detail-panel">
        <div class="panel-title-group">
          <h3>Metric Family Scores</h3>
          <div class="panel-subtitle">Domain-level score summary used by the final quality score.</div>
        </div>
        {render_quality_family_scores(quality_score.get('family_scores', []))}
      </div>
      <details class="panel quality-components-details">
        <summary>
          <div class="panel-title-group">
            <h3>Component Scores</h3>
            <div class="panel-subtitle">Reference quantiles and score direction for each contributing metric.</div>
          </div>
        </summary>
        <div class="quality-components-body">
          {render_quality_component_table(quality_score.get('components', []))}
        </div>
      </details>
    </div>

    <div class="section">
      <h2>Preprocessing QA</h2>
      <div class="panel">
        {render_gallery(qa_assets, prefix="../")}
      </div>
    </div>

    <div class="section">
      <h2>Artifact Review</h2>
      <div class="two-col">
        <div class="panel">
          {render_artifact_gallery(summary['artifacts']['assets'], prefix="../")}
        </div>
        <div class="panel">
          <div class="metric-list">
            <div class="metric-box"><div class="k">Bad-channel count</div><div class="v">{fmt_int(summary['artifacts']['bad_channels_count'])}</div></div>
            <div class="metric-box"><div class="k">Bad-segment count</div><div class="v">{fmt_int(summary['artifacts']['bad_segments'])}</div></div>
            <div class="metric-box"><div class="k">Bad Duration</div><div class="v">{fmt_float(summary['artifacts'].get('bad_duration_sec'), 1, ' s')}</div></div>
            <div class="metric-box"><div class="k">Bad-segment proportion</div><div class="v">{fmt_float((summary['artifacts'].get('bad_ratio') * 100) if summary['artifacts'].get('bad_ratio') is not None else None, 1, '%')}</div></div>
          </div>
          <div class="section">
            <h2>Bad-channel list</h2>
            {render_bad_channel_block(summary['artifacts']['bad_channels'])}
          </div>
          <div class="section">
            <h2>Bad-segment details</h2>
            {render_bad_segment_block(summary['artifacts'].get('bad_segment_rows', []))}
          </div>
        </div>
      </div>
    </div>

    <div class="section">
      <h2>ICA Review</h2>
      <div class="two-col">
        <div class="panel">
          <div class="info-note" style="margin-top:0; margin-bottom:12px">Detected abnormal ICA components are shown first and highlighted as components marked for exclusion. Unmarked components are retained as reference views.</div>
          {render_gallery(
              ica_topography_assets,
              prefix="../"
          )}
        </div>
        <div class="panel">
          <div class="metric-list">
            <div class="metric-box"><div class="k">Marked Components</div><div class="v">{fmt_int(summary['ica']['marked_count'])}</div></div>
            <div class="metric-box"><div class="k">ECG Candidates</div><div class="v">{fmt_int(len(summary['ica']['ecg_indices']))}</div></div>
            <div class="metric-box"><div class="k">EOG Candidates</div><div class="v">{fmt_int(len(summary['ica']['eog_indices']))}</div></div>
            <div class="metric-box"><div class="k">Components Total</div><div class="v">{fmt_int(summary['ica']['n_components'])}</div></div>
          </div>
          <div class="section">
            <h2>Marked Components</h2>
            <div class="chips">{''.join(f'<span class="chip">IC {html_text(comp)}</span>' for comp in summary['ica']['marked_components']) or '<span class="small">No marked components saved.</span>'}</div>
          </div>
          <div class="section">
            <h2>ICA timecourse panels</h2>
            {render_gallery(summary['ica']['sources'], prefix="../")}
          </div>
        </div>
      </div>
    </div>

    <div class="section">
      <h2>Epochs</h2>
      <div class="panel">
        <div class="metric-list">
          <div class="metric-box"><div class="k">Rejected Epochs</div><div class="v">{fmt_int(len(summary['epochs'].get('rejected_epochs', [])))}</div></div>
          <div class="metric-box"><div class="k">Remaining Epochs</div><div class="v">{fmt_int(summary['epochs'].get('remaining_epochs'))}</div></div>
          <div class="metric-box"><div class="k">Estimated Total</div><div class="v">{fmt_int(summary['epochs'].get('total_epochs_est'))}</div></div>
          <div class="metric-box"><div class="k">Epoch rejection rate</div><div class="v">{fmt_float((summary['epochs'].get('reject_rate') * 100) if summary['epochs'].get('reject_rate') is not None else None, 1, '%')}</div></div>
        </div>
        <div class="section">
          {render_gallery(summary['epochs']['assets'], prefix="../")}
        </div>
      </div>
    </div>

    <div class="section">
      <h2>Covariance</h2>
      <div class="panel">
        {render_gallery(summary['covariance']['assets'], prefix="../")}
      </div>
    </div>

    <div class="section">
      <h2>Coregistration</h2>
      <div class="panel">
        <div class="metric-list">
          <div class="metric-box"><div class="k">Mean Distance</div><div class="v">{fmt_float(summary['coregistration']['dist_mean'], 2, ' mm')}</div></div>
          <div class="metric-box"><div class="k">Max Distance</div><div class="v">{fmt_float(summary['coregistration']['dist_max'], 2, ' mm')}</div></div>
          <div class="metric-box"><div class="k">Min Distance</div><div class="v">{fmt_float(summary['coregistration']['dist_min'], 2, ' mm')}</div></div>
        </div>
        <div class="section">
          <div class="info-note" style="margin-top:0; margin-bottom:12px">Coregistration figures are grouped by processing stage. The final downstream transform corresponds to the fine-tuned ICP pair: <code>*_coreg_icp_finetune.png</code> and <code>*_coreg_icp_finetune_brain.png</code>.</div>
          {render_coreg_gallery(summary['coregistration']['assets'], prefix="../")}
        </div>
      </div>
    </div>

    <div class="section">
      <h2>Head model</h2>
      <div class="panel">
        {render_gallery(summary['headmodel']['assets'], prefix="../")}
      </div>
    </div>

    <div class="section">
      <h2>Source Localization</h2>
      <div class="panel">
        {render_gallery(summary['source']['assets'], prefix="../")}
      </div>
    </div>

    <div class="section">
      <h2>Packaged Sidecar Files</h2>
      <div class="panel">
        {render_file_rows(summary['files'], prefix="../")}
      </div>
    </div>

    <div class="footer">
      Generated by MEGFlow static HTML report generator on {html_text(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}.
    </div>
  </div>
</body>
</html>
"""

    subject_html_path = output_root / "subjects" / f"{summary['subject_slug']}.html"
    ensure_dir(subject_html_path.parent)
    with open(subject_html_path, "w", encoding="utf-8") as f:
        f.write(content)


def build_index_html(dataset_summary: dict[str, Any], subject_summaries: list[dict[str, Any]], output_root: Path) -> None:
    sorted_subjects = sorted(subject_summaries, key=lambda item: (str(item["subject"]).lower(), str(item["subject"])))
    threshold_counts = {
        "megqc_score": 0,
        "bad_channels": 0,
        "bad_segments": 0,
        "coreg_mean": 0,
        "epoch_reject": 0,
        "missing_steps": 0,
    }
    subject_rows = []
    for summary in sorted_subjects:
        bad_channels = summary["artifacts"]["bad_channels_count"]
        bad_segments = summary["artifacts"]["bad_segments"]
        megqc_score = summary["quality_score"].get("score_0_100")
        coreg_mean = summary["coregistration"]["dist_mean"]
        epoch_reject_rate = summary["epochs"].get("reject_rate")
        expected_steps = summary.get("expected_steps") or {}
        missing_steps = [
            key for key, _ in STEP_DEFS
            if expected_steps.get(key, True) and not summary["steps"].get(key)
        ]
        missing_steps_str = ",".join(missing_steps)
        risk_score = summary["alarm_count"] * 100
        risk_score += bad_channels
        risk_score += bad_segments
        if megqc_score is None:
            risk_score += 75
        else:
            risk_score += max(0, int((summary["thresholds"].get("megqc_alarm_score", 70) - float(megqc_score)) * 2))
        risk_score += int((epoch_reject_rate or 0) * 100)
        risk_score += len(missing_steps) * 25
        if coreg_mean is not None:
            risk_score += int(float(coreg_mean) * 10)
        summary["_static_risk_score"] = risk_score

        if megqc_score is None or float(megqc_score) < summary["thresholds"].get("megqc_alarm_score", 70):
            threshold_counts["megqc_score"] += 1
        if bad_channels > summary["thresholds"]["bad_channel_threshold"]:
            threshold_counts["bad_channels"] += 1
        if bad_segments > summary["thresholds"]["bad_segment_threshold"]:
            threshold_counts["bad_segments"] += 1
        if coreg_mean is not None and float(coreg_mean) > summary["thresholds"]["coreg_mean_threshold"]:
            threshold_counts["coreg_mean"] += 1
        if epoch_reject_rate is not None and float(epoch_reject_rate) > summary["thresholds"]["epoch_reject_rate_threshold"]:
            threshold_counts["epoch_reject"] += 1
        if missing_steps:
            threshold_counts["missing_steps"] += 1

        search_blob = " ".join(
            [
                summary["subject"],
                summary["status"],
                f"megqc:{megqc_score}",
                " ".join(alarm["category"] for alarm in summary["alarms"]),
                " ".join(alarm["message"] for alarm in summary["alarms"]),
                missing_steps_str,
            ]
        )
        row_class = ""
        if summary["status"] == "FAIL":
            row_class = "row-fail"
        elif summary["status"] == "WARN":
            row_class = "row-warn"
        failed_steps = summary.get("failed_steps") or {}
        step_data_attrs = " ".join(
            f'data-step-{key}="{"na" if not expected_steps.get(key, True) else ("failed" if failed_steps.get(key) else ("1" if summary["steps"].get(key) else "0"))}"'
            for key, _ in STEP_DEFS
        )
        subject_rows.append(
            f"""
            <tr class="{row_class}" data-search="{html_text(search_blob)}" data-status="{html_text(summary['status'].lower())}" data-subject="{html_text(summary['subject'])}" data-subject-url="subjects/{html_text(summary['subject_slug'])}.html" data-quality-score="{'' if megqc_score is None else megqc_score}" data-alarm-count="{summary['alarm_count']}" data-bad-channels="{bad_channels}" data-bad-segments="{bad_segments}" data-marked-ica="{summary['ica']['marked_count']}" data-coreg-mean="{'' if coreg_mean is None else coreg_mean}" data-coreg-max="{'' if summary['coregistration']['dist_max'] is None else summary['coregistration']['dist_max']}" data-epoch-reject="{'' if epoch_reject_rate is None else epoch_reject_rate}" data-risk-score="{risk_score}" data-missing-steps="{html_text(missing_steps_str)}" data-missing-count="{len(missing_steps)}" {step_data_attrs}>
              <td><a href="subjects/{html_text(summary['subject_slug'])}.html">{html_text(summary['subject'])}</a></td>
              <td>{render_status_pill(summary['status'])}</td>
              <td>{fmt_float(megqc_score, 1)}</td>
              <td>{fmt_int(summary['alarm_count'])}</td>
              <td>{fmt_int(bad_channels)}</td>
              <td>{fmt_int(bad_segments)}</td>
              <td>{fmt_int(summary['ica']['marked_count'])}</td>
              <td>{fmt_float(coreg_mean, 2)}</td>
              <td>{fmt_float(summary['coregistration']['dist_max'], 2)}</td>
              <td>{fmt_float((epoch_reject_rate * 100) if epoch_reject_rate is not None else None, 1, '%')}</td>
              <td>{render_step_snapshot(summary, compact=True)}</td>
            </tr>
            """
        )

    def subject_priority_key(summary: dict[str, Any]) -> tuple[int, int, int, str]:
        alarms = summary.get("alarms") or []
        danger_count = sum(1 for alarm in alarms if alarm.get("severity") == "danger")
        status_rank = {"FAIL": 0, "WARN": 1, "PASS": 2}.get(str(summary.get("status")), 3)
        return (status_rank, -danger_count, -int(summary.get("_static_risk_score") or 0), str(summary.get("subject") or ""))

    priority_subjects = sorted(
        [
            summary for summary in sorted_subjects if summary["status"] != "PASS" or summary["alarm_count"] > 0
        ],
        key=subject_priority_key,
    )
    hot_subjects = priority_subjects[:12]
    alarm_records = []
    for summary in hot_subjects:
        if not summary["alarms"]:
            continue
        for alarm in summary["alarms"]:
            alarm_records.append(
                {
                    "summary": summary,
                    "alarm": alarm,
                    "sort_key": (
                        0 if alarm.get("severity") == "danger" else 1,
                        subject_priority_key(summary),
                        str(alarm.get("category") or ""),
                    ),
                }
            )
    alarm_rows = []
    for record in sorted(alarm_records, key=lambda item: item["sort_key"]):
        summary = record["summary"]
        alarm = record["alarm"]
        css_class = "danger" if alarm["severity"] == "danger" else ""
        search_blob = f"{summary['subject']} {alarm['category']} {alarm['message']}"
        alarm_rows.append(
            f"""
            <div class="alarm-item alarm-row {css_class}" data-search="{html_text(search_blob)}">
              <div class="category"><a href="subjects/{html_text(summary['subject_slug'])}.html">{html_text(summary['subject'])}</a> · {html_text(alarm['category'])}</div>
              <div>{html_text(alarm['message'])}</div>
            </div>
            """
        )

    top_subject_cards = []
    for summary in priority_subjects[:6]:
        top_subject_cards.append(
            f"""
            <div class="top-subject-item">
              <strong><a href="subjects/{html_text(summary['subject_slug'])}.html">{html_text(summary['subject'])}</a></strong>
              <div class="chips">
                {render_status_pill(summary['status'])}
                <span class="pill neutral">QC alerts: {fmt_int(summary['alarm_count'])}</span>
              </div>
              <div class="small" style="margin-top:8px">Bad-channel count {fmt_int(summary['artifacts']['bad_channels_count'])}, bad-segment count {fmt_int(summary['artifacts']['bad_segments'])}, mean coregistration distance {fmt_float(summary['coregistration']['dist_mean'], 2, ' mm')}</div>
              <div class="small">QC score {fmt_float(summary['quality_score'].get('score_0_100'), 1)} / 100</div>
            </div>
            """
        )
    priority_placeholder = (
        '<div class="small">All subjects passed the current static thresholds.</div>'
        if not priority_subjects
        else '<div class="small">No subjects available.</div>'
    )

    threshold_cards = [
        ("QC score below threshold", threshold_counts["megqc_score"]),
        ("Bad-channel count above threshold", threshold_counts["bad_channels"]),
        ("Bad-segment count above threshold", threshold_counts["bad_segments"]),
        ("Mean coregistration distance above threshold", threshold_counts["coreg_mean"]),
        ("Epoch rejection rate above threshold", threshold_counts["epoch_reject"]),
        ("Any missing steps", threshold_counts["missing_steps"]),
    ]

    step_completion_summary = "".join(
        (
            f'<span class="summary-chip">{html_text(label)} N/A</span>'
            if not (dataset_summary.get("expected_steps") or {}).get(key, True)
            else f'<span class="summary-chip">{html_text(label)} {fmt_int(dataset_summary["step_completion"][key])}/{fmt_int(dataset_summary["total_subjects"])}</span>'
        )
        for key, label in STEP_DEFS
    )

    status_bar_items = []
    total_subjects = max(1, dataset_summary["total_subjects"])
    for label, count, css in [
        ("Passed", dataset_summary["pass_count"], "good"),
        ("Warning", dataset_summary["warn_count"], "warn"),
        ("Failed", dataset_summary["fail_count"], "danger"),
    ]:
        width = (count / total_subjects) * 100 if dataset_summary["total_subjects"] else 0
        status_bar_items.append(
            f"""
            <div>
              <div class="stat-bar-label">
                <span>{label}</span>
                <span>{fmt_int(count)} / {fmt_int(dataset_summary['total_subjects'])}</span>
              </div>
              <div class="stat-bar-track">
                <div class="stat-bar-fill" style="width:{width:.1f}%"></div>
              </div>
            </div>
            """
        )

    content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MEGFlow Processing and QC Report</title>
  <link rel="icon" type="image/png" href="assets/favicon.png">
  <link rel="stylesheet" href="assets/report.css">
  <script src="assets/report.js"></script>
</head>
<body>
  <div class="container">
    <div class="hero">
      <h1>MEGFlow Processing and QC Report</h1>
      <p>Dataset-level report for large-scale MEG processing and QC. It keeps summary pages, copied evidence figures, and sidecar files together for offline review and download.</p>
      <p>Report root: {html_text(dataset_summary['report_root'])}</p>
      <div class="filter-panel">
        <div class="filter-grid">
          <div class="control-group search-control">
            <label for="subjectSearch">Search</label>
            <input id="subjectSearch" type="text" placeholder="Search subject, status, or QC alert" oninput="resetSubjectPage()">
          </div>
          <div class="control-group">
            <label for="subjectStatusFilter">Status</label>
            <select id="subjectStatusFilter" onchange="resetSubjectPage()">
              <option value="all">All status</option>
              <option value="pass">Passed</option>
              <option value="warn">Warning</option>
              <option value="fail">Failed</option>
            </select>
          </div>
          <div class="control-group">
            <label for="subjectMissingStepFilter">Missing Step</label>
            <select id="subjectMissingStepFilter" onchange="resetSubjectPage()">
              <option value="all">All step completeness</option>
              <option value="quality_score">Missing quality score</option>
              <option value="basic_preproc">Missing basic preprocessing</option>
              <option value="artifacts">Missing artifacts</option>
              <option value="ica">Missing ICA</option>
              <option value="epochs">Missing epochs</option>
              <option value="covariance">Missing covariance</option>
              <option value="coregistration">Missing MEG-MRI coregistration</option>
              <option value="headmodel">Missing head model</option>
              <option value="source">Missing source localization</option>
            </select>
          </div>
          <div class="control-group">
            <label for="subjectSortBy">Sort</label>
            <select id="subjectSortBy" onchange="setSubjectSortFromSelect()">
              <option value="risk" selected>Sort by risk</option>
              <option value="status">Sort by status</option>
              <option value="subject">Sort by subject</option>
              <option value="missing_steps">Sort by missing steps</option>
              <option value="quality_score">Sort by quality score</option>
              <option value="alarm_count">Sort by QC alerts</option>
              <option value="bad_channels">Sort by bad-channel count</option>
              <option value="bad_segments">Sort by bad-segment count</option>
              <option value="marked_ica">Sort by marked ICA</option>
              <option value="coreg_mean">Sort by mean coregistration distance</option>
              <option value="coreg_max">Sort by maximum coregistration distance</option>
              <option value="epoch_reject">Sort by epoch rejection rate</option>
            </select>
          </div>
          <div class="quality-score-controls">
            <div class="control-group">
              <label for="qualityScoreMode">QC Score</label>
              <select id="qualityScoreMode" onchange="resetSubjectPage()">
                <option value="all">All scores</option>
                <option value="gte">Score at or above</option>
                <option value="lt">Score below</option>
                <option value="missing">Missing score</option>
              </select>
            </div>
            <div class="control-group">
              <label for="qualityScoreThreshold">QC Score Cutoff</label>
              <input id="qualityScoreThreshold" type="number" min="0" max="100" step="1" value="{fmt_float(dataset_summary['thresholds'].get('megqc_alarm_score'), 0)}" oninput="resetSubjectPage()">
            </div>
          </div>
          <div class="control-group">
            <label for="subjectPageSize">Page Size</label>
            <select id="subjectPageSize" onchange="resetSubjectPage()">
              <option value="10">10 / page</option>
              <option value="20" selected>20 / page</option>
              <option value="50">50 / page</option>
              <option value="100">100 / page</option>
            </select>
          </div>
        </div>
      </div>
      <div class="hero-links">
        <a href="data/dataset_summary.json" target="_blank">Dataset summary JSON</a>
        <a href="data/subjects.csv" target="_blank">Subjects CSV</a>
        <a href="alarms.html">QC alert board</a>
      </div>
    </div>
{dataset_summary.get("workflow_html") or ""}

    <div class="grid cards">
      <div class="card">
        <div class="label">Total Subjects</div>
        <div class="value">{fmt_int(dataset_summary['total_subjects'])}</div>
      </div>
      <div class="card">
        <div class="label">Passed</div>
        <div class="value">{fmt_int(dataset_summary['pass_count'])}</div>
      </div>
      <div class="card">
        <div class="label">Warning</div>
        <div class="value">{fmt_int(dataset_summary['warn_count'])}</div>
      </div>
      <div class="card">
        <div class="label">Failed</div>
        <div class="value">{fmt_int(dataset_summary['fail_count'])}</div>
      </div>
      <div class="card">
        <div class="label">Total QC alerts</div>
        <div class="value">{fmt_int(dataset_summary['alarm_count'])}</div>
      </div>
    </div>

    <div class="section">
      <div class="dashboard-grid">
        <div class="panel">
          <div class="panel-kicker">Dataset Overview</div>
          <div class="panel-title-row">
            <div class="panel-title-group">
              <h3>Preprocessing Overview</h3>
              <div class="panel-subtitle">Aggregate preprocessing quality indicators across the current dataset.</div>
            </div>
          </div>
          <div class="metric-list">
            <div class="metric-box"><div class="k">Mean QC score</div><div class="v">{fmt_float(dataset_summary['averages']['megqc_score'], 1)}</div></div>
            <div class="metric-box"><div class="k">Mean bad-channel count</div><div class="v">{fmt_float(dataset_summary['averages']['bad_channels'], 1)}</div></div>
            <div class="metric-box"><div class="k">Mean bad-segment count</div><div class="v">{fmt_float(dataset_summary['averages']['bad_segments'], 1)}</div></div>
            <div class="metric-box"><div class="k">Mean coregistration distance</div><div class="v">{fmt_float(dataset_summary['averages']['coreg_mean_mm'], 2, ' mm')}</div></div>
            <div class="metric-box"><div class="k">Maximum coregistration distance</div><div class="v">{fmt_float(dataset_summary['averages']['coreg_max_mm'], 2, ' mm')}</div></div>
            <div class="metric-box"><div class="k">Mean epoch rejection rate</div><div class="v">{fmt_float((dataset_summary['averages']['epoch_reject_rate'] * 100) if dataset_summary['averages']['epoch_reject_rate'] is not None else None, 1, '%')}</div></div>
            <div class="metric-box"><div class="k">Total QC alerts</div><div class="v">{fmt_int(dataset_summary['alarm_count'])}</div></div>
          </div>
        </div>
        <div class="panel">
          <div class="panel-kicker">Dataset Overview</div>
          <div class="panel-title-row">
            <div class="panel-title-group">
              <h3>Status Distribution</h3>
              <div class="panel-subtitle">Passed, Warning, and Failed counts under the current static QC rules.</div>
            </div>
          </div>
          <div class="stat-bar-list">
            {''.join(status_bar_items)}
          </div>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="panel">
        <div class="panel-kicker">Completion Matrix</div>
        <div class="panel-title-row">
          <div class="panel-title-group">
            <h3>Step Completion Heat Matrix</h3>
            <div class="panel-subtitle">Current-page subjects on rows, preprocessing steps on columns, with sticky subject labels for large datasets.</div>
          </div>
        </div>
        <div class="step-matrix-shell">
          <div class="step-matrix-meta">
            <div class="small" id="stepMatrixInfo">Heat matrix shows the current page slice and updates with homepage filters.</div>
            <div class="step-matrix-summary" id="stepMatrixSummary">{step_completion_summary}</div>
          </div>
          <div id="stepCompletionMatrix">
            <div class="small">Loading step matrix...</div>
          </div>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="panel">
        <div class="panel-kicker">Priority Queue</div>
        <div class="panel-title-row">
          <div class="panel-title-group">
            <h3>Subjects Prioritized for Review</h3>
            <div class="panel-subtitle">Subjects with the highest number or severity of QC alerts.</div>
          </div>
        </div>
        <div class="top-subject-list">
          {''.join(top_subject_cards) or priority_placeholder}
        </div>
      </div>
    </div>

    <div class="section">
      <div class="dashboard-grid">
        <div class="panel">
          <div class="panel-kicker">Thresholds</div>
          <div class="panel-title-row">
            <div class="panel-title-group">
              <h3>Threshold Exceedance Summary</h3>
              <div class="panel-subtitle">Counts of subjects breaching the current static QC thresholds.</div>
            </div>
          </div>
          <div class="metric-list">
            {''.join(f'<div class="metric-box"><div class="k">{html_text(label)}</div><div class="v">{fmt_int(count)}</div></div>' for label, count in threshold_cards)}
          </div>
        </div>
        <div class="panel">
          <div class="panel-kicker">Rulebook</div>
          <div class="panel-title-row">
            <div class="panel-title-group">
              <h3>Static QC Rule Summary</h3>
              <div class="panel-subtitle">How the static report derives Passed, Warning, Failed, and completion state.</div>
            </div>
          </div>
          <div class="rule-list">
            <div class="rule-item"><strong>Passed</strong><div class="small">No QC alerts under the current static thresholds.</div></div>
            <div class="rule-item"><strong>Warning</strong><div class="small">1-2 QC alerts and no danger-level alert.</div></div>
            <div class="rule-item"><strong>Failed</strong><div class="small">3 or more QC alerts, or at least one danger-level alert such as a coregistration threshold breach.</div></div>
            <div class="rule-item"><strong>Normative Reference QC Score</strong><div class="small">0-100, higher is better. Files below the processing minimum are skipped downstream; files below the warning threshold remain visible and are flagged.</div></div>
            <div class="rule-item"><strong>Step Completion</strong><div class="small">Completion is presence-based. A step counts as complete when its expected report outputs exist, not when it necessarily passes QC.</div></div>
            <div class="rule-item"><strong>Adjust Thresholds</strong><div class="small">Regenerate the static report with CLI flags such as <code>--bad_channel_threshold</code>, <code>--bad_segment_threshold</code>, <code>--coreg_mean_threshold</code>, <code>--coreg_max_threshold</code>, and <code>--epoch_reject_rate_threshold</code>.</div></div>
          </div>
        </div>
      </div>
    </div>

    <div class="section">
      <h2>High-Priority QC Alerts</h2>
      <div class="panel">
        <div class="toolbar" style="margin-top:0">
          <input id="alarmSearch" type="text" placeholder="Search QC alerts" oninput="filterAlarmRows('alarmSearch', 'alarmBoard')">
        </div>
        <div class="table-count" id="alarmCountInfo" style="margin-bottom:10px">Showing 0 of 0 QC alerts</div>
        <div id="alarmBoard" class="alarm-list">
          {''.join(alarm_rows) or '<div class="small">No QC alerts found across the dataset.</div>'}
        </div>
      </div>
    </div>

    <div class="section">
      <h2>Subject Summary Table</h2>
      <div class="panel table-wrap">
        <div class="subject-table-controls">
          <div class="table-count" id="subjectCountInfo">Showing 0-0 of 0 matched subjects</div>
          <div class="pager">
            <button id="subjectPrevBtn" onclick="setSubjectPage(-1)">Previous</button>
            <span id="subjectPageInfo" class="table-count">Page 1 / 1</span>
            <button id="subjectNextBtn" onclick="setSubjectPage(1)">Next</button>
          </div>
        </div>
        <table id="subjectTable">
          <thead>
            <tr>
              <th class="sortable"><button type="button" class="sort-header" data-sort-key="subject" onclick="setSubjectSort('subject')"><span>Subject</span><span class="sort-indicator">↕</span></button></th>
              <th class="sortable"><button type="button" class="sort-header" data-sort-key="status" onclick="setSubjectSort('status')"><span>Status</span><span class="sort-indicator">↕</span></button></th>
              <th class="sortable"><button type="button" class="sort-header" data-sort-key="quality_score" onclick="setSubjectSort('quality_score')"><span>QC Score</span><span class="sort-indicator">↕</span></button></th>
              <th class="sortable"><button type="button" class="sort-header" data-sort-key="alarm_count" onclick="setSubjectSort('alarm_count')"><span>QC alerts</span><span class="sort-indicator">↕</span></button></th>
              <th class="sortable"><button type="button" class="sort-header" data-sort-key="bad_channels" onclick="setSubjectSort('bad_channels')"><span>Bad-channel count</span><span class="sort-indicator">↕</span></button></th>
              <th class="sortable"><button type="button" class="sort-header" data-sort-key="bad_segments" onclick="setSubjectSort('bad_segments')"><span>Bad-segment count</span><span class="sort-indicator">↕</span></button></th>
              <th class="sortable"><button type="button" class="sort-header" data-sort-key="marked_ica" onclick="setSubjectSort('marked_ica')"><span>Marked ICA</span><span class="sort-indicator">↕</span></button></th>
              <th class="sortable"><button type="button" class="sort-header" data-sort-key="coreg_mean" onclick="setSubjectSort('coreg_mean')"><span>Mean coregistration distance</span><span class="sort-indicator">↕</span></button></th>
              <th class="sortable"><button type="button" class="sort-header" data-sort-key="coreg_max" onclick="setSubjectSort('coreg_max')"><span>Maximum coregistration distance</span><span class="sort-indicator">↕</span></button></th>
              <th class="sortable"><button type="button" class="sort-header" data-sort-key="epoch_reject" onclick="setSubjectSort('epoch_reject')"><span>Epoch rejection rate</span><span class="sort-indicator">↕</span></button></th>
              <th>Step Snapshot</th>
            </tr>
          </thead>
          <tbody>
            {''.join(subject_rows) or '<tr><td colspan="11">No subjects found.</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>

    <div class="footer">
      Generated by MEGFlow static HTML report generator on {html_text(dataset_summary['generated_at'])}.
    </div>
  </div>
</body>
</html>
"""

    with open(output_root / "index.html", "w", encoding="utf-8") as f:
        f.write(content)


def build_alarms_html(subject_summaries: list[dict[str, Any]], output_root: Path) -> None:
    rows = []
    for summary in sorted(subject_summaries, key=lambda item: (-item["alarm_count"], item["subject"])):
        for alarm in summary["alarms"]:
            css_class = "danger" if alarm["severity"] == "danger" else ""
            search_blob = f"{summary['subject']} {alarm['category']} {alarm['severity']} {alarm['message']}"
            rows.append(
                f"""
                <div class="alarm-item alarm-row {css_class}" data-search="{html_text(search_blob)}">
                  <div class="category"><a href="subjects/{html_text(summary['subject_slug'])}.html">{html_text(summary['subject'])}</a> · {html_text(alarm['category'])}</div>
                  <div>{html_text(alarm['message'])}</div>
                </div>
                """
            )

    content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MEGFlow QC Alert Board</title>
  <link rel="icon" type="image/png" href="assets/favicon.png">
  <link rel="stylesheet" href="assets/report.css">
  <script src="assets/report.js"></script>
</head>
<body>
  <div class="container">
    <a class="back-link" href="index.html">&larr; Back to dataset summary</a>
    <div class="hero">
      <h1>QC Alert Board</h1>
      <p>Cross-subject static QC alert board for fast triage and prioritization.</p>
      <div class="toolbar">
        <input id="alarmSearch" type="text" placeholder="Search subject, category, or message" oninput="filterAlarmRows('alarmSearch', 'alarmList')">
      </div>
    </div>
    <div class="panel">
      <div id="alarmList" class="alarm-list">
        {''.join(rows) or '<div class="small">No QC alerts. All subjects passed the static checks.</div>'}
      </div>
    </div>
    <div class="footer">
      Generated by MEGFlow static HTML report generator on {html_text(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}.
    </div>
  </div>
</body>
</html>
"""

    with open(output_root / "alarms.html", "w", encoding="utf-8") as f:
        f.write(content)


def write_assets(output_root: Path) -> None:
    assets_dir = ensure_dir(output_root / "assets")
    with open(assets_dir / "report.css", "w", encoding="utf-8") as f:
        f.write(REPORT_CSS)
    with open(assets_dir / "report.js", "w", encoding="utf-8") as f:
        f.write(REPORT_JS)
    if FAVICON_PATH.exists():
        shutil.copy2(FAVICON_PATH, assets_dir / "favicon.png")


def generate_static_report(args: argparse.Namespace) -> Path:
    report_root_input = Path(args.report_root).resolve()
    report_root, preprocessed_dir = resolve_report_dirs(report_root_input)
    output_root = Path(args.output_dir).resolve() if args.output_dir else report_root / "static_html_report"
    thresholds = {
        "bad_channel_threshold": args.bad_channel_threshold,
        "bad_segment_threshold": args.bad_segment_threshold,
        "coreg_mean_threshold": args.coreg_mean_threshold,
        "coreg_max_threshold": args.coreg_max_threshold,
        "epoch_reject_rate_threshold": args.epoch_reject_rate_threshold,
        "megqc_alarm_score": args.megqc_alarm_score,
    }

    if output_root.exists():
        shutil.rmtree(output_root)
    ensure_dir(output_root)
    write_assets(output_root)

    subjects = find_subjects(preprocessed_dir)
    if not subjects:
        raise ValueError(
            f"No subjects were discovered under preprocessed directory: {preprocessed_dir}. "
            "Please verify that the MEGFlow outputs have been generated."
        )
    wf_ctx = load_workflow_context(report_root, preprocessed_dir)
    qc_scope = qc_completeness_scope_from_manifest(wf_ctx.get("manifest"))
    task_details_by_subject = collect_nextflow_task_details(
        report_root,
        preprocessed_dir,
        output_root,
        subjects,
        wf_ctx.get("manifest") if isinstance(wf_ctx.get("manifest"), dict) else None,
        task_log_mode=args.task_log_mode,
    )
    if not qc_scope.get("run_meg"):
        inferred_scope = infer_qc_scope_from_task_details(task_details_by_subject)
        if inferred_scope:
            qc_scope = inferred_scope
            wf_ctx = apply_inferred_workflow_scope(wf_ctx, inferred_scope)
    subject_summaries = [
        collect_subject_data(
            subject,
            report_root,
            output_root,
            thresholds,
            qc_scope=qc_scope,
            task_details=task_details_by_subject.get(subject, []),
            artifact_overview_duration=args.artifact_overview_duration,
        )
        for subject in subjects
    ]
    ensure_dir(output_root / "data")
    manifest_src = preprocessed_dir / "logs" / "megflow_run_manifest.json"
    if manifest_src.is_file():
        shutil.copy2(manifest_src, output_root / "data" / "megflow_run_manifest.json")
    cfg_dst = output_root / "data" / "nextflow.config.txt"
    wf_ctx["nextflow_config_bundled"] = False
    wf_ctx["nextflow_config_source_name"] = None
    mfest = wf_ctx.get("manifest") if isinstance(wf_ctx.get("manifest"), dict) else None
    cfg_src, cfg_src_desc = _nextflow_config_source_for_bundle(report_root, preprocessed_dir, mfest)
    if cfg_src is not None:
        shutil.copy2(cfg_src, cfg_dst)
        wf_ctx["nextflow_config_bundled"] = True
        wf_ctx["nextflow_config_source_name"] = cfg_src_desc
    workflow_html = render_workflow_dataset_html(wf_ctx, subject_summaries)
    wf_meta = workflow_meta_for_json(wf_ctx)
    dataset_summary = build_dataset_summary(
        report_root,
        output_root,
        subject_summaries,
        thresholds,
        workflow_html=workflow_html,
        workflow_meta=wf_meta,
        qc_scope=qc_scope,
    )

    for summary in subject_summaries:
        build_subject_html(summary, output_root)

    build_index_html(dataset_summary, subject_summaries, output_root)
    build_alarms_html(subject_summaries, output_root)

    if str_to_bool(args.zip_output):
        shutil.make_archive(str(output_root), "zip", root_dir=output_root)

    return output_root


def main() -> None:
    args = parse_args()
    output_root = generate_static_report(args)
    print(f"Static HTML report generated at: {output_root}")
    if str_to_bool(args.zip_output):
        print(f"Zip package generated at: {output_root}.zip")


if __name__ == "__main__":
    main()
