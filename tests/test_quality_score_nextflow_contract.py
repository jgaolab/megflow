from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NEXTFLOW_FILE = ROOT / "nextflow" / "megflow.nf"


def quality_process_text() -> str:
    text = NEXTFLOW_FILE.read_text(encoding="utf-8")
    return text.split("process score_meg_quality", 1)[1].split(
        "process meg_basic_preproc",
        1,
    )[0]


def test_quality_process_stages_canonical_public_names():
    process_text = quality_process_text()

    for suffix in (
        "summary.json",
        "component_scores.csv",
        "normative_quality_score.png",
    ):
        assert f"${{qc_output_stem}}.{suffix}" in process_text
        assert f"${{qc_output_stem}}.${{qc_model}}.{suffix}" not in process_text


def test_quality_profile_is_used_only_as_a_runtime_argument():
    process_text = quality_process_text()

    assert '--model "${cfgText(megqc_config,' in process_text
    assert "qc_model =" not in process_text
