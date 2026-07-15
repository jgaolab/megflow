import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = REPO_ROOT / "megflow" / "reports"
NEXTFLOW = os.environ.get("MEGFLOW_NEXTFLOW") or shutil.which("nextflow")


class NextflowReportLayoutIntegrationTests(unittest.TestCase):
    def _assert_live_trace_survives(self, report_package, managed_directories):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_root = root / "output"
            nextflow_dir = output_root / report_package / "nextflow"
            nextflow_dir.mkdir(parents=True)
            workflow_file = root / "layout_test.nf"
            config_file = root / "layout_test.config"

            workflow_file.write_text(
                f'''nextflow.enable.dsl=2

process rebuild_static_report {{
    output:
    path "done.txt"

    script:
    """
    {json.dumps(sys.executable)} - <<'PY'
from pathlib import Path
import sys
sys.path.insert(0, {json.dumps(str(REPORTS_DIR))})
from report_layout import prepare_report_output

prepare_report_output(
    Path({json.dumps(str(output_root / report_package))}),
    {json.dumps(managed_directories)},
)
Path("done.txt").write_text("done\\\\n", encoding="utf-8")
PY
    """
}}

workflow {{
    rebuild_static_report()
}}
''',
                encoding="utf-8",
            )
            config_file.write_text(
                f"""process.executor = 'local'
workDir = {json.dumps(str(output_root / 'work'))}
report {{
    enabled = true
    file = {json.dumps(str(nextflow_dir / 'report.html'))}
    overwrite = true
}}
timeline {{
    enabled = true
    file = {json.dumps(str(nextflow_dir / 'timeline.html'))}
    overwrite = true
}}
trace {{
    enabled = true
    file = {json.dumps(str(nextflow_dir / 'trace.txt'))}
    overwrite = true
}}
""",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    NEXTFLOW,
                    "-log",
                    str(nextflow_dir / "nextflow.log"),
                    "-C",
                    str(config_file),
                    "run",
                    str(workflow_file),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                timeout=120,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for filename in ("nextflow.log", "report.html", "timeline.html", "trace.txt"):
                self.assertTrue((nextflow_dir / filename).is_file(), filename)
            trace_text = (nextflow_dir / "trace.txt").read_text(encoding="utf-8")
            self.assertIn("rebuild_static_report", trace_text)
            self.assertIn("COMPLETED", trace_text)

    @unittest.skipUnless(NEXTFLOW, "set MEGFLOW_NEXTFLOW or install Nextflow")
    def test_live_trace_survives_dataset_and_corpus_report_rebuild(self):
        layouts = (
            ("static_html_report", ["assets", "data", "files", "subjects"]),
            ("corpus_static_html_report", ["assets", "data", "datasets"]),
        )
        for report_package, managed_directories in layouts:
            with self.subTest(report_package=report_package):
                self._assert_live_trace_survives(report_package, managed_directories)


if __name__ == "__main__":
    unittest.main()
