import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def repository_owned_text_files():
    yield REPO_ROOT / "README.md"
    yield from (
        path for path in REPO_ROOT.glob("*.sh") if not path.name.startswith("._")
    )
    for root, patterns in (
        (REPO_ROOT / "scripts", ("*.sh", "*.ps1", "*.md")),
        (REPO_ROOT / "nextflow", ("*.sh", "*.nf", "*.config")),
        (REPO_ROOT / "docs" / "source", ("*.rst", "*.py")),
        (REPO_ROOT / "examples", ("*.ipynb", "*.md")),
    ):
        for pattern in patterns:
            yield from (
                path for path in root.rglob(pattern) if not path.name.startswith("._")
            )


class DockerImageNamespaceTests(unittest.TestCase):
    def test_repository_owned_sources_do_not_reference_legacy_image_namespace(self):
        legacy_image = "cmr" + "lab/megflow"
        legacy_sif = "cmr" + "lab_megflow"
        matches = []

        for path in repository_owned_text_files():
            text = path.read_text(encoding="utf-8")
            if legacy_image in text or legacy_sif in text:
                matches.append(str(path.relative_to(REPO_ROOT)))

        self.assertEqual(matches, [])

    def test_build_script_targets_published_image_namespace(self):
        script = (REPO_ROOT / "build_megflow.sh").read_text(encoding="utf-8")
        self.assertIn("IMAGE_NAME=cplmeg/megflow", script)


if __name__ == "__main__":
    unittest.main()
