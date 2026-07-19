import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NEXTFLOW_FILE = ROOT / "nextflow" / "megflow.nf"


def quality_process_text() -> str:
    text = NEXTFLOW_FILE.read_text(encoding="utf-8")
    return text.split("process score_meg_quality", 1)[1].split(
        "process meg_basic_preproc",
        1,
    )[0]


class QualityScoreNextflowContractTests(unittest.TestCase):
    def test_quality_process_stages_canonical_public_names(self):
        process_text = quality_process_text()

        for suffix in (
            "summary.json",
            "component_scores.csv",
            "normative_quality_score.png",
        ):
            self.assertIn(f"${{qc_output_stem}}.{suffix}", process_text)
            self.assertNotIn(
                f"${{qc_output_stem}}.${{qc_model}}.{suffix}",
                process_text,
            )

    def test_quality_profile_is_used_only_as_a_runtime_argument(self):
        process_text = quality_process_text()

        self.assertIn('--model "${cfgText(megqc_config,', process_text)
        self.assertNotIn("qc_model =", process_text)


if __name__ == "__main__":
    unittest.main()
