import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKER_RUNNER = REPO_ROOT / "nextflow" / "run_for_docker.sh"
INSTALLATION_DOC = REPO_ROOT / "docs" / "source" / "quickstart" / "installation.rst"


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
            'RUN_CONFIG_FILE="/program/nextflow/run_nextflow.config"',
            f'RUN_CONFIG_FILE="{self.run_config}"',
        ).replace(
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

    def test_help_and_installation_list_the_same_entrypoint_options(self):
        result = self._run("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        docs = INSTALLATION_DOC.read_text(encoding="utf-8")
        expected_options = (
            "--config",
            "--input",
            "--output",
            "--steps",
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
        self.assertIn(anatomy_init, config)
        self.assertLess(config.index(anatomy_init), config.index(license_assignment))
        self.assertNotIn("params.megflow.datasets.docker_input.report", config)
        self.assertNotIn("params.megflow.datasets.docker_input.anatomy.method =", config)
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
            "--fs_subjects_dir",
            str(fs_root),
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        config = (output_dir / "nextflow.config").read_text(encoding="utf-8")
        expected_lines = (
            f'params.megflow.corpus_root = "{input_dir}"',
            f'params.megflow.fs_subjects_root = "{fs_root}"',
            'params.megflow.defaults.steps = "all"',
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
