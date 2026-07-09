#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build a static corpus-level HTML report from multiple MEGFlow dataset reports.

The corpus report bundles each dataset-level ``static_html_report`` package so
the output directory can be downloaded and viewed offline without copying the
full preprocessing outputs.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


STEP_DEFS = [
    ("quality_score", "Quality score"),
    ("basic_preproc", "Basic preprocessing"),
    ("artifacts", "Artifacts"),
    ("ica", "ICA"),
    ("epochs", "Epochs"),
    ("covariance", "Covariance"),
    ("coregistration", "MEG-MRI coregistration"),
    ("headmodel", "Head model"),
    ("source", "Source localization"),
]

STATIC_DIR = Path(__file__).resolve().parent / "_static"
FAVICON_PATH = STATIC_DIR / "favicon.png"


REPORT_CSS = """
:root {
  --bg: #f7f8fb;
  --panel: #ffffff;
  --text: #17212b;
  --muted: #667085;
  --line: #dbe4ee;
  --accent: #2f6fed;
  --accent-soft: #eef4ff;
  --good: #067647;
  --good-soft: #ddf9eb;
  --warn: #b54708;
  --warn-soft: #fff4dd;
  --danger: #c4320a;
  --danger-soft: #ffe9e5;
  --shadow: 0 14px 36px rgba(15, 23, 42, 0.08);
}

* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  background: var(--bg);
  color: var(--text);
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.container {
  width: min(1320px, calc(100% - 48px));
  margin: 0 auto;
  padding: 28px 0 56px;
}
.hero {
  background: linear-gradient(180deg, #f1f6ff, #eaf1ff);
  border: 1px solid rgba(47, 111, 237, 0.14);
  border-radius: 24px;
  box-shadow: var(--shadow);
  padding: 28px 32px;
  margin-bottom: 22px;
}
.eyebrow {
  display: inline-flex;
  padding: 6px 12px;
  border-radius: 999px;
  background: rgba(47, 111, 237, 0.08);
  color: #1f4acc;
  font-size: 0.84rem;
  font-weight: 700;
  margin-bottom: 10px;
}
h1 { margin: 0 0 10px; font-size: 2.05rem; }
h2 { margin: 0; font-size: 1.1rem; }
p { color: var(--muted); margin: 6px 0; }
.grid {
  display: grid;
  gap: 16px;
}
.kpi-grid {
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  margin-bottom: 22px;
}
.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 20px;
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.05);
}
.kpi .label {
  color: var(--muted);
  font-size: 0.84rem;
  font-weight: 700;
}
.kpi .value {
  font-size: 2rem;
  font-weight: 800;
  margin-top: 8px;
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 16px;
}
.toolbar input,
.toolbar select {
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 10px 12px;
  min-width: 180px;
  background: #fff;
}
.pill {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 0.82rem;
  font-weight: 700;
  white-space: nowrap;
}
.pill.good { color: var(--good); background: var(--good-soft); }
.pill.warn { color: var(--warn); background: var(--warn-soft); }
.pill.danger { color: var(--danger); background: var(--danger-soft); }
.pill.neutral { color: #475467; background: #eef2f6; }
.step-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.step-chip {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 4px 8px;
  font-size: 0.78rem;
  color: #475467;
  background: #fff;
}
table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 14px;
}
th, td {
  border-bottom: 1px solid var(--line);
  padding: 12px 10px;
  text-align: left;
  vertical-align: middle;
  font-size: 0.92rem;
}
th {
  color: var(--muted);
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
th.sortable {
  padding: 0;
}
.sort-header {
  width: 100%;
  min-height: 42px;
  display: inline-flex;
  align-items: center;
  justify-content: flex-start;
  gap: 6px;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  letter-spacing: inherit;
  text-transform: inherit;
  text-align: left;
  cursor: pointer;
  padding: 12px 10px;
}
.sort-header:hover,
.sort-header.active {
  color: var(--accent);
}
.sort-indicator {
  color: #98a2b3;
  font-size: 0.74rem;
}
.sort-header.active .sort-indicator {
  color: var(--accent);
}
tr:hover td { background: #fafcff; }
.mono {
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 0.82rem;
  color: #475467;
  overflow-wrap: anywhere;
}
.footer {
  color: var(--muted);
  font-size: 0.84rem;
  margin-top: 24px;
  text-align: center;
}
@media (max-width: 980px) {
  .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .container { width: min(100% - 28px, 1320px); }
  table { display: block; overflow-x: auto; white-space: nowrap; }
}
"""


REPORT_JS = """
window.__datasetTableState = { sortKey: "alarms", sortDirection: "desc" };

function normalizeText(value) {
  return (value || "").toString().trim().toLowerCase();
}

function toNumber(value) {
  if (value === undefined || value === null || value === "") {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function getDefaultSortDirection(sortKey) {
  return sortKey === "dataset" || sortKey === "status" ? "asc" : "desc";
}

function compareText(a, b) {
  return normalizeText(a).localeCompare(normalizeText(b), undefined, { numeric: true, sensitivity: "base" });
}

function compareNumbers(a, b, direction) {
  const na = toNumber(a);
  const nb = toNumber(b);
  if (na === null && nb === null) return 0;
  if (na === null) return 1;
  if (nb === null) return -1;
  return direction === "asc" ? na - nb : nb - na;
}

function compareDatasetRows(a, b, sortKey, direction) {
  let result = 0;
  if (sortKey === "dataset") {
    result = compareText(a.dataset.dataset, b.dataset.dataset);
    return direction === "asc" ? result : -result;
  }
  if (sortKey === "status") {
    result = compareNumbers(a.dataset.statusRank, b.dataset.statusRank, "asc");
    return direction === "asc" ? result : -result;
  }
  result = compareNumbers(a.dataset[sortKey], b.dataset[sortKey], direction);
  if (result !== 0) {
    return result;
  }
  return compareText(a.dataset.dataset, b.dataset.dataset);
}

function updateDatasetSortHeaders() {
  const state = window.__datasetTableState;
  document.querySelectorAll("#datasetTable [data-sort-key]").forEach((button) => {
    const active = button.dataset.sortKey === state.sortKey;
    button.classList.toggle("active", active);
    button.setAttribute("aria-sort", active ? state.sortDirection : "none");
    const indicator = button.querySelector(".sort-indicator");
    if (indicator) {
      indicator.textContent = active ? (state.sortDirection === "asc" ? "↑" : "↓") : "↕";
    }
  });
}

function setDatasetSort(sortKey) {
  const state = window.__datasetTableState;
  if (state.sortKey === sortKey) {
    state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
  } else {
    state.sortKey = sortKey;
    state.sortDirection = getDefaultSortDirection(sortKey);
  }
  filterDatasets();
}

function filterDatasets() {
  const query = normalizeText(document.getElementById("datasetSearch")?.value);
  const status = normalizeText(document.getElementById("datasetStatus")?.value || "all");
  const tbody = document.querySelector("#datasetTable tbody");
  if (!tbody) return;
  const state = window.__datasetTableState;
  const rows = Array.from(tbody.querySelectorAll("tr[data-search]"));
  rows.sort((a, b) => compareDatasetRows(a, b, state.sortKey, state.sortDirection));
  rows.forEach((row) => tbody.appendChild(row));
  let visible = 0;
  rows.forEach((row) => {
    const matchesQuery = !query || normalizeText(row.dataset.search).includes(query);
    const matchesStatus = status === "all" || normalizeText(row.dataset.status) === status;
    const show = matchesQuery && matchesStatus;
    row.style.display = show ? "" : "none";
    if (show) visible += 1;
  });
  const count = document.getElementById("datasetCount");
  if (count) count.textContent = `${visible} dataset${visible === 1 ? "" : "s"} shown`;
  updateDatasetSortHeaders();
}

document.addEventListener("DOMContentLoaded", filterDatasets);
"""


@dataclass
class DatasetReport:
    name: str
    output_root: Path
    static_report_dir: Path
    summary_path: Path
    report_index: Path
    summary: dict[str, Any]


def html_text(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def fmt_int(value: Any) -> str:
    try:
        return f"{int(value)}"
    except (TypeError, ValueError):
        return "N/A"


def fmt_float(value: Any, digits: int = 1, suffix: str = "") -> str:
    try:
        return f"{float(value):.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return "N/A"


def finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def average(values: list[float | None]) -> float | None:
    cleaned = [float(value) for value in values if value is not None]
    if not cleaned:
        return None
    return sum(cleaned) / len(cleaned)


def status_pill(status: str) -> str:
    status = (status or "UNKNOWN").upper()
    labels = {
        "PASS": ("good", "Passed"),
        "WARN": ("warn", "Warning"),
        "FAIL": ("danger", "Failed"),
    }
    css, label = labels.get(status, ("neutral", status))
    return f'<span class="pill {css}">{html_text(label)}</span>'


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def slugify(value: Any, fallback: str = "dataset") -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("._-")
    return slug or fallback


def load_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        value = json.load(f)
    return value if isinstance(value, dict) else {}


def discover_dataset_reports(corpus_root: Path, output_dir: Path | None = None) -> list[DatasetReport]:
    reports: list[DatasetReport] = []
    corpus_root = corpus_root.resolve()
    output_dir_resolved = output_dir.resolve() if output_dir else None

    for summary_path in sorted(corpus_root.rglob("static_html_report/data/dataset_summary.json")):
        if output_dir_resolved and output_dir_resolved in summary_path.resolve().parents:
            continue
        static_report_dir = summary_path.parents[1]
        dataset_output_root = summary_path.parents[2]
        report_index = static_report_dir / "index.html"
        if not report_index.is_file():
            continue
        summary = load_json(summary_path)
        reports.append(
            DatasetReport(
                name=dataset_output_root.name,
                output_root=dataset_output_root,
                static_report_dir=static_report_dir,
                summary_path=summary_path,
                report_index=report_index,
                summary=summary,
            )
        )

    return reports


def bundle_dataset_reports(reports: list[DatasetReport], output_dir: Path) -> dict[Path, str]:
    """Copy dataset-level static reports into the corpus package.

    Returns a map from source dataset summary path to the bundled index.html path
    relative to the corpus output directory.
    """
    bundled_links: dict[Path, str] = {}
    datasets_dir = ensure_dir(output_dir / "datasets")
    used_names: dict[str, int] = {}

    for report in reports:
        base_name = slugify(report.name)
        used_names[base_name] = used_names.get(base_name, 0) + 1
        dataset_dir_name = base_name if used_names[base_name] == 1 else f"{base_name}-{used_names[base_name]}"
        dest_static_dir = datasets_dir / dataset_dir_name / "static_html_report"
        if dest_static_dir.exists():
            shutil.rmtree(dest_static_dir)
        ensure_dir(dest_static_dir.parent)
        shutil.copytree(report.static_report_dir, dest_static_dir)
        inject_corpus_back_links(dest_static_dir, output_dir / "index.html", report.name)
        bundled_links[report.summary_path] = os.path.relpath(dest_static_dir / "index.html", output_dir)

    return bundled_links


def write_assets(output_dir: Path) -> None:
    assets_dir = ensure_dir(output_dir / "assets")
    if FAVICON_PATH.exists():
        shutil.copy2(FAVICON_PATH, assets_dir / "favicon.png")


def inject_corpus_back_links(static_report_dir: Path, corpus_index: Path, dataset_name: str) -> None:
    marker = "<!-- megflow-corpus-back-link -->"
    for html_path in sorted(static_report_dir.rglob("*.html")):
        try:
            content = html_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if marker in content or "<body" not in content:
            continue

        rel_corpus_index = os.path.relpath(corpus_index, html_path.parent)
        link_html = f"""
{marker}
<div style="position:sticky;top:12px;z-index:9999;width:min(1500px,calc(100% - 48px));margin:12px auto 0;display:flex;align-items:center;gap:10px;padding:10px 14px;border:1px solid #dbe4ee;border-radius:14px;background:rgba(255,255,255,.94);box-shadow:0 10px 28px rgba(15,23,42,.08);font-family:Segoe UI,PingFang SC,Microsoft YaHei,sans-serif;font-size:14px;backdrop-filter:blur(8px);">
  <a href="{html.escape(rel_corpus_index)}" style="color:#1f4acc;text-decoration:none;font-weight:800;">&larr; Corpus overview</a>
  <span style="color:#667085;">{html.escape(dataset_name)}</span>
</div>
"""
        updated = re.sub(r"(<body[^>]*>)", r"\1" + link_html, content, count=1, flags=re.IGNORECASE)
        html_path.write_text(updated, encoding="utf-8")


def build_corpus_summary(
    reports: list[DatasetReport],
    corpus_root: Path,
    output_dir: Path,
    bundled_links: dict[Path, str],
) -> dict[str, Any]:
    total_subjects = sum(int(report.summary.get("total_subjects") or 0) for report in reports)
    pass_count = sum(int(report.summary.get("pass_count") or 0) for report in reports)
    warn_count = sum(int(report.summary.get("warn_count") or 0) for report in reports)
    fail_count = sum(int(report.summary.get("fail_count") or 0) for report in reports)
    alarm_count = sum(int(report.summary.get("alarm_count") or 0) for report in reports)
    all_megqc_scores: list[float | None] = []
    total_qc_scored = 0
    total_qc_missing = 0
    total_qc_warning = 0

    step_completion = {
        key: sum(int((report.summary.get("step_completion") or {}).get(key) or 0) for report in reports)
        for key, _ in STEP_DEFS
    }
    step_expected_subjects = {
        key: sum(
            int(report.summary.get("total_subjects") or 0)
            for report in reports
            if (report.summary.get("expected_steps") or {}).get(key, True)
        )
        for key, _ in STEP_DEFS
    }

    datasets = []
    for report in reports:
        source_rel_index = os.path.relpath(report.report_index, output_dir)
        bundled_rel_index = bundled_links.get(report.summary_path, source_rel_index)
        summary = report.summary
        total = int(summary.get("total_subjects") or 0)
        thresholds = summary.get("thresholds") or {}
        megqc_alarm_score = finite_float(thresholds.get("megqc_alarm_score"))
        subjects = summary.get("subjects") or []
        subject_scores = [finite_float(item.get("megqc_score")) for item in subjects if isinstance(item, dict)]
        scored_scores = [score for score in subject_scores if score is not None]
        qc_scored_count = len(scored_scores)
        qc_missing_count = max(total - qc_scored_count, 0)
        qc_warning_count = (
            sum(1 for score in scored_scores if megqc_alarm_score is not None and score < megqc_alarm_score)
            if megqc_alarm_score is not None
            else 0
        )
        all_megqc_scores.extend(scored_scores)
        total_qc_scored += qc_scored_count
        total_qc_missing += qc_missing_count
        total_qc_warning += qc_warning_count
        status = "PASS"
        if int(summary.get("fail_count") or 0) > 0:
            status = "FAIL"
        elif int(summary.get("warn_count") or 0) > 0:
            status = "WARN"
        datasets.append(
            {
                "dataset": report.name,
                "status": status,
                "total_subjects": total,
                "pass_count": int(summary.get("pass_count") or 0),
                "warn_count": int(summary.get("warn_count") or 0),
                "fail_count": int(summary.get("fail_count") or 0),
                "alarm_count": int(summary.get("alarm_count") or 0),
                "report_root": summary.get("report_root", str(report.output_root)),
                "report_index": bundled_rel_index,
                "source_report_index": source_rel_index,
                "step_completion": summary.get("step_completion") or {},
                "expected_steps": summary.get("expected_steps") or {},
                "averages": summary.get("averages") or {},
                "quality_score": {
                    "avg_score": average(scored_scores),
                    "scored_count": qc_scored_count,
                    "missing_count": qc_missing_count,
                    "warning_count": qc_warning_count,
                    "alarm_score": megqc_alarm_score,
                },
            }
        )

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "corpus_root": str(corpus_root),
        "dataset_count": len(reports),
        "total_subjects": total_subjects,
        "pass_count": pass_count,
        "warn_count": warn_count,
        "fail_count": fail_count,
        "alarm_count": alarm_count,
        "quality_score": {
            "avg_score": average(all_megqc_scores),
            "scored_count": total_qc_scored,
            "missing_count": total_qc_missing,
            "warning_count": total_qc_warning,
        },
        "step_completion": step_completion,
        "step_expected_subjects": step_expected_subjects,
        "datasets": datasets,
    }


def write_data_files(summary: dict[str, Any], output_dir: Path) -> None:
    data_dir = ensure_dir(output_dir / "data")
    with open(data_dir / "corpus_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    with open(data_dir / "datasets.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "dataset",
                "status",
                "total_subjects",
                "pass_count",
                "warn_count",
                "fail_count",
                "alarm_count",
                "avg_megqc_score",
                "megqc_scored_count",
                "megqc_missing_count",
                "megqc_warning_count",
                "megqc_alarm_score",
                "report_index",
                "source_report_index",
                "report_root",
            ]
        )
        for dataset in summary["datasets"]:
            writer.writerow(
                [
                    dataset["dataset"],
                    dataset["status"],
                    dataset["total_subjects"],
                    dataset["pass_count"],
                    dataset["warn_count"],
                    dataset["fail_count"],
                    dataset["alarm_count"],
                    (dataset.get("quality_score") or {}).get("avg_score"),
                    (dataset.get("quality_score") or {}).get("scored_count"),
                    (dataset.get("quality_score") or {}).get("missing_count"),
                    (dataset.get("quality_score") or {}).get("warning_count"),
                    (dataset.get("quality_score") or {}).get("alarm_score"),
                    dataset["report_index"],
                    dataset.get("source_report_index", ""),
                    dataset["report_root"],
                ]
            )


def build_index_html(summary: dict[str, Any], output_dir: Path) -> None:
    status_rank = {"PASS": 0, "WARN": 1, "FAIL": 2}
    rows = []
    for dataset in sorted(summary["datasets"], key=lambda item: (-item["alarm_count"], item["dataset"])):
        step_chips = "".join(
            (
                f'<span class="step-chip">{html_text(label)} N/A</span>'
                if not (dataset.get("expected_steps") or {}).get(key, True)
                else f'<span class="step-chip">{html_text(label)} '
                f'{fmt_int((dataset.get("step_completion") or {}).get(key))}/{fmt_int(dataset["total_subjects"])}</span>'
            )
            for key, label in STEP_DEFS
        )
        averages = dataset.get("averages") or {}
        quality_score = dataset.get("quality_score") or {}
        search_blob = " ".join(
            [
                dataset["dataset"],
                dataset["status"],
                dataset.get("report_root", ""),
            ]
        )
        avg_qc = (dataset.get("quality_score") or {}).get("avg_score")
        qc_warnings = (dataset.get("quality_score") or {}).get("warning_count")
        avg_bad_channels = averages.get("bad_channels")
        avg_bad_segments = averages.get("bad_segments")
        avg_coreg = averages.get("coreg_mean_mm")
        rows.append(
            f"""
            <tr data-status="{html_text(dataset['status'].lower())}"
                data-status-rank="{status_rank.get(str(dataset['status']).upper(), 99)}"
                data-search="{html_text(search_blob)}"
                data-dataset="{html_text(dataset['dataset'])}"
                data-subjects="{html_text(dataset['total_subjects'])}"
                data-passed="{html_text(dataset['pass_count'])}"
                data-warning="{html_text(dataset['warn_count'])}"
                data-failed="{html_text(dataset['fail_count'])}"
                data-alarms="{html_text(dataset['alarm_count'])}"
                data-avg-qc="{html_text('' if avg_qc is None else avg_qc)}"
                data-qc-warnings="{html_text('' if qc_warnings is None else qc_warnings)}"
                data-avg-bad-ch="{html_text('' if avg_bad_channels is None else avg_bad_channels)}"
                data-avg-bad-seg="{html_text('' if avg_bad_segments is None else avg_bad_segments)}"
                data-avg-coreg="{html_text('' if avg_coreg is None else avg_coreg)}">
              <td><a href="{html_text(dataset['report_index'])}">{html_text(dataset['dataset'])}</a></td>
              <td>{status_pill(dataset['status'])}</td>
              <td>{fmt_int(dataset['total_subjects'])}</td>
              <td>{fmt_int(dataset['pass_count'])}</td>
              <td>{fmt_int(dataset['warn_count'])}</td>
              <td>{fmt_int(dataset['fail_count'])}</td>
              <td>{fmt_int(dataset['alarm_count'])}</td>
              <td>{fmt_float(avg_qc, 1)}</td>
              <td>{fmt_int(qc_warnings)}</td>
              <td>{fmt_float(avg_bad_channels, 1)}</td>
              <td>{fmt_float(avg_bad_segments, 1)}</td>
              <td>{fmt_float(avg_coreg, 2, ' mm')}</td>
              <td><div class="step-chips">{step_chips}</div></td>
            </tr>
            """
        )

    step_summary = "".join(
        (
            f'<span class="step-chip">{html_text(label)} N/A</span>'
            if not int((summary.get("step_expected_subjects") or {}).get(key) or 0)
            else f'<span class="step-chip">{html_text(label)} {fmt_int(summary["step_completion"].get(key))}/{fmt_int((summary.get("step_expected_subjects") or {}).get(key))}</span>'
        )
        for key, label in STEP_DEFS
    )

    content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MEGFlow Corpus Static Report</title>
  <link rel="icon" type="image/png" href="assets/favicon.png">
  <style>{REPORT_CSS}</style>
</head>
<body>
  <div class="container">
    <section class="hero">
      <div class="eyebrow">MEGFlow Corpus Report</div>
      <h1>Corpus-Level MEG Processing and QC Summary</h1>
      <p>Aggregated static report across multiple bundled MEGFlow dataset-level reports.</p>
      <p class="mono">Corpus root: {html_text(summary['corpus_root'])}</p>
      <div class="toolbar">
        <input id="datasetSearch" type="text" placeholder="Search dataset or path" oninput="filterDatasets()">
        <select id="datasetStatus" onchange="filterDatasets()">
          <option value="all">All statuses</option>
          <option value="pass">Passed</option>
          <option value="warn">Warning</option>
          <option value="fail">Failed</option>
        </select>
        <a href="data/corpus_summary.json" target="_blank">Corpus JSON</a>
        <a href="data/datasets.csv" target="_blank">Datasets CSV</a>
      </div>
    </section>

    <section class="grid kpi-grid">
      <div class="panel kpi"><div class="label">Datasets</div><div class="value">{fmt_int(summary['dataset_count'])}</div></div>
      <div class="panel kpi"><div class="label">Subjects</div><div class="value">{fmt_int(summary['total_subjects'])}</div></div>
      <div class="panel kpi"><div class="label">Passed</div><div class="value">{fmt_int(summary['pass_count'])}</div></div>
      <div class="panel kpi"><div class="label">Warning / Failed</div><div class="value">{fmt_int(summary['warn_count'])} / {fmt_int(summary['fail_count'])}</div></div>
      <div class="panel kpi"><div class="label">QC alerts</div><div class="value">{fmt_int(summary['alarm_count'])}</div></div>
      <div class="panel kpi"><div class="label">Mean QC score</div><div class="value">{fmt_float((summary.get('quality_score') or {}).get('avg_score'), 1)}</div></div>
      <div class="panel kpi"><div class="label">QC Warnings</div><div class="value">{fmt_int((summary.get('quality_score') or {}).get('warning_count'))}</div></div>
    </section>

    <section class="panel">
      <h2>Pipeline Completion</h2>
      <p>Completed subject counts summed across all dataset-level reports.</p>
      <div class="step-chips">{step_summary}</div>
    </section>

    <section class="panel" style="margin-top:16px">
      <h2>Datasets</h2>
      <p id="datasetCount">0 datasets shown</p>
      <table id="datasetTable">
        <thead>
          <tr>
            <th class="sortable"><button type="button" class="sort-header" data-sort-key="dataset" onclick="setDatasetSort('dataset')"><span>Dataset</span><span class="sort-indicator">↕</span></button></th>
            <th class="sortable"><button type="button" class="sort-header" data-sort-key="status" onclick="setDatasetSort('status')"><span>Status</span><span class="sort-indicator">↕</span></button></th>
            <th class="sortable"><button type="button" class="sort-header" data-sort-key="subjects" onclick="setDatasetSort('subjects')"><span>Subjects</span><span class="sort-indicator">↕</span></button></th>
            <th class="sortable"><button type="button" class="sort-header" data-sort-key="passed" onclick="setDatasetSort('passed')"><span>Passed</span><span class="sort-indicator">↕</span></button></th>
            <th class="sortable"><button type="button" class="sort-header" data-sort-key="warning" onclick="setDatasetSort('warning')"><span>Warning</span><span class="sort-indicator">↕</span></button></th>
            <th class="sortable"><button type="button" class="sort-header" data-sort-key="failed" onclick="setDatasetSort('failed')"><span>Failed</span><span class="sort-indicator">↕</span></button></th>
            <th class="sortable"><button type="button" class="sort-header" data-sort-key="alarms" onclick="setDatasetSort('alarms')"><span>QC alerts</span><span class="sort-indicator">↕</span></button></th>
            <th class="sortable"><button type="button" class="sort-header" data-sort-key="avgQc" onclick="setDatasetSort('avgQc')"><span>Mean QC score</span><span class="sort-indicator">↕</span></button></th>
            <th class="sortable"><button type="button" class="sort-header" data-sort-key="qcWarnings" onclick="setDatasetSort('qcWarnings')"><span>QC Warnings</span><span class="sort-indicator">↕</span></button></th>
            <th class="sortable"><button type="button" class="sort-header" data-sort-key="avgBadCh" onclick="setDatasetSort('avgBadCh')"><span>Mean bad-channel count</span><span class="sort-indicator">↕</span></button></th>
            <th class="sortable"><button type="button" class="sort-header" data-sort-key="avgBadSeg" onclick="setDatasetSort('avgBadSeg')"><span>Mean bad-segment count</span><span class="sort-indicator">↕</span></button></th>
            <th class="sortable"><button type="button" class="sort-header" data-sort-key="avgCoreg" onclick="setDatasetSort('avgCoreg')"><span>Mean coregistration distance</span><span class="sort-indicator">↕</span></button></th>
            <th>Steps</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows) or '<tr><td colspan="13">No dataset reports found.</td></tr>'}
        </tbody>
      </table>
    </section>
    <div class="footer">Generated by MEGFlow corpus static report on {html_text(summary['generated_at'])}.</div>
  </div>
  <script>{REPORT_JS}</script>
</body>
</html>
"""
    with open(output_dir / "index.html", "w", encoding="utf-8") as f:
        f.write(content)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a corpus-level static HTML report.")
    parser.add_argument(
        "--corpus_root",
        default=None,
        help="Directory containing one or more MEGFlow output roots with static_html_report bundles.",
    )
    parser.add_argument(
        "--output_dir",
        default=None,
        help="Directory to write the portable corpus report package. Defaults to <corpus_root>/corpus_static_html_report.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.corpus_root:
        raise SystemExit("--corpus_root is required")
    corpus_root = Path(args.corpus_root).resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else corpus_root / "corpus_static_html_report"
    if output_dir == corpus_root:
        raise ValueError("--output_dir must be separate from --corpus_root so source dataset reports are not overwritten.")
    reports = discover_dataset_reports(corpus_root, output_dir)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    ensure_dir(output_dir)
    write_assets(output_dir)
    bundled_links = bundle_dataset_reports(reports, output_dir)
    summary = build_corpus_summary(reports, corpus_root, output_dir, bundled_links)
    write_data_files(summary, output_dir)
    build_index_html(summary, output_dir)
    print(f"Corpus static report generated at {output_dir}")


if __name__ == "__main__":
    main()
