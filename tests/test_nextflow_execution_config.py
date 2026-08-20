import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Optional, Set


REPO_ROOT = Path(__file__).resolve().parents[1]
PIPELINE = REPO_ROOT / "nextflow" / "megflow.nf"
SOURCE_CONFIG = REPO_ROOT / "nextflow" / "nextflow.config"
DOCKER_CONFIG = REPO_ROOT / "nextflow" / "nextflow_for_docker.config"
FULL_WORKFLOW_CONFIG = REPO_ROOT / "nextflow" / "full_workflow.config"
FULL_WORKFLOW_DOC = REPO_ROOT / "docs" / "source" / "tutorial" / "full_workflow.rst"
QUICKSTART_DOC = REPO_ROOT / "docs" / "source" / "quickstart" / "quick_guide.rst"
DEEPREJECT_DOC = REPO_ROOT / "docs" / "source" / "reference" / "deepreject.rst"
DOCKER_RUNNER = REPO_ROOT / "nextflow" / "run_for_docker.sh"
DOCKERFILE = REPO_ROOT / "megflow.Dockerfile"
INTERACTIVE_APP = REPO_ROOT / "megflow" / "reports" / "reports.py"
INTERACTIVE_NEXTFLOW = REPO_ROOT / "megflow" / "reports" / "reports" / "nextflow.py"
INTERACTIVE_CONFIG = REPO_ROOT / "megflow" / "reports" / "reports" / "nx_config_online.py"
MULTI_DATASET_DEMO = REPO_ROOT / "nextflow" / "nextflow_multi_dataset_demo.config"
CORPUS_EXAMPLE = REPO_ROOT / "nextflow" / "nextflow_corpus.config"
OPM_COG_TASK_OVERRIDE_EXAMPLE = REPO_ROOT / "nextflow" / "nextflow_opm_cog_task_overrides_example.config"
MAXWELL_TSSS_EXAMPLE = REPO_ROOT / "nextflow" / "nextflow_maxwell_tsss_example.config"
PSEUDOMRI_DOCKER_OVERLAY = REPO_ROOT / "nextflow" / "nextflow_pseudomri_docker.config"
MULTI_DATASET_SOURCE_RUNNER = (
    REPO_ROOT / "examples" / "run_scripts" / "corpus_source.sh"
)
PROFILE_INTEGRATION_TEST = REPO_ROOT / "tests" / "test_nextflow_profile_integration.py"
VALIDATION_RUNNER = REPO_ROOT / "scripts" / "validation" / "run_validation.sh"
VALIDATION_UNITTEST_GATE = REPO_ROOT / "scripts" / "validation" / "run_unittest_gate.py"
WINDOWS_INSTALL_VALIDATOR = REPO_ROOT / "scripts" / "validation" / "validate_windows_installer.py"
VALIDATION_REQUIREMENTS = REPO_ROOT / "requirements_validation.txt"
DOCUMENTATION_REQUIREMENTS = REPO_ROOT / "requirements_doc.txt"
VALIDATION_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "validation.yml"
SHIPPED_SOURCE_EXAMPLES = (
    (MULTI_DATASET_DEMO, "corpus_static_html_report"),
    (CORPUS_EXAMPLE, "corpus_static_html_report"),
    (OPM_COG_TASK_OVERRIDE_EXAMPLE, "static_html_report"),
    (MAXWELL_TSSS_EXAMPLE, "static_html_report"),
)
DOCKER_OVERLAY_EXAMPLES = (
    REPO_ROOT / "examples" / "megflow" / "nextflow_for_cog.config",
    REPO_ROOT / "examples" / "megflow" / "nextflow_for_cog-anat.config",
)


def process_names() -> set[str]:
    return set(re.findall(r"^process\s+([A-Za-z_]\w*)\s*\{", PIPELINE.read_text(encoding="utf-8"), re.MULTILINE))


def process_selectors(config: Path) -> list[str]:
    text = config.read_text(encoding="utf-8")
    pattern = re.compile(r"withName:\s*(?:'([^']+)'|\"([^\"]+)\"|([A-Za-z_]\w*))")
    return [next(value for value in match.groups() if value) for match in pattern.finditer(text)]


def strip_groovy_strings_and_comments(line: str) -> str:
    code = line.split("//", 1)[0]
    return re.sub(r"""'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*" """.strip(), "", code)


def named_config_block(text: str, block_name: str) -> str:
    lines = text.splitlines()
    start_pattern = re.compile(rf"^\s*{re.escape(block_name)}\s*\{{\s*$")
    start = next(
        (index for index, line in enumerate(lines) if start_pattern.match(line)),
        None,
    )
    if start is None:
        raise AssertionError(f"Missing config block: {block_name}")

    depth = 1
    body = []
    for line in lines[start + 1 :]:
        structural = strip_groovy_strings_and_comments(line)
        depth += structural.count("{")
        depth -= structural.count("}")
        if depth == 0:
            return "\n".join(body)
        body.append(line)
    raise AssertionError(f"Unterminated config block: {block_name}")


def config_assignments(block: str) -> dict[str, str]:
    assignments = {}
    stack = []
    block_pattern = re.compile(r"^\s*(\$?[A-Za-z_]\w*)\s*\{\s*$")
    assignment_pattern = re.compile(
        r"^\s*([A-Za-z_]\w*)\s*=\s*(.*?)\s*(?://.*)?$"
    )
    for line in block.splitlines():
        structural = strip_groovy_strings_and_comments(line).strip()
        block_match = block_pattern.match(structural)
        if block_match:
            stack.append(block_match.group(1))
            continue
        if structural == "}":
            if stack:
                stack.pop()
            continue
        assignment_match = assignment_pattern.match(line)
        if assignment_match:
            key, value = assignment_match.groups()
            assignments[".".join((*stack, key))] = value
    return assignments


def normalized_config_block(
    text: str,
    block_name: str,
    omitted_assignments: Optional[Set[str]] = None,
) -> list[str]:
    omitted_assignments = omitted_assignments or set()
    normalized = []
    for line in named_config_block(text, block_name).splitlines():
        active = line.split("//", 1)[0].strip()
        if not active:
            continue
        assignment = re.match(r"^([A-Za-z_]\w*)\s*=", active)
        if assignment and assignment.group(1) in omitted_assignments:
            continue
        normalized.append(active)
    return normalized


def active_groovy_code(text: str) -> str:
    return "\n".join(line.split("//", 1)[0] for line in text.splitlines())


def top_level_config_blocks(text: str) -> list[str]:
    blocks = []
    depth = 0
    block_pattern = re.compile(r"^\s*([A-Za-z_]\w*)\s*\{\s*$")
    for line in active_groovy_code(text).splitlines():
        structural = strip_groovy_strings_and_comments(line)
        if depth == 0:
            block_match = block_pattern.match(structural)
            if block_match:
                blocks.append(block_match.group(1))
        depth += structural.count("{")
        depth -= structural.count("}")
    return blocks


def available_configs() -> tuple[Path, ...]:
    return (SOURCE_CONFIG, DOCKER_CONFIG) if DOCKER_CONFIG.is_file() else (SOURCE_CONFIG,)


def packaged_docker_config() -> Path:
    return DOCKER_CONFIG if DOCKER_CONFIG.is_file() else SOURCE_CONFIG


def packaged_docker_runner() -> Path:
    return DOCKER_RUNNER if DOCKER_RUNNER.is_file() else REPO_ROOT / "nextflow" / "run.sh"


def workflow_job(workflow: str, job_name: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(job_name)}:\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)",
        workflow,
    )
    return "" if match is None else match.group(1)


class NextflowExecutionConfigTests(unittest.TestCase):
    def test_source_and_docker_public_defaults_are_consistent(self):
        source_defaults = normalized_config_block(
            SOURCE_CONFIG.read_text(encoding="utf-8"),
            "defaults",
            omitted_assignments={"pseudomri_template_dir"},
        )
        docker_defaults = normalized_config_block(
            DOCKER_CONFIG.read_text(encoding="utf-8"),
            "defaults",
            omitted_assignments={"pseudomri_template_dir"},
        )
        self.assertEqual(source_defaults, docker_defaults)

    def test_unified_qc_threshold_defaults_are_exact(self):
        expected = {
            "megqc.alarm_score": "70.0",
            "report.coreg_max_threshold": "20.0",
            "report.epoch_reject_rate_threshold": "0.90",
        }
        for config in (SOURCE_CONFIG, DOCKER_CONFIG, FULL_WORKFLOW_CONFIG):
            assignments = config_assignments(
                named_config_block(config.read_text(encoding="utf-8"), "defaults")
            )
            with self.subTest(config=config.name):
                self.assertEqual(
                    {key: assignments.get(key) for key in expected},
                    expected,
                )

    def test_public_docs_use_the_unified_qc_threshold_defaults(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        qc_metrics = (
            REPO_ROOT / "docs" / "source" / "reference" / "qc_metrics.rst"
        ).read_text(encoding="utf-8")
        self.assertIn("alarm_score = 70.0", readme)
        for obsolete in (
            "``60 / 70``",
            "``coreg_max_threshold = 10.0 / 20.0``",
            "``epoch_reject_rate_threshold = 0.30 / 0.90``",
        ):
            with self.subTest(obsolete=obsolete):
                self.assertNotIn(obsolete, qc_metrics)
        for current in (
            "``70.0`` through ``megqc.alarm_score``",
            "``coreg_max_threshold = 20.0`` mm",
            "``epoch_reject_rate_threshold = 0.90``",
        ):
            with self.subTest(current=current):
                self.assertIn(current, qc_metrics)

    def test_full_workflow_overlay_covers_every_public_default(self):
        self.assertTrue(FULL_WORKFLOW_CONFIG.is_file())
        docker_defaults = normalized_config_block(
            DOCKER_CONFIG.read_text(encoding="utf-8"),
            "defaults",
            omitted_assignments={"pseudomri_template_dir"},
        )
        overlay_defaults = normalized_config_block(
            FULL_WORKFLOW_CONFIG.read_text(encoding="utf-8"),
            "defaults",
        )
        self.assertEqual(overlay_defaults, docker_defaults)

    def test_full_workflow_overlay_excludes_environment_and_failure_internals(self):
        self.assertTrue(FULL_WORKFLOW_CONFIG.is_file())
        text = FULL_WORKFLOW_CONFIG.read_text(encoding="utf-8")
        active = active_groovy_code(text)
        self.assertEqual(top_level_config_blocks(text), ["params"])
        forbidden_patterns = (
            r"(?m)^\s*(?:code_dir|output_dir|report_scope|corpus_root|workDir)\s*=",
            r"(?m)^\s*(?:log|timeline|trace|workflow|profiles|docker)(?:\.|\s*\{)",
            r"(?m)^\s*report\.",
            r"(?m)^\s*datasets\s*\{",
            r"\berrorStrategy\b",
            r"\bexecutor\b",
        )
        for pattern in forbidden_patterns:
            with self.subTest(pattern=pattern):
                self.assertNotRegex(active, pattern)

    def test_full_workflow_documentation_describes_the_overlay_contract(self):
        text = FULL_WORKFLOW_DOC.read_text(encoding="utf-8")
        compact = " ".join(text.split())
        expected = (
            ":doc:`Quickstart <../quickstart/quick_guide>`",
            ":download:`Download full_workflow.config <../../../nextflow/full_workflow.config>`",
            "``defaults -> dataset -> recording``",
            "--config /config/full_workflow.config",
            "-c /path/to/full_workflow.config",
        )
        for fragment in expected:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)
        self.assertIn(
            "Do not use Nextflow ``-C`` with it, and do not mount it over "
            "``/program/nextflow/nextflow.config``",
            compact,
        )

        quickstart = QUICKSTART_DOC.read_text(encoding="utf-8")
        self.assertIn(
            ":download:`complete user overlay "
            "<../../../nextflow/full_workflow.config>`",
            quickstart,
        )

    def test_profile_integration_uses_a_test_local_nextflow_launch_directory(self):
        text = PROFILE_INTEGRATION_TEST.read_text(encoding="utf-8")
        self.assertIn("cwd=output_dir", text)
        self.assertNotIn("cwd=REPO_ROOT", text)

    def test_validation_entrypoints_share_explicit_non_skipping_gates(self):
        self.assertTrue(VALIDATION_RUNNER.is_file())
        self.assertTrue(VALIDATION_UNITTEST_GATE.is_file())
        self.assertTrue(VALIDATION_REQUIREMENTS.is_file())
        self.assertTrue(VALIDATION_WORKFLOW.is_file())

        runner = VALIDATION_RUNNER.read_text(encoding="utf-8")
        for mode in ("routing-ci", "routing", "scientific", "all"):
            self.assertIn(f"{mode})", runner)
        self.assertIn("MEGFLOW_NEXTFLOW", runner)
        self.assertIn("command -v python3", runner)
        self.assertIn(
            '${ROOT_DIR}:${ROOT_DIR}/megflow:${ROOT_DIR}/tests',
            runner,
        )
        self.assertIn("test_nextflow_profile_integration", runner)
        self.assertIn("test_validation_runner", runner)
        self.assertIn("test_mne_config_contract", runner)
        self.assertIn("sphinx_autodoc_typehints", runner)
        self.assertIn("install requirements_doc.txt", runner)
        unittest_gate = VALIDATION_UNITTEST_GATE.read_text(encoding="utf-8")
        self.assertIn("Unexpected skipped tests", unittest_gate)

        requirements = VALIDATION_REQUIREMENTS.read_text(encoding="utf-8")
        for pinned_dependency in (
            "h5py==3.12.1",
            "scikit-learn==1.6.1",
            "sleepecg==0.5.5",
            "Sphinx==7.3.7",
        ):
            self.assertIn(pinned_dependency, requirements)

        workflow = VALIDATION_WORKFLOW.read_text(encoding="utf-8")
        self.assertRegex(workflow, r"(?m)^  push:\s*$")
        self.assertNotIn("branches: [main, master]", workflow)
        self.assertIn("run_validation.sh routing-ci", workflow)
        self.assertIn("run_validation.sh scientific", workflow)
        self.assertIn("uses: actions/checkout@v6", workflow)
        self.assertIn("uses: actions/setup-java@v5", workflow)
        self.assertIn("uses: actions/setup-python@v6", workflow)
        self.assertIn(
            "python -m pip install --no-deps -e ./megflow/tools/osl-ephys",
            workflow,
        )

    def test_ci_routing_gate_is_explicit_and_keeps_full_matrices_local(self):
        runner = VALIDATION_RUNNER.read_text(encoding="utf-8")
        ci_body = runner.split("run_routing_ci() {", 1)[1].split("\n}", 1)[0]
        full_body = runner.split("run_routing() {", 1)[1].split("\n}", 1)[0]

        expected_ci_contracts = (
            "test_documentation_config_examples.DocumentationConfigExamplesTests",
            "test_all_documented_groovy_blocks_parse_together",
            "test_quality_score_nextflow_contract",
            "test_anatomy_step_matrix_schedules_only_selected_method",
            "test_with_anatomy_modifier_stops_at_requested_meg_stage",
            "test_recording_level_steps_reduce_the_dataset_stage",
            "test_dataset_and_recording_overrides_do_not_cross_route",
            "test_mne_and_osl_kwargs_survive_default_dataset_recording_merges",
            "test_raw_covariance_pairs_with_the_correct_dataset_noise_recording",
            "test_lcmv_data_covariance_is_conditional_and_uses_exact_source_input",
            "test_missing_raw_covariance_pair_fails_instead_of_silently_skipping_source",
            "test_resume_invalidates_event_dependent_lineage_and_new_inputs",
            "test_strict_processing_failure_terminates_before_report_submission",
            "test_live_trace_survives_dataset_and_corpus_report_rebuild",
        )
        for contract in expected_ci_contracts:
            self.assertIn(contract, ci_body)

        self.assertNotRegex(
            ci_body,
            r"(?m)^\s+test_nextflow_profile_integration\s*\\?$",
        )
        self.assertNotRegex(
            ci_body,
            r"(?m)^\s+test_documentation_config_examples\s*\\?$",
        )
        self.assertRegex(
            full_body,
            r"(?m)^\s+test_nextflow_profile_integration\s*\\?$",
        )
        self.assertRegex(
            full_body,
            r"(?m)^\s+test_documentation_config_examples\s*\\?$",
        )
        self.assertIn("run_timed_unittest_gate", runner)
        self.assertIn("parse_shipped_configs", ci_body)
        self.assertIn("parse_shipped_configs", full_body)

    def test_installer_validation_jobs_are_native_and_nonduplicated(self):
        workflow = VALIDATION_WORKFLOW.read_text(encoding="utf-8")
        runner = VALIDATION_RUNNER.read_text(encoding="utf-8")
        ci_body = runner.split("run_routing_ci() {", 1)[1].split("\n}", 1)[0]
        full_body = runner.split("run_routing() {", 1)[1].split("\n}", 1)[0]

        linux_job = workflow_job(workflow, "linux-installer")
        macos_job = workflow_job(workflow, "macos-installer")
        windows_job = workflow_job(workflow, "windows-installer")

        self.assertIn("runs-on: ubuntu-latest", linux_job)
        self.assertIn("test_install_scripts.InstallerMetadataContractTests", linux_job)
        self.assertIn("test_install_scripts.LinuxInstallerContractTests", linux_job)

        self.assertIn("runs-on: macos-latest", macos_job)
        self.assertIn("test_install_scripts.MacOSInstallerContractTests", macos_job)

        self.assertIn("runs-on: windows-latest", windows_job)
        self.assertIn("validate_windows_installer.py", windows_job)
        self.assertIn("test_install_scripts.WindowsInstallerContractTests", windows_job)

        self.assertNotRegex(
            ci_body,
            r"(?m)^\s+test_install_scripts\s*\\?$",
        )
        self.assertRegex(
            full_body,
            r"(?m)^\s+test_install_scripts\s*\\?$",
        )

    def test_validation_workflow_local_inputs_are_tracked(self):
        required_paths = (
            ".github/workflows/validation.yml",
            "megflow.Dockerfile",
            "nextflow/nextflow.config",
            "nextflow/nextflow_for_docker.config",
            "nextflow/run_for_docker.sh",
            "nextflow/nextflow_multi_dataset_demo.config",
            "nextflow/nextflow_corpus.config",
            "nextflow/nextflow_opm_cog_task_overrides_example.config",
            "nextflow/nextflow_maxwell_tsss_example.config",
            "examples/megflow/nextflow_for_cog.config",
            "examples/megflow/nextflow_for_cog-anat.config",
            "requirements_doc.txt",
            "requirements_validation.txt",
            "scripts/validation/run_unittest_gate.py",
            "scripts/validation/run_validation.sh",
            "scripts/validation/validate_windows_installer.py",
        )
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", *required_paths],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"Validation workflow inputs must be tracked by Git:\n{result.stderr}",
        )

    def test_validation_gates_cover_every_test_module_and_windows_parser(self):
        runner = VALIDATION_RUNNER.read_text(encoding="utf-8")
        tracked_tests = subprocess.run(
            ["git", "ls-files", "tests/test_*.py"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        test_modules = {
            Path(path).stem
            for path in tracked_tests.stdout.splitlines()
        }
        omitted = sorted(module for module in test_modules if module not in runner)
        self.assertEqual(omitted, [])

        self.assertTrue(WINDOWS_INSTALL_VALIDATOR.is_file())
        workflow = VALIDATION_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("runs-on: windows-latest", workflow)
        self.assertIn("validate_windows_installer.py", workflow)

    def test_documentation_job_uses_a_minimal_pinned_environment(self):
        requirements = [
            line.strip()
            for line in DOCUMENTATION_REQUIREMENTS.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(
            requirements,
            [
                "Jinja2==3.1.3",
                "pydata-sphinx-theme==0.15.4",
                "Sphinx==7.3.7",
                "sphinx-autodoc-typehints==2.3.0",
                "sphinx-book-theme==1.1.4",
                "sphinx-click==6.0.0",
                "sphinx-copybutton==0.5.2",
                "sphinx_design==0.6.1",
            ],
        )

        workflow = VALIDATION_WORKFLOW.read_text(encoding="utf-8")
        self.assertGreaterEqual(
            workflow.count("python -m pip install --upgrade pip"),
            2,
        )
        routing_job = workflow.split("  nextflow-routing:", 1)[1].split(
            "  scientific-contracts:", 1
        )[0]
        self.assertIn("timeout-minutes: 15", routing_job)

    def test_every_process_selector_matches_current_pipeline(self):
        names = process_names()
        self.assertTrue(names)
        for config in available_configs():
            unmatched = [selector for selector in process_selectors(config) if not any(re.fullmatch(selector, name) for name in names)]
            self.assertEqual(unmatched, [], config.name)

    def test_observability_outputs_are_enabled_and_scoped_to_output_dir(self):
        for config in available_configs():
            text = config.read_text(encoding="utf-8")
            self.assertIn('report_scope = "dataset"', text)
            self.assertIn("params.megflow.report_scope == 'corpus'", text)
            self.assertIn("'corpus_static_html_report'", text)
            self.assertIn("'static_html_report'", text)
            self.assertIn('/nextflow/nextflow.log"', text)
            self.assertIn('/nextflow/report.html"', text)
            self.assertIn('/nextflow/timeline.html"', text)
            self.assertIn('/nextflow/trace.txt"', text)
            self.assertGreaterEqual(text.count("enabled = true"), 3)

    def test_base_configs_use_declarative_v2_syntax(self):
        for config in available_configs():
            text = config.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"(?m)^\s*def\s+", config.name)
            self.assertNotRegex(text, r"(?m)^\s*if\s*\(", config.name)

    def test_local_execution_defaults_are_identical_and_public(self):
        expected = {
            "local_cpus": '"auto"',
            "local_memory": '"auto"',
            "local_max_tasks": '"auto"',
        }
        for config in (SOURCE_CONFIG, DOCKER_CONFIG, FULL_WORKFLOW_CONFIG):
            assignments = config_assignments(
                named_config_block(config.read_text(encoding="utf-8"), "execution")
            )
            with self.subTest(config=config.name):
                self.assertEqual(assignments, expected)

    def test_local_executor_maps_each_fixed_resource_override_independently(self):
        expected = {
            "$local.cpus": (
                '"${-> params.megflow.execution.local_cpus == \'auto\' ? '
                "Runtime.runtime.availableProcessors() : "
                'params.megflow.execution.local_cpus}"'
            ),
            "$local.memory": (
                '"${-> params.megflow.execution.local_memory == \'auto\' ? '
                "java.lang.management.ManagementFactory.operatingSystemMXBean."
                "totalPhysicalMemorySize : params.megflow.execution.local_memory}"
                '"'
            ),
            "$local.queueSize": (
                '"${-> params.megflow.execution.local_max_tasks == \'auto\' ? '
                "Runtime.runtime.availableProcessors() : "
                'params.megflow.execution.local_max_tasks}"'
            ),
        }
        for config in available_configs():
            assignments = config_assignments(
                named_config_block(config.read_text(encoding="utf-8"), "executor")
            )
            with self.subTest(config=config.name):
                self.assertEqual(
                    {key: assignments.get(key) for key in expected},
                    expected,
                )

    def test_fixed_additive_overlay_resolves_local_executor_values(self):
        nextflow = os.environ.get("MEGFLOW_NEXTFLOW") or shutil.which("nextflow")
        self.assertIsNotNone(
            nextflow,
            "Nextflow 24.10.3 is required; set MEGFLOW_NEXTFLOW to its executable",
        )
        version = subprocess.run(
            [nextflow, "-version"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertIn("version 24.10.3", version.stdout + version.stderr)

        with tempfile.TemporaryDirectory() as tmpdir:
            overlay = Path(tmpdir) / "fixed-local.config"
            overlay.write_text(
                """
params {
    megflow {
        execution {
            local_cpus = 16
            local_memory = "48 GB"
            local_max_tasks = 3
        }
    }
}
""".strip()
                + "\n",
                encoding="utf-8",
            )
            expected = (
                "executor.$local.cpus = '16'",
                "executor.$local.memory = '48 GB'",
                "executor.$local.queueSize = '3'",
            )
            for base in (SOURCE_CONFIG, DOCKER_CONFIG):
                composition = Path(tmpdir) / f"composed-{base.name}"
                composition.write_text(
                    f'includeConfig "{base.as_posix()}"\n'
                    f'includeConfig "{overlay.as_posix()}"\n',
                    encoding="utf-8",
                )
                result = subprocess.run(
                    [
                        nextflow,
                        "-C",
                        str(composition),
                        "config",
                        str(PIPELINE),
                        "-o",
                        "flat",
                    ],
                    cwd=REPO_ROOT,
                    env={**os.environ, "NXF_SYNTAX_PARSER": "v1"},
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
                with self.subTest(base=base.name):
                    self.assertEqual(result.returncode, 0, result.stderr)
                    for line in expected:
                        self.assertTrue(
                            line in result.stdout,
                            f"{base.name}: missing resolved flat-config line {line}",
                        )

    def test_detect_artifacts_injects_task_cpu_budget(self):
        pipeline = PIPELINE.read_text(encoding="utf-8")
        process_text = pipeline.split("process detect_artifacts {", 1)[1].split(
            "process run_ica {", 1
        )[0]
        self.assertIn(
            "artifact_config = new LinkedHashMap(moduleConfig(effective_config, 'artifacts'))",
            process_text,
        )
        self.assertIn("artifact_config.runtime_cpus = task.cpus", process_text)
        self.assertIn("artifact_config_json = configJson(artifact_config)", process_text)
        self.assertIn("--config '${artifact_config_json}'", process_text)

    def test_public_artifact_defaults_use_runtime_aware_parallelism(self):
        configs = (
            SOURCE_CONFIG,
            DOCKER_CONFIG,
            FULL_WORKFLOW_CONFIG,
            CORPUS_EXAMPLE,
            MULTI_DATASET_DEMO,
        )
        for config in configs:
            text = config.read_text(encoding="utf-8")
            with self.subTest(config=config.name):
                self.assertRegex(text, r'(?m)^\s*fold_workers\s*=\s*"auto"\s*$')
                self.assertRegex(text, r'(?m)^\s*cpu_threads\s*=\s*"auto"\s*$')
                self.assertRegex(
                    text,
                    r'(?m)^\s*artifact_image_n_jobs\s*=\s*"auto"\s*$',
                )

    def test_public_configs_show_the_model_validated_deepreject_preproc_recipe(self):
        configs = (
            SOURCE_CONFIG,
            DOCKER_CONFIG,
            FULL_WORKFLOW_CONFIG,
            CORPUS_EXAMPLE,
            MULTI_DATASET_DEMO,
        )
        expected_steps = (
            '[filter: [l_freq: 1.0, h_freq: 100.0, method: "iir", '
            'iir_params: [order: 5, ftype: "butter"]]]',
            '[notch_filter: [freqs: 50]]',
            '[resample: [sfreq: 250]]',
        )
        for config in configs:
            text = config.read_text(encoding="utf-8")
            deepreject_defaults = text.split("deepreject {", 1)[1].split(
                "find_bad_channels {", 1
            )[0]
            with self.subTest(config=config.name):
                self.assertIn("preproc = [", deepreject_defaults)
                positions = [deepreject_defaults.index(step) for step in expected_steps]
                self.assertEqual(positions, sorted(positions))
                for legacy_field in (
                    "filter_l_freq",
                    "filter_h_freq",
                    "resample_sfreq",
                ):
                    self.assertNotIn(legacy_field, text)

    def test_public_docs_warn_when_departing_from_deepreject_default(self):
        documents = (
            REPO_ROOT / "README.md",
            DEEPREJECT_DOC,
            QUICKSTART_DOC,
        )
        for document in documents:
            text = document.read_text(encoding="utf-8")
            compact = " ".join(text.split()).lower()
            with self.subTest(document=document.name):
                self.assertIn("**warning", compact)
                self.assertIn("model-validated default", compact)
                self.assertIn("cannot recreate unavailable source information", compact)
                for legacy_field in (
                    "filter_l_freq",
                    "filter_h_freq",
                    "resample_sfreq",
                ):
                    self.assertNotIn(legacy_field, text)

    def test_process_native_thread_caps_follow_outer_parallelism(self):
        variable_thread_exports = (
            "NUMEXPR_MAX_THREADS=${task.cpus}",
            "OMP_NUM_THREADS=${task.cpus}",
            "MKL_NUM_THREADS=${task.cpus}",
            "OPENBLAS_NUM_THREADS=${task.cpus}",
        )
        single_thread_exports = tuple(
            export.replace("${task.cpus}", "1")
            for export in variable_thread_exports
        )
        for config in available_configs():
            text = config.read_text(encoding="utf-8")
            process_block = named_config_block(text, "process")
            default_before_script = re.search(
                r"(?m)^\s{4}beforeScript\s*=\s*\{\s*\"(?P<value>[^\"]+)\"\s*\}\s*$",
                process_block,
            )
            self.assertIsNotNone(default_before_script, config.name)
            for export in variable_thread_exports:
                self.assertIn(export, default_before_script.group("value"), config.name)

            for process_name in ("score_meg_quality", "detect_artifacts"):
                selector = re.search(
                    rf"(?ms)^\s{{4}}withName:\s*{process_name}\s*\{{(?P<body>.*?)^\s{{4}}\}}",
                    process_block,
                )
                self.assertIsNotNone(selector, f"{config.name}: {process_name}")
                selector_body = selector.group("body")
                for export in single_thread_exports:
                    self.assertIn(export, selector_body, f"{config.name}: {process_name}")

        pipeline = PIPELINE.read_text(encoding="utf-8")
        score_process = pipeline.split("process score_meg_quality {", 1)[1].split(
            "process detect_artifacts {", 1
        )[0]
        self.assertIn('--n_jobs ${task.cpus}', score_process)

    def test_corpus_examples_do_not_bundle_fixed_thread_or_fork_limits(self):
        fixed_thread_pattern = re.compile(
            r"(?:NUMEXPR_MAX_THREADS|OMP_NUM_THREADS|MKL_NUM_THREADS|"
            r"OPENBLAS_NUM_THREADS)=8"
        )
        for config in (CORPUS_EXAMPLE, MULTI_DATASET_DEMO):
            text = config.read_text(encoding="utf-8")
            with self.subTest(config=config.name):
                self.assertNotRegex(text, fixed_thread_pattern)
                self.assertNotRegex(text, r"(?m)^\s*maxForks\s*=\s*(?:4|6)\s*$")
                self.assertEqual(
                    re.findall(r"(?m)^\s*maxForks\s*=\s*(\d+)\s*$", text),
                    ["1"],
                )
                import_selector = re.search(
                    r"(?ms)withName:\s*import_meg_dataset\s*\{(?P<body>.*?)\}",
                    text,
                )
                self.assertIsNotNone(import_selector, config.name)
                self.assertIn("maxForks = 1", import_selector.group("body"))

    def test_full_overlay_and_docs_show_global_and_per_process_limits(self):
        overlay = FULL_WORKFLOW_CONFIG.read_text(encoding="utf-8")
        self.assertIn('local_cpus = "auto"', overlay)
        self.assertIn('local_memory = "auto"', overlay)
        self.assertIn('local_max_tasks = "auto"', overlay)
        self.assertRegex(
            overlay,
            r"(?ms)^// process \{.*?withName:\s*detect_artifacts\s*\{.*?"
            r"maxForks\s*=\s*\d+",
        )

        for document in (
            REPO_ROOT / "docs" / "source" / "reference" / "configuration_execution.rst",
            REPO_ROOT / "README.md",
        ):
            text = document.read_text(encoding="utf-8")
            with self.subTest(document=document.name):
                self.assertIn('local_cpus = 16', text)
                self.assertIn('local_memory = "48 GB"', text)
                self.assertIn('local_max_tasks = 3', text)
                self.assertRegex(
                    text,
                    r"(?ms)process\s*\{.*?withName:\s*\w+\s*\{.*?maxForks\s*=\s*\d+",
                )
                for concept in ("CPU", "memory", "DAG", "maxForks"):
                    self.assertIn(concept, text)

    def test_docker_runner_generates_declarative_runtime_overrides(self):
        text = packaged_docker_runner().read_text(encoding="utf-8")
        self.assertNotIn("def megflowRuntime", text)
        self.assertNotIn("new LinkedHashMap(params.megflow", text)
        self.assertIn(
            'params.megflow.datasets.docker_input.name = "docker_input"',
            text,
        )
        self.assertIn(
            'params.megflow.datasets.docker_input.dataset_dir = "${escaped_input}"',
            text,
        )
        self.assertIn(
            'params.megflow.datasets.docker_input.anatomy.fs_license_file',
            text,
        )
        self.assertIn(
            'params.megflow.defaults.anatomy.fs_license_file',
            text,
        )
        self.assertIn(
            'params.megflow.datasets.docker_input.dataset_dir = ""',
            text,
        )

    def test_container_supports_nextflow_26_with_v1_pipeline_syntax(self):
        runner = packaged_docker_runner().read_text(encoding="utf-8")
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        self.assertIn("export NXF_SYNTAX_PARSER=v1", runner)
        self.assertIn("openjdk-17-jdk", dockerfile)
        self.assertNotIn("openjdk-11-jdk", dockerfile)
        self.assertIn("JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64", dockerfile)
        self.assertIn("NXF_JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64", dockerfile)
        self.assertIn("NXF_SYNTAX_PARSER='v1'", dockerfile)

    def test_source_config_has_portable_execution_profiles(self):
        self.assertTrue(SOURCE_CONFIG.is_file())
        text = SOURCE_CONFIG.read_text(encoding="utf-8")
        for profile in ("local", "docker", "slurm", "singularity", "lenient", "strict", "debug"):
            self.assertRegex(text, rf"(?m)^\s{{4}}{profile}\s*\{{")
        self.assertIn('executor.queueSize = (System.getenv("MEGFLOW_SLURM_QUEUE_SIZE") ?: "100") as int', text)

    def test_coregistration_retry_exhaustion_falls_back_to_ignore(self):
        selector_pattern = re.compile(
            r"(?ms)^\s{4}withName: coregistration\s*\{(?P<body>.*?)^\s{4}\}"
        )
        for config in available_configs():
            text = config.read_text(encoding="utf-8")
            match = selector_pattern.search(text)
            self.assertIsNotNone(match, config.name)
            selector = match.group("body")
            self.assertIn("maxRetries = 6", selector, config.name)
            self.assertIn("task.attempt <= 6", selector, config.name)
            self.assertIn('task.exitStatus == 1', selector, config.name)
            self.assertIn('params.megflow.error_mode == "strict"', selector, config.name)

    def test_normmegqc_defaults_resample_to_250_hz(self):
        standalone_defaults = (
            MULTI_DATASET_DEMO,
            REPO_ROOT / "nextflow" / "nextflow_corpus.config",
        )
        configs = available_configs() + tuple(
            path
            for path in standalone_defaults
            if path.is_file()
        )
        for config in configs:
            text = config.read_text(encoding="utf-8")
            match = re.search(
                r"(?s)\bmegqc\s*(?:\{|:\s*\[)(.*?)"
                r"\n\s{12}preproc\s*(?:\{|:\s*\[)",
                text,
            )
            self.assertIsNotNone(match, config.name)
            qc_block = match.group(1)
            if "[filter:" not in qc_block:
                # Omitting megqc.preproc selects the scorer's tested
                # reference-aligned fallback; a partial explicit recipe does not.
                self.assertNotRegex(qc_block, r"\bpreproc\s*(?:=|:)", config.name)
                continue
            filter_index = qc_block.index("[filter:")
            notch_index = qc_block.index("[notch_filter:")
            resample_index = qc_block.index("[resample: [sfreq: 250]]")
            self.assertLess(filter_index, notch_index, config.name)
            self.assertLess(notch_index, resample_index, config.name)

    def test_ica_component_default_uses_explained_variance(self):
        canonical_configs = (
            SOURCE_CONFIG,
            DOCKER_CONFIG,
            CORPUS_EXAMPLE,
            MULTI_DATASET_DEMO,
        )
        for config in canonical_configs:
            text = config.read_text(encoding="utf-8")
            self.assertRegex(
                text,
                r"(?s)\bica\s*\{.*?\bnum_components\s*=\s*0\.9999\b",
                config.name,
            )
            self.assertNotRegex(
                text,
                r"\bnum_components\s*=\s*60\b",
                config.name,
            )

        pipeline = PIPELINE.read_text(encoding="utf-8")
        self.assertIn(
            "num_ic = cfgGet(ica_config, ['num_components'], 0.9999)",
            pipeline,
        )

    def test_outer_container_does_not_enable_nested_docker(self):
        text = packaged_docker_config().read_text(encoding="utf-8")
        self.assertRegex(text, r"(?s)docker\s*\{\s*enabled\s*=\s*false\s*\}")
        self.assertNotIn("runOptions = '-u $(id -u):$(id -g)'", text)

    def test_deepprep_runtime_is_owned_by_the_outer_megflow_image(self):
        pipeline_text = PIPELINE.read_text(encoding="utf-8")
        runtime_fields = (
            "deepprep_backend",
            "deepprep_command",
            "deepprep_container",
            "deepprep_sif",
        )
        configs = (
            SOURCE_CONFIG,
            DOCKER_CONFIG,
            REPO_ROOT / "nextflow" / "nextflow_corpus.config",
            MULTI_DATASET_DEMO,
            REPO_ROOT / "nextflow" / "nextflow_meg_masc_deepprep_anat.config",
        )
        for config in configs:
            if config.is_file():
                text = config.read_text(encoding="utf-8")
                for field in runtime_fields:
                    self.assertNotIn(field, text, config.name)

        for field in runtime_fields:
            self.assertNotIn(f"['anatomy', '{field}']", pipeline_text)
        self.assertIn(
            'deepprep_command="/opt/DeepPrep/deepprep/deepprep.sh"',
            pipeline_text,
        )
        self.assertNotRegex(pipeline_text, r"(?m)^\s*docker run\b")
        self.assertNotRegex(pipeline_text, r"(?m)^\s*singularity exec\b")

        source_text = SOURCE_CONFIG.read_text(encoding="utf-8")
        self.assertIn(
            'process.container = System.getenv("MEGFLOW_DOCKER_IMAGE") ?: "cplmeg/megflow:1.0.0"',
            source_text,
        )

    def test_docker_runner_uses_effective_nextflow_log_option(self):
        text = packaged_docker_runner().read_text(encoding="utf-8")
        self.assertIn('nextflow -log "${nextflow_report_dir}/nextflow.log" run', text)
        self.assertIn('nextflow -log "${corpus_nextflow_dir}/nextflow.log" run', text)
        self.assertIn('${run_output_dir}/static_html_report/nextflow', text)
        self.assertIn('${OUTPUT_DIR}/corpus_static_html_report/nextflow', text)

    def test_docker_runner_preserves_v2_profiles_and_uses_corpus_cli(self):
        text = packaged_docker_runner().read_text(encoding="utf-8")
        self.assertIn('--corpus) CORPUS_MODE=true', text)
        self.assertNotIn("--cohort", text)
        self.assertNotIn("--anat_only", text)
        self.assertNotIn("--meg_only", text)
        self.assertNotIn("new LinkedHashMap(params.megflow.datasets ?: [:])", text)
        self.assertIn(
            'params.megflow.datasets.docker_input.dataset_dir = ""',
            text,
        )
        self.assertIn("params.megflow.dataset_include", text)
        self.assertIn("params.megflow.defaults.anatomy.fs_license_file", text)
        self.assertIn('cp "$RUN_CONFIG_FILE" "${OUTPUT_DIR}/nextflow.config"', text)

    def test_interactive_reports_keep_run_root_separate_from_selected_dataset(self):
        app_text = INTERACTIVE_APP.read_text(encoding="utf-8")
        nextflow_text = INTERACTIVE_NEXTFLOW.read_text(encoding="utf-8")
        config_text = INTERACTIVE_CONFIG.read_text(encoding="utf-8")

        self.assertIn("st.session_state.run_report_root = str(base_report_path)", app_text)
        self.assertIn("st.session_state.dataset_report_path = str(selected_path)", app_text)
        self.assertIn('st.session_state.get("run_report_root", "/output")', nextflow_text)
        self.assertNotIn('st.session_state.get("dataset_report_path"', nextflow_text)
        self.assertIn('st.session_state.get("run_report_root", "/output")', config_text)

    def test_multi_dataset_demo_uses_v2_dataset_profiles(self):
        self.assertTrue(MULTI_DATASET_DEMO.is_file())
        text = MULTI_DATASET_DEMO.read_text(encoding="utf-8")
        self.assertIn('includeConfig "nextflow.config"', text)
        self.assertIn('report_scope = "corpus"', text)
        for profile in ("WAND_visual", "SMN4Lang_RDR", "MEG_MASC_word"):
            self.assertRegex(text, rf"(?m)^\s+{profile}\s*\{{")
        self.assertIn('deepreject {', text)
        self.assertIn('mode = "lenient"', text)
        self.assertNotIn("params.dataset_dir", text)

    def test_opm_cog_example_covers_all_three_profile_levels(self):
        self.assertTrue(OPM_COG_TASK_OVERRIDE_EXAMPLE.is_file())
        text = OPM_COG_TASK_OVERRIDE_EXAMPLE.read_text(encoding="utf-8")
        self.assertIn('includeConfig "nextflow.config"', text)
        self.assertRegex(text, r"(?s)params\s*\{.*megflow\s*\{.*defaults\s*\{")
        self.assertRegex(text, r"(?s)defaults\s*\{.*steps\s*=\s*\"meg_all\"")
        self.assertRegex(text, r"(?s)epochs\s*\{.*epochs\s*\{.*tmin\s*=\s*-0\.2")
        self.assertRegex(text, r"(?s)datasets\s*\{.*OPM_COG\s*\{.*recordings\s*\{")
        for task in ("aef", "vef", "tap", "ssvef"):
            self.assertRegex(text, rf'(?s)match\s*\{{\s*task\s*=\s*"{task}"\s*\}}')
        self.assertIn('task = ["aef", "vef", "tap", "ssvef"]', text)
        self.assertGreaterEqual(text.count("forward {"), 5)
        self.assertGreaterEqual(text.count("visualization {"), 4)

    def test_maxwell_tsss_example_uses_declarative_profile_configuration(self):
        self.assertTrue(MAXWELL_TSSS_EXAMPLE.is_file())
        text = MAXWELL_TSSS_EXAMPLE.read_text(encoding="utf-8")
        self.assertIn('includeConfig "nextflow.config"', text)
        self.assertNotRegex(text, r"(?m)^def\s+")
        self.assertRegex(text, r"(?s)params\s*\{.*megflow\s*\{.*defaults\s*\{")
        self.assertGreaterEqual(text.count('preproc {'), 3)
        self.assertRegex(text, r"(?s)datasets\s*\{.*MEGIN_SITE_A\s*\{")
        self.assertRegex(text, r"(?m)^\s+recordings\s*\{")
        self.assertEqual(text.count("[maxwell_filter: ["), 3)
        self.assertIn("st_duration: 10.0", text)
        self.assertIn("st_duration: 20.0", text)
        self.assertIn('calibration: "/data/site-a/calibration/sss_cal.dat"', text)

    def test_user_profile_configs_avoid_groovy_map_assembly(self):
        exceptions = {
            "deepprep.common.config",
            "nextflow.config",
            "nextflow_for_docker.config",
        }
        profile_configs = sorted(
            path
            for path in (REPO_ROOT / "nextflow").glob("*.config")
            if path.name not in exceptions
        )
        self.assertTrue(profile_configs)
        for config in profile_configs:
            text = config.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"(?m)^def\s+", config.name)
            self.assertNotIn("params.megflow = params.megflow +", text, config.name)
            self.assertNotRegex(text, r"\binherited[A-Z]\w*", config.name)
            self.assertNotIn("params.megflow.datasets.clear()", text, config.name)

    def test_user_facing_configs_and_docs_use_nested_megflow_blocks(self):
        non_nested_syntax = re.compile(
            r"(?:params\.megflow(?:\.[A-Za-z_]\w*)+\s*=(?!=)"
            r"|(?m:^\s*megflow\s*=\s*\[)"
            r"|\bdatasets\s*=\s*\["
            r"|\brecordings\s*[:=]\s*\[)"
        )
        paths = [REPO_ROOT / "README.md"]
        for pattern in ("*.rst", "*.md"):
            paths.extend((REPO_ROOT / "docs" / "source").rglob(pattern))
        paths.extend((REPO_ROOT / "examples").rglob("*.config"))
        paths.extend((REPO_ROOT / "nextflow").glob("*.config"))
        paths = [
            path
            for path in paths
            if not path.name.startswith("._")
            and path.name != "deepprep.common.config"
        ]

        offenders = {}
        for path in paths:
            matches = non_nested_syntax.findall(path.read_text(encoding="utf-8"))
            if matches:
                offenders[str(path.relative_to(REPO_ROOT))] = matches

        self.assertEqual(offenders, {})

    def test_documented_groovy_configs_show_the_complete_outer_scope(self):
        def rst_groovy_blocks(text):
            lines = text.splitlines()
            blocks = []
            index = 0
            while index < len(lines):
                if lines[index].strip() != ".. code-block:: groovy":
                    index += 1
                    continue
                index += 1
                block = []
                while index < len(lines) and (
                    not lines[index].strip() or lines[index].startswith("   ")
                ):
                    if lines[index].startswith("   "):
                        block.append(lines[index][3:])
                    index += 1
                blocks.append(block)
            return blocks

        def markdown_groovy_blocks(text):
            return [
                match.group(1).splitlines()
                for match in re.finditer(r"(?ms)^```groovy\s*\n(.*?)^```\s*$", text)
            ]

        offenders = []
        doc_paths = sorted(
            path
            for path in (REPO_ROOT / "docs" / "source").rglob("*.rst")
            if not path.name.startswith("._")
        )
        doc_paths.append(REPO_ROOT / "README.md")
        for path in doc_paths:
            text = path.read_text(encoding="utf-8")
            blocks = (
                markdown_groovy_blocks(text)
                if path.suffix == ".md"
                else rst_groovy_blocks(text)
            )
            for block_index, block in enumerate(blocks, start=1):
                significant = [
                    line.strip()
                    for line in block
                    if line.strip() and not line.strip().startswith("//")
                ]
                first_line = significant[0] if significant else ""
                if first_line not in {"params {", "process {"}:
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)} block {block_index}: {first_line}"
                    )

        self.assertEqual(offenders, [])

    def test_multi_dataset_source_runner_requires_an_explicit_config_without_docker(self):
        self.assertTrue(MULTI_DATASET_SOURCE_RUNNER.is_file())
        text = MULTI_DATASET_SOURCE_RUNNER.read_text(encoding="utf-8")
        self.assertIn('die "--config is required"', text)
        self.assertIn('-C "$CONFIG"', text)
        self.assertIn('-profile "$PROFILE"', text)
        self.assertIn('-log "$LOG_FILE"', text)
        self.assertNotIn("nextflow_multi_dataset_demo.config", text)
        self.assertNotIn("docker run", text)
        self.assertNotIn("--cohort", text)

    def test_shipped_source_examples_publish_common_execution_outputs(self):
        for config, package in SHIPPED_SOURCE_EXAMPLES:
            self.assertTrue(config.is_file(), config)
            text = config.read_text(encoding="utf-8")
            self.assertIn('includeConfig "nextflow.config"', text, config.name)
            self.assertIn('workDir = "${params.megflow.output_dir}/work"', text, config.name)
            self.assertIn(f'log.file = "${{params.megflow.output_dir}}/{package}/nextflow/nextflow.log"', text, config.name)
            self.assertIn(f'report.file = "${{params.megflow.output_dir}}/{package}/nextflow/report.html"', text, config.name)
            self.assertIn(f'timeline.file = "${{params.megflow.output_dir}}/{package}/nextflow/timeline.html"', text, config.name)
            self.assertIn(f'trace.file = "${{params.megflow.output_dir}}/{package}/nextflow/trace.txt"', text, config.name)

    def test_docker_overlay_examples_use_v2_dataset_keys(self):
        for config in DOCKER_OVERLAY_EXAMPLES:
            self.assertTrue(config.is_file(), config)
            text = config.read_text(encoding="utf-8")
            self.assertRegex(
                text,
                r"(?s)params\s*\{.*megflow\s*\{.*datasets\s*\{.*docker_input\s*\{",
                config.name,
            )
            self.assertNotRegex(
                text,
                r"(?m)^\s*params\.megflow(?:\.[A-Za-z_]\w*)+\s*=",
                config.name,
            )

    def test_pseudomri_docker_overlay_resolves_both_base_config_locations(self):
        overlay = PSEUDOMRI_DOCKER_OVERLAY.read_text(encoding="utf-8")
        runner = DOCKER_RUNNER.read_text(encoding="utf-8")
        self.assertIn("MEGFLOW_DOCKER_BASE_CONFIG", overlay)
        self.assertIn("'nextflow_for_docker.config'", overlay)
        self.assertIn(
            'MEGFLOW_DOCKER_BASE_CONFIG:-/program/nextflow/nextflow.config',
            runner,
        )

    def test_shipped_corpus_example_has_explicit_dataset_profiles(self):
        self.assertTrue(CORPUS_EXAMPLE.is_file())
        text = CORPUS_EXAMPLE.read_text(encoding="utf-8")
        self.assertIn('report_scope = "corpus"', text)
        for profile in ("WAND_visual", "SMN4Lang_RDR", "MEG_MASC_word"):
            self.assertRegex(text, rf"(?m)^\s+{profile}\s*\{{")

    def test_recording_identity_and_source_inputs_are_routed_explicitly(self):
        text = PIPELINE.read_text(encoding="utf-8")
        self.assertIn("List recordingKey(String datasetName, def rawPathValue)", text)
        self.assertIn("--forward_file \"${fwd_file}\"", text)
        self.assertIn("--noise_covariance_file \"${bl_cov_file}\"", text)
        self.assertNotIn("new File(raw_data_file).exists()", text)
        self.assertEqual(
            text.count(
                "failOnMismatch: megflowErrorMode().equalsIgnoreCase('strict')"
            ),
            2,
        )
        self.assertIn("Source routing clean lineage mismatch", text)

    def test_skip_ica_routes_artifact_sidecars_and_hash_into_epochs(self):
        text = PIPELINE.read_text(encoding="utf-8")
        epochs_process = text.split("process epochs {", 1)[1].split(
            "\nprocess ", 1
        )[0]
        routing = text.split("native_non_reference_clean_subject_ch", 1)[1]

        self.assertIn("native_non_reference_artifacts_with_hash_ch", routing)
        self.assertIn(
            "native_epoch_from_preproc_ch = "
            "native_non_reference_artifacts_with_hash_ch",
            routing,
        )
        self.assertIn('val(bad_channels)', epochs_process)
        self.assertIn('val(bad_segments)', epochs_process)
        self.assertIn('--fname_bad_channels "${bad_channels}"', epochs_process)
        self.assertIn('--fname_bad_segments "${bad_segments}"', epochs_process)
        self.assertIn(
            "'', artifact_hash, bad_channels, bad_segments)",
            routing,
        )

    def test_reports_use_a_value_barrier_and_never_resume_from_cache(self):
        text = PIPELINE.read_text(encoding="utf-8")
        self.assertGreaterEqual(text.count("cache false"), 2)
        self.assertIn("report_completion_tokens = dataset_token_ch", text)
        self.assertIn(".mix(source_token_ch)\n        .collect()", text)
        self.assertIn("val completion_tokens", text)
        self.assertRegex(
            text,
            r"native_reports\s*=\s*generate_static_html_report\(\s*"
            r"native_dataset_report_row_ch,\s*"
            r"report_completion_tokens\s*\)",
        )
        self.assertNotIn("report_wait_token_ch", text)
        self.assertNotIn("stable -resume caching", text)

    def test_rank_and_lcmv_covariance_contracts_are_explicit(self):
        pipeline_text = PIPELINE.read_text(encoding="utf-8")
        covariance_text = (REPO_ROOT / "megflow" / "compute_covariance.py").read_text(
            encoding="utf-8"
        )
        source_text = (REPO_ROOT / "megflow" / "source_localization.py").read_text(
            encoding="utf-8"
        )

        for config in available_configs():
            text = config.read_text(encoding="utf-8")
            self.assertRegex(text, r'rank_policy\s*(?:=|:)\s*"auto"', config.name)
            self.assertRegex(text, r"data_covariance\s*(?:\{|:\s*\[)", config.name)

        self.assertIn('--source_data_file "${source_data_file}"', pipeline_text)
        self.assertIn('--data_covariance_file \\"${lcmv_data_cov_file}\\"', pipeline_text)
        self.assertIn('--resolved_rank_file "${resolved_rank_file}"', pipeline_text)
        self.assertIn("Covariance/source input lineage mismatch", pipeline_text)
        self.assertIn('/source_visualization.py"', pipeline_text)
        self.assertIn("task.exitStatus == 2", SOURCE_CONFIG.read_text(encoding="utf-8"))
        self.assertIn('output_dir / "lcmv-data-cov.fif"', covariance_text)
        self.assertIn('output_dir / "resolved-rank.json"', covariance_text)
        self.assertIn("def load_resolved_rank", source_text)
        self.assertNotIn("mne.compute_raw_covariance(", source_text)
        self.assertNotIn("mne.compute_covariance(", source_text)

    def test_mne_and_osl_parameter_passthrough_contracts_are_explicit(self):
        pipeline_text = PIPELINE.read_text(encoding="utf-8")
        preproc_text = (REPO_ROOT / "megflow" / "meg_preproc_osl.py").read_text(
            encoding="utf-8"
        )
        wrapper_text = (
            REPO_ROOT
            / "megflow"
            / "tools"
            / "osl-ephys"
            / "osl_ephys"
            / "preprocessing"
            / "mne_wrappers.py"
        ).read_text(encoding="utf-8")
        source_text = (REPO_ROOT / "megflow" / "source_localization.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("def _osl_preprocessing_config(config):", preproc_text)
        self.assertIn("osl_config.pop('digitization', None)", preproc_text)
        self.assertNotIn("{'preproc': config.get('preproc', [])}", preproc_text)
        self.assertIn("def steps = out.remove('steps')", pipeline_text)
        self.assertIn("preproc_config: preproc_config", pipeline_text)
        self.assertIn("epochs_config: epochs_config", pipeline_text)
        self.assertIn("covariance_config: covariance_config", pipeline_text)
        self.assertIn("source_config: source_config", pipeline_text)
        self.assertIn("np.asarray(freqs, dtype=float).reshape(-1)", wrapper_text)

        self.assertIn("def _minimum_norm_mne_kwargs", source_text)
        self.assertIn('"make_inverse_operator"', source_text)
        self.assertIn('"apply_inverse_raw"', source_text)
        self.assertIn("def _lcmv_mne_kwargs", source_text)
        self.assertIn('"apply_lcmv_raw"', source_text)
        self.assertIn("apply_lcmv(evoked, filters, **apply_lcmv_kwargs)", source_text)
        self.assertIn("apply_lcmv_raw(raw, filters, **apply_lcmv_kwargs)", source_text)

        default_configs = available_configs() + tuple(
            path
            for path in (
                MULTI_DATASET_DEMO,
                REPO_ROOT / "nextflow" / "nextflow_corpus.config",
            )
            if path.is_file()
        )
        for config in default_configs:
            self.assertRegex(
                config.read_text(encoding="utf-8"),
                r"lambda2\s*(?:=|:)\s*0\.1111111111111111",
                config.name,
            )

    def test_raw_covariance_pairing_is_channel_backed_and_many_to_one(self):
        text = PIPELINE.read_text(encoding="utf-8")
        self.assertIn("native_raw_cov_reference_keys_v", text)
        self.assertIn(
            ".combine(native_cov_raw_candidates_ch, by: 0)",
            text,
        )
        self.assertIn("isRawCovarianceReferenceKey", text)
        self.assertIn("raw_covariance_task_id must contain only", text)

    def test_external_inputs_are_explicit_cache_lineage_values(self):
        text = PIPELINE.read_text(encoding="utf-8")
        self.assertIn("val(raw_inventory_hash)", text)
        self.assertIn("val(t1_inventory_hash)", text)
        self.assertIn("raw_input_fingerprint", text)
        self.assertIn("val(events_hash)", text)
        self.assertIn("val(epoch_hash)", text)
        self.assertIn("val(anatomy_hash)", text)
        self.assertIn("_implementation_fingerprint", text)

    def test_published_process_outputs_have_task_local_resume_guards(self):
        text = PIPELINE.read_text(encoding="utf-8")
        self.assertIn("String megInputStem(def pathValue)", text)
        self.assertIn("endsWith('.fif.gz')", text)
        guards = (
            "pseudomri-output.guard",
            "freesurfer-reconstruction.guard",
            "freesurfer-head-surface.guard",
            "deepprep-reconstruction.guard",
            "mkheadsurf-output.guard",
            "bem-surfaces-output.guard",
            "bem-solution-output.guard",
            "qc-summary-output.guard",
            "qc-components-output.guard",
            "qc-plot-output.guard",
            "preproc-output.guard",
            "bad-channels-output.guard",
            "bad-segments-output.guard",
            "ica-sources-output.guard",
            "ica-decomposition-output.guard",
            "ica-label-output.guard",
            "clean-raw-output.guard",
            "epoch-output.guard",
            "epoch-analysis-output.guard",
            "noise-covariance-output.guard",
            "data-covariance-output.guard",
            "resolved-rank-output.guard",
            "coregistration-output.guard",
            "forward-solution-output.guard",
            "source-imaging-output.guard",
        )
        for guard in guards:
            with self.subTest(guard=guard):
                self.assertIn(f'path "{guard}"', text)
                self.assertGreaterEqual(text.count(guard), 3)

    def test_profile_validation_guards_ambiguous_and_colliding_outputs(self):
        text = PIPELINE.read_text(encoding="utf-8")
        self.assertIn("Unknown match fields", text)
        self.assertIn("Multiple recording profiles matched", text)
        self.assertIn("share output identifiers", text)
        self.assertIn("overlapping ${field} paths", text)

    def test_process_output_directories_are_internal_and_hidden_from_configs(self):
        pipeline_text = PIPELINE.read_text(encoding="utf-8")
        fixed_dirs = {
            "ica": "ica_report",
            "epochs": "epochs",
            "coreg": "trans",
            "covariance": "covariance",
            "forward": "forward_solution",
            "source": "source_recon",
        }
        self.assertIn("Map fixedProcessOutputDirs()", pipeline_text)
        self.assertIn("validateFixedProcessOutputDirs(effectiveConfig, context)", pipeline_text)
        self.assertIn("output_dir is internal and fixed to", pipeline_text)
        for module, directory in fixed_dirs.items():
            self.assertIn(f"{module}: '{directory}'", pipeline_text)
            self.assertIn(f"processOutputDir('{module}')", pipeline_text)

        public_configs = available_configs() + tuple(
            path
            for path in (
                MULTI_DATASET_DEMO,
                REPO_ROOT / "nextflow" / "nextflow_corpus.config",
            )
            if path.is_file()
        )
        for config in public_configs:
            text = config.read_text(encoding="utf-8")
            for directory in fixed_dirs.values():
                self.assertNotIn(
                    f'output_dir: "{directory}"',
                    text,
                    f"{config.name} exposes fixed process directory {directory}",
                )


if __name__ == "__main__":
    unittest.main()
