import re
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PIPELINE = REPO_ROOT / "nextflow" / "megflow.nf"
SOURCE_CONFIG = REPO_ROOT / "nextflow" / "nextflow.config"
DOCKER_CONFIG = REPO_ROOT / "nextflow" / "nextflow_for_docker.config"
DOCKER_RUNNER = REPO_ROOT / "nextflow" / "run_for_docker.sh"
INTERACTIVE_APP = REPO_ROOT / "megflow" / "reports" / "reports.py"
INTERACTIVE_NEXTFLOW = REPO_ROOT / "megflow" / "reports" / "reports" / "nextflow.py"
INTERACTIVE_CONFIG = REPO_ROOT / "megflow" / "reports" / "reports" / "nx_config_online.py"
MULTI_DATASET_DEMO = REPO_ROOT / "nextflow" / "nextflow_multi_dataset_demo.config"
OPM_COG_TASK_OVERRIDE_EXAMPLE = REPO_ROOT / "nextflow" / "nextflow_opm_cog_task_overrides_example.config"
MAXWELL_TSSS_EXAMPLE = REPO_ROOT / "nextflow" / "nextflow_maxwell_tsss_example.config"
MULTI_DATASET_SOURCE_RUNNER = REPO_ROOT / "run_MultiDatasets_sourcecode.sh"
OPM_COG_RUNNER = REPO_ROOT / "run_OPM_COG.sh"
MEGQC_CONFIG = REPO_ROOT / "nextflow" / "nextflow_for_megqc.config"
PROFILE_INTEGRATION_TEST = REPO_ROOT / "tests" / "test_nextflow_profile_integration.py"
VALIDATION_RUNNER = REPO_ROOT / "scripts" / "validation" / "run_validation.sh"
VALIDATION_UNITTEST_GATE = REPO_ROOT / "scripts" / "validation" / "run_unittest_gate.py"
WINDOWS_INSTALL_VALIDATOR = REPO_ROOT / "scripts" / "validation" / "validate_windows_installer.py"
VALIDATION_REQUIREMENTS = REPO_ROOT / "requirements_validation.txt"
DOCUMENTATION_REQUIREMENTS = REPO_ROOT / "requirements_doc.txt"
VALIDATION_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "validation.yml"
DATASET_CONFIGS = (
    REPO_ROOT / "nextflow" / "nextflow_for_holmes.config",
    MEGQC_CONFIG,
    REPO_ROOT / "nextflow" / "nextflow_for_opm_cog.config",
    REPO_ROOT / "nextflow" / "nextflow_for_smn4lang.config",
)
LEGACY_DATASET_CONFIGS = (
    REPO_ROOT / "nextflow" / "nextflow_for_Holmes.config",
    REPO_ROOT / "nextflow" / "nextflow_for_opm.config",
)


def process_names() -> set[str]:
    return set(re.findall(r"^process\s+([A-Za-z_]\w*)\s*\{", PIPELINE.read_text(encoding="utf-8"), re.MULTILINE))


def process_selectors(config: Path) -> list[str]:
    text = config.read_text(encoding="utf-8")
    pattern = re.compile(r"withName:\s*(?:'([^']+)'|\"([^\"]+)\"|([A-Za-z_]\w*))")
    return [next(value for value in match.groups() if value) for match in pattern.finditer(text)]


def available_configs() -> tuple[Path, ...]:
    return (SOURCE_CONFIG, DOCKER_CONFIG) if DOCKER_CONFIG.is_file() else (SOURCE_CONFIG,)


def packaged_docker_config() -> Path:
    return DOCKER_CONFIG if DOCKER_CONFIG.is_file() else SOURCE_CONFIG


def packaged_docker_runner() -> Path:
    return DOCKER_RUNNER if DOCKER_RUNNER.is_file() else REPO_ROOT / "nextflow" / "run.sh"


class NextflowExecutionConfigTests(unittest.TestCase):
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
        for mode in ("routing", "scientific", "all"):
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
        self.assertIn("run_validation.sh routing", workflow)
        self.assertIn("run_validation.sh scientific", workflow)
        self.assertIn(
            "python -m pip install --no-deps -e ./megflow/tools/osl-ephys",
            workflow,
        )

    def test_validation_workflow_local_inputs_are_tracked(self):
        required_paths = (
            ".github/workflows/validation.yml",
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
        test_modules = {
            path.stem
            for path in (REPO_ROOT / "tests").glob("test_*.py")
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
        self.assertIn("timeout-minutes: 30", routing_job)

    def test_every_process_selector_matches_current_pipeline(self):
        names = process_names()
        self.assertTrue(names)
        for config in available_configs():
            unmatched = [selector for selector in process_selectors(config) if not any(re.fullmatch(selector, name) for name in names)]
            self.assertEqual(unmatched, [], config.name)

    def test_observability_outputs_are_enabled_and_scoped_to_output_dir(self):
        for config in available_configs():
            text = config.read_text(encoding="utf-8")
            self.assertIn('report_scope: "dataset"', text)
            self.assertIn('def megflowNextflowDir = "${params.megflow.output_dir}/${megflowReportPackage}/nextflow"', text)
            self.assertIn('file = "${megflowNextflowDir}/nextflow.log"', text)
            self.assertIn('file = "${megflowNextflowDir}/report.html"', text)
            self.assertIn('file = "${megflowNextflowDir}/timeline.html"', text)
            self.assertIn('file = "${megflowNextflowDir}/trace.txt"', text)
            self.assertGreaterEqual(text.count("enabled = true"), 3)

    def test_source_config_has_portable_execution_profiles(self):
        if not DOCKER_CONFIG.is_file():
            self.skipTest("the container image packages only its Docker execution config")
        text = SOURCE_CONFIG.read_text(encoding="utf-8")
        for profile in ("local", "docker", "slurm", "singularity", "lenient", "strict", "debug"):
            self.assertRegex(text, rf"(?m)^\s{{4}}{profile}\s*\{{")
        self.assertIn('executor.queueSize = (System.getenv("MEGFLOW_SLURM_QUEUE_SIZE") ?: "100") as int', text)

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
                r"(?s)megqc:\s*\[(.*?)\n\s{12}preproc:\s*\[",
                text,
            )
            self.assertIsNotNone(match, config.name)
            qc_block = match.group(1)
            if "[filter:" not in qc_block:
                # Omitting megqc.preproc selects the scorer's tested
                # reference-aligned fallback; a partial explicit recipe does not.
                self.assertNotIn("preproc:", qc_block, config.name)
                continue
            filter_index = qc_block.index("[filter:")
            notch_index = qc_block.index("[notch_filter:")
            resample_index = qc_block.index("[resample: [sfreq: 250]]")
            self.assertLess(filter_index, notch_index, config.name)
            self.assertLess(notch_index, resample_index, config.name)

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
        self.assertIn("new LinkedHashMap(params.megflow.datasets ?: [:])", text)
        self.assertIn('megflowRuntimeCorpusDatasets.remove("docker_input")', text)
        self.assertIn("params.megflow.dataset_include", text)
        self.assertIn("megflowRuntimeAnatomy.fs_license_file", text)
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
        self.assertIn('report_scope: "corpus"', text)
        for profile in ("WAND_visual", "SMN4Lang_RDR", "MEG_MASC_word"):
            self.assertRegex(text, rf"(?m)^\s{{12}}{profile}:\s*\[")
        self.assertIn('deepreject: [', text)
        self.assertIn('mode: "lenient"', text)
        self.assertNotIn("params.dataset_dir", text)

    def test_opm_cog_example_covers_all_three_profile_levels(self):
        self.assertTrue(OPM_COG_TASK_OVERRIDE_EXAMPLE.is_file())
        text = OPM_COG_TASK_OVERRIDE_EXAMPLE.read_text(encoding="utf-8")
        self.assertIn('includeConfig "nextflow.config"', text)
        self.assertIn('params.megflow.defaults.steps = "meg_all"', text)
        self.assertIn("params.megflow.defaults.epochs.epochs.tmin = -0.2", text)
        self.assertIn("params.megflow.datasets = [", text)
        self.assertRegex(text, r"(?m)^\s{4}OPM_COG:\s*\[")
        self.assertRegex(text, r"(?m)^\s{8}recordings:\s*\[")
        for task in ("aef", "vef", "tap", "ssvef"):
            self.assertIn(f'match: [task: "{task}"]', text)
        self.assertIn('task: ["aef", "vef", "tap", "ssvef"]', text)
        self.assertGreaterEqual(text.count("forward: [epoch_label:"), 4)
        self.assertGreaterEqual(text.count("visualization: ["), 4)

    def test_maxwell_tsss_example_uses_declarative_profile_configuration(self):
        self.assertTrue(MAXWELL_TSSS_EXAMPLE.is_file())
        text = MAXWELL_TSSS_EXAMPLE.read_text(encoding="utf-8")
        self.assertIn('includeConfig "nextflow.config"', text)
        self.assertNotRegex(text, r"(?m)^def\s+")
        self.assertIn('params.megflow.defaults.preproc = [', text)
        self.assertIn('params.megflow.datasets = [', text)
        self.assertRegex(text, r"(?m)^\s{4}MEGIN_SITE_A:\s*\[")
        self.assertRegex(text, r"(?m)^\s{8}recordings:\s*\[")
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

    def test_multi_dataset_source_runner_uses_demo_config_without_docker(self):
        self.assertTrue(MULTI_DATASET_SOURCE_RUNNER.is_file())
        text = MULTI_DATASET_SOURCE_RUNNER.read_text(encoding="utf-8")
        self.assertIn("nextflow/nextflow_multi_dataset_demo.config", text)
        self.assertIn('-C "$CONFIG"', text)
        self.assertIn('-profile "$PROFILE"', text)
        self.assertIn('-log "$LOG_FILE"', text)
        self.assertIn("Do not pass --steps to source Nextflow runs.", text)
        self.assertNotIn("docker run", text)
        self.assertNotIn("--cohort", text)

    def test_dataset_configs_inherit_common_execution_policy(self):
        available = tuple(config for config in DATASET_CONFIGS if config.is_file())
        if not available:
            self.skipTest("dataset-specific source configs are not packaged in the image")

        self.assertEqual(available, DATASET_CONFIGS)
        for config in available:
            text = config.read_text(encoding="utf-8")
            self.assertIn('includeConfig "nextflow.config"', text, config.name)
            self.assertNotIn("error_mode:", text, config.name)
            self.assertNotIn("code_dir:", text, config.name)
            self.assertIn('workDir = "${params.megflow.output_dir}/work"', text, config.name)
            package = "corpus_static_html_report" if config == MEGQC_CONFIG else "static_html_report"
            self.assertIn(f'log.file = "${{params.megflow.output_dir}}/{package}/nextflow/nextflow.log"', text, config.name)
            self.assertIn(f'report.file = "${{params.megflow.output_dir}}/{package}/nextflow/report.html"', text, config.name)
            self.assertIn(f'timeline.file = "${{params.megflow.output_dir}}/{package}/nextflow/timeline.html"', text, config.name)
            self.assertIn(f'trace.file = "${{params.megflow.output_dir}}/{package}/nextflow/trace.txt"', text, config.name)
            self.assertIn("-profile local,lenient -resume", text, config.name)

        for legacy_config in LEGACY_DATASET_CONFIGS:
            self.assertFalse(legacy_config.exists(), legacy_config.name)

    def test_opm_cog_runner_keeps_image_base_config_visible(self):
        if not OPM_COG_RUNNER.is_file():
            self.skipTest("the source-only OPM-COG runner is not packaged in the image")

        text = OPM_COG_RUNNER.read_text(encoding="utf-8")
        self.assertIn("--user \"$(id -u):$(id -g)\"", text)
        self.assertIn('${config_file}:/program/nextflow/nextflow_for_opm_cog.config:ro', text)
        self.assertIn("-C /program/nextflow/nextflow_for_opm_cog.config", text)
        self.assertNotIn("nextflow_for_opm_cog.config:/program/nextflow/nextflow.config", text)

    def test_megqc_config_uses_corpus_discovery_without_dataset_overrides(self):
        if not MEGQC_CONFIG.is_file():
            self.skipTest("the source-only MEGQC corpus config is not packaged in the image")

        text = MEGQC_CONFIG.read_text(encoding="utf-8")
        self.assertIn('params.megflow.corpus_root = "/data/liaopan/datasets/MEGQC"', text)
        self.assertIn('params.megflow.report_scope = "corpus"', text)
        self.assertIn('params.megflow.dataset_exclude = ["Z_BACK"]', text)
        self.assertIn('params.megflow.defaults.steps = "meg_artifacts"', text)
        self.assertIn("params.megflow.datasets = [:]", text)

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

    def test_reports_use_a_value_barrier_and_never_resume_from_cache(self):
        text = PIPELINE.read_text(encoding="utf-8")
        self.assertGreaterEqual(text.count("cache false"), 2)
        self.assertIn("report_completion_tokens = dataset_token_ch", text)
        self.assertIn(".mix(source_token_ch)\n        .collect()", text)
        self.assertIn("val completion_tokens", text)
        self.assertIn(
            "generate_static_html_report(\n"
            "        native_dataset_report_row_ch,\n"
            "        report_completion_tokens\n"
            "    )",
            text,
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
            self.assertIn('rank_policy: "auto"', text, config.name)
            self.assertIn("data_covariance: [", text, config.name)

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
            self.assertIn(
                "lambda2: 0.1111111111111111",
                config.read_text(encoding="utf-8"),
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
