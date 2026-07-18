import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NEXTFLOW_FILE = ROOT / "nextflow" / "megflow.nf"
TRACKED_DEFAULT_CONFIGS = (
    ROOT / "nextflow" / "nextflow.config",
    ROOT / "nextflow" / "nextflow_corpus.config",
    ROOT / "nextflow" / "nextflow_for_docker.config",
    ROOT / "nextflow" / "nextflow_multi_dataset_demo.config",
)
OPTIONAL_USER_CONFIGS = (
    ROOT / "nextflow" / "nextflow_for_holmes.config",
)
DEFAULT_CONFIGS = TRACKED_DEFAULT_CONFIGS + tuple(
    path for path in OPTIONAL_USER_CONFIGS if path.is_file()
)


def process_block(source, process_name, next_process_name):
    start = source.index(f"process {process_name} {{")
    end = source.index(f"process {next_process_name} {{", start)
    return source[start:end]


class MegnetConfigMigrationTests(unittest.TestCase):
    def test_all_default_configs_use_new_independent_switches(self):
        for config_path in DEFAULT_CONFIGS:
            with self.subTest(config=config_path.name):
                source = config_path.read_text(encoding="utf-8")
                self.assertRegex(source, r"(?m)^\s*mne_icalabel:\s*true,")
                self.assertRegex(source, r"(?m)^\s*megnet_retrained:\s*false,")
                self.assertNotRegex(source, r"megnet_retrained\.enabled")
                self.assertNotRegex(source, r"(?m)^\s*ica_label:\s*")


class MegnetNextflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = NEXTFLOW_FILE.read_text(encoding="utf-8")
        cls.label_process = process_block(
            cls.source,
            "run_ic_label",
            "apply_ica",
        )

    def test_label_process_receives_precomputed_ica_sources(self):
        self.assertIn('--ica_sources_file "${ica_source}"', self.label_process)

    def test_label_process_refreshes_auto_outputs_and_guards_method_json(self):
        self.assertIn("--refresh-existing", self.label_process)
        self.assertIn("ica-label-scores-output.guard", self.label_process)
        self.assertIn("ecg_eog_scores.json", self.label_process)

    def test_label_process_uses_a_dedicated_cached_implementation_hash(self):
        self.assertIn("String icaLabelImplementationFingerprint", self.source)
        for relative_path in (
            "run_ica_label.py",
            "tools/megnet_retrained/__init__.py",
            "tools/megnet_retrained/inference.py",
            "tools/megnet_retrained/runtime/preprocessing.py",
            "tools/megnet_retrained/model.onnx",
        ):
            with self.subTest(path=relative_path):
                self.assertIn(relative_path, self.source)
        self.assertIn("def icaLabelFingerprints = [:]", self.source)
        self.assertIn(
            "icaLabelImplementationFingerprint(effective_config.code_dir)",
            self.source,
        )
        self.assertIn("val(ica_label_code_hash)", self.label_process)
        self.assertIn("code_hash = ica_label_code_hash", self.label_process)


if __name__ == "__main__":
    unittest.main()
