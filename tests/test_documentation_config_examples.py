import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PIPELINE = REPO_ROOT / "nextflow" / "megflow.nf"
DOCKER_CONFIG = REPO_ROOT / "nextflow" / "nextflow_for_docker.config"
DOCKER_RUNNER = REPO_ROOT / "nextflow" / "run_for_docker.sh"
VALIDATION_RUNNER = REPO_ROOT / "scripts" / "validation" / "run_validation.sh"
NEXTFLOW = os.environ.get("MEGFLOW_NEXTFLOW") or shutil.which("nextflow")

EXAMPLE_PAGES = (
    REPO_ROOT / "docs" / "source" / "reference" / "examples.rst",
    REPO_ROOT / "docs" / "source" / "reference" / "examples_single_dataset.rst",
    REPO_ROOT / "docs" / "source" / "reference" / "examples_profiles.rst",
)


@dataclass(frozen=True)
class DocumentationCodeBlock:
    page: Path
    anchor: str
    language: str
    index: int
    line: int
    text: str

    @property
    def key(self):
        relative_page = self.page.relative_to(REPO_ROOT).as_posix()
        return f"{relative_page}::{self.anchor}::{self.language}::{self.index}"


def block_key(page_name, anchor, language, index=1):
    return (
        f"docs/source/reference/{page_name}::{anchor}::{language}::{index}"
    )


EXPECTED_BLOCK_KEYS = {
    block_key("examples.rst", "example-canonical-templates", "groovy"),
    block_key("examples_single_dataset.rst", "example-first-meg-pass", "groovy"),
    block_key("examples_single_dataset.rst", "example-first-meg-pass", "bash"),
    block_key("examples_single_dataset.rst", "example-anatomy-only", "groovy"),
    block_key("examples_single_dataset.rst", "example-anatomy-only", "bash"),
    block_key("examples_single_dataset.rst", "example-full-meg", "groovy"),
    block_key("examples_single_dataset.rst", "example-full-meg", "bash"),
    block_key("examples_single_dataset.rst", "example-resting-epochs", "groovy"),
    block_key("examples_single_dataset.rst", "example-bids-events", "groovy"),
    block_key("examples_single_dataset.rst", "example-trigger-events", "groovy"),
    block_key("examples_single_dataset.rst", "example-lcmv-covariance", "groovy", 1),
    block_key("examples_single_dataset.rst", "example-lcmv-covariance", "groovy", 2),
    block_key("examples_single_dataset.rst", "example-raw-covariance", "groovy", 1),
    block_key("examples_single_dataset.rst", "example-raw-covariance", "groovy", 2),
    block_key("examples_single_dataset.rst", "example-maxwell-tsss", "groovy"),
    block_key("examples_profiles.rst", "example-deepreject", "groovy"),
    block_key("examples_profiles.rst", "example-recording-overrides", "groovy"),
    block_key("examples_profiles.rst", "example-docker-corpus", "text"),
    block_key("examples_profiles.rst", "example-docker-corpus", "groovy"),
    block_key("examples_profiles.rst", "example-docker-corpus", "bash"),
    block_key("examples_profiles.rst", "example-source-multi-dataset", "bash", 1),
    block_key("examples_profiles.rst", "example-source-multi-dataset", "bash", 2),
    block_key("examples_profiles.rst", "example-cluster-execution", "bash"),
}


GROOVY_RUNTIME_PROFILES = {
    block_key("examples.rst", "example-canonical-templates", "groovy"): (
        "docker_input",
    ),
    block_key("examples_single_dataset.rst", "example-first-meg-pass", "groovy"): (
        "docker_input",
    ),
    block_key("examples_single_dataset.rst", "example-anatomy-only", "groovy"): (
        "docker_input",
    ),
    block_key("examples_single_dataset.rst", "example-full-meg", "groovy"): (
        "docker_input",
    ),
    block_key("examples_single_dataset.rst", "example-resting-epochs", "groovy"): (
        "docker_input",
    ),
    block_key("examples_single_dataset.rst", "example-bids-events", "groovy"): (
        "docker_input",
    ),
    block_key("examples_single_dataset.rst", "example-trigger-events", "groovy"): (
        "docker_input",
    ),
    block_key("examples_single_dataset.rst", "example-lcmv-covariance", "groovy", 1): (
        "docker_input",
    ),
    block_key("examples_single_dataset.rst", "example-lcmv-covariance", "groovy", 2): (
        "docker_input",
    ),
    block_key("examples_single_dataset.rst", "example-raw-covariance", "groovy", 1): (
        "docker_input",
    ),
    block_key("examples_single_dataset.rst", "example-raw-covariance", "groovy", 2): (
        "docker_input",
    ),
    block_key("examples_single_dataset.rst", "example-maxwell-tsss", "groovy"): (
        "MEGIN_SITE_A",
    ),
    block_key("examples_profiles.rst", "example-deepreject", "groovy"): (
        "MEG_MASC_word",
    ),
    block_key("examples_profiles.rst", "example-recording-overrides", "groovy"): (
        "LanguageStudy",
    ),
    block_key("examples_profiles.rst", "example-docker-corpus", "groovy"): (
        "WAND",
        "SMN4Lang",
        "MEG-MASC",
    ),
}


PREVIEW_EXAMPLES = {
    block_key("examples_single_dataset.rst", "example-anatomy-only", "groovy"),
    block_key("examples_single_dataset.rst", "example-full-meg", "groovy"),
    block_key("examples_single_dataset.rst", "example-lcmv-covariance", "groovy", 1),
    block_key("examples_single_dataset.rst", "example-raw-covariance", "groovy", 1),
    block_key("examples_profiles.rst", "example-recording-overrides", "groovy"),
    block_key("examples_profiles.rst", "example-docker-corpus", "groovy"),
}


EXPECTED_LINKED_CONFIGS = {
    "nextflow/nextflow.config",
    "nextflow/nextflow_for_docker.config",
    "nextflow/nextflow_maxwell_tsss_example.config",
    "nextflow/nextflow_multi_dataset_demo.config",
    "nextflow/nextflow_opm_cog_task_overrides_example.config",
    "nextflow/quickstart.config",
}


def extract_code_blocks(page):
    lines = page.read_text(encoding="utf-8").splitlines()
    current_anchor = None
    counters = defaultdict(int)
    blocks = []
    index = 0
    while index < len(lines):
        line = lines[index]
        anchor_match = re.match(r"^\.\. _([^:]+):\s*$", line)
        if anchor_match:
            current_anchor = anchor_match.group(1)

        code_match = re.match(r"^(\s*)\.\. code-block::\s+([\w+-]+)\s*$", line)
        if not code_match:
            index += 1
            continue
        if current_anchor is None:
            raise AssertionError(f"Code block without an anchor: {page}:{index + 1}")

        directive_indent = len(code_match.group(1))
        language = code_match.group(2)
        content_lines = []
        cursor = index + 1
        while cursor < len(lines):
            candidate = lines[cursor]
            candidate_indent = len(candidate) - len(candidate.lstrip())
            if candidate and candidate_indent <= directive_indent:
                break
            content_lines.append(candidate)
            cursor += 1

        while content_lines and not content_lines[0].strip():
            content_lines.pop(0)
        while content_lines and not content_lines[-1].strip():
            content_lines.pop()
        content = textwrap.dedent("\n".join(content_lines)).rstrip()
        counters[(current_anchor, language)] += 1
        blocks.append(
            DocumentationCodeBlock(
                page=page,
                anchor=current_anchor,
                language=language,
                index=counters[(current_anchor, language)],
                line=index + 1,
                text=content,
            )
        )
        index = cursor
    return blocks


def all_blocks():
    return [block for page in EXAMPLE_PAGES for block in extract_code_blocks(page)]


def all_documented_groovy_snippets():
    snippets = []
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    snippets.extend(
        match.group(1).strip()
        for match in re.finditer(r"(?ms)^```groovy\s*\n(.*?)^```\s*$", readme)
    )

    for page in sorted((REPO_ROOT / "docs" / "source").rglob("*.rst")):
        if page.name.startswith("._"):
            continue
        lines = page.read_text(encoding="utf-8").splitlines()
        index = 0
        while index < len(lines):
            match = re.match(r"^(\s*)\.\. code-block::\s+groovy\s*$", lines[index])
            if not match:
                index += 1
                continue
            directive_indent = len(match.group(1))
            content = []
            index += 1
            while index < len(lines):
                line = lines[index]
                line_indent = len(line) - len(line.lstrip())
                if line and line_indent <= directive_indent:
                    break
                content.append(line)
                index += 1
            snippet = textwrap.dedent("\n".join(content)).strip()
            if snippet:
                snippets.append(snippet)
    return snippets


def linked_config_paths():
    paths = set()
    for page in EXAMPLE_PAGES:
        content = page.read_text(encoding="utf-8")
        for target in re.findall(r":download:`[^`]*?<([^>]+)>`", content, re.DOTALL):
            resolved = (page.parent / target.strip()).resolve()
            paths.add(resolved.relative_to(REPO_ROOT).as_posix())
        paths.update(
            re.findall(
                r"https://github\.com/jgaolab/megflow/blob/main/(nextflow/[^>`\s]+)",
                content,
            )
        )
    return paths


def documented_docker_options(block):
    command = re.sub(r"\\\n\s*", " ", block.text)
    tokens = shlex.split(command)
    image_index = next(
        index
        for index, token in enumerate(tokens)
        if token.startswith("cplmeg/megflow:")
    )
    return {token for token in tokens[image_index + 1 :] if token.startswith("-")}


def docker_entrypoint_options():
    runner = DOCKER_RUNNER.read_text(encoding="utf-8")
    argument_parser = runner.split("# Process input arguments", 1)[1].split(
        "# If --view_report", 1
    )[0]
    options = set()
    for pattern in re.findall(
        r"^\s*([*.A-Za-z0-9_|-]+)\)\s+", argument_parser, re.MULTILINE
    ):
        for option in pattern.split("|"):
            option = option.strip()
            if option.startswith("-"):
                options.add(option)
    return options


def slug(value):
    return re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()


def write_runtime_config(path, block, profiles, root):
    output_dir = root / "output"
    dataset_assignments = [
        'params.megflow.datasets["docker_input"] = '
        'params.megflow.datasets["docker_input"] ?: [:]',
        'params.megflow.datasets["docker_input"].dataset_dir = ""',
    ]
    for profile in profiles:
        dataset_dir = root / "datasets" / slug(profile)
        dataset_dir.mkdir(parents=True, exist_ok=True)
        profile_literal = json.dumps(profile)
        dataset_assignments.extend(
            [
                f"params.megflow.datasets[{profile_literal}] = "
                f"params.megflow.datasets[{profile_literal}] ?: [:]",
                f"params.megflow.datasets[{profile_literal}].dataset_dir = "
                f"{json.dumps(str(dataset_dir))}",
                f'params.megflow.datasets[{profile_literal}].steps = "report"',
            ]
        )

    report_scope = "corpus" if len(profiles) > 1 else "dataset"
    path.write_text(
        textwrap.dedent(
            f"""
            includeConfig {json.dumps(str(DOCKER_CONFIG))}

            {block.text}

            // Synthetic documentation-validation overrides.
            params.megflow.code_dir = {json.dumps(str(REPO_ROOT / 'megflow'))}
            params.megflow.output_dir = {json.dumps(str(output_dir))}
            params.megflow.corpus_root = ""
            params.megflow.dataset_include = {json.dumps(list(profiles))}
            params.megflow.dataset_exclude = []
            params.megflow.report_scope = "{report_scope}"
            params.megflow.error_mode = "strict"
            params.megflow.defaults.steps = "report"
            params.megflow.defaults.report.static_task_log_mode = "none"
            {os.linesep.join(dataset_assignments)}

            workDir = {json.dumps(str(root / 'work'))}
            log.file = {json.dumps(str(output_dir / 'nextflow.log'))}
            report.enabled = false
            timeline.enabled = false
            trace.enabled = false
            docker.enabled = false
            process {{
                executor = "local"
                maxForks = 1
                withName: '.*' {{
                    cpus = 1
                    memory = "512 MB"
                }}
            }}
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return output_dir


class DocumentationConfigExamplesTests(unittest.TestCase):
    maxDiff = None

    def test_readme_links_canonical_public_scripts_without_cleanup_helper(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        run_scripts = (
            "examples/run_scripts/single_dataset_docker.sh",
            "examples/run_scripts/corpus_docker.sh",
            "examples/run_scripts/corpus_source.sh",
            "examples/run_scripts/interactive_report.sh",
        )
        development_scripts = (
            "scripts/development/build_megflow.sh",
            "scripts/development/build_docs.sh",
            "scripts/development/docker2sif.sh",
            "scripts/development/rm_none_docker.sh",
        )

        for script in run_scripts + development_scripts:
            with self.subTest(script=script):
                self.assertIn(f"]({script})", readme)
        self.assertNotIn("clean_docker.sh", readme)

    def test_readme_development_uses_the_public_helper_workflow_order(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        development = readme.index("## 🛠️ Development")
        subsections = (
            "### Prerequisites",
            "### Local Development Setup",
            "### Public Developer-Script Reference",
            "### Building the Docker Image",
            "### Building and Strictly Validating Documentation",
            "### Validation and Regression-Test Modes",
            "### Advanced Local Docker-to-SIF Conversion",
            "### Dangling-Image Cleanup Safety",
            "### Pull-Request Workflow",
        )
        positions = [readme.index(subsection, development) for subsection in subsections]
        self.assertEqual(positions, sorted(positions))

    def test_user_facing_wand_examples_use_clean_display_name(self):
        doc_paths = [REPO_ROOT / "README.md"]
        doc_paths.extend(
            path
            for path in (REPO_ROOT / "docs" / "source").rglob("*.rst")
            if not path.name.startswith("._")
        )
        offenders = {
            str(path.relative_to(REPO_ROOT)): [
                index
                for index, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), start=1
                )
                if "WAND_Extracted" in line
            ]
            for path in doc_paths
        }
        self.assertEqual(
            {path: lines for path, lines in offenders.items() if lines},
            {},
        )

    def test_validation_runner_executes_documented_examples(self):
        runner = VALIDATION_RUNNER.read_text(encoding="utf-8")
        self.assertIn("test_documentation_config_examples", runner)

    def test_every_documentation_code_block_is_in_the_validation_manifest(self):
        actual = {block.key for block in all_blocks()}
        self.assertEqual(actual, EXPECTED_BLOCK_KEYS)

        groovy_keys = {
            block.key for block in all_blocks() if block.language == "groovy"
        }
        self.assertEqual(groovy_keys, set(GROOVY_RUNTIME_PROFILES))

    def test_linked_configs_exist_and_are_tracked(self):
        linked = linked_config_paths()
        self.assertEqual(linked, EXPECTED_LINKED_CONFIGS)
        for relative_path in sorted(linked):
            with self.subTest(config=relative_path):
                self.assertTrue((REPO_ROOT / relative_path).is_file())
                result = subprocess.run(
                    ["git", "ls-files", "--error-unmatch", relative_path],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_documented_shell_commands_are_valid_bash(self):
        for block in all_blocks():
            if block.language != "bash":
                continue
            with self.subTest(example=block.key):
                result = subprocess.run(
                    ["bash", "-n"],
                    input=block.text + "\n",
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_documented_docker_flags_match_the_current_entrypoint(self):
        supported = docker_entrypoint_options()
        docker_blocks = [
            block
            for block in all_blocks()
            if block.language == "bash" and "docker run" in block.text
        ]
        self.assertTrue(docker_blocks)
        for block in docker_blocks:
            with self.subTest(example=block.key):
                unknown = documented_docker_options(block) - supported
                self.assertEqual(unknown, set())

    def test_documented_enum_values_match_current_implementations(self):
        blocks = all_blocks()
        groovy = "\n".join(
            block.text for block in blocks if block.language == "groovy"
        )
        bash = "\n".join(block.text for block in blocks if block.language == "bash")

        pipeline = PIPELINE.read_text(encoding="utf-8")
        supported_steps = set(
            re.findall(r"case '([^']+)':", pipeline.split("Map parseMegPipelineSteps", 1)[1])
        )
        documented_steps = set(
            re.findall(r"\bsteps\s*(?:=|:)\s*[\"']([^\"']+)", groovy)
        )
        documented_steps.update(re.findall(r"--steps\s+([^\s\\]+)", bash))
        self.assertEqual(documented_steps - supported_steps, set())

        epochs_source = (REPO_ROOT / "megflow" / "epochs.py").read_text(
            encoding="utf-8"
        )
        supported_task_types = set(
            re.findall(r"task_type\s*(?:==|!=)\s*'([^']+)'", epochs_source)
        )
        documented_task_types = set(
            re.findall(r"task_type\s*(?:=|:)\s*[\"']([^\"']+)", groovy)
        )
        self.assertTrue(documented_task_types)
        self.assertEqual(documented_task_types - supported_task_types, set())

        supported_event_sources = set(
            re.findall(r"event_source\s*(?:==|!=)\s*'([^']+)'", epochs_source)
        )
        documented_event_sources = set(
            re.findall(r"event_source\s*(?:=|:)\s*[\"']([^\"']+)", groovy)
        )
        self.assertTrue(documented_event_sources)
        self.assertEqual(documented_event_sources - supported_event_sources, set())

        artifacts_source = (
            REPO_ROOT / "megflow" / "meg_detect_artifacts.py"
        ).read_text(encoding="utf-8")
        mode_section = artifacts_source.split("DEEPREJECT_MODE_PRESETS = {", 1)[1].split(
            "\n}\n\nDEEPREJECT_RECOMMENDED_INPUT", 1
        )[0]
        supported_deepreject_modes = set(
            re.findall(r'^    "([^"]+)": \{', mode_section, re.MULTILINE)
        )
        documented_deepreject_modes = set()
        for block_match in re.finditer(
            r"(?s)\bdeepreject\s*(?:=|:)?\s*(?:\{|\[)(.*?)(?:\}|\])",
            groovy,
        ):
            mode = re.search(
                r"\bmode\s*(?:=|:)\s*[\"']([^\"']+)",
                block_match.group(1),
            )
            if mode:
                documented_deepreject_modes.add(mode.group(1))
        self.assertTrue(documented_deepreject_modes)
        self.assertEqual(
            documented_deepreject_modes - supported_deepreject_modes, set()
        )

        utils_source = (REPO_ROOT / "megflow" / "utils.py").read_text(
            encoding="utf-8"
        )
        aliases_section = utils_source.split("aliases = {", 1)[1].split("\n    }", 1)[0]
        supported_source_methods = set(
            re.findall(r'"[^"]+": "([^"]+)"', aliases_section)
        )
        documented_source_methods = set()
        for values in re.findall(
            r"source_methods\s*(?:=|:)\s*\[([^\]]*)\]", groovy
        ):
            documented_source_methods.update(
                re.findall(r"[\"']([^\"']+)[\"']", values)
            )
        self.assertTrue(documented_source_methods)
        self.assertEqual(documented_source_methods - supported_source_methods, set())

        allowed_match_line = re.search(
            r"allowedMatchKeys = \[([^\]]+)\] as Set", pipeline
        )
        self.assertIsNotNone(allowed_match_line)
        supported_match_fields = set(
            re.findall(r"'([^']+)'", allowed_match_line.group(1))
        )
        documented_match_fields = set()
        for match_groups in re.findall(
            r"(?s)\bmatch\s*(?:=|:)?\s*(?:\[([^\]]+)|\{([^}]+))",
            groovy,
        ):
            match_body = match_groups[0] or match_groups[1]
            documented_match_fields.update(
                re.findall(
                    r"(?:^|,|\n)\s*([A-Za-z_]\w*)\s*(?:=|:)", match_body
                )
            )
        self.assertTrue(documented_match_fields)
        self.assertEqual(documented_match_fields - supported_match_fields, set())

    def test_explicit_lcmv_rank_example_also_enables_lcmv(self):
        lcmv_rank_key = block_key(
            "examples_single_dataset.rst",
            "example-lcmv-covariance",
            "groovy",
            2,
        )
        block = next(block for block in all_blocks() if block.key == lcmv_rank_key)
        methods = re.search(
            r"source_methods\s*(?:=|:)\s*\[([^\]]+)\]", block.text
        )
        self.assertIsNotNone(methods)
        self.assertIn('"LCMV"', methods.group(1))

    def test_documented_source_runner_exists_and_has_valid_bash(self):
        runner = REPO_ROOT / "run_MultiDatasets_sourcecode.sh"
        self.assertTrue(runner.is_file())
        result = subprocess.run(
            ["bash", "-n", str(runner)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(NEXTFLOW, "set MEGFLOW_NEXTFLOW or install Nextflow")
class DocumentationConfigExamplesIntegrationTests(unittest.TestCase):
    maxDiff = None

    def run_nextflow(self, command, *, cwd, timeout=180):
        result = subprocess.run(
            [NEXTFLOW, *command],
            cwd=cwd,
            env=dict(
                os.environ,
                NXF_ANSI_LOG="false",
                NXF_OFFLINE="true",
                NXF_SYNTAX_PARSER="v1",
            ),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result, result.stdout + result.stderr

    def test_every_linked_config_is_accepted_by_nextflow(self):
        for relative_path in sorted(EXPECTED_LINKED_CONFIGS):
            config = REPO_ROOT / relative_path
            with self.subTest(config=relative_path):
                result, combined = self.run_nextflow(
                    ["-C", str(config), "config", str(PIPELINE), "-o", "flat"],
                    cwd=REPO_ROOT,
                    timeout=90,
                )
                self.assertEqual(result.returncode, 0, combined)

    def test_all_documented_groovy_blocks_parse_together(self):
        snippets = all_documented_groovy_snippets()
        self.assertTrue(snippets)
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "documented-examples.config"
            config.write_text("\n\n".join(snippets) + "\n", encoding="utf-8")
            result, combined = self.run_nextflow(
                ["-C", str(config), "config", str(PIPELINE), "-o", "flat"],
                cwd=REPO_ROOT,
                timeout=90,
            )
        self.assertEqual(result.returncode, 0, combined)

    def test_every_groovy_example_parses_and_representative_examples_preview(self):
        blocks = {block.key: block for block in all_blocks()}
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for key, profiles in GROOVY_RUNTIME_PROFILES.items():
                case_root = root / slug(key)
                case_root.mkdir(parents=True)
                config = case_root / "example.config"
                output_dir = write_runtime_config(
                    config, blocks[key], profiles, case_root
                )
                output_dir.mkdir(parents=True)
                (output_dir / ".nextflow").mkdir()

                if key in PREVIEW_EXAMPLES:
                    command = [
                        "-log",
                        str(output_dir / "driver.log"),
                        "-C",
                        str(config),
                        "run",
                        str(PIPELINE),
                        "-preview",
                    ]
                    phase = "preview"
                    timeout = 180
                else:
                    command = [
                        "-C",
                        str(config),
                        "config",
                        str(PIPELINE),
                        "-o",
                        "flat",
                    ]
                    phase = "parse"
                    timeout = 90

                with self.subTest(example=key, phase=phase):
                    result, combined = self.run_nextflow(
                        command,
                        cwd=output_dir,
                        timeout=timeout,
                    )
                    if result.returncode != 0 and (output_dir / "driver.log").is_file():
                        combined += "\n--- driver.log ---\n" + (
                            output_dir / "driver.log"
                        ).read_text(encoding="utf-8", errors="replace")
                    self.assertEqual(result.returncode, 0, combined)


if __name__ == "__main__":
    unittest.main()
