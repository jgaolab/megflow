#!/usr/bin/env python3
"""Shared directory layout for MEGFlow static and Nextflow reports."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DATASET_SCOPE = "dataset"
CORPUS_SCOPE = "corpus"
REPORT_PACKAGE_NAMES = {
    DATASET_SCOPE: "static_html_report",
    CORPUS_SCOPE: "corpus_static_html_report",
}
NEXTFLOW_DIRNAME = "nextflow"


@dataclass(frozen=True)
class NextflowArtifacts:
    directory: Path
    report: Path
    timeline: Path
    trace: Path
    log: Path
    legacy: bool = False


def normalize_report_scope(scope: str | None) -> str:
    normalized = str(scope or DATASET_SCOPE).strip().lower()
    if normalized not in REPORT_PACKAGE_NAMES:
        raise ValueError(
            f"Unsupported report scope: {scope!r}. "
            f"Expected one of: {', '.join(sorted(REPORT_PACKAGE_NAMES))}."
        )
    return normalized


def infer_report_scope(run_root: Path | str) -> str:
    root = Path(run_root)
    if root.name == REPORT_PACKAGE_NAMES[CORPUS_SCOPE]:
        return CORPUS_SCOPE
    if (root / REPORT_PACKAGE_NAMES[CORPUS_SCOPE]).is_dir() or (root / "datasets").is_dir():
        return CORPUS_SCOPE
    return DATASET_SCOPE


def report_package_dir(run_root: Path | str, scope: str = DATASET_SCOPE) -> Path:
    return Path(run_root) / REPORT_PACKAGE_NAMES[normalize_report_scope(scope)]


def canonical_nextflow_dir(run_root: Path | str, scope: str = DATASET_SCOPE) -> Path:
    root = Path(run_root)
    normalized_scope = normalize_report_scope(scope)
    if root.name == REPORT_PACKAGE_NAMES[normalized_scope]:
        return root / NEXTFLOW_DIRNAME
    return report_package_dir(root, normalized_scope) / NEXTFLOW_DIRNAME


def nextflow_artifacts(directory: Path | str, *, legacy: bool = False) -> NextflowArtifacts:
    directory = Path(directory)
    return NextflowArtifacts(
        directory=directory,
        report=directory / "report.html",
        timeline=directory / "timeline.html",
        trace=directory / "trace.txt",
        log=directory / "nextflow.log",
        legacy=legacy,
    )


def candidate_nextflow_dirs(run_root: Path | str, scope: str | None = None) -> list[Path]:
    root = Path(run_root)
    inferred_scope = normalize_report_scope(scope) if scope is not None else infer_report_scope(root)
    alternate_scope = CORPUS_SCOPE if inferred_scope == DATASET_SCOPE else DATASET_SCOPE
    candidates: list[Path] = []

    if root.name == NEXTFLOW_DIRNAME:
        candidates.append(root)
    if root.name in REPORT_PACKAGE_NAMES.values():
        candidates.append(root / NEXTFLOW_DIRNAME)
    candidates.append(canonical_nextflow_dir(root, inferred_scope))
    if scope is None:
        candidates.append(canonical_nextflow_dir(root, alternate_scope))
    candidates.append(root / NEXTFLOW_DIRNAME)

    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate not in seen:
            unique.append(candidate)
            seen.add(candidate)
    return unique


def resolve_nextflow_artifacts(run_root: Path | str, scope: str | None = None) -> NextflowArtifacts:
    """Resolve the run-level Nextflow files, preferring the canonical layout."""

    root = Path(run_root)
    for directory in candidate_nextflow_dirs(root, scope):
        if directory.is_dir():
            return nextflow_artifacts(directory)

    legacy_corpus = NextflowArtifacts(
        directory=root,
        report=root / "corpus_report.html",
        timeline=root / "corpus_timeline.html",
        trace=root / "corpus_trace.txt",
        log=root / "logs" / "nextflow.log",
        legacy=True,
    )
    legacy_dataset = NextflowArtifacts(
        directory=root,
        report=root / "report.html",
        timeline=root / "timeline.html",
        trace=root / "trace.txt",
        log=root / "logs" / "nextflow.log",
        legacy=True,
    )
    legacy_layouts = (
        (legacy_corpus, legacy_dataset)
        if infer_report_scope(root) == CORPUS_SCOPE
        else (legacy_dataset, legacy_corpus)
    )
    for layout in legacy_layouts:
        if any(path.is_file() for path in (layout.report, layout.timeline, layout.trace, layout.log)):
            return layout

    target_scope = normalize_report_scope(scope) if scope is not None else infer_report_scope(root)
    return nextflow_artifacts(canonical_nextflow_dir(root, target_scope))


def prepare_report_output(output_root: Path | str, managed_directories: Iterable[str]) -> Path:
    """Rebuild MEGFlow-owned directories while preserving ``nextflow/``."""

    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    for name in managed_directories:
        if not name or Path(name).name != name:
            raise ValueError(f"Managed report directory must be a simple name: {name!r}")
        if name == NEXTFLOW_DIRNAME:
            raise ValueError(f"{NEXTFLOW_DIRNAME}/ is owned by Nextflow and cannot be rebuilt")
        path = root / name
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
    return root
