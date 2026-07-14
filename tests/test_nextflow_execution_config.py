import re
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
MULTI_DATASET_SOURCE_RUNNER = REPO_ROOT / "run_MultiDatasets_sourcecode.sh"
OPM_COG_RUNNER = REPO_ROOT / "run_OPM_COG.sh"
MEGQC_CONFIG = REPO_ROOT / "nextflow" / "nextflow_for_megqc.config"
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
        for profile in ("local", "slurm", "singularity", "lenient", "strict", "debug"):
            self.assertRegex(text, rf"(?m)^\s{{4}}{profile}\s*\{{")
        self.assertIn('executor.queueSize = (System.getenv("MEGFLOW_SLURM_QUEUE_SIZE") ?: "100") as int', text)

    def test_outer_container_does_not_enable_nested_docker(self):
        text = packaged_docker_config().read_text(encoding="utf-8")
        self.assertRegex(text, r"(?s)docker\s*\{\s*enabled\s*=\s*false\s*\}")
        self.assertNotIn("runOptions = '-u $(id -u):$(id -g)'", text)

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
        self.assertIn("failOnMismatch: true", text)
        self.assertIn("Source routing clean lineage mismatch", text)

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

    def test_profile_validation_guards_ambiguous_and_colliding_outputs(self):
        text = PIPELINE.read_text(encoding="utf-8")
        self.assertIn("Unknown match fields", text)
        self.assertIn("Multiple recording profiles matched", text)
        self.assertIn("share output identifiers", text)
        self.assertIn("overlapping ${field} paths", text)


if __name__ == "__main__":
    unittest.main()
