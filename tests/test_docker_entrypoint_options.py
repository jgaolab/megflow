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
        self.streamlit_args = self.root / "streamlit-args.txt"
        self.streamlit_env = self.root / "streamlit-env.txt"

        self._write_executable(
            self.fake_bin / "nextflow",
            '#!/bin/bash\nprintf "%s\\n" "$@" > "$MEGFLOW_TEST_NEXTFLOW_ARGS"\n',
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
            'params.megflow = [defaults: [steps: "meg_all", anatomy: [is_bids: false]], '
            'datasets: [docker_input: [name: "docker_input"], '
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
            "--static_task_log_mode",
            "--static_artifact_overview_duration",
            "--fs_license_file",
            "--fs_subjects_dir",
            "--t1_dir",
            "--t1_input_type",
            "--t1_dicom_series_glob",
            "--anatomy_preprocess_method",
            "--resume",
        )
        for option in expected_options:
            self.assertIn(option, result.stdout)
            self.assertIn(option, docs)
        self.assertIn("Single-dataset structural MRI input root", result.stdout)
        self.assertIn("nifti|dicom for non-BIDS FreeSurfer input", result.stdout)
        self.assertIn("Quoted relative glob", result.stdout)
        self.assertIn("single-dataset mode", docs)
        self.assertIn("non-BIDS FreeSurfer", docs)
        self.assertIn("quote the value", docs)

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
            "--t1_input_type",
            "dicom",
            "--t1_dicom_series_glob",
            "*T1*",
            "--anatomy_preprocess_method",
            "freesurfer",
            "--static_task_log_mode",
            "failed",
            "--static_artifact_overview_duration",
            "30.5",
            "--resume",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        config = (output_dir / "nextflow.config").read_text(encoding="utf-8")
        expected_lines = (
            f'megflowRuntimeDockerInput.dataset_dir = "{input_dir}"',
            f'megflowRuntimeDockerInput.output_dir = "{output_dir}"',
            f'megflowRuntimeDockerInput.t1_dir = "{t1_dir}"',
            f'megflowRuntimeDockerInput.fs_subjects_dir = "{fs_dir}"',
            'megflowRuntimeDockerInput.steps = "anatomy"',
            'megflowRuntimeAnatomy.method = "freesurfer"',
            'megflowRuntimeAnatomy.t1_input_type = "dicom"',
            'megflowRuntimeAnatomy.t1_dicom_series_glob = "*T1*"',
            f'megflowRuntimeAnatomy.fs_license_file = "{license_file}"',
            'megflowRuntimeReport.static_task_log_mode = "failed"',
            "megflowRuntimeReport.static_artifact_overview_duration = 30.5",
        )
        for line in expected_lines:
            self.assertIn(line, config)
        self.assertIn("-resume", self.nextflow_args.read_text(encoding="utf-8").splitlines())

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
            "--t1_input_type",
            "dicom",
            "--t1_dicom_series_glob",
            "*mprage*",
            "--anatomy_preprocess_method",
            "freesurfer",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        config = (output_dir / "nextflow.config").read_text(encoding="utf-8")
        expected_lines = (
            f'params.megflow.corpus_root = "{input_dir}"',
            f'params.megflow.fs_subjects_root = "{fs_root}"',
            'megflowRuntimeDefaults.steps = "all"',
            'megflowRuntimeAnatomy.method = "freesurfer"',
            'megflowRuntimeAnatomy.t1_input_type = "dicom"',
            'megflowRuntimeAnatomy.t1_dicom_series_glob = "*mprage*"',
            'megflowRuntimeCorpusDatasets.remove("docker_input")',
            'NamedDataset: [steps: "meg_epochs"]',
        )
        for line in expected_lines:
            self.assertIn(line, config)

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

    def test_invalid_t1_input_type_is_rejected(self):
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
            "--t1_input_type",
            "not-a-real-type",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected nifti or dicom", result.stdout)
        self.assertFalse(self.nextflow_args.exists())

    def test_absolute_t1_dicom_series_glob_is_rejected(self):
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
            "--t1_dicom_series_glob",
            "/absolute/*T1*",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be a relative glob", result.stdout)
        self.assertFalse(self.nextflow_args.exists())


if __name__ == "__main__":
    unittest.main()
