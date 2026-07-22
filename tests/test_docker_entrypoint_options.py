import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"
DOCKER_RUNNER = REPO_ROOT / "nextflow" / "run_for_docker.sh"
INSTALLATION_DOC = REPO_ROOT / "docs" / "source" / "quickstart" / "installation.rst"
QUICKSTART_DOC = REPO_ROOT / "docs" / "source" / "quickstart" / "quick_guide.rst"
CONFIGURATION_DOC = REPO_ROOT / "docs" / "source" / "reference" / "configuration.rst"
INDEX_DOC = REPO_ROOT / "docs" / "source" / "index.rst"
SPHINX_CONFIG = REPO_ROOT / "docs" / "source" / "conf.py"
OPM_CONVERSION_DOC = REPO_ROOT / "docs" / "source" / "reference" / "opm_conversion.rst"
INTERACTIVE_PREPROC = REPO_ROOT / "megflow" / "reports" / "reports" / "preproc.py"
QUICKSTART_CONFIG = REPO_ROOT / "nextflow" / "quickstart.config"
EXAMPLES_DOC = REPO_ROOT / "docs" / "source" / "reference" / "examples.rst"


class DockerEntrypointOptionTests(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tempdir.name)
        self.fake_bin = self.root / "bin"
        self.fake_bin.mkdir()
        self.nextflow_args = self.root / "nextflow-args.txt"
        self.nextflow_pwd = self.root / "nextflow-pwd.txt"
        self.streamlit_args = self.root / "streamlit-args.txt"
        self.streamlit_env = self.root / "streamlit-env.txt"

        self._write_executable(
            self.fake_bin / "nextflow",
            "#!/bin/bash\n"
            'printf "%s\\n" "$@" > "$MEGFLOW_TEST_NEXTFLOW_ARGS"\n'
            'pwd > "$MEGFLOW_TEST_NEXTFLOW_PWD"\n'
            'test -d .nextflow\n',
        )
        self._write_executable(
            self.fake_bin / "streamlit",
            "#!/bin/bash\n"
            'printf "%s\\n" "$@" > "$MEGFLOW_TEST_STREAMLIT_ARGS"\n'
            'printf "DATASET_REPORT_PATH=%s\\nSUBJECTS_DIR=%s\\n" '
            '"${DATASET_REPORT_PATH:-}" "${SUBJECTS_DIR:-}" > "$MEGFLOW_TEST_STREAMLIT_ENV"\n',
        )

        self.base_config = self.root / "base.config"
        self.base_config.write_text(
            'params.megflow = [defaults: [steps: "meg_all", '
            'anatomy: [is_bids: false, method: "pseudomri", '
            't1_input_type: "dicom", t1_dicom_series_glob: "*T1*"], '
            'report: [static_task_log_mode: "none", '
            'static_artifact_overview_duration: 45.0]], '
            'datasets: [docker_input: [name: "docker_input", '
            't1_dir: "/configured/t1"], '
            'NamedDataset: [steps: "meg_epochs"]]]\n',
            encoding="utf-8",
        )
        self.pipeline = self.root / "megflow.nf"
        self.pipeline.write_text("// fake pipeline\n", encoding="utf-8")
        self.run_config = self.root / "run_nextflow.config"
        self.runner = self.root / "run.sh"
        runner_text = DOCKER_RUNNER.read_text(encoding="utf-8")
        runner_text = runner_text.replace(
            'NEXTFLOW_FILE="/program/nextflow/megflow.nf"',
            f'NEXTFLOW_FILE="{self.pipeline}"',
        )
        self._write_executable(self.runner, runner_text)

        self.env = os.environ.copy()
        self.env.update(
            {
                "PATH": f"{self.fake_bin}:{self.env['PATH']}",
                "MEGFLOW_DOCKER_DROPPED": "1",
                "MEGFLOW_TEST_NEXTFLOW_ARGS": str(self.nextflow_args),
                "MEGFLOW_TEST_NEXTFLOW_PWD": str(self.nextflow_pwd),
                "MEGFLOW_TEST_STREAMLIT_ARGS": str(self.streamlit_args),
                "MEGFLOW_TEST_STREAMLIT_ENV": str(self.streamlit_env),
                "MEGFLOW_RUN_CONFIG_FILE": str(self.run_config),
            }
        )

    def tearDown(self):
        self._tempdir.cleanup()

    @staticmethod
    def _write_executable(path: Path, text: str):
        path.write_text(text, encoding="utf-8")
        path.chmod(0o755)

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(self.runner), *args],
            env=self.env,
            text=True,
            capture_output=True,
        )

    def test_runtime_config_is_written_below_the_writable_output_root(self):
        runner = self.root / "read-only-compatible-run.sh"
        runner_text = DOCKER_RUNNER.read_text(encoding="utf-8").replace(
            'NEXTFLOW_FILE="/program/nextflow/megflow.nf"',
            f'NEXTFLOW_FILE="{self.pipeline}"',
        )
        self._write_executable(runner, runner_text)
        input_dir = self.root / "input"
        output_dir = self.root / "output"
        input_dir.mkdir()
        output_dir.mkdir()
        env = self.env.copy()
        env.pop("MEGFLOW_RUN_CONFIG_FILE", None)

        result = subprocess.run(
            [
                "bash",
                str(runner),
                "-c",
                str(self.base_config),
                "-i",
                str(input_dir),
                "-o",
                str(output_dir),
                "--steps",
                "report",
            ],
            env=env,
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            (output_dir / ".nextflow-launch" / "run_nextflow.config").is_file()
        )
        self.assertNotIn("/program/nextflow/run_nextflow.config", runner_text)

    def test_help_and_installation_list_the_same_entrypoint_options(self):
        result = self._run("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        docs = INSTALLATION_DOC.read_text(encoding="utf-8")
        expected_options = (
            "--config",
            "--input",
            "--output",
            "--steps",
            "--anat-method",
            "--view-report",
            "--corpus",
            "--fs_license_file",
            "--fs_subjects_dir",
            "--t1_dir",
            "--resume",
            "--help",
        )
        for option in expected_options:
            self.assertIn(option, result.stdout)
            self.assertIn(option, docs)
        removed_options = (
            "--static_task_log_mode",
            "--static_artifact_overview_duration",
            "--t1_input_type",
            "--t1_dicom_series_glob",
            "--anatomy_preprocess_method",
        )
        for option in removed_options:
            self.assertNotIn(option, result.stdout)
            self.assertNotIn(option, docs)
        self.assertIn("Single-dataset structural MRI input root", result.stdout)
        self.assertIn("single-dataset mode", docs)
        self.assertIn("mkdir -p /data/out /data/smri", docs)
        self.assertIn("root:root", docs)
        self.assertIn(
            "Anatomy method: freesurfer, deepprep, or pseudomri", result.stdout
        )
        for method in ("freesurfer", "deepprep", "pseudomri"):
            self.assertIn(f"``{method}``", docs)

    def test_readme_meg_all_step_includes_default_nmdq_scoring(self):
        readme = README.read_text(encoding="utf-8")
        meg_all_row = next(
            line for line in readme.splitlines() if line.startswith("| `meg_all` |")
        )
        self.assertIn("NMDQ score", meg_all_row)
        self.assertIn("`megqc.enabled`", meg_all_row)
        self.assertIn("default", meg_all_row.lower())

    def test_readme_names_options_after_the_image_as_megflow_options(self):
        readme = README.read_text(encoding="utf-8")
        self.assertIn("[megflow_options]", readme)
        self.assertNotIn("[nextflow_options]", readme)

    def test_container_install_commands_do_not_require_a_repository_checkout(self):
        for document in (README, INSTALLATION_DOC):
            with self.subTest(document=document.name):
                text = document.read_text(encoding="utf-8").lower()
                container_section = text.split(
                    "recommended: containerized", 1
                )[1].split("alternative:", 1)[0]
                self.assertNotIn("repository root", container_section)
                self.assertIn("raw.githubusercontent.com", container_section)
                self.assertIn("megflow_version=1.0.0", container_section)

    def test_readme_uses_current_workflow_and_report_terms(self):
        readme = README.read_text(encoding="utf-8")
        normalized_readme = readme.lower()
        with_anatomy_row = next(
            line for line in readme.splitlines() if line.startswith("| `with_anatomy` |")
        )
        self.assertIn("concurrently", with_anatomy_row)
        self.assertNotIn("Artifact rejection", readme)
        self.assertIn("bad-channel and bad-segment detection", normalized_readme)
        self.assertIn("static HTML", readme)
        self.assertIn("interactive", readme)
        self.assertNotIn("MEGQC", readme)
        self.assertIn("NormMEG-QC", readme)

    def test_readme_keeps_validation_with_developer_setup(self):
        readme = README.read_text(encoding="utf-8")
        development = readme.split("## 🛠️ Development", 1)[1]
        self.assertLess(
            development.index("### Local Development Setup"),
            development.index("### Validation and Regression-Test Modes"),
        )
        self.assertLess(
            development.index("### Validation and Regression-Test Modes"),
            development.index("### Building the Docker Image"),
        )

    def test_configuration_docs_distinguish_all_config_cli_layers(self):
        text = CONFIGURATION_DOC.read_text(encoding="utf-8")
        normalized_text = " ".join(text.split())
        for expected in (
            "Docker entrypoint",
            "``-c`` / ``--config``",
            "soft override",
            "hard override",
            "``nextflow -c``",
            "``nextflow -C``",
            "ignore all other configuration files",
        ):
            self.assertIn(expected, normalized_text)

    def test_validation_navigation_is_separate_from_reference(self):
        index = INDEX_DOC.read_text(encoding="utf-8")
        reference = index.split(":caption: Reference", 1)[1].split(
            ".. toctree::", 1
        )[0]
        development = index.split(":caption: Development", 1)[1]
        self.assertNotIn("reference/validation", reference)
        self.assertIn("reference/validation", development)

    def test_sphinx_refs_and_internal_card_links_are_strict(self):
        config = SPHINX_CONFIG.read_text(encoding="utf-8")
        index = INDEX_DOC.read_text(encoding="utf-8")
        opm = OPM_CONVERSION_DOC.read_text(encoding="utf-8")
        self.assertNotIn('"ref.ref"', config)
        self.assertNotRegex(index, r":link:\s+\S+\.html")
        self.assertGreaterEqual(index.count(":link-type: doc"), 10)
        self.assertNotIn(":func:`mne.find_events`", opm)
        self.assertIn("https://mne.tools/stable/generated/mne.find_events.html", opm)
        self.assertIn("copyright = '2026,", config)

    def test_interactive_saved_files_only_lists_persisted_sidecars(self):
        source = INTERACTIVE_PREPROC.read_text(encoding="utf-8")
        saved_details = source.split(
            'with st.expander("📄 Saved Files Details"', 1
        )[1].split("# Reset navigation", 1)[0]
        self.assertIn("**Bad channels:**", saved_details)
        self.assertIn("**Bad segments:**", saved_details)
        self.assertNotIn("**Raw data:**", saved_details)

    def test_quickstart_ships_a_safe_downloadable_project_overlay(self):
        self.assertTrue(QUICKSTART_CONFIG.is_file())
        config = QUICKSTART_CONFIG.read_text(encoding="utf-8")
        self.assertRegex(
            config,
            r"(?s)params\s*\{.*megflow\s*\{.*datasets\s*\{.*"
            r"docker_input\s*\{.*steps\s*=\s*\"meg_ica\"",
        )
        for selector in (
            "subject_id = null",
            "session_id = null",
            "task = null",
            "run_id = null",
            "raw_include_keywords = null",
            "raw_exclude_keywords = null",
        ):
            self.assertIn(selector, config)
        self.assertNotIn("/data/liaopan", config)

        quickstart = QUICKSTART_DOC.read_text(encoding="utf-8")
        self.assertIn(
            ".. literalinclude:: ../../../nextflow/quickstart.config", quickstart
        )
        self.assertIn(
            ":download:`Download quickstart.config "
            "<../../../nextflow/quickstart.config>`",
            quickstart,
        )
        self.assertIn(
            ":download:`authoritative Docker defaults "
            "<../../../nextflow/nextflow_for_docker.config>`",
            quickstart,
        )
        self.assertIn("HOST_PATH:CONTAINER_PATH", quickstart)
        self.assertIn("mkdir -p /path/to/output /path/to/smri", quickstart)
        self.assertIn("root:root", quickstart)
        self.assertIn("test -w /path/to/smri", quickstart)
        for option in (
            "``-v``",
            "``-i``",
            "``-o``",
            "``--steps``",
            "``--resume``",
        ):
            self.assertIn(option, quickstart)

    def test_quickstart_writability_checks_explain_success_and_failure(self):
        quickstart = QUICKSTART_DOC.read_text(encoding="utf-8")
        for path in ("/path/to/output", "/path/to/smri"):
            self.assertIn(f'echo "OK: {path} is writable"', quickstart)
            self.assertIn(
                f'echo "FAILED: {path} is not writable"', quickstart
            )
        self.assertIn("Both checks must print ``OK``", quickstart)
        self.assertIn("If either check prints ``FAILED``", quickstart)

    def test_quickstart_covers_smn4lang_results_and_beginner_goals(self):
        quickstart = QUICKSTART_DOC.read_text(encoding="utf-8")
        for smn_selector in (
            'subject_id: ["02"]',
            'task: ["RDR"]',
            'run_id: ["1"]',
        ):
            self.assertIn(smn_selector, quickstart)
        self.assertNotIn("/data/liaopan", quickstart)

        for stage in (
            "``meg_artifacts``",
            "``meg_ica``",
            "``meg_epochs``",
            "``anatomy``",
            "``meg_all``",
            "``all``",
            "``report``",
        ):
            self.assertIn(stage, quickstart)
        for beginner_setting in (
            "meg_import.subject_id",
            "fixed_length_duration",
            "event_source",
            "preproc.steps",
            "deepreject.enabled",
            "find_bad_channels_lof: null",
            "ic_ecg",
            "ic_eog",
            "ic_outlier",
            "source_methods",
        ):
            self.assertIn(beginner_setting, quickstart)
        for detail_link in (
            ":doc:`report guide <../tutorial/reports>`",
            ":doc:`complete output guide <../tutorial/outputs>`",
            ":doc:`pipeline details <../details/pipeline_details>`",
        ):
            self.assertIn(detail_link, quickstart)

        examples = EXAMPLES_DOC.read_text(encoding="utf-8")
        self.assertIn(
            ":download:`quickstart.config <../../../nextflow/quickstart.config>`",
            examples,
        )

    def test_single_dataset_options_generate_expected_runtime_config(self):
        input_dir = self.root / "single-input"
        output_dir = self.root / "single-output"
        t1_dir = self.root / "single-t1"
        fs_dir = self.root / "single-fs"
        for path in (input_dir, t1_dir):
            path.mkdir()
        license_file = self.root / "license.txt"
        license_file.write_text("license\n", encoding="utf-8")

        result = self._run(
            "--config",
            str(self.base_config),
            "--input",
            str(input_dir),
            "--output",
            str(output_dir),
            "--steps",
            "anatomy",
            "--anat-method",
            "deepprep",
            "--fs_license_file",
            str(license_file),
            "--fs_subjects_dir",
            str(fs_dir),
            "--t1_dir",
            str(t1_dir),
            "--resume",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        config = (output_dir / "nextflow.config").read_text(encoding="utf-8")
        expected_lines = (
            f'params.megflow.datasets.docker_input.dataset_dir = "{input_dir}"',
            f'params.megflow.datasets.docker_input.output_dir = "{output_dir}"',
            f'params.megflow.datasets.docker_input.t1_dir = "{t1_dir}"',
            f'params.megflow.datasets.docker_input.fs_subjects_dir = "{fs_dir}"',
            'params.megflow.datasets.docker_input.steps = "anatomy"',
            'params.megflow.datasets.docker_input.anatomy.method = "deepprep"',
            f'params.megflow.datasets.docker_input.anatomy.fs_license_file = "{license_file}"',
        )
        for line in expected_lines:
            self.assertIn(line, config)
        anatomy_init = (
            "params.megflow.datasets.docker_input.anatomy = "
            "params.megflow.datasets.docker_input.anatomy ?: [:]"
        )
        license_assignment = (
            f'params.megflow.datasets.docker_input.anatomy.fs_license_file = "{license_file}"'
        )
        method_assignment = (
            'params.megflow.datasets.docker_input.anatomy.method = "deepprep"'
        )
        self.assertIn(anatomy_init, config)
        self.assertLess(config.index(anatomy_init), config.index(method_assignment))
        self.assertLess(config.index(anatomy_init), config.index(license_assignment))
        self.assertNotIn("params.megflow.datasets.docker_input.report", config)
        self.assertNotIn("params.megflow.datasets.docker_input.anatomy.t1_input_type =", config)
        self.assertNotIn("params.megflow.datasets.docker_input.anatomy.t1_dicom_series_glob =", config)
        self.assertIn("-resume", self.nextflow_args.read_text(encoding="utf-8").splitlines())

    def test_single_dataset_launches_nextflow_from_output_launch_directory(self):
        input_dir = self.root / "single-launch-input"
        output_dir = self.root / "single-launch-output"
        input_dir.mkdir()

        result = self._run(
            "--config",
            str(self.base_config),
            "--input",
            str(input_dir),
            "--output",
            str(output_dir),
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        launch_dir = output_dir / ".nextflow-launch"
        self.assertEqual(
            Path(self.nextflow_pwd.read_text(encoding="utf-8").strip()),
            launch_dir,
        )
        self.assertTrue((launch_dir / ".nextflow").is_dir())

    def test_config_controls_report_anatomy_and_default_t1_dir(self):
        input_dir = self.root / "single-input"
        output_dir = self.root / "single-output"
        input_dir.mkdir()

        result = self._run(
            "--config",
            str(self.base_config),
            "--input",
            str(input_dir),
            "--output",
            str(output_dir),
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        config = (output_dir / "nextflow.config").read_text(encoding="utf-8")
        self.assertIn('t1_dir: "/configured/t1"', config)
        self.assertIn('method: "pseudomri"', config)
        self.assertIn('static_task_log_mode: "none"', config)
        self.assertIn("static_artifact_overview_duration: 45.0", config)
        self.assertNotIn("params.megflow.datasets.docker_input.t1_dir =", config)
        self.assertNotIn(
            "params.megflow.datasets.docker_input.anatomy.method =", config
        )
        self.assertNotIn("params.megflow.datasets.docker_input.anatomy.fs_license_file =", config)
        self.assertNotIn("params.megflow.datasets.docker_input.report", config)

    def test_corpus_options_generate_shared_defaults_and_preserve_profiles(self):
        input_dir = self.root / "corpus-input"
        output_dir = self.root / "corpus-output"
        fs_root = self.root / "corpus-fs"
        for dataset in ("DatasetA", "DatasetB"):
            (input_dir / dataset).mkdir(parents=True)

        result = self._run(
            "--config",
            str(self.base_config),
            "--input",
            str(input_dir),
            "--output",
            str(output_dir),
            "--corpus",
            "--steps",
            "all",
            "--anat-method",
            "deepprep",
            "--fs_subjects_dir",
            str(fs_root),
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        config = (output_dir / "nextflow.config").read_text(encoding="utf-8")
        expected_lines = (
            f'params.megflow.corpus_root = "{input_dir}"',
            f'params.megflow.fs_subjects_root = "{fs_root}"',
            'params.megflow.defaults.steps = "all"',
            'params.megflow.defaults.anatomy.method = "deepprep"',
            'params.megflow.datasets.docker_input.dataset_dir = ""',
            'NamedDataset: [steps: "meg_epochs"]',
        )
        for line in expected_lines:
            self.assertIn(line, config)
        self.assertNotIn("params.megflow.defaults.anatomy.fs_license_file =", config)
        self.assertNotIn("params.megflow.defaults.report", config)

    def test_corpus_launches_nextflow_from_output_launch_directory(self):
        input_dir = self.root / "corpus-launch-input"
        output_dir = self.root / "corpus-launch-output"
        fs_root = self.root / "corpus-launch-fs"
        (input_dir / "DatasetA").mkdir(parents=True)

        result = self._run(
            "--config",
            str(self.base_config),
            "--input",
            str(input_dir),
            "--output",
            str(output_dir),
            "--corpus",
            "--fs_subjects_dir",
            str(fs_root),
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        launch_dir = output_dir / ".nextflow-launch"
        self.assertEqual(
            Path(self.nextflow_pwd.read_text(encoding="utf-8").strip()),
            launch_dir,
        )
        self.assertTrue((launch_dir / ".nextflow").is_dir())

    def test_view_report_starts_streamlit_without_nextflow(self):
        output_dir = self.root / "report-output"
        fs_dir = self.root / "report-fs"
        output_dir.mkdir()
        fs_dir.mkdir()

        result = self._run(
            "--view-report",
            "--output",
            str(output_dir),
            "--fs_subjects_dir",
            str(fs_dir),
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertFalse(self.nextflow_args.exists())
        self.assertIn("run", self.streamlit_args.read_text(encoding="utf-8").splitlines())
        environment = self.streamlit_env.read_text(encoding="utf-8")
        self.assertIn(f"DATASET_REPORT_PATH={output_dir}", environment)
        self.assertIn(f"SUBJECTS_DIR={fs_dir}", environment)

    def test_corpus_rejects_single_dataset_t1_dir(self):
        input_dir = self.root / "corpus-input"
        output_dir = self.root / "corpus-output"
        t1_dir = self.root / "corpus-t1"
        fs_root = self.root / "corpus-fs"
        (input_dir / "DatasetA").mkdir(parents=True)
        t1_dir.mkdir()

        result = self._run(
            "--config",
            str(self.base_config),
            "--input",
            str(input_dir),
            "--output",
            str(output_dir),
            "--corpus",
            "--fs_subjects_dir",
            str(fs_root),
            "--t1_dir",
            str(t1_dir),
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--t1_dir is only valid for a single-dataset run", result.stdout)
        self.assertFalse(self.nextflow_args.exists())

    def test_anat_method_rejects_unknown_value(self):
        input_dir = self.root / "invalid-anat-input"
        output_dir = self.root / "invalid-anat-output"
        input_dir.mkdir()

        result = self._run(
            "--config",
            str(self.base_config),
            "--input",
            str(input_dir),
            "--output",
            str(output_dir),
            "--anat-method",
            "invalid",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "Error: --anat-method must be one of: "
            "freesurfer, deepprep, pseudomri",
            result.stdout,
        )
        self.assertFalse(self.nextflow_args.exists())

    def test_removed_processing_options_are_rejected(self):
        removed_options = (
            ("--static_task_log_mode", "failed"),
            ("--task-log-mode", "failed"),
            ("--static_artifact_overview_duration", "30.5"),
            ("--artifact-overview-duration", "30.5"),
            ("--t1_input_type", "dicom"),
            ("--t1_dicom_series_glob", "*T1*"),
            ("--t1-dicom-series-glob", "*T1*"),
            ("--anatomy_preprocess_method", "freesurfer"),
            ("--anatomy-preprocess-method", "freesurfer"),
        )

        for option, value in removed_options:
            with self.subTest(option=option):
                result = self._run(option, value)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"Unknown parameter: {option}", result.stdout)


if __name__ == "__main__":
    unittest.main()
