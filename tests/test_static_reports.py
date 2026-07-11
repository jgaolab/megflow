import json
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
import static_html_report as static_report


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


class StaticQualityScoreTests(unittest.TestCase):
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
                },
            ]
        )

        self.assertIn("Bad channel / bad segment mask", rendered)
        self.assertIn("Overview plot", rendered)
        self.assertIn('src="mask.jpg"', rendered)
        self.assertIn('src="overview.jpg"', rendered)

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
