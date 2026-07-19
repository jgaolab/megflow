import csv
import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PIPELINE = REPO_ROOT / "nextflow" / "megflow.nf"
NEXTFLOW = os.environ.get("MEGFLOW_NEXTFLOW") or shutil.which("nextflow")


REPORT_PROCESSES = {"generate_static_html_report"}
MEG_ARTIFACT_PROCESSES = {
    "import_meg_dataset",
    "score_meg_quality",
    "meg_basic_preproc",
    "detect_artifacts",
    "generate_static_html_report",
}
MEG_ICA_PROCESSES = MEG_ARTIFACT_PROCESSES | {
    "run_ica",
    "run_ic_label",
    "apply_ica",
}
MEG_EPOCH_PROCESSES = MEG_ICA_PROCESSES | {"epochs"}
MEG_SKIP_ICA_EPOCH_PROCESSES = MEG_ARTIFACT_PROCESSES | {"epochs"}
MEG_SOURCE_PROCESSES = MEG_EPOCH_PROCESSES | {
    "compute_covariance",
    "coregistration",
    "forward_solution",
    "source_imaging",
}
FREESURFER_ANATOMY_PROCESSES = {
    "import_mri_dataset",
    "run_freesurfer",
    "generate_bem",
}
DEEPPREP_ANATOMY_PROCESSES = {
    "import_mri_dataset",
    "run_deepprep",
    "run_mkheadsurf",
    "generate_bem",
}
PSEUDOMRI_ANATOMY_PROCESSES = {
    "import_meg_dataset",
    "generate_pseudomri",
    "run_freesurfer",
    "generate_bem",
}
DATASET_LEVEL_MEG_PROCESSES = {"import_meg_dataset", "generate_static_html_report"}
RECORDING_ARTIFACT_PROCESSES = MEG_ARTIFACT_PROCESSES - DATASET_LEVEL_MEG_PROCESSES
RECORDING_ICA_PROCESSES = MEG_ICA_PROCESSES - DATASET_LEVEL_MEG_PROCESSES
RECORDING_EPOCH_PROCESSES = MEG_EPOCH_PROCESSES - DATASET_LEVEL_MEG_PROCESSES
RECORDING_SKIP_ICA_EPOCH_PROCESSES = (
    MEG_SKIP_ICA_EPOCH_PROCESSES - DATASET_LEVEL_MEG_PROCESSES
)
RECORDING_SOURCE_PROCESSES = MEG_SOURCE_PROCESSES - DATASET_LEVEL_MEG_PROCESSES
VISIBLE_PROCESS_CANDIDATES = (
    MEG_SOURCE_PROCESSES
    | FREESURFER_ANATOMY_PROCESSES
    | DEEPPREP_ANATOMY_PROCESSES
    | PSEUDOMRI_ANATOMY_PROCESSES
    | {"generate_corpus_static_html_report"}
)


def groovy_string(value):
    return json.dumps(str(value))


def dataset_block(name, dataset_dir, *, steps="meg_all", extra=""):
    return textwrap.dedent(
        f"""
        {name}: [
            dataset_dir: {groovy_string(dataset_dir)},
            steps: {groovy_string(steps)}{extra}
        ]
        """
    ).strip()


def create_dataset(root, tasks=("main",), *, with_t1=True):
    meg_dir = root / "sub-01" / "meg"
    meg_dir.mkdir(parents=True)
    for task in tasks:
        (meg_dir / f"sub-01_task-{task}_run-01_meg.fif").write_text(
            f"synthetic {task}\n", encoding="utf-8"
        )
        (meg_dir / f"sub-01_task-{task}_run-01_events.tsv").write_text(
            "onset\tduration\ttrial_type\n0\t0\tstub\n", encoding="utf-8"
        )
    if with_t1:
        anat_dir = root / "sub-01" / "anat"
        anat_dir.mkdir(parents=True)
        (anat_dir / "sub-01_T1w.nii.gz").write_text("synthetic T1\n", encoding="utf-8")


def write_config(
    path,
    output_dir,
    datasets_text,
    *,
    defaults_override="[:]",
    error_mode="strict",
):
    path.write_text(
        textwrap.dedent(
            f"""
            params {{
                megflow = [
                    code_dir: {groovy_string(REPO_ROOT / 'megflow')},
                    output_dir: {groovy_string(output_dir)},
                    corpus_root: "",
                    dataset_include: [],
                    dataset_exclude: [],
                    error_mode: {groovy_string(error_mode)},
                    defaults: ([
                        steps: "meg_all",
                        dataset_format: "raw",
                        file_suffix: ".fif",
                        is_bids: true,
                        visualize: false,
                        rank_policy: "auto",
                        seeds: [osl: 2025, ica: 2025],
                        anatomy: [method: "freesurfer", is_bids: true, select_tag: ""],
                        mri_import: [:],
                        meg_import: [:],
                        megqc: [enabled: true, min_score: 0.0],
                        preproc: [steps: []],
                        digitization: [enabled: false],
                        artifacts: [:],
                        ica: [num_components: 2],
                        ic_label: [:],
                        epochs: [
                            preproc: [],
                            task_type: "rest",
                            resting: [fixed_length_duration: 2.0]
                        ],
                        bem: [ico: 4, conductivity: [0.3]],
                        coreg: [visualize: false],
                        covariance: [type: "epochs", visualize: false],
                        forward: [epoch_label: "event", surface: "white", spacing: "ico4"],
                        source: [type: "epochs", visualize: false, source_methods: [], data_type: "meg", spacing: "ico4", epoch_label: "event"],
                        report: [static_task_log_mode: "none"]
                    ] + {defaults_override}),
                    datasets: [
                        {datasets_text}
                    ]
                ]
            }}

            workDir = {groovy_string(output_dir / 'work')}
            log.file = {groovy_string(output_dir / 'nextflow.log')}
            report.enabled = false
            timeline.enabled = false
            trace {{
                enabled = true
                file = {groovy_string(output_dir / 'trace.txt')}
                overwrite = true
            }}
            process {{
                executor = "local"
                errorStrategy = {{ params.megflow.error_mode == "strict" ? "terminate" : "ignore" }}
                maxForks = 8

                // Stub tasks only create tiny fixture files. Override production
                // process directives so routing tests do not depend on runner RAM.
                withName: '.*' {{
                    cpus = 1
                    memory = "512 MB"
                }}
            }}
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


@unittest.skipUnless(NEXTFLOW, "set MEGFLOW_NEXTFLOW or install Nextflow")
class NextflowProfileIntegrationTests(unittest.TestCase):
    maxDiff = None

    def run_pipeline(
        self,
        config,
        output_dir,
        *,
        stub=True,
        resume=False,
        expect_success=True,
        ansi_log=False,
    ):
        output_dir.mkdir(parents=True, exist_ok=True)
        command = [
            NEXTFLOW,
            "-log",
            str(output_dir / "driver.log"),
            "-C",
            str(config),
            "run",
            str(PIPELINE),
        ]
        if stub:
            command.append("-stub-run")
        if resume:
            command.append("-resume")
        result = subprocess.run(
            command,
            cwd=output_dir,
            env=dict(
                os.environ,
                NXF_ANSI_LOG="true" if ansi_log else "false",
                TERM="xterm",
            ),
            text=True,
            capture_output=True,
            timeout=240,
        )
        combined = result.stdout + result.stderr
        driver_log = output_dir / "driver.log"
        if result.returncode != 0 and driver_log.is_file():
            combined += "\n--- Nextflow driver.log ---\n" + driver_log.read_text(
                encoding="utf-8", errors="replace"
            )
        if expect_success and result.returncode != 0:
            self.fail(f"Nextflow failed ({result.returncode}):\n{combined}")
        if not expect_success and result.returncode == 0:
            self.fail(f"Nextflow unexpectedly succeeded:\n{combined}")
        return result, combined

    def displayed_processes(self, terminal_output, process_names):
        ansi_escape = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        normalized = ansi_escape.sub("", terminal_output).replace("\r", "\n")
        return {
            process_name
            for process_name in process_names
            if re.search(
                rf"(?m)^\[[^\]\n]*\]\s+{re.escape(process_name)}(?:\s|\()",
                normalized,
            )
        }

    def trace_names(self, output_dir):
        with (output_dir / "trace.txt").open(encoding="utf-8") as handle:
            return [row["name"] for row in csv.DictReader(handle, delimiter="\t")]

    def trace_rows(self, output_dir):
        with (output_dir / "trace.txt").open(encoding="utf-8") as handle:
            return list(csv.DictReader(handle, delimiter="\t"))

    def trace_processes_for_dataset(self, output_dir, dataset_name):
        processes = set()
        for row in self.trace_rows(output_dir):
            name = row["name"]
            if " (" not in name:
                continue
            process_name, tag = name.split(" (", 1)
            tag = tag.removesuffix(")")
            if tag == dataset_name or tag.startswith(f"{dataset_name}:"):
                processes.add(process_name)
        return processes

    def trace_processes_for_recording(
        self, output_dir, dataset_name, recording_name
    ):
        tag_prefix = f"{dataset_name}:{recording_name}"
        processes = set()
        for row in self.trace_rows(output_dir):
            name = row["name"]
            if " (" not in name:
                continue
            process_name, tag = name.split(" (", 1)
            tag = tag.removesuffix(")")
            if tag == tag_prefix or tag.startswith(f"{tag_prefix}_"):
                processes.add(process_name)
        return processes

    def assert_terminal_output(self, output, dataset_name, terminal):
        preproc = output / "datasets" / dataset_name / "preprocessed"
        recording = "sub-01_task-main_run-01_meg"
        if terminal == "report":
            return
        if terminal in {
            "artifacts",
            "ica",
            "epochs",
            "epochs_skip_ica",
            "source",
        }:
            self.assertTrue(
                (preproc / recording / f"{recording}_preproc-raw.fif").is_file()
            )
        if terminal in {"artifacts", "ica", "epochs", "epochs_skip_ica", "source"}:
            artifact_dir = preproc / "artifact_report" / recording
            artifact_basename = f"{recording}_preproc-raw"
            self.assertTrue(
                (artifact_dir / f"{artifact_basename}_bad_channels.txt").is_file()
            )
            self.assertTrue(
                (artifact_dir / f"{artifact_basename}_bad_segments.txt").is_file()
            )
        if terminal in {"ica", "epochs", "source"}:
            self.assertTrue(
                (
                    preproc
                    / recording
                    / f"{recording}_preproc-raw_clean_raw.fif"
                ).is_file()
            )
        if terminal in {"epochs", "epochs_skip_ica"}:
            self.assertTrue(any((preproc / "epochs" / recording).glob("*-epo.fif")))
        if terminal == "source":
            self.assertTrue(
                (preproc / "source_recon" / recording / "routing.json").is_file()
            )

    def test_meg_step_matrix_schedules_exact_process_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            cases = {
                "report_stage": ("report", REPORT_PROCESSES, "report"),
                "artifacts_stage": (
                    "meg_artifacts",
                    MEG_ARTIFACT_PROCESSES,
                    "artifacts",
                ),
                "ica_stage": ("meg_ica", MEG_ICA_PROCESSES, "ica"),
                "epochs_stage": ("meg_epochs", MEG_EPOCH_PROCESSES, "epochs"),
                "skip_ica_stage": (
                    "meg_epochs,skip_ica",
                    MEG_SKIP_ICA_EPOCH_PROCESSES,
                    "epochs_skip_ica",
                ),
                "full_stage": ("meg_all", MEG_SOURCE_PROCESSES, "source"),
                "all_stage": (
                    "all",
                    MEG_SOURCE_PROCESSES | FREESURFER_ANATOMY_PROCESSES,
                    "source",
                ),
                "default_stage": (None, MEG_SOURCE_PROCESSES, "source"),
                "meg_alias": (" MeG ", MEG_SOURCE_PROCESSES, "source"),
                "artifacts_alias": (
                    " ARTIFACTS ",
                    MEG_ARTIFACT_PROCESSES,
                    "artifacts",
                ),
                "ica_alias": (" IcA ", MEG_ICA_PROCESSES, "ica"),
                "epochs_alias": (
                    " EpOcHs , SkIp_IcA ",
                    MEG_SKIP_ICA_EPOCH_PROCESSES,
                    "epochs_skip_ica",
                ),
            }
            blocks = []
            for name, (steps, _, _) in cases.items():
                dataset_dir = root / name
                create_dataset(dataset_dir)
                if steps is None:
                    blocks.append(
                        textwrap.dedent(
                            f"""
                            {name}: [
                                dataset_dir: {groovy_string(dataset_dir)}
                            ]
                            """
                        ).strip()
                    )
                else:
                    blocks.append(dataset_block(name, dataset_dir, steps=steps))
            config = root / "stages.config"
            write_config(config, output, ",\n".join(blocks))

            self.run_pipeline(config, output)
            names = self.trace_names(output)
            for dataset_name, (_, expected_processes, terminal) in cases.items():
                with self.subTest(dataset=dataset_name):
                    self.assertEqual(
                        self.trace_processes_for_dataset(output, dataset_name),
                        expected_processes,
                    )
                    self.assert_terminal_output(output, dataset_name, terminal)

            self.assertEqual(
                sum(
                    name.startswith("generate_corpus_static_html_report (")
                    for name in names
                ),
                1,
            )
            self.assertTrue(
                (
                    output
                    / "smri"
                    / "all_stage"
                    / "sub-01"
                    / "bem"
                    / "stub-bem.done"
                ).is_file()
            )

    def test_anatomy_step_matrix_schedules_only_selected_method(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            dicom_root = root / "dicom-input"
            dicom_series = dicom_root / "subject01"
            dicom_series.mkdir(parents=True)
            (dicom_series / "image.dcm").write_text(
                "synthetic DICOM\n", encoding="utf-8"
            )

            cases = {
                "freesurfer_stage": (
                    root / "freesurfer_stage",
                    "",
                    FREESURFER_ANATOMY_PROCESSES,
                    "sub-01",
                ),
                "deepprep_stage": (
                    root / "deepprep_stage",
                    ',\n    anatomy: [method: "deepprep", is_bids: true]',
                    DEEPPREP_ANATOMY_PROCESSES,
                    "sub-01",
                ),
                "pseudomri_stage": (
                    root / "pseudomri_stage",
                    ',\n    anatomy: [method: "pseudomri", is_bids: false]',
                    PSEUDOMRI_ANATOMY_PROCESSES,
                    "sub-01",
                ),
                "native_nifti_stage": (
                    root / "native_nifti_stage",
                    ',\n    anatomy: [method: "freesurfer", is_bids: false, t1_input_type: "nifti"]',
                    {"run_freesurfer", "generate_bem"},
                    "sub-01_native",
                ),
                "dicom_stage": (
                    root / "dicom_stage",
                    f',\n    t1_dir: {groovy_string(dicom_root)},'
                    '\n    anatomy: [method: "freesurfer", is_bids: false, t1_input_type: "dicom"]',
                    {"dcm2niix", "run_freesurfer", "generate_bem"},
                    "subject01_stub",
                ),
            }
            blocks = []
            for name, (dataset_dir, extra, _, _) in cases.items():
                create_dataset(dataset_dir)
                if name == "native_nifti_stage":
                    (dataset_dir / "sub-01_native.nii.gz").write_text(
                        "synthetic native T1\n", encoding="utf-8"
                    )
                blocks.append(
                    dataset_block(name, dataset_dir, steps="anatomy", extra=extra)
                )

            config = root / "anatomy-stages.config"
            write_config(config, output, ",\n".join(blocks))
            self.run_pipeline(config, output)

            for dataset_name, (_, _, expected_processes, subject_name) in cases.items():
                with self.subTest(dataset=dataset_name):
                    self.assertEqual(
                        self.trace_processes_for_dataset(output, dataset_name),
                        expected_processes,
                    )
                    self.assertTrue(
                        (
                            output
                            / "smri"
                            / dataset_name
                            / subject_name
                            / "bem"
                            / "stub-bem.done"
                        ).is_file()
                    )

    def test_resume_reruns_each_owner_with_a_missing_published_anatomy_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            cases = {
                "pseudomri_missing": (
                    ',\n    anatomy: [method: "pseudomri", is_bids: false]',
                    "generate_pseudomri",
                ),
                "freesurfer_missing": ("", "run_freesurfer"),
                "deepprep_missing": (
                    ',\n    anatomy: [method: "deepprep", is_bids: true]',
                    "run_deepprep",
                ),
                "mkheadsurf_missing": (
                    ',\n    anatomy: [method: "deepprep", is_bids: true]',
                    "run_mkheadsurf",
                ),
                "bem_missing": ("", "generate_bem"),
                "control": ("", None),
            }
            blocks = []
            for dataset_name, (extra, _) in cases.items():
                dataset_dir = root / dataset_name
                create_dataset(dataset_dir)
                blocks.append(
                    dataset_block(
                        dataset_name,
                        dataset_dir,
                        steps="anatomy",
                        extra=extra,
                    )
                )
            config = root / "resume-anatomy-owner-matrix.config"
            write_config(config, output, ",\n".join(blocks))
            self.run_pipeline(config, output)

            smri = output / "smri"
            targets = {
                "pseudomri_missing": output
                / "datasets"
                / "pseudomri_missing"
                / "preprocessed"
                / "pseudomri"
                / "sub-01"
                / "sub-01.nii.gz",
                "freesurfer_missing": smri
                / "freesurfer_missing"
                / "sub-01"
                / "scripts"
                / "recon-all.done",
                "deepprep_missing": smri
                / "deepprep_missing"
                / "sub-01"
                / "scripts"
                / "recon-all.done",
                "mkheadsurf_missing": smri
                / "mkheadsurf_missing"
                / "sub-01"
                / "surf"
                / "lh.seghead",
                "bem_missing": smri
                / "bem_missing"
                / "sub-01"
                / "bem"
                / "sub-01_ico4_watershed_bem-sol.fif",
            }
            for dataset_name, target in targets.items():
                with self.subTest(delete=dataset_name):
                    self.assertTrue(target.is_file(), target)
                    target.unlink()

            self.run_pipeline(config, output, resume=True)
            rows = self.trace_rows(output)

            def dataset_subject_status(process_name, dataset_name):
                matching = [
                    row["status"]
                    for row in rows
                    if row["name"].startswith(f"{process_name} ({dataset_name}:")
                ]
                self.assertEqual(
                    len(matching), 1, (process_name, dataset_name, rows)
                )
                return matching[0]

            for dataset_name, (_, owner_process) in cases.items():
                if owner_process is None:
                    continue
                with self.subTest(owner=owner_process, dataset=dataset_name):
                    self.assertEqual(
                        dataset_subject_status(owner_process, dataset_name),
                        "COMPLETED",
                    )
                    self.assertTrue(targets[dataset_name].is_file())

            for process_name in ("run_freesurfer", "generate_bem"):
                self.assertEqual(
                    dataset_subject_status(process_name, "control"),
                    "CACHED",
                    process_name,
                )

    def test_with_anatomy_modifier_stops_at_requested_meg_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            cases = {
                "artifacts_with_anatomy": (
                    "meg_artifacts,with_anatomy",
                    MEG_ARTIFACT_PROCESSES | FREESURFER_ANATOMY_PROCESSES,
                    "artifacts",
                ),
                "ica_with_anatomy": (
                    "meg_ica,with_anatomy",
                    MEG_ICA_PROCESSES | FREESURFER_ANATOMY_PROCESSES,
                    "ica",
                ),
                "epochs_with_anatomy": (
                    "meg_epochs,with_anatomy",
                    MEG_EPOCH_PROCESSES | FREESURFER_ANATOMY_PROCESSES,
                    "epochs",
                ),
            }
            blocks = []
            for name, (steps, _, _) in cases.items():
                dataset_dir = root / name
                create_dataset(dataset_dir)
                blocks.append(dataset_block(name, dataset_dir, steps=steps))

            config = root / "with-anatomy.config"
            write_config(config, output, ",\n".join(blocks))
            self.run_pipeline(config, output)

            for dataset_name, (_, expected_processes, terminal) in cases.items():
                with self.subTest(dataset=dataset_name):
                    self.assertEqual(
                        self.trace_processes_for_dataset(output, dataset_name),
                        expected_processes,
                    )
                    self.assert_terminal_output(output, dataset_name, terminal)
                    self.assertTrue(
                        (
                            output
                            / "smri"
                            / dataset_name
                            / "sub-01"
                            / "bem"
                            / "stub-bem.done"
                        ).is_file()
                    )

    def test_invalid_step_values_fail_before_process_submission(self):
        invalid_cases = {
            "empty": ("", "MEGFlow steps is empty"),
            "unknown_primary": ("meg_unknown", "Unknown steps 'meg_unknown'"),
            "unknown_modifier": (
                "meg_epochs,unknown",
                "Unknown steps modifier: unknown",
            ),
            "skip_ica_wrong_stage": (
                "meg_ica,skip_ica",
                "skip_ica is only supported with meg_epochs",
            ),
            "meg_all_with_anatomy": (
                "meg_all,with_anatomy",
                "steps=meg_all cannot be combined with with_anatomy",
            ),
            "report_with_anatomy": (
                "report,with_anatomy",
                "with_anatomy is only supported with meg_artifacts, meg_ica, or meg_epochs",
            ),
            "all_with_anatomy": (
                "all,with_anatomy",
                "with_anatomy is only supported with meg_artifacts, meg_ica, or meg_epochs",
            ),
        }
        for name, (steps, message) in invalid_cases.items():
            with self.subTest(case=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                output = root / "output"
                dataset = root / "dataset"
                create_dataset(dataset)
                config = root / "invalid-steps.config"
                write_config(
                    config,
                    output,
                    dataset_block("dataset", dataset, steps=steps),
                )

                _, combined = self.run_pipeline(
                    config, output, stub=False, expect_success=False
                )
                self.assertIn(message, combined)
                self.assertNotIn("Submitted process", combined)

    def test_invalid_report_and_anatomy_config_fail_before_process_submission(self):
        invalid_cases = {
            "task_log_mode": (
                ', report: [static_task_log_mode: "verbose"]',
                "report.static_task_log_mode must be one of",
            ),
            "artifact_overview_duration": (
                ", report: [static_artifact_overview_duration: 0]",
                "report.static_artifact_overview_duration must be a positive number",
            ),
            "t1_input_type": (
                ', anatomy: [method: "freesurfer", is_bids: false, '
                't1_input_type: "archive"]',
                "anatomy.t1_input_type must be nifti or dicom",
            ),
            "absolute_dicom_glob": (
                ', anatomy: [method: "freesurfer", is_bids: false, '
                't1_input_type: "dicom", t1_dicom_series_glob: "/T1/*"]',
                "anatomy.t1_dicom_series_glob must be relative",
            ),
        }
        for name, (profile_extra, message) in invalid_cases.items():
            with self.subTest(case=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                output = root / "output"
                dataset = root / "dataset"
                create_dataset(dataset)
                config = root / "invalid-profile.config"
                write_config(
                    config,
                    output,
                    dataset_block(
                        "dataset",
                        dataset,
                        steps="anatomy",
                        extra=profile_extra,
                    ),
                )

                _, combined = self.run_pipeline(
                    config, output, expect_success=False
                )
                self.assertIn(message, combined)
                self.assertNotIn("Submitted process", combined)

    def test_dataset_and_recording_overrides_do_not_cross_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            dataset_a = root / "sub-decoy-dataset-a"
            dataset_b = root / "dataset-b"
            create_dataset(dataset_a, ("auditory", "visual"))
            create_dataset(dataset_b, ("language",))

            recordings = """,
                recordings: [
                    auditory_profile: [
                        match: [subject: "01", task: "auditory"],
                        preproc: [test_marker: "auditory"],
                        epochs: [event_time_shift_sec: 0.01],
                        covariance: [event_time_shift_sec: 0.01],
                        forward: [epoch_label: "auditory", spacing: "ico4"],
                        source: [epoch_label: "auditory"]
                    ],
                    visual_profile: [
                        match: [subject: "01", task: "visual"],
                        preproc: [test_marker: "visual"],
                        epochs: [event_time_shift_sec: 0.02],
                        covariance: [event_time_shift_sec: 0.02],
                        forward: [epoch_label: "visual", spacing: "ico4"],
                        source: [epoch_label: "visual"]
                    ]
                ]"""
            dataset_b_extra = """,
                preproc: [test_marker: "language"],
                epochs: [event_time_shift_sec: 0.03],
                covariance: [event_time_shift_sec: 0.03],
                forward: [epoch_label: "language", spacing: "ico4"],
                source: [epoch_label: "language"]"""
            blocks = [
                dataset_block("dataset_a", dataset_a, extra=recordings),
                dataset_block("dataset_b", dataset_b, extra=dataset_b_extra),
            ]
            config = root / "routing.config"
            write_config(config, output, ",\n".join(blocks))
            self.run_pipeline(config, output)

            expectations = [
                ("dataset_a", "auditory", "auditory_profile"),
                ("dataset_a", "visual", "visual_profile"),
                ("dataset_b", "language", ""),
            ]
            for dataset, task, profile in expectations:
                recording = f"sub-01_task-{task}_run-01_meg"
                route = (
                    output
                    / "datasets"
                    / dataset
                    / "preprocessed"
                    / "source_recon"
                    / recording
                    / "routing.json"
                )
                payload = json.loads(route.read_text(encoding="utf-8"))
                self.assertEqual(payload["key"], [dataset, recording])
                self.assertEqual(payload["recording_profile"], profile)
                self.assertEqual(payload["config_marker"], task)
                self.assertEqual(payload["source_config"]["epoch_label"], task)
                self.assertIn(f"/epochs/{recording}/", payload["epoch_file"])
                self.assertIn(
                    f"/forward_solution/{recording}/{task}_ico4-fwd.fif",
                    payload["forward_file"],
                )
                self.assertIn(f"/covariance/{recording}/", payload["covariance_file"])
                self.assertNotIn("dataset_a", payload["forward_file"] if dataset == "dataset_b" else "")

    def test_mne_and_osl_kwargs_survive_default_dataset_recording_merges(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            dataset = root / "dataset"
            create_dataset(dataset, ("regular", "special"))
            defaults_override = """[
                preproc: [
                    meta: [event_codes: [default_event: 1]],
                    steps: [[filter: [
                        l_freq: 1.0, h_freq: 90.0, method: "iir",
                        iir_params: [order: 4, ftype: "butter"], phase: "zero"
                    ]]]
                ],
                epochs: [
                    preproc: [], task_type: "resting",
                    resting: [fixed_length_duration: 2.0],
                    epochs: [
                        event_id: 1, tmin: -0.2, tmax: 0.8,
                        baseline: [null, 0.0], proj: true, decim: 1,
                        reject: [mag: 4e-12]
                    ]
                ],
                covariance: [
                    type: "epochs", visualize: false,
                    covariance: [
                        keep_sample_mean: true, tmin: null, tmax: 0.0,
                        method: "empirical", cv: 3
                    ]
                ],
                source: [
                    type: "epochs", visualize: false,
                    source_methods: ["dSPM"], data_type: "meg",
                    spacing: "ico4", epoch_label: "event",
                    dSPM: [
                        make_inverse_operator: [
                            loose: "auto", depth: 0.8, fixed: "auto", use_cps: true
                        ],
                        apply_inverse: [
                            lambda2: 0.1111111111111111,
                            method: "dSPM", pick_ori: "normal"
                        ]
                    ]
                ]
            ]"""
            extra = """,
                preproc: [
                    meta: [event_codes: [dataset_event: 2]],
                    steps: [[filter: [
                        l_freq: 1.0, h_freq: 70.0, method: "iir",
                        iir_params: [order: 5, ftype: "butter"], phase: "zero-double"
                    ]]]
                ],
                epochs: [epochs: [tmax: 0.6, proj: false]],
                covariance: [covariance: [cv: 5]],
                source: [dSPM: [make_inverse_operator: [depth: 0.6]]],
                recordings: [
                    special_parameters: [
                        match: [task: "special"],
                        preproc: [steps: [[filter: [
                            l_freq: 2.0, h_freq: 40.0, method: "iir",
                            iir_params: [order: 3, ftype: "butter"], phase: "zero"
                        ]]]],
                        epochs: [epochs: [decim: 2, reject_tmin: -0.1]],
                        covariance: [covariance: [tmax: -0.01, n_jobs: 1]],
                        source: [dSPM: [apply_inverse: [lambda2: 0.04, use_cps: false]]]
                    ]
                ]"""
            config = root / "mne-config-contract.config"
            write_config(
                config,
                output,
                dataset_block("dataset", dataset, extra=extra),
                defaults_override=defaults_override,
            )
            self.run_pipeline(config, output)

            regular_recording = "sub-01_task-regular_run-01_meg"
            regular_route = json.loads(
                (
                    output
                    / "preprocessed"
                    / "source_recon"
                    / regular_recording
                    / "routing.json"
                ).read_text(encoding="utf-8")
            )
            special_recording = "sub-01_task-special_run-01_meg"
            special_route = json.loads(
                (
                    output
                    / "preprocessed"
                    / "source_recon"
                    / special_recording
                    / "routing.json"
                ).read_text(encoding="utf-8")
            )

            self.assertEqual(regular_route["recording_profile"], "")
            self.assertEqual(
                regular_route["preproc_config"]["meta"]["event_codes"],
                {"default_event": 1, "dataset_event": 2},
            )
            regular_filter = regular_route["preproc_config"]["preproc"][0]["filter"]
            self.assertEqual(regular_filter["h_freq"], 70.0)
            self.assertEqual(regular_filter["phase"], "zero-double")

            self.assertEqual(special_route["recording_profile"], "special_parameters")
            self.assertNotIn("steps", special_route["preproc_config"])
            self.assertEqual(
                special_route["preproc_config"]["meta"]["event_codes"],
                {"default_event": 1, "dataset_event": 2},
            )
            special_filter = special_route["preproc_config"]["preproc"][0]["filter"]
            self.assertEqual(
                special_filter,
                {
                    "l_freq": 2.0,
                    "h_freq": 40.0,
                    "method": "iir",
                    "iir_params": {"order": 3, "ftype": "butter"},
                    "phase": "zero",
                },
            )

            epoch_kwargs = special_route["epochs_config"]["epochs"]
            self.assertEqual(epoch_kwargs["tmin"], -0.2)
            self.assertEqual(epoch_kwargs["tmax"], 0.6)
            self.assertFalse(epoch_kwargs["proj"])
            self.assertEqual(epoch_kwargs["decim"], 2)
            self.assertEqual(epoch_kwargs["reject_tmin"], -0.1)
            self.assertEqual(epoch_kwargs["reject"]["mag"], 4e-12)

            covariance_kwargs = special_route["covariance_config"]["covariance"]
            self.assertTrue(covariance_kwargs["keep_sample_mean"])
            self.assertEqual(covariance_kwargs["method"], "empirical")
            self.assertEqual(covariance_kwargs["cv"], 5)
            self.assertEqual(covariance_kwargs["tmax"], -0.01)
            self.assertEqual(covariance_kwargs["n_jobs"], 1)

            source_config = special_route["source_config"]
            inverse_kwargs = source_config["dSPM"]["make_inverse_operator"]
            apply_kwargs = source_config["dSPM"]["apply_inverse"]
            self.assertEqual(inverse_kwargs["loose"], "auto")
            self.assertEqual(inverse_kwargs["depth"], 0.6)
            self.assertEqual(inverse_kwargs["fixed"], "auto")
            self.assertTrue(inverse_kwargs["use_cps"])
            self.assertEqual(apply_kwargs["lambda2"], 0.04)
            self.assertEqual(apply_kwargs["method"], "dSPM")
            self.assertEqual(apply_kwargs["pick_ori"], "normal")
            self.assertFalse(apply_kwargs["use_cps"])

    def test_recording_level_steps_reduce_the_dataset_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            dataset = root / "dataset"
            create_dataset(
                dataset,
                ("report", "artifacts", "ica", "epochs", "skipica", "full"),
            )
            extra = """,
                recordings: [
                    report_only: [match: [task: "report"], steps: "report"],
                    artifacts_only: [match: [task: "artifacts"], steps: "meg_artifacts"],
                    ica_only: [match: [task: "ica"], steps: "meg_ica"],
                    epochs_only: [match: [task: "epochs"], steps: "meg_epochs"],
                    epochs_without_ica: [match: [task: "skipica"], steps: "meg_epochs,skip_ica"]
                ]"""
            config = root / "recording-steps.config"
            write_config(config, output, dataset_block("dataset", dataset, extra=extra))
            self.run_pipeline(config, output)

            preproc = output / "preprocessed"
            report_recording = "sub-01_task-report_run-01_meg"
            artifacts_recording = "sub-01_task-artifacts_run-01_meg"
            ica_recording = "sub-01_task-ica_run-01_meg"
            epochs_recording = "sub-01_task-epochs_run-01_meg"
            skip_ica_recording = "sub-01_task-skipica_run-01_meg"
            full_recording = "sub-01_task-full_run-01_meg"

            expected_by_recording = {
                report_recording: set(),
                artifacts_recording: RECORDING_ARTIFACT_PROCESSES,
                ica_recording: RECORDING_ICA_PROCESSES,
                epochs_recording: RECORDING_EPOCH_PROCESSES,
                skip_ica_recording: RECORDING_SKIP_ICA_EPOCH_PROCESSES,
                full_recording: RECORDING_SOURCE_PROCESSES,
            }
            for recording_name, expected_processes in expected_by_recording.items():
                with self.subTest(recording=recording_name):
                    self.assertEqual(
                        self.trace_processes_for_recording(
                            output, "dataset", recording_name
                        ),
                        expected_processes,
                    )

            self.assertFalse((preproc / report_recording).exists())
            self.assertFalse((preproc / "ica_report" / artifacts_recording).exists())
            self.assertTrue((preproc / "ica_report" / ica_recording).is_dir())
            self.assertFalse((preproc / "epochs" / ica_recording).exists())
            self.assertTrue(any((preproc / "epochs" / epochs_recording).glob("*-epo.fif")))
            self.assertFalse((preproc / "source_recon" / epochs_recording).exists())
            self.assertFalse((preproc / "ica_report" / skip_ica_recording).exists())
            self.assertTrue(
                any((preproc / "epochs" / skip_ica_recording).glob("*-epo.fif"))
            )
            self.assertTrue(
                (preproc / "source_recon" / full_recording / "routing.json").is_file()
            )

    def test_raw_covariance_pairs_with_the_correct_dataset_noise_recording(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            blocks = []
            for dataset, experiments, noise in (
                ("dataset_a", ("experimentA", "controlA"), "noiseA"),
                ("dataset_b", ("experimentB", "controlB"), "noiseB"),
            ):
                dataset_dir = root / dataset
                create_dataset(dataset_dir, (*experiments, noise))
                extra = f""",
                    recordings: [
                        epochs_source_with_raw_covariance: [
                            match: [task: "{experiments[0]}"],
                            covariance: [type: "raw", raw_covariance_task_id: "{noise}", output_dir: "covariance"],
                            source: [
                                type: "epochs",
                                source_methods: ["LCMV"],
                                LCMV: [data_covariance: [method: "empirical"], make_lcmv: [:]]
                            ]
                        ],
                        raw_source_with_raw_covariance: [
                            match: [task: "{experiments[1]}"],
                            covariance: [type: "raw", raw_covariance_task_id: "{noise}", output_dir: "covariance"],
                            source: [
                                type: "raw",
                                source_methods: ["LCMV"],
                                LCMV: [data_covariance: [method: "empirical"], make_lcmv: [:]]
                            ]
                        ],
                        delayed_noise: [
                            match: [task: "{noise}"],
                            test_stub_delay_sec: 1
                        ]
                    ]"""
                blocks.append(dataset_block(dataset, dataset_dir, extra=extra))
            config = root / "raw-covariance.config"
            write_config(config, output, ",\n".join(blocks))
            self.run_pipeline(config, output)

            for dataset, experiments, noise, other_noise in (
                ("dataset_a", ("experimentA", "controlA"), "noiseA", "noiseB"),
                ("dataset_b", ("experimentB", "controlB"), "noiseB", "noiseA"),
            ):
                preproc = output / "datasets" / dataset / "preprocessed"
                for experiment in experiments:
                    recording = f"sub-01_task-{experiment}_run-01_meg"
                    route = preproc / "source_recon" / recording / "routing.json"
                    payload = json.loads(route.read_text(encoding="utf-8"))
                    covariance_text = Path(payload["covariance_file"]).read_text(encoding="utf-8")
                    data_covariance_text = Path(payload["data_covariance_file"]).read_text(
                        encoding="utf-8"
                    )
                    self.assertIn(f"task-{noise}", covariance_text)
                    self.assertNotIn(f"task-{other_noise}", covariance_text)
                    self.assertIn(f"task-{experiment}", data_covariance_text)
                    self.assertNotIn(f"task-{noise}", data_covariance_text)
                    self.assertEqual(
                        payload["noise_recording_key"],
                        [dataset, f"sub-01_task-{noise}_run-01_meg"],
                    )
                    expected_source_type = (
                        "epochs" if experiment == experiments[0] else "raw"
                    )
                    expected_source_hash = (
                        payload["epoch_hash"]
                        if expected_source_type == "epochs"
                        else payload["analysis_hash"]
                    )
                    self.assertEqual(payload["source_type"], expected_source_type)
                    self.assertTrue(Path(payload["resolved_rank_file"]).is_file())
                    self.assertRegex(payload["resolved_rank_hash"], r"^[0-9a-f]{64}$")
                    self.assertEqual(
                        payload["covariance_source_hash"], expected_source_hash
                    )
                    self.assertTrue(payload["lcmv_required"])
                    self.assertNotEqual(payload["data_covariance_hash"], "not-required")
                noise_recording = f"sub-01_task-{noise}_run-01_meg"
                self.assertFalse((preproc / "epochs" / noise_recording).exists())
                self.assertFalse((preproc / "source_recon" / noise_recording).exists())

    def test_lcmv_data_covariance_is_conditional_and_uses_exact_source_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            dataset = root / "dataset"
            create_dataset(dataset, ("dspm", "lcmvepochs", "lcmvraw"))
            extra = """,
                epochs: [preproc: [[resample: [sfreq: 100]]]],
                recordings: [
                    dspm_only: [
                        match: [task: "dspm"],
                        source: [source_methods: ["dSPM"]]
                    ],
                    epochs_lcmv: [
                        match: [task: "lcmvepochs"],
                        source: [
                            type: "epochs",
                            source_methods: ["LCMV"],
                            LCMV: [data_covariance: [method: "empirical"], make_lcmv: [:]]
                        ]
                    ],
                    raw_lcmv: [
                        match: [task: "lcmvraw"],
                        source: [
                            type: "raw",
                            source_methods: ["LCMV"],
                            LCMV: [data_covariance: [method: "empirical"], make_lcmv: [:]]
                        ]
                    ]
                ]"""
            config = root / "lcmv-routing.config"
            write_config(config, output, dataset_block("dataset", dataset, extra=extra))
            self.run_pipeline(config, output)

            preproc = output / "preprocessed"
            expectations = {
                "dspm": (False, "epochs", "epoch_hash"),
                "lcmvepochs": (True, "epochs", "epoch_hash"),
                "lcmvraw": (True, "raw", "analysis_hash"),
            }
            for task, (needs_lcmv, source_type, source_hash_field) in expectations.items():
                recording = f"sub-01_task-{task}_run-01_meg"
                route = preproc / "source_recon" / recording / "routing.json"
                payload = json.loads(route.read_text(encoding="utf-8"))
                data_covariance = preproc / "covariance" / recording / "lcmv-data-cov.fif"

                self.assertEqual(payload["lcmv_required"], needs_lcmv)
                self.assertEqual(payload["source_type"], source_type)
                self.assertTrue(Path(payload["resolved_rank_file"]).is_file())
                self.assertRegex(payload["resolved_rank_hash"], r"^[0-9a-f]{64}$")
                self.assertEqual(
                    payload["covariance_source_hash"], payload[source_hash_field]
                )
                self.assertEqual(data_covariance.exists(), needs_lcmv)
                if needs_lcmv:
                    self.assertEqual(payload["data_covariance_file"], str(data_covariance))
                    self.assertNotEqual(payload["data_covariance_hash"], "not-required")
                else:
                    self.assertEqual(payload["data_covariance_file"], "")
                    self.assertEqual(payload["data_covariance_hash"], "not-required")

            raw_route = json.loads(
                (
                    preproc
                    / "source_recon"
                    / "sub-01_task-lcmvraw_run-01_meg"
                    / "routing.json"
                ).read_text(encoding="utf-8")
            )
            self.assertTrue(raw_route["source_input_file"].endswith("_analysis-raw.fif"))

    def test_missing_raw_covariance_pair_fails_instead_of_silently_skipping_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            dataset = root / "dataset"
            create_dataset(dataset, ("experiment",))
            extra = """,
                covariance: [type: "raw", raw_covariance_task_id: "missing_noise"]"""
            config = root / "missing-noise.config"
            write_config(config, output, dataset_block("dataset", dataset, extra=extra))

            _, combined = self.run_pipeline(config, output, expect_success=False)
            self.assertRegex(combined, r"(?i)(join|mismatch|missing)")

    def test_invalid_recording_scope_fails_before_heavy_processing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            dataset = root / "dataset"
            create_dataset(dataset)
            extra = """,
                recordings: [
                    invalid: [
                        match: [task: "main"],
                        meg_import: [task: ["other"]]
                    ]
                ]"""
            config = root / "invalid-scope.config"
            write_config(config, output, dataset_block("dataset", dataset, extra=extra))

            _, combined = self.run_pipeline(
                config, output, stub=False, expect_success=False
            )
            self.assertIn("dataset-only fields", combined)

    def test_nonstandard_process_output_directory_fails_fast(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            dataset = root / "dataset"
            create_dataset(dataset)
            extra = """,
                epochs: [output_dir: "custom_epochs"]"""
            config = root / "invalid-process-output.config"
            write_config(config, output, dataset_block("dataset", dataset, extra=extra))

            _, combined = self.run_pipeline(
                config, output, stub=False, expect_success=False
            )
            self.assertIn(
                "epochs.output_dir is internal and fixed to 'epochs'", combined
            )
            self.assertIn("dataset-level output_dir", combined)

    def test_invalid_match_fields_and_overlapping_profiles_fail_fast(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "dataset"
            create_dataset(dataset)

            invalid_match = root / "invalid-match.config"
            invalid_match_extra = """,
                recordings: [typo: [match: [tasks: "main"], preproc: [test_marker: "bad"]]]"""
            write_config(
                invalid_match,
                root / "invalid-match-output",
                dataset_block("dataset", dataset, extra=invalid_match_extra),
            )
            _, combined = self.run_pipeline(
                invalid_match,
                root / "invalid-match-output",
                stub=False,
                expect_success=False,
            )
            self.assertIn("Unknown match fields", combined)

            overlapping = root / "overlapping.config"
            overlapping_extra = """,
                recordings: [
                    first: [match: [task: "main"], preproc: [test_marker: "first"]],
                    second: [match: [subject: "01"], preproc: [test_marker: "second"]]
                ]"""
            write_config(
                overlapping,
                root / "overlapping-output",
                dataset_block("dataset", dataset, extra=overlapping_extra),
            )
            _, combined = self.run_pipeline(
                overlapping, root / "overlapping-output", expect_success=False
            )
            self.assertIn("Multiple recording profiles matched", combined)

            excessive_stage = root / "excessive-stage.config"
            excessive_extra = """,
                recordings: [
                    too_far: [match: [task: "main"], steps: "meg_all"]
                ]"""
            write_config(
                excessive_stage,
                root / "excessive-stage-output",
                dataset_block(
                    "dataset", dataset, steps="meg_ica", extra=excessive_extra
                ),
            )
            _, combined = self.run_pipeline(
                excessive_stage,
                root / "excessive-stage-output",
                expect_success=False,
            )
            self.assertIn("cannot exceed the dataset MEG stage", combined)

    def test_duplicate_recording_ids_and_overlapping_dataset_outputs_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "duplicate-recordings"
            for folder in ("first", "second"):
                meg_dir = dataset / folder / "sub-01" / "meg"
                meg_dir.mkdir(parents=True)
                (meg_dir / "sub-01_task-main_run-01_meg.fif").write_text(
                    folder, encoding="utf-8"
                )
            duplicate_config = root / "duplicate-recordings.config"
            write_config(
                duplicate_config,
                root / "duplicate-output",
                dataset_block("dataset", dataset, steps="meg_artifacts"),
            )
            _, combined = self.run_pipeline(
                duplicate_config, root / "duplicate-output", expect_success=False
            )
            self.assertIn("share output identifiers", combined)

            dataset_a = root / "dataset-a"
            dataset_b = root / "dataset-b"
            create_dataset(dataset_a)
            create_dataset(dataset_b)
            shared = root / "shared-output"
            blocks = [
                dataset_block(
                    "dataset_a",
                    dataset_a,
                    steps="report",
                    extra=f",\n    output_dir: {groovy_string(shared)}",
                ),
                dataset_block(
                    "dataset_b",
                    dataset_b,
                    steps="report",
                    extra=f",\n    output_dir: {groovy_string(shared / 'nested')}",
                ),
            ]
            overlap_config = root / "overlap-output.config"
            write_config(overlap_config, root / "corpus-output", ",\n".join(blocks))
            _, combined = self.run_pipeline(
                overlap_config,
                root / "corpus-output",
                stub=False,
                expect_success=False,
            )
            self.assertIn("overlapping output_dir paths", combined)

    def test_resume_invalidates_event_dependent_lineage_and_new_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            dataset = root / "dataset"
            create_dataset(dataset)
            code_dir = root / "code"
            code_dir.mkdir()
            (code_dir / "utils.py").write_text("IMPLEMENTATION = 1\n", encoding="utf-8")
            config = root / "resume.config"
            write_config(
                config,
                output,
                dataset_block(
                    "dataset",
                    dataset,
                    extra=f",\n    code_dir: {groovy_string(code_dir)}",
                ),
            )

            self.run_pipeline(config, output)
            time.sleep(1.1)
            events_file = (
                dataset
                / "sub-01"
                / "meg"
                / "sub-01_task-main_run-01_events.tsv"
            )
            events_file.write_text(
                "onset\tduration\ttrial_type\n0\t0\tchanged-event\n",
                encoding="utf-8",
            )
            self.run_pipeline(config, output, resume=True)
            rows = self.trace_rows(output)

            def statuses(process_name):
                return {
                    row["status"]
                    for row in rows
                    if row["name"].startswith(f"{process_name} (")
                }

            for process_name in (
                "import_meg_dataset",
                "score_meg_quality",
                "meg_basic_preproc",
                "detect_artifacts",
                "run_ica",
                "run_ic_label",
                "apply_ica",
                "coregistration",
            ):
                self.assertEqual(statuses(process_name), {"CACHED"}, process_name)

            for process_name in (
                "epochs",
                "compute_covariance",
                "forward_solution",
                "source_imaging",
            ):
                self.assertEqual(statuses(process_name), {"COMPLETED"}, process_name)
            self.assertEqual(
                statuses("generate_static_html_report"), {"COMPLETED"}
            )

            time.sleep(1.1)
            meg_dir = dataset / "sub-01" / "meg"
            (meg_dir / "sub-01_task-second_run-01_meg.fif").write_text(
                "synthetic second\n", encoding="utf-8"
            )
            (meg_dir / "sub-01_task-second_run-01_events.tsv").write_text(
                "onset\tduration\ttrial_type\n0\t0\tstub\n", encoding="utf-8"
            )
            self.run_pipeline(config, output, resume=True)
            rows = self.trace_rows(output)
            import_rows = [
                row for row in rows if row["name"].startswith("import_meg_dataset (")
            ]
            self.assertEqual([row["status"] for row in import_rows], ["COMPLETED"])
            for process_name in (
                "score_meg_quality",
                "meg_basic_preproc",
                "epochs",
                "compute_covariance",
                "forward_solution",
                "source_imaging",
            ):
                self.assertEqual(
                    {
                        row["status"]
                        for row in rows
                        if row["name"].startswith(f"{process_name} (")
                    },
                    {"CACHED", "COMPLETED"},
                    process_name,
                )
            new_route = (
                output
                / "preprocessed"
                / "source_recon"
                / "sub-01_task-second_run-01_meg"
                / "routing.json"
            )
            self.assertTrue(new_route.is_file())

            time.sleep(1.1)
            main_raw = meg_dir / "sub-01_task-main_run-01_meg.fif"
            main_raw.write_text("synthetic main changed\n", encoding="utf-8")
            self.run_pipeline(config, output, resume=True)
            rows = self.trace_rows(output)

            def recording_status(process_name, task_name):
                matching = [
                    row["status"]
                    for row in rows
                    if row["name"].startswith(f"{process_name} (")
                    and f"task-{task_name}" in row["name"]
                ]
                self.assertEqual(len(matching), 1, (process_name, task_name, rows))
                return matching[0]

            for process_name in (
                "score_meg_quality",
                "meg_basic_preproc",
                "epochs",
                "compute_covariance",
                "forward_solution",
                "source_imaging",
            ):
                self.assertEqual(
                    recording_status(process_name, "main"),
                    "COMPLETED",
                    process_name,
                )
                self.assertEqual(
                    recording_status(process_name, "second"),
                    "CACHED",
                    process_name,
                )

            time.sleep(1.1)
            (code_dir / "utils.py").write_text(
                "IMPLEMENTATION = 2\n", encoding="utf-8"
            )
            self.run_pipeline(config, output, resume=True)
            rows = self.trace_rows(output)
            for process_name in (
                "import_meg_dataset",
                "score_meg_quality",
                "meg_basic_preproc",
                "epochs",
                "compute_covariance",
                "forward_solution",
                "source_imaging",
            ):
                process_rows = [
                    row
                    for row in rows
                    if row["name"].startswith(f"{process_name} (")
                ]
                self.assertTrue(process_rows, process_name)
                self.assertEqual(
                    {row["status"] for row in process_rows},
                    {"COMPLETED"},
                    process_name,
                )

    def test_resume_distinguishes_edited_sidecars_from_missing_generated_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            dataset = root / "dataset"
            create_dataset(dataset, ("main", "control"))
            config = root / "resume-published-outputs.config"
            write_config(config, output, dataset_block("dataset", dataset))

            recording_processes = (
                "score_meg_quality",
                "meg_basic_preproc",
                "detect_artifacts",
                "run_ica",
                "run_ic_label",
                "apply_ica",
                "epochs",
                "compute_covariance",
                "coregistration",
                "forward_solution",
                "source_imaging",
            )

            def recording_status(process_name, task_name):
                matching = [
                    row["status"]
                    for row in self.trace_rows(output)
                    if row["name"].startswith(f"{process_name} (")
                    and f"task-{task_name}" in row["name"]
                ]
                self.assertEqual(
                    len(matching),
                    1,
                    (process_name, task_name, self.trace_rows(output)),
                )
                return matching[0]

            def dataset_status(process_name):
                matching = [
                    row["status"]
                    for row in self.trace_rows(output)
                    if row["name"].startswith(f"{process_name} (")
                ]
                self.assertEqual(len(matching), 1, (process_name, matching))
                return matching[0]

            self.run_pipeline(config, output)
            self.run_pipeline(config, output, resume=True)
            for process_name in recording_processes:
                for task_name in ("main", "control"):
                    self.assertEqual(
                        recording_status(process_name, task_name),
                        "CACHED",
                        (process_name, task_name),
                    )
            self.assertEqual(
                dataset_status("generate_static_html_report"), "COMPLETED"
            )

            preproc = output / "preprocessed"
            main_recording = "sub-01_task-main_run-01_meg"
            bad_segments = (
                preproc
                / "artifact_report"
                / main_recording
                / f"{main_recording}_preproc-raw_bad_segments.txt"
            )
            time.sleep(1.1)
            bad_segments.write_text("12.5 13.0\n", encoding="utf-8")
            self.run_pipeline(config, output, resume=True)

            for process_name in (
                "score_meg_quality",
                "meg_basic_preproc",
                "detect_artifacts",
            ):
                self.assertEqual(
                    recording_status(process_name, "main"),
                    "CACHED",
                    process_name,
                )
            for process_name in (
                "run_ica",
                "run_ic_label",
                "apply_ica",
                "epochs",
                "compute_covariance",
                "forward_solution",
                "source_imaging",
            ):
                self.assertEqual(
                    recording_status(process_name, "main"),
                    "COMPLETED",
                    process_name,
                )
            self.assertEqual(recording_status("coregistration", "main"), "COMPLETED")
            for process_name in recording_processes:
                self.assertEqual(
                    recording_status(process_name, "control"),
                    "CACHED",
                    process_name,
                )
            self.assertEqual(
                dataset_status("generate_static_html_report"), "COMPLETED"
            )

            epoch_files = list((preproc / "epochs" / main_recording).glob("*-epo.fif"))
            self.assertEqual(len(epoch_files), 1, epoch_files)
            epoch_files[0].unlink()
            self.run_pipeline(config, output, resume=True)

            self.assertTrue(epoch_files[0].is_file())
            for process_name in (
                "epochs",
                "compute_covariance",
                "forward_solution",
                "source_imaging",
            ):
                self.assertEqual(
                    recording_status(process_name, "main"),
                    "COMPLETED",
                    process_name,
                )
            for process_name in (
                "score_meg_quality",
                "meg_basic_preproc",
                "detect_artifacts",
                "run_ica",
                "run_ic_label",
                "apply_ica",
                "coregistration",
            ):
                self.assertEqual(
                    recording_status(process_name, "main"),
                    "CACHED",
                    process_name,
                )
            for process_name in recording_processes:
                self.assertEqual(
                    recording_status(process_name, "control"),
                    "CACHED",
                    process_name,
                )
            self.assertEqual(
                dataset_status("generate_static_html_report"), "COMPLETED"
            )

    def test_resume_reruns_each_owner_with_a_missing_published_meg_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            dataset = root / "dataset"
            owner_by_task = {
                "qc": "score_meg_quality",
                "preproc": "meg_basic_preproc",
                "artifacts": "detect_artifacts",
                "ica": "run_ica",
                "label": "run_ic_label",
                "scores": "run_ic_label",
                "clean": "apply_ica",
                "epochs": "epochs",
                "epochanalysis": "epochs",
                "covariance": "compute_covariance",
                "coreg": "coregistration",
                "forward": "forward_solution",
                "source": "source_imaging",
            }
            create_dataset(dataset, (*owner_by_task, "control"))
            extra = """,
                epochs: [preproc: [[resample: [sfreq: 100]]]]"""
            config = root / "resume-owner-matrix.config"
            write_config(
                config,
                output,
                dataset_block("dataset", dataset, extra=extra),
            )
            self.run_pipeline(config, output)

            preproc = output / "preprocessed"

            def recording(task_name):
                return f"sub-01_task-{task_name}_run-01_meg"

            def only_match(path):
                matches = list(path.parent.glob(path.name))
                self.assertEqual(len(matches), 1, matches)
                return matches[0]

            targets = {
                "qc": only_match(
                    preproc
                    / "quality_control"
                    / recording("qc")
                    / "*.summary.json"
                ),
                "preproc": preproc
                / recording("preproc")
                / f"{recording('preproc')}_preproc-raw.fif",
                "artifacts": preproc
                / "artifact_report"
                / recording("artifacts")
                / f"{recording('artifacts')}_preproc-raw_bad_segments.txt",
                "ica": preproc
                / "ica_report"
                / recording("ica")
                / f"{recording('ica')}_preproc-raw_ica.fif",
                "label": preproc
                / "ica_report"
                / recording("label")
                / "marked_components.txt",
                "scores": preproc
                / "ica_report"
                / recording("scores")
                / "ecg_eog_scores.json",
                "clean": preproc
                / recording("clean")
                / f"{recording('clean')}_preproc-raw_clean_raw.fif",
                "epochs": only_match(
                    preproc / "epochs" / recording("epochs") / "*-epo.fif"
                ),
                "epochanalysis": only_match(
                    preproc
                    / "epochs"
                    / recording("epochanalysis")
                    / "*_analysis-raw.fif"
                ),
                "covariance": preproc
                / "covariance"
                / recording("covariance")
                / "bl-cov.fif",
                "coreg": preproc
                / "trans"
                / recording("coreg")
                / "coreg-trans.fif",
                "forward": preproc
                / "forward_solution"
                / recording("forward")
                / "event_ico4-fwd.fif",
                "source": preproc / "source_recon" / recording("source"),
            }
            for task_name, target in targets.items():
                with self.subTest(delete=task_name):
                    self.assertTrue(target.exists(), target)
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink()

            self.run_pipeline(config, output, resume=True)
            rows = self.trace_rows(output)

            def recording_status(process_name, task_name):
                matching = [
                    row["status"]
                    for row in rows
                    if row["name"].startswith(f"{process_name} (")
                    and f"task-{task_name}" in row["name"]
                ]
                self.assertEqual(len(matching), 1, (process_name, task_name, rows))
                return matching[0]

            for task_name, owner_process in owner_by_task.items():
                with self.subTest(owner=owner_process, task=task_name):
                    self.assertEqual(
                        recording_status(owner_process, task_name), "COMPLETED"
                    )
                    self.assertTrue(targets[task_name].exists(), targets[task_name])

            for process_name in (
                "score_meg_quality",
                "meg_basic_preproc",
                "detect_artifacts",
                "run_ica",
                "run_ic_label",
                "apply_ica",
                "epochs",
                "compute_covariance",
                "coregistration",
                "forward_solution",
                "source_imaging",
            ):
                self.assertEqual(
                    recording_status(process_name, "control"),
                    "CACHED",
                    process_name,
                )
            report_rows = [
                row
                for row in rows
                if row["name"].startswith("generate_static_html_report (")
            ]
            self.assertEqual([row["status"] for row in report_rows], ["COMPLETED"])

    def test_lenient_failures_and_qc_exclusion_still_schedule_all_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            failures = {
                "qcfail": "score_meg_quality",
                "preprocfail": "meg_basic_preproc",
                "artifactfail": "detect_artifacts",
                "icafail": "run_ica",
                "labelfail": "run_ic_label",
                "applyfail": "apply_ica",
                "epochfail": "epochs",
                "covfail": "compute_covariance",
                "coregfail": "coregistration",
                "forwardfail": "forward_solution",
                "sourcefail": "source_imaging",
            }

            mixed_dataset = root / "mixed"
            create_dataset(mixed_dataset, (*failures, "success"))
            failure_profiles = ",\n".join(
                f"""{task_name}: [
                    match: [task: {groovy_string(task_name)}],
                    test_stub_fail_process: {groovy_string(process_name)}
                ]"""
                for task_name, process_name in failures.items()
            )
            mixed_extra = f""",
                recordings: [
                    {failure_profiles}
                ]"""

            all_failed_dataset = root / "all-failed"
            create_dataset(all_failed_dataset, ("allfail",))
            all_failed_extra = """,
                recordings: [
                    fail_immediately: [
                        match: [task: "allfail"],
                        test_stub_fail_process: "score_meg_quality"
                    ]
                ]"""

            excluded_dataset = root / "qc-excluded"
            create_dataset(excluded_dataset, ("lowqc",))
            excluded_extra = """,
                megqc: [min_score: 50.0],
                recordings: [
                    below_gate: [
                        match: [task: "lowqc"],
                        test_stub_qc_score: 10.0
                    ]
                ]"""

            blocks = [
                dataset_block("mixed", mixed_dataset, extra=mixed_extra),
                dataset_block(
                    "all_failed", all_failed_dataset, extra=all_failed_extra
                ),
                dataset_block(
                    "qc_excluded", excluded_dataset, extra=excluded_extra
                ),
            ]
            config = root / "lenient-failures.config"
            write_config(
                config,
                output,
                ",\n".join(blocks),
                error_mode="lenient",
            )
            self.run_pipeline(config, output)
            rows = self.trace_rows(output)

            for task_name, process_name in failures.items():
                with self.subTest(failure=process_name):
                    matching = [
                        row
                        for row in rows
                        if row["name"].startswith(f"{process_name} (mixed:")
                        and f"task-{task_name}" in row["name"]
                    ]
                    self.assertEqual(len(matching), 1, matching)
                    self.assertNotIn(
                        matching[0]["status"], {"COMPLETED", "CACHED"}
                    )

            success_source = [
                row
                for row in rows
                if row["name"].startswith("source_imaging (mixed:")
                and "task-success" in row["name"]
            ]
            self.assertEqual(
                [row["status"] for row in success_source], ["COMPLETED"]
            )
            self.assertFalse(
                any(
                    row["name"].startswith("meg_basic_preproc (all_failed:")
                    for row in rows
                )
            )
            self.assertFalse(
                any(
                    row["name"].startswith("meg_basic_preproc (qc_excluded:")
                    for row in rows
                )
            )

            dataset_reports = [
                row
                for row in rows
                if row["name"].startswith("generate_static_html_report (")
            ]
            self.assertEqual(len(dataset_reports), 3, dataset_reports)
            self.assertEqual(
                {row["status"] for row in dataset_reports}, {"COMPLETED"}
            )
            corpus_reports = [
                row
                for row in rows
                if row["name"].startswith("generate_corpus_static_html_report (")
            ]
            self.assertEqual(
                [row["status"] for row in corpus_reports], ["COMPLETED"]
            )

    def test_single_dataset_stage_ui_registers_only_selected_processes(self):
        cases = {
            "report": ("report", REPORT_PROCESSES),
            "anatomy": ("anatomy", FREESURFER_ANATOMY_PROCESSES),
            "artifacts": ("meg_artifacts", MEG_ARTIFACT_PROCESSES),
            "ica": ("meg_ica", MEG_ICA_PROCESSES),
            "epochs": ("meg_epochs", MEG_EPOCH_PROCESSES),
            "epochs_skip_ica": (
                "meg_epochs,skip_ica",
                MEG_SKIP_ICA_EPOCH_PROCESSES,
            ),
            "source": ("meg_all", MEG_SOURCE_PROCESSES),
            "all": (
                "all",
                MEG_SOURCE_PROCESSES | FREESURFER_ANATOMY_PROCESSES,
            ),
        }
        for case_name, (steps, expected_processes) in cases.items():
            with self.subTest(case=case_name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                output = root / "output"
                dataset = root / "dataset"
                create_dataset(dataset)
                config = root / "stage.config"
                write_config(
                    config,
                    output,
                    dataset_block("dataset", dataset, steps=steps),
                )

                _, combined = self.run_pipeline(
                    config,
                    output,
                    ansi_log=True,
                )
                displayed = self.displayed_processes(
                    combined,
                    VISIBLE_PROCESS_CANDIDATES,
                )
                self.assertEqual(displayed, expected_processes, combined)

    def test_strict_processing_failure_terminates_before_report_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            dataset = root / "dataset"
            create_dataset(dataset, ("fail",))
            extra = """,
                recordings: [
                    fail_qc: [
                        match: [task: "fail"],
                        test_stub_fail_process: "score_meg_quality"
                    ]
                ]"""
            config = root / "strict-failure.config"
            write_config(
                config,
                output,
                dataset_block("dataset", dataset, extra=extra),
                error_mode="strict",
            )
            self.run_pipeline(config, output, expect_success=False)
            names = self.trace_names(output)
            self.assertTrue(
                any(name.startswith("score_meg_quality (") for name in names)
            )
            self.assertFalse(
                any(name.startswith("generate_static_html_report (") for name in names)
            )


if __name__ == "__main__":
    unittest.main()
