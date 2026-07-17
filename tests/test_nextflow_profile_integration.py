import csv
import json
import os
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


def write_config(path, output_dir, datasets_text, *, defaults_override="[:]"):
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
                    error_mode: "strict",
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
                errorStrategy = "terminate"
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
        self, config, output_dir, *, stub=True, resume=False, expect_success=True
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
            cwd=REPO_ROOT,
            env=dict(os.environ, NXF_ANSI_LOG="false"),
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

    def trace_names(self, output_dir):
        with (output_dir / "trace.txt").open(encoding="utf-8") as handle:
            return [row["name"] for row in csv.DictReader(handle, delimiter="\t")]

    def trace_rows(self, output_dir):
        with (output_dir / "trace.txt").open(encoding="utf-8") as handle:
            return list(csv.DictReader(handle, delimiter="\t"))

    def test_stage_matrix_and_anatomy_meg_synchronization(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            stages = {
                "report_stage": "report",
                "anatomy_stage": "anatomy",
                "deepprep_stage": "anatomy",
                "pseudomri_stage": "anatomy",
                "native_nifti_stage": "anatomy",
                "dicom_stage": "anatomy",
                "artifacts_stage": "meg_artifacts",
                "ica_stage": "meg_ica",
                "epochs_stage": "meg_epochs",
                "skip_ica_stage": "meg_epochs,skip_ica",
                "full_stage": "meg_all",
                "all_stage": "all",
            }
            blocks = []
            for name, steps in stages.items():
                dataset_dir = root / name
                create_dataset(dataset_dir)
                if name == "native_nifti_stage":
                    (dataset_dir / "sub-01_native.nii.gz").write_text(
                        "synthetic native T1\n", encoding="utf-8"
                    )
                dicom_root = root / "dicom-input"
                if name == "dicom_stage":
                    dicom_series = dicom_root / "subject01"
                    dicom_series.mkdir(parents=True)
                    (dicom_series / "image.dcm").write_text(
                        "synthetic DICOM\n", encoding="utf-8"
                    )
                anatomy_extra = {
                    "deepprep_stage": ',\n    anatomy: [method: "deepprep", is_bids: true]',
                    "pseudomri_stage": ',\n    anatomy: [method: "pseudomri", is_bids: false]',
                    "native_nifti_stage": ',\n    anatomy: [method: "freesurfer", is_bids: false, t1_input_type: "nifti"]',
                    "dicom_stage": (
                        f',\n    t1_dir: {groovy_string(dicom_root)},'
                        '\n    anatomy: [method: "freesurfer", is_bids: false, t1_input_type: "dicom"]'
                    ),
                }.get(name, "")
                blocks.append(
                    dataset_block(name, dataset_dir, steps=steps, extra=anatomy_extra)
                )
            config = root / "stages.config"
            write_config(config, output, ",\n".join(blocks))

            self.run_pipeline(config, output)
            names = self.trace_names(output)
            report_datasets = {
                "report_stage",
                "artifacts_stage",
                "ica_stage",
                "epochs_stage",
                "skip_ica_stage",
                "full_stage",
                "all_stage",
            }
            for dataset_name in report_datasets:
                self.assertTrue(
                    any(
                        name.startswith(
                            f"generate_static_html_report ({dataset_name})"
                        )
                        for name in names
                    ),
                    dataset_name,
                )
            self.assertFalse(any("import_meg_dataset (report_stage)" in name for name in names))

            smri = output / "smri"
            self.assertTrue((smri / "anatomy_stage" / "sub-01" / "bem" / "stub-bem.done").is_file())
            self.assertTrue((smri / "deepprep_stage" / "sub-01" / "bem" / "stub-bem.done").is_file())
            self.assertTrue((smri / "pseudomri_stage" / "sub-01" / "bem" / "stub-bem.done").is_file())
            self.assertTrue((smri / "native_nifti_stage" / "sub-01_native" / "bem" / "stub-bem.done").is_file())
            self.assertTrue((smri / "dicom_stage" / "subject01_stub" / "bem" / "stub-bem.done").is_file())
            self.assertTrue((smri / "all_stage" / "sub-01" / "bem" / "stub-bem.done").is_file())
            self.assertTrue(any(name.startswith("run_deepprep (deepprep_stage") for name in names))
            self.assertTrue(any(name.startswith("generate_pseudomri (pseudomri_stage") for name in names))
            self.assertTrue(any(name.startswith("dcm2niix (dicom_stage") for name in names))

            for name in ("artifacts_stage", "ica_stage", "epochs_stage", "skip_ica_stage", "full_stage", "all_stage"):
                preproc = output / "datasets" / name / "preprocessed"
                recording = "sub-01_task-main_run-01_meg"
                self.assertTrue((preproc / recording / f"{recording}_preproc-raw.fif").is_file(), name)

            artifacts_preproc = output / "datasets" / "artifacts_stage" / "preprocessed"
            self.assertFalse((artifacts_preproc / "ica_report").exists())

            ica_preproc = output / "datasets" / "ica_stage" / "preprocessed"
            self.assertTrue((ica_preproc / "sub-01_task-main_run-01_meg" / "sub-01_task-main_run-01_meg_preproc-raw_clean_raw.fif").is_file())
            self.assertFalse((ica_preproc / "epochs").exists())

            skip_preproc = output / "datasets" / "skip_ica_stage" / "preprocessed"
            self.assertFalse((skip_preproc / "ica_report").exists())
            self.assertTrue(any((skip_preproc / "epochs").rglob("*-epo.fif")))

            for name in ("full_stage", "all_stage"):
                route = (
                    output
                    / "datasets"
                    / name
                    / "preprocessed"
                    / "source_recon"
                    / "sub-01_task-main_run-01_meg"
                    / "routing.json"
                )
                self.assertTrue(route.is_file(), name)

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
            create_dataset(dataset, ("artifacts", "ica", "epochs", "full"))
            extra = """,
                recordings: [
                    artifacts_only: [match: [task: "artifacts"], steps: "meg_artifacts"],
                    ica_only: [match: [task: "ica"], steps: "meg_ica"],
                    epochs_only: [match: [task: "epochs"], steps: "meg_epochs"]
                ]"""
            config = root / "recording-steps.config"
            write_config(config, output, dataset_block("dataset", dataset, extra=extra))
            self.run_pipeline(config, output)

            preproc = output / "preprocessed"
            artifacts_recording = "sub-01_task-artifacts_run-01_meg"
            ica_recording = "sub-01_task-ica_run-01_meg"
            epochs_recording = "sub-01_task-epochs_run-01_meg"
            full_recording = "sub-01_task-full_run-01_meg"

            self.assertFalse((preproc / "ica_report" / artifacts_recording).exists())
            self.assertTrue((preproc / "ica_report" / ica_recording).is_dir())
            self.assertFalse((preproc / "epochs" / ica_recording).exists())
            self.assertTrue(any((preproc / "epochs" / epochs_recording).glob("*-epo.fif")))
            self.assertFalse((preproc / "source_recon" / epochs_recording).exists())
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


if __name__ == "__main__":
    unittest.main()
