import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import mne
import numpy as np
from PIL import Image


REPORTS_DIR = Path(__file__).resolve().parents[1] / "megflow" / "reports"
if str(REPORTS_DIR) not in sys.path:
    sys.path.insert(0, str(REPORTS_DIR))

import corpus_static_html_report as corpus_report
import report_layout
import static_html_report as static_report
import workflow_diagram as workflow_report


class ReportDirectoryLifecycleTests(unittest.TestCase):
    def test_static_and_corpus_pages_link_to_canonical_nextflow_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)
            nextflow_dir = output_root / "nextflow"
            nextflow_dir.mkdir()
            (nextflow_dir / "trace.txt").write_text("trace", encoding="utf-8")
            (nextflow_dir / "nextflow.log").write_text("log", encoding="utf-8")

            for rendered in (
                static_report.render_nextflow_artifact_links(output_root),
                corpus_report.render_nextflow_artifact_links(output_root),
            ):
                self.assertIn('href="nextflow/report.html"', rendered)
                self.assertIn('href="nextflow/timeline.html"', rendered)
                self.assertIn('href="nextflow/trace.txt"', rendered)
                self.assertIn('href="nextflow/nextflow.log"', rendered)

    def test_selective_rebuild_preserves_nextflow_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "static_html_report"
            trace_file = output_root / "nextflow" / "trace.txt"
            stale_subject = output_root / "subjects" / "sub-removed.html"
            stale_asset = output_root / "assets" / "old.css"
            trace_file.parent.mkdir(parents=True)
            stale_subject.parent.mkdir(parents=True)
            stale_asset.parent.mkdir(parents=True)
            trace_file.write_text("live trace\n", encoding="utf-8")
            stale_subject.write_text("old subject", encoding="utf-8")
            stale_asset.write_text("old css", encoding="utf-8")

            report_layout.prepare_report_output(
                output_root,
                static_report.MANAGED_REPORT_DIRECTORIES,
            )

            self.assertEqual(trace_file.read_text(encoding="utf-8"), "live trace\n")
            self.assertFalse(stale_subject.exists())
            self.assertFalse(stale_asset.exists())
            for directory in static_report.MANAGED_REPORT_DIRECTORIES:
                self.assertTrue((output_root / directory).is_dir())

    def test_nextflow_directory_cannot_be_managed_by_report_generator(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(ValueError, "owned by Nextflow"):
                report_layout.prepare_report_output(Path(tmpdir), ["nextflow"])

    def test_run_level_resolver_prefers_corpus_layout_and_supports_legacy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_root = Path(tmpdir)
            corpus_nextflow = run_root / "corpus_static_html_report" / "nextflow"
            corpus_nextflow.mkdir(parents=True)
            (corpus_nextflow / "trace.txt").write_text("trace", encoding="utf-8")

            resolved = report_layout.resolve_nextflow_artifacts(run_root)
            self.assertEqual(resolved.directory, corpus_nextflow)
            self.assertEqual(resolved.report, corpus_nextflow / "report.html")
            self.assertFalse(resolved.legacy)

        with tempfile.TemporaryDirectory() as tmpdir:
            run_root = Path(tmpdir)
            (run_root / "corpus_report.html").write_text("report", encoding="utf-8")
            (run_root / "datasets").mkdir()

            resolved = report_layout.resolve_nextflow_artifacts(run_root)
            self.assertEqual(resolved.report, run_root / "corpus_report.html")
            self.assertTrue(resolved.legacy)

    def test_explicit_report_scope_does_not_cross_into_other_new_layout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_root = Path(tmpdir)
            (run_root / "static_html_report" / "nextflow").mkdir(parents=True)

            resolved = report_layout.resolve_nextflow_artifacts(
                run_root,
                report_layout.CORPUS_SCOPE,
            )

            self.assertEqual(
                resolved.directory,
                run_root / "corpus_static_html_report" / "nextflow",
            )


class StaticIcaAlertConfigurationTests(unittest.TestCase):
    def test_missing_ecg_eog_component_alerts_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_root = Path(tmpdir) / "report"
            ica_dir = report_root / "preprocessed" / "ica_report" / "sub-01"
            ica_dir.mkdir(parents=True)
            (ica_dir / "marked_components.txt").write_text("", encoding="utf-8")
            (ica_dir / "ecg_eog_scores.json").write_text(
                json.dumps({"ecg_indices": [], "eog_indices": [], "ecg": [], "eog": []}),
                encoding="utf-8",
            )

            default_summary = static_report.collect_subject_data(
                "sub-01",
                report_root,
                Path(tmpdir) / "default_report",
                dict(static_report.DEFAULT_THRESHOLDS),
            )
            default_messages = {alarm["message"] for alarm in default_summary["alarms"]}
            self.assertIn("No ECG-related components detected.", default_messages)
            self.assertIn("No EOG-related components detected.", default_messages)

            disabled_summary = static_report.collect_subject_data(
                "sub-01",
                report_root,
                Path(tmpdir) / "disabled_report",
                dict(static_report.DEFAULT_THRESHOLDS),
                alert_missing_ecg_components=False,
                alert_missing_eog_components=False,
            )
            disabled_messages = {alarm["message"] for alarm in disabled_summary["alarms"]}
            self.assertNotIn("No ECG-related components detected.", disabled_messages)
            self.assertNotIn("No EOG-related components detected.", disabled_messages)

            (ica_dir / "ecg_eog_scores.json").write_text(
                json.dumps(
                    {
                        "ecg_indices": [],
                        "eog_indices": [],
                        "ecg": [],
                        "eog": [],
                        "category_switches": {
                            "ecg": False,
                            "eog": True,
                            "outlier": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            category_gated_summary = static_report.collect_subject_data(
                "sub-01",
                report_root,
                Path(tmpdir) / "category_gated_report",
                dict(static_report.DEFAULT_THRESHOLDS),
                qc_scope={
                    "meg_stage": 3,
                    "skip_ica": False,
                    "run_meg": True,
                    "megqc_enabled": True,
                },
            )
            category_gated_messages = {
                alarm["message"] for alarm in category_gated_summary["alarms"]
            }
            self.assertNotIn(
                "No ECG-related components detected.",
                category_gated_messages,
            )
            self.assertIn(
                "No EOG-related components detected.",
                category_gated_messages,
            )
            self.assertFalse(category_gated_summary["ica"]["ecg_enabled"])
            self.assertTrue(category_gated_summary["ica"]["eog_enabled"])


class StaticManifestScopeTests(unittest.TestCase):
    def test_nested_ica_category_switches_control_report_expectations(self):
        manifest = {
            "parsed": {
                "primary": "meg_all",
                "meg_stage": 3,
                "run_meg": True,
                "run_anatomy": False,
                "skip_ica": False,
            },
            "params_snapshot": {
                "effective_config": {
                    "ic_label": {
                        "ic_ecg": False,
                        "ic_eog": True,
                    }
                }
            },
        }

        scope = static_report.qc_completeness_scope_from_manifest(manifest)

        self.assertFalse(scope["ic_ecg_enabled"])
        self.assertTrue(scope["ic_eog_enabled"])

    def test_nested_effective_config_disables_normmeg_qc_expectations(self):
        manifest = {
            "parsed": {
                "primary": "meg_all",
                "meg_stage": 3,
                "run_meg": True,
                "run_anatomy": False,
                "skip_ica": False,
            },
            "params_snapshot": {
                "effective_config": {"megqc": {"enabled": False}}
            },
        }

        scope = static_report.qc_completeness_scope_from_manifest(manifest)
        nodes, _ = static_report.build_workflow_nodes(manifest, "manifest")

        self.assertFalse(scope["megqc_enabled"])
        self.assertNotIn("quality_score", {node["key"] for node in nodes})

        with tempfile.TemporaryDirectory() as tmpdir:
            summary = static_report.collect_subject_data(
                "sub-01_task-rest_meg",
                Path(tmpdir) / "run",
                Path(tmpdir) / "static",
                dict(static_report.DEFAULT_THRESHOLDS),
                qc_scope=scope,
            )

        quality_categories = {
            alarm["category"]
            for alarm in summary["alarms"]
            if alarm["category"] == static_report.NMDQ_FULL_NAME
        }
        self.assertEqual(quality_categories, set())

    def test_disabled_normmeg_qc_ignores_stale_score_sidecars(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            subject = "sub-01_task-rest_meg"
            qc_dir = root / "run" / "preprocessed" / "quality_control" / subject
            qc_dir.mkdir(parents=True)
            (qc_dir / "old-model.summary.json").write_text(
                json.dumps({"score_0_100": 91.0}), encoding="utf-8"
            )

            summary = static_report.collect_subject_data(
                subject,
                root / "run",
                root / "static",
                dict(static_report.DEFAULT_THRESHOLDS),
                qc_scope={
                    "meg_stage": 3,
                    "skip_ica": False,
                    "run_meg": True,
                    "megqc_enabled": False,
                },
            )

        self.assertFalse(summary["quality_score"]["exists"])
        self.assertFalse(summary["steps"]["quality_score"])
        self.assertIsNone(summary["quality_score"]["score_0_100"])

    def test_completion_uses_derivatives_when_optional_figures_are_disabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            report_root = root / "run"
            preprocessed = report_root / "preprocessed"
            subject = "sub-01_task-test_meg"

            epoch_dir = preprocessed / "epochs" / subject
            covariance_dir = preprocessed / "covariance" / subject
            forward_dir = preprocessed / "forward_solution" / subject
            source_dir = preprocessed / "source_recon" / subject
            for directory in (epoch_dir, covariance_dir, forward_dir, source_dir):
                directory.mkdir(parents=True)

            (epoch_dir / "test-epo.fif").touch()
            (covariance_dir / "bl-cov.fif").touch()
            (covariance_dir / "resolved-rank.json").write_text(
                json.dumps({"rank": {"meg": 50}}), encoding="utf-8"
            )
            (forward_dir / "test-ico4-fwd.fif").touch()
            (source_dir / "test_evoked_dSPM-ico4-stc.h5").touch()

            summary = static_report.collect_subject_data(
                subject,
                report_root,
                root / "static",
                dict(static_report.DEFAULT_THRESHOLDS),
                qc_scope={
                    "meg_stage": 3,
                    "skip_ica": False,
                    "run_meg": True,
                    "megqc_enabled": False,
                },
            )

        for step in ("epochs", "covariance", "headmodel", "source"):
            self.assertTrue(summary["steps"][step], step)

    def test_workflow_details_read_nested_effective_configuration(self):
        manifest = {
            "steps_raw": "all",
            "parsed": {
                "primary": "all",
                "meg_stage": 3,
                "run_meg": True,
                "run_anatomy": True,
                "skip_ica": False,
            },
            "params_snapshot": {
                "dataset_dir": "/data/study",
                "effective_config": {
                    "dataset_format": "bids",
                    "is_bids": True,
                    "anatomy": {"method": "deepprep"},
                    "megqc": {
                        "enabled": False,
                        "min_score": 50.0,
                        "alarm_score": 70.0,
                    },
                    "covariance": {"type": "raw"},
                    "source": {"type": "epochs"},
                },
            },
        }

        groups = {
            title: dict(rows)
            for title, rows in workflow_report._workflow_detail_groups(manifest)
        }

        self.assertEqual(groups["Input data"]["dataset_format"], "bids")
        self.assertEqual(groups["Input data"]["is_bids"], "yes")
        self.assertEqual(groups["Normative QC"]["megqc_enabled"], "no")
        self.assertEqual(groups["Normative QC"]["megqc_min_score"], "50.0")
        self.assertEqual(groups["Anatomy"]["anatomy_preprocess_method"], "deepprep")
        self.assertEqual(groups["Source model"]["covar_type"], "raw")
        self.assertEqual(groups["Source model"]["src_type"], "epochs")

    def test_missing_config_hint_does_not_claim_a_nonexistent_snapshot_copy(self):
        rendered = workflow_report._nextflow_config_hint_html(
            {"nextflow_config_bundled": False}
        )

        self.assertNotIn("into <code>preprocessed/logs/</code>", rendered)
        self.assertIn("dataset output root", rendered)

    def test_full_workflow_diagram_uses_scientific_branch_dependencies(self):
        manifest = {
            "steps_raw": "all",
            "parsed": {
                "primary": "all",
                "meg_stage": 3,
                "run_meg": True,
                "run_anatomy": True,
                "skip_ica": False,
            },
            "params_snapshot": {
                "effective_config": {
                    "megqc": {"enabled": False},
                    "covariance": {"type": "epochs"},
                    "source": {"type": "epochs"},
                }
            },
        }

        nodes, _ = workflow_report.build_workflow_nodes(manifest, "manifest")
        dependencies = {
            node["key"]: set(node.get("depends_on", [])) for node in nodes
        }
        labels = {node["key"]: node["label"] for node in nodes}
        lanes = {node["key"]: node["lane"] for node in nodes}

        self.assertEqual(dependencies["covariance"], {"epochs"})
        self.assertEqual(
            dependencies["coregistration"],
            {"ica", "anatomy_structural"},
        )
        self.assertEqual(
            dependencies["headmodel"],
            {"coregistration", "anatomy_structural"},
        )
        self.assertEqual(
            dependencies["source"],
            {"epochs", "covariance", "headmodel"},
        )
        self.assertEqual(labels["headmodel"], "Head model")
        self.assertEqual(lanes["coregistration"], "model")
        self.assertEqual(lanes["headmodel"], "model")

    def test_raw_covariance_and_raw_source_branch_from_clean_meg(self):
        manifest = {
            "steps_raw": "meg_all",
            "parsed": {
                "primary": "meg_all",
                "meg_stage": 3,
                "run_meg": True,
                "run_anatomy": False,
                "skip_ica": False,
            },
            "params_snapshot": {
                "effective_config": {
                    "megqc": {"enabled": False},
                    "covariance": {"type": "raw"},
                    "source": {"type": "raw"},
                }
            },
        }

        nodes, _ = workflow_report.build_workflow_nodes(manifest, "manifest")
        dependencies = {
            node["key"]: set(node.get("depends_on", [])) for node in nodes
        }

        self.assertEqual(dependencies["covariance"], {"ica"})
        self.assertEqual(dependencies["coregistration"], {"ica"})
        self.assertEqual(dependencies["headmodel"], {"coregistration"})
        self.assertEqual(
            dependencies["source"],
            {"ica", "covariance", "headmodel"},
        )

    def test_skip_ica_connects_artifacts_directly_to_epochs(self):
        manifest = {
            "steps_raw": "meg_epochs,skip_ica",
            "parsed": {
                "primary": "meg_epochs",
                "meg_stage": 2,
                "run_meg": True,
                "run_anatomy": False,
                "skip_ica": True,
            },
            "params_snapshot": {
                "effective_config": {"megqc": {"enabled": False}}
            },
        }

        nodes, _ = workflow_report.build_workflow_nodes(manifest, "manifest")
        dependencies = {
            node["key"]: set(node.get("depends_on", [])) for node in nodes
        }

        self.assertNotIn("ica", dependencies)
        self.assertEqual(dependencies["epochs"], {"artifacts"})

    def test_workflow_svg_routes_explicit_anatomy_edges_orthogonally(self):
        manifest = {
            "steps_raw": "all",
            "parsed": {
                "primary": "all",
                "meg_stage": 3,
                "run_meg": True,
                "run_anatomy": True,
                "skip_ica": False,
            },
            "params_snapshot": {
                "effective_config": {
                    "megqc": {"enabled": False},
                    "covariance": {"type": "epochs"},
                    "source": {"type": "epochs"},
                }
            },
        }
        nodes, _ = workflow_report.build_workflow_nodes(manifest, "manifest")

        rendered = workflow_report._render_svg(nodes, lambda _node: "done")

        self.assertIn('class="wf-edge wf-edge-direct"', rendered)
        self.assertIn(
            'class="wf-edge wf-edge-routed wf-edge-cross-lane"',
            rendered,
        )
        self.assertIn(
            'data-from="anatomy_structural" data-to="coregistration"',
            rendered,
        )
        self.assertIn(
            'data-from="anatomy_structural" data-to="headmodel"',
            rendered,
        )
        self.assertIn(
            'data-from="anatomy_structural" data-to="coregistration">'
            '<title>Structural MRI -&gt; Coregistration</title>'
            '<path d="M330.0,270.0 V332.0 H584.0 V310.0"',
            rendered,
        )
        self.assertIn(
            'data-from="anatomy_structural" data-to="headmodel">'
            '<title>Structural MRI -&gt; Head model</title>'
            '<path d="M260.0,310.0 V344.0 H746.0 V310.0"',
            rendered,
        )
        self.assertNotIn('d="M330.0,270.0 H514.0"', rendered)
        self.assertIn(
            "<title>Structural MRI -&gt; Coregistration</title>",
            rendered,
        )
        self.assertIn(
            "<title>Structural MRI -&gt; Head model</title>",
            rendered,
        )
        self.assertIn('class="wf-port"', rendered)
        self.assertNotRegex(rendered, r'd="[^"]*\bC')
        self.assertNotIn("wf-edge-branch", rendered)

    def test_full_workflow_svg_uses_requested_cross_lane_ports_and_small_marker(self):
        manifest = {
            "steps_raw": "meg_all",
            "parsed": {
                "primary": "meg_all",
                "meg_stage": 3,
                "run_meg": True,
                "run_anatomy": False,
                "skip_ica": False,
            },
            "params_snapshot": {
                "effective_config": {
                    "megqc": {"enabled": True},
                    "covariance": {"type": "epochs"},
                    "source": {"type": "epochs"},
                }
            },
        }
        nodes, _ = workflow_report.build_workflow_nodes(manifest, "manifest")

        rendered = workflow_report._render_svg(nodes, lambda _node: "done")

        self.assertIn(
            'markerWidth="7" markerHeight="7" refX="6.5" refY="3.5" '
            'orient="auto" markerUnits="userSpaceOnUse"',
            rendered,
        )
        self.assertIn(
            'data-from="ica" data-to="coregistration"><title>ICA -&gt; '
            'Coregistration</title><path d="M584.0,146.0 V270.0 H676.0"',
            rendered,
        )
        self.assertIn(
            'data-from="headmodel" data-to="source"><title>Head model -&gt; '
            'Source localization</title><path d="M978.0,270.0 H1070.0 V146.0"',
            rendered,
        )
        self.assertIn('data-from="epochs" data-to="source"', rendered)
        self.assertIn('data-from="covariance" data-to="source"', rendered)
        self.assertIn('r="2.6" class="wf-port"', rendered)

    def test_workflow_connector_css_restores_light_visual_hierarchy(self):
        css = static_report.REPORT_CSS

        self.assertIn("fill: rgba(66, 103, 213, 0.38);", css)
        self.assertIn("stroke: rgba(66, 103, 213, 0.26);", css)
        self.assertIn("stroke-width: 1.8;", css)
        self.assertNotIn("rgba(57, 80, 157, 0.82)", css)
        self.assertNotIn("rgba(57, 80, 157, 0.68)", css)
        self.assertNotIn("rgba(77, 92, 151, 0.66)", css)
        self.assertNotIn("rgba(41, 91, 137, 0.72)", css)


class CorpusDatasetStepsTests(unittest.TestCase):
    def test_dataset_steps_are_compact_with_expandable_details(self):
        dataset = {
            "total_subjects": 10,
            "expected_steps": {key: True for key, _ in corpus_report.STEP_DEFS},
            "step_completion": {key: 10 for key, _ in corpus_report.STEP_DEFS},
        }

        rendered = corpus_report.render_dataset_steps(dataset)

        self.assertIn('class="dataset-steps complete"', rendered)
        self.assertIn('class="step-progress"', rendered)
        self.assertIn('style="width:100.0%"', rendered)
        self.assertIn('class="step-count">9/9</span>', rendered)
        self.assertIn("90/90 subject-stage outputs", rendered)
        self.assertEqual(rendered.count('class="step-chip"'), 9)

    def test_partial_and_not_applicable_steps_are_summarized_correctly(self):
        expected_steps = {key: True for key, _ in corpus_report.STEP_DEFS}
        expected_steps["source"] = False
        completion = {key: 10 for key, _ in corpus_report.STEP_DEFS}
        completion["coregistration"] = 8
        dataset = {
            "total_subjects": 10,
            "expected_steps": expected_steps,
            "step_completion": completion,
        }

        rendered = corpus_report.render_dataset_steps(dataset)

        self.assertIn('class="dataset-steps partial"', rendered)
        self.assertIn('class="step-count">7/8</span>', rendered)
        self.assertIn("78/80 subject-stage outputs", rendered)
        self.assertIn("Source localization N/A", rendered)


class CorpusBundledNavigationTests(unittest.TestCase):
    def test_corpus_bundle_keeps_one_run_level_nextflow_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_output = root / "source" / "StudyA"
            source_static = source_output / "static_html_report"
            source_summary = source_static / "data" / "dataset_summary.json"
            source_summary.parent.mkdir(parents=True)
            (source_static / "index.html").write_text("<html><body>dataset</body></html>", encoding="utf-8")
            source_summary.write_text("{}", encoding="utf-8")
            source_nextflow = source_static / "nextflow"
            source_nextflow.mkdir()
            (source_nextflow / "report.html").write_text("dataset copy", encoding="utf-8")

            corpus_output = root / "corpus_static_html_report"
            corpus_trace = corpus_output / "nextflow" / "trace.txt"
            corpus_trace.parent.mkdir(parents=True)
            corpus_trace.write_text("run trace", encoding="utf-8")
            report = corpus_report.DatasetReport(
                name="StudyA",
                output_root=source_output,
                static_report_dir=source_static,
                summary_path=source_summary,
                report_index=source_static / "index.html",
                summary={},
            )

            corpus_report.bundle_dataset_reports([report], corpus_output)

            bundled_static = corpus_output / "datasets" / "StudyA" / "static_html_report"
            self.assertFalse((bundled_static / "nextflow").exists())
            self.assertEqual(corpus_trace.read_text(encoding="utf-8"), "run trace")

    def test_subject_navigation_returns_to_dataset_overview(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            corpus_dir = Path(tmpdir) / "corpus_report"
            static_dir = corpus_dir / "datasets" / "StudyA" / "static_html_report"
            subject_page = static_dir / "subjects" / "sub-01.html"
            dataset_page = static_dir / "index.html"
            corpus_page = corpus_dir / "index.html"
            subject_page.parent.mkdir(parents=True)
            corpus_page.parent.mkdir(parents=True, exist_ok=True)
            subject_page.write_text("<html><body>subject</body></html>", encoding="utf-8")
            dataset_page.write_text("<html><body>dataset</body></html>", encoding="utf-8")
            corpus_page.write_text("<html><body>corpus</body></html>", encoding="utf-8")

            corpus_report.inject_corpus_back_links(static_dir, corpus_page, "StudyA")

            subject_html = subject_page.read_text(encoding="utf-8")
            dataset_html = dataset_page.read_text(encoding="utf-8")
            self.assertIn('&larr; Dataset overview', subject_html)
            self.assertIn('href="../index.html"', subject_html)
            self.assertNotIn('&larr; Corpus overview', subject_html)
            self.assertIn('&larr; Corpus overview', dataset_html)
            self.assertIn(
                f'href="{os.path.relpath(corpus_page, dataset_page.parent)}"',
                dataset_html,
            )


class StaticQualityScoreTests(unittest.TestCase):
    def test_quality_preprocessing_table_renders_resampling(self):
        rendered = static_report.render_quality_preprocessing_steps(
            [
                {
                    "step": "resample",
                    "sfreq_before": 1000.0,
                    "sfreq_after": 250.0,
                    "method": "fft",
                    "status": "applied",
                }
            ]
        )

        self.assertIn("<td>resample</td>", rendered)
        self.assertIn("1000.0 Hz", rendered)
        self.assertIn("250.0 Hz", rendered)
        self.assertIn("<td>fft</td>", rendered)

        skipped = static_report.render_quality_preprocessing_steps(
            [{"step": "resample", "sfreq": 250.0, "status": "skipped"}]
        )
        self.assertIn("<td>skipped</td>", skipped)

    def test_subject_report_omits_internal_quality_profile_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_root = Path(tmpdir) / "report"
            output_root = Path(tmpdir) / "static"
            subject = "sub-01_task-test_run-1_meg"
            qc_dir = report_root / "preprocessed" / "quality_control" / subject
            qc_dir.mkdir(parents=True)
            (qc_dir / "recording.summary.json").write_text(
                json.dumps(
                    {
                        "score_0_100": 82.3,
                        "model": "internal-profile-id",
                        "bad_channel_policy": "internal-channel-policy",
                        "bad_annotation_policy": "internal-annotation-policy",
                        "family_scores": [],
                    }
                ),
                encoding="utf-8",
            )

            summary = static_report.collect_subject_data(
                subject,
                report_root,
                output_root,
                dict(static_report.DEFAULT_THRESHOLDS),
            )
            static_report.build_subject_html(summary, output_root)
            rendered = (output_root / "subjects" / f"{subject}.html").read_text(encoding="utf-8")

            self.assertNotIn("internal-profile-id", rendered)
            self.assertNotIn("internal-channel-policy", rendered)
            self.assertNotIn("internal-annotation-policy", rendered)
            self.assertIn(f"<h2>{static_report.NMDQ_FULL_NAME}</h2>", rendered)
            self.assertIn('class="term-full">Normative MEG Data Quality Score</span>', rendered)
            self.assertIn('class="term-short" title="Normative MEG Data Quality Score">NMDQ Score</span>', rendered)
            self.assertNotIn("NormMEG-QC NMDQ Score", rendered)

    def test_responsive_quality_labels_keep_full_and_compact_names(self):
        rendered = static_report.responsive_label(
            static_report.NMDQ_FULL_NAME,
            static_report.NMDQ_SHORT_NAME,
        )

        self.assertIn(static_report.NMDQ_FULL_NAME, rendered)
        self.assertIn(static_report.NMDQ_SHORT_NAME, rendered)
        self.assertIn("@container (max-width: 260px)", static_report.REPORT_CSS)

        corpus_rendered = corpus_report.responsive_label(
            corpus_report.NMDQ_FULL_NAME,
            corpus_report.NMDQ_SHORT_NAME,
        )
        self.assertIn(corpus_report.NMDQ_FULL_NAME, corpus_rendered)
        self.assertIn(corpus_report.NMDQ_SHORT_NAME, corpus_rendered)
        self.assertIn("@container (max-width: 260px)", corpus_report.REPORT_CSS)

    def test_family_score_table_uses_readable_labels_and_components(self):
        rendered = static_report.render_quality_family_scores(
            [
                {
                    "domain": "Statistical",
                    "family": "ptp_amp.abs_q95",
                    "display_label": "Peak-to-peak amplitude, absolute Q95",
                    "score_0_100": 83.25,
                    "n_components": 2,
                    "components": ["MAG", "GRAD"],
                }
            ]
        )

        self.assertIn("Peak-to-peak amplitude, absolute Q95", rendered)
        self.assertIn("Statistical", rendered)
        self.assertIn("83.2", rendered)
        self.assertIn("MAG, GRAD", rendered)
        self.assertNotIn("ptp_amp.abs_q95</td>", rendered)

    def test_quality_score_files_use_new_plot_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            qc_dir = Path(tmpdir)
            summary = qc_dir / "recording.summary.json"
            components = qc_dir / "recording.component_scores.csv"
            figure = qc_dir / "recording.normative_quality_score.png"
            summary.write_text("{}", encoding="utf-8")
            components.write_text("family,metric\n", encoding="utf-8")
            figure.write_bytes(b"png")

            found = static_report.find_quality_score_files(qc_dir)

            self.assertEqual(found, (summary, components, figure))

    def test_quality_score_files_select_the_newest_complete_model_triplet(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            qc_dir = Path(tmpdir)
            old_paths = [
                qc_dir / "recording.aaa-old.summary.json",
                qc_dir / "recording.aaa-old.component_scores.csv",
                qc_dir / "recording.aaa-old.normative_quality_score.png",
            ]
            new_paths = [
                qc_dir / "recording.zzz-new.summary.json",
                qc_dir / "recording.zzz-new.component_scores.csv",
                qc_dir / "recording.zzz-new.normative_quality_score.png",
            ]
            for path in [*old_paths, *new_paths]:
                path.touch()
            for path in old_paths:
                os.utime(path, (1, 1))
            for path in new_paths:
                os.utime(path, (2, 2))

            found = static_report.find_quality_score_files(qc_dir)

            self.assertEqual(found, tuple(new_paths))


class StaticArtifactOverviewTests(unittest.TestCase):
    def test_artifact_gallery_keeps_mask_and_waveform_as_separate_groups(self):
        rendered = static_report.render_artifact_gallery(
            [
                {
                    "title": "Artifact mask heatmap",
                    "rel_path": "mask.jpg",
                    "artifact_group": "mask",
                },
                {
                    "title": "Artifact Overview",
                    "rel_path": "overview.jpg",
                    "artifact_group": "overview",
                    "details": "Start time 0.0 s · Duration 20.0 s",
                    "note": static_report.ARTIFACT_OVERVIEW_DISPLAY_NOTE,
                },
            ]
        )

        self.assertIn("Bad channel / bad segment mask", rendered)
        self.assertIn("Overview plot", rendered)
        self.assertIn('src="mask.jpg"', rendered)
        self.assertIn('src="overview.jpg"', rendered)
        self.assertIn(static_report.ARTIFACT_OVERVIEW_DISPLAY_NOTE, rendered)
        self.assertLess(
            rendered.index("Start time 0.0 s · Duration 20.0 s"),
            rendered.index(static_report.ARTIFACT_OVERVIEW_DISPLAY_NOTE),
        )

    def test_artifact_overview_renders_shared_scale_meg_waveforms(self):
        sfreq = 200.0
        duration = 20.0
        n_channels = 16
        n_times = int(sfreq * duration)
        times = np.arange(n_times) / sfreq
        rng = np.random.default_rng(2025)
        data = rng.normal(scale=0.18e-12, size=(n_channels, n_times))

        burst = (times >= 3.0) & (times < 4.0)
        data[0, burst] += 4.0e-12 * np.sin(2 * np.pi * 70.0 * times[burst])

        multichannel = (times >= 8.0) & (times < 8.4)
        data[:, multichannel] += 5.0e-12

        spike_sample = int(12.0 * sfreq)
        data[1, spike_sample : spike_sample + 2] += 20.0e-12

        info = mne.create_info(
            [f"MEG {idx + 1:03d}" for idx in range(n_channels)],
            sfreq,
            ch_types=["mag"] * n_channels,
        )
        raw = mne.io.RawArray(data, info, verbose=False)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            raw_file = tmpdir / "synthetic_raw.fif"
            raw.save(raw_file, overwrite=True, verbose=False)
            result = static_report.generate_static_artifact_overview(
                raw_file=raw_file,
                bad_channels=["MEG 002"],
                bad_segment_rows=[
                    {"onset_sec": 3.0, "duration_sec": 1.0},
                    {"onset_sec": 8.0, "duration_sec": 0.4},
                    {"onset_sec": 12.0, "duration_sec": 0.02},
                ],
                output_root=tmpdir,
                subject_slug="synthetic",
                overview_duration=duration,
            )

            self.assertIsNotNone(result)
            self.assertEqual(result["overview_type"], "mne_shared_scale_waveforms")
            self.assertTrue(result["artifact_emphasis_applied"])
            self.assertEqual(result["plot_bins"], n_times)
            self.assertEqual(result["details"], "Start time 0.0 s · Duration 20.0 s")

            image_path = tmpdir / result["rel_path"]
            self.assertTrue(image_path.is_file())
            with Image.open(image_path) as image:
                self.assertEqual(image.format, "JPEG")
                self.assertLessEqual(image.width, 2000)
                self.assertLessEqual(image.height, 1000)
                marked_pixels = np.asarray(image.convert("RGB"), dtype=int)
                self.assertGreater(marked_pixels.std(), 5.0)
                marked_warm_pixels = (
                    (marked_pixels[:, :, 0] - marked_pixels[:, :, 2] > 45)
                    & (marked_pixels[:, :, 0] - marked_pixels[:, :, 1] > 18)
                    & (marked_pixels[:, :, 0] > 145)
                )
                self.assertGreater(np.count_nonzero(marked_warm_pixels), 100)

            neutral_result = static_report.generate_static_artifact_overview(
                raw_file=raw_file,
                bad_channels=[],
                bad_segment_rows=[],
                output_root=tmpdir,
                subject_slug="synthetic_neutral",
                overview_duration=duration,
            )
            self.assertIsNotNone(neutral_result)
            self.assertFalse(neutral_result["artifact_emphasis_applied"])
            self.assertEqual(neutral_result["overview_type"], "mne_shared_scale_waveforms")
            with Image.open(tmpdir / neutral_result["rel_path"]) as image:
                neutral_pixels = np.asarray(image.convert("RGB"), dtype=int)
                dark_pixels = np.all(neutral_pixels < 180, axis=2)
                self.assertGreater(np.count_nonzero(dark_pixels), 5000)
                neutral_warm_pixels = (
                    (neutral_pixels[:, :, 0] - neutral_pixels[:, :, 2] > 45)
                    & (neutral_pixels[:, :, 0] - neutral_pixels[:, :, 1] > 18)
                    & (neutral_pixels[:, :, 0] > 145)
                )
                self.assertEqual(np.count_nonzero(neutral_warm_pixels), 0)


class StaticTraceParsingTests(unittest.TestCase):
    def test_trace_is_discovered_in_static_report_nextflow_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_root = Path(tmpdir)
            preprocessed_dir = report_root / "preprocessed"
            output_root = report_root / "static_html_report"
            trace_file = output_root / "nextflow" / "trace.txt"
            preprocessed_dir.mkdir()
            trace_file.parent.mkdir(parents=True)
            trace_file.write_text(
                "task_id\thash\tname\tstatus\texit\n"
                "1\taa/bbcc\tdetect_artifacts (Demo:sub-01)\tCOMPLETED\t0\n",
                encoding="utf-8",
            )

            tasks = static_report.collect_nextflow_task_details(
                report_root=report_root,
                preprocessed_dir=preprocessed_dir,
                output_root=output_root,
                subjects=["sub-01"],
                manifest=None,
            )

            self.assertEqual(tasks["sub-01"][0]["process"], "detect_artifacts")

    def test_nul_bytes_in_nextflow_trace_do_not_break_report_generation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_root = Path(tmpdir)
            preprocessed_dir = report_root / "preprocessed"
            output_root = report_root / "static_html_report"
            preprocessed_dir.mkdir()
            output_root.mkdir()
            (report_root / "trace.txt").write_bytes(
                b"task_id\thash\tname\tstatus\texit\n"
                b"1\taa/bbcc\tsource_imaging (Demo:sub-01)\x00\tCOMPLETED\t0\n"
            )

            tasks = static_report.collect_nextflow_task_details(
                report_root=report_root,
                preprocessed_dir=preprocessed_dir,
                output_root=output_root,
                subjects=["sub-01"],
                manifest=None,
            )

            self.assertEqual(len(tasks["sub-01"]), 1)
            self.assertEqual(tasks["sub-01"][0]["process"], "source_imaging")
            self.assertEqual(tasks["sub-01"][0]["status"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
