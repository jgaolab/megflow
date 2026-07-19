# Beginner-Friendly Quickstart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a beginner-oriented MEGFlow Quickstart that explains the Docker path model, includes a runnable starter overlay and SMN4Lang example, links detailed results, and provides goal-oriented configuration recipes.

**Architecture:** Keep the first run linear and conservative, stopping at `meg_ica`. Store the runnable starter overlay in `nextflow/quickstart.config`, render that exact file inside the Sphinx page, and protect the documentation contract with focused assertions in the existing Docker entrypoint test module.

**Tech Stack:** reStructuredText/Sphinx, Nextflow Groovy configuration, Python `unittest`, Docker entrypoint shell interface.

## Global Constraints

- Do not change pipeline behavior or scientific defaults.
- The active starter overlay stops at `meg_ica` and leaves every MEG selector at `null`.
- The first public SMN4Lang example selects subject `02`, task `RDR`, and run `1` without site-specific `/data/liaopan/...` paths.
- `nextflow/nextflow_for_docker.config` remains the authoritative complete Docker configuration.
- Omitted starter-overlay values inherit the image defaults; document this explicitly.
- Do not imply that task events, timing shifts, covariance choices, or source settings are universal.
- Preserve all unrelated working-tree changes.

---

### Task 1: Add a Failing Quickstart Documentation Contract

**Files:**
- Modify: `tests/test_docker_entrypoint_options.py`
- Test: `tests/test_docker_entrypoint_options.py`

**Interfaces:**
- Consumes: repository paths resolved from `REPO_ROOT`.
- Produces: two test methods that define the required starter overlay, command explanation, SMN4Lang selector, results links, recipes, and canonical-template link.

- [ ] **Step 1: Add Quickstart paths beside the existing installation path**

Add these constants immediately after `INSTALLATION_DOC`:

```python
QUICKSTART_DOC = REPO_ROOT / "docs" / "source" / "quickstart" / "quick_guide.rst"
QUICKSTART_CONFIG = REPO_ROOT / "nextflow" / "quickstart.config"
EXAMPLES_DOC = REPO_ROOT / "docs" / "source" / "reference" / "examples.rst"
```

- [ ] **Step 2: Add the two focused contract tests**

Add these methods after `test_help_and_installation_list_the_same_entrypoint_options`:

```python
    def test_quickstart_ships_a_safe_downloadable_project_overlay(self):
        self.assertTrue(QUICKSTART_CONFIG.is_file())
        config = QUICKSTART_CONFIG.read_text(encoding="utf-8")
        self.assertIn(
            'params.megflow.datasets.docker_input.steps = "meg_ica"', config
        )
        for selector in (
            "subject_id: null",
            "session_id: null",
            "task: null",
            "run_id: null",
            "raw_include_keywords: null",
            "raw_exclude_keywords: null",
        ):
            self.assertIn(selector, config)
        self.assertNotIn("/data/liaopan", config)

        quickstart = QUICKSTART_DOC.read_text(encoding="utf-8")
        self.assertIn(
            ".. literalinclude:: ../../../nextflow/quickstart.config", quickstart
        )
        self.assertIn(
            ":download:`Download ``quickstart.config`` "
            "<../../../nextflow/quickstart.config>`",
            quickstart,
        )
        self.assertIn(
            ":download:`authoritative Docker defaults "
            "<../../../nextflow/nextflow_for_docker.config>`",
            quickstart,
        )
        self.assertIn("HOST_PATH:CONTAINER_PATH", quickstart)
        for option in (
            "``-v``",
            "``-i``",
            "``-o``",
            "``--steps``",
            "``--resume``",
        ):
            self.assertIn(option, quickstart)

    def test_quickstart_covers_smn4lang_results_and_beginner_goals(self):
        quickstart = QUICKSTART_DOC.read_text(encoding="utf-8")
        for smn_selector in (
            'subject_id: ["02"]',
            'task: ["RDR"]',
            'run_id: ["1"]',
        ):
            self.assertIn(smn_selector, quickstart)
        self.assertNotIn("/data/liaopan", quickstart)

        for stage in (
            "``meg_artifacts``",
            "``meg_ica``",
            "``meg_epochs``",
            "``anatomy``",
            "``meg_all``",
            "``all``",
            "``report``",
        ):
            self.assertIn(stage, quickstart)
        for beginner_setting in (
            "meg_import.subject_id",
            "fixed_length_duration",
            "event_source",
            "preproc.steps",
            "deepreject.enabled",
            "find_bad_channels_lof: null",
            "ic_ecg",
            "ic_eog",
            "ic_outlier",
            "source_methods",
        ):
            self.assertIn(beginner_setting, quickstart)
        for detail_link in (
            ":doc:`report guide <../tutorial/reports>`",
            ":doc:`complete output guide <../tutorial/outputs>`",
            ":doc:`pipeline details <../details/pipeline_details>`",
        ):
            self.assertIn(detail_link, quickstart)

        examples = EXAMPLES_DOC.read_text(encoding="utf-8")
        self.assertIn(
            ":download:`quickstart.config <../../../nextflow/quickstart.config>`",
            examples,
        )
```

- [ ] **Step 3: Run the new tests and verify the RED state**

Run:

```bash
python scripts/validation/run_unittest_gate.py \
  test_docker_entrypoint_options.DockerEntrypointOptionTests.test_quickstart_ships_a_safe_downloadable_project_overlay \
  test_docker_entrypoint_options.DockerEntrypointOptionTests.test_quickstart_covers_smn4lang_results_and_beginner_goals
```

Expected: both tests fail on the missing `nextflow/quickstart.config` or missing
Quickstart content. They must not fail on a Python import or syntax error.

---

### Task 2: Ship the Starter Overlay and Rewrite the Quickstart

**Files:**
- Create: `nextflow/quickstart.config`
- Modify: `docs/source/quickstart/quick_guide.rst`
- Modify: `docs/source/reference/examples.rst`
- Test: `tests/test_docker_entrypoint_options.py`

**Interfaces:**
- Consumes: image defaults, the `docker_input` profile, and existing Sphinx pages.
- Produces: one valid project overlay plus a Quickstart whose literal include and download point to that exact file.

- [ ] **Step 1: Create the starter overlay**

Create `nextflow/quickstart.config` with exactly:

```groovy
// MEGFlow Docker project overlay for a first quality-control run.
//
// The Docker image loads its complete defaults before this file. Keep only
// study-specific changes here and add more blocks when your analysis needs
// them. A null selector means "include every discovered value".

params.megflow.datasets.docker_input.steps = "meg_ica"

params.megflow.datasets.docker_input.meg_import = [
    subject_id: null,              // e.g. ["01", "02"] or "first:10"
    session_id: null,              // e.g. ["01"]
    task: null,                    // e.g. ["rest"] or ["RDR"]
    run_id: null,                  // e.g. ["1"]
    raw_include_keywords: null,    // optional for non-BIDS filename discovery
    raw_exclude_keywords: null     // optional for non-BIDS filename discovery
]
```

- [ ] **Step 2: Replace the Quickstart with the approved linear flow**

Rewrite `docs/source/quickstart/quick_guide.rst` in this exact heading order:

```rst
Quickstart
==========

Before You Start
----------------

Understand the Docker Paths
---------------------------

Run One Command
---------------

Worked Example: SMN4Lang
------------------------

Check the Results
-----------------

Start from ``quickstart.config``
--------------------------------

What Do I Need to Change?
-------------------------

Select Subjects, Sessions, Tasks, or Runs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Stop at the Stage You Need
~~~~~~~~~~~~~~~~~~~~~~~~~~

Create Resting-State or Task Epochs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Change Filtering, Notch Frequency, or Sampling Rate
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Turn Artifact Detectors On or Off
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Control Which ICA Components Are Removed
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Prepare a Source-Level Run
~~~~~~~~~~~~~~~~~~~~~~~~~~

Rebuild Only the Report
~~~~~~~~~~~~~~~~~~~~~~~

Next Steps
----------
```

Use this exact generic command and state that only the host paths left of the
colons normally change:

```rst
.. code-block:: bash

   docker run --rm -it \
     -v /path/to/bids_or_raw_meg:/input \
     -v /path/to/output:/output \
     cplmeg/megflow:1.0.0 \
     -i /input \
     -o /output \
     --steps meg_ica \
     --resume
```

Before the command, define `-v HOST_PATH:CONTAINER_PATH` and show a table that
maps the editable host input/output paths to fixed `/input` and `/output`
aliases. After it, provide a table explaining `docker run`, `--rm`, `-it`,
`-v`, the image tag, `-i`, `-o`, `--steps meg_ica`, and `--resume`. State that
`meg_ica` includes import, continuous preprocessing, artifact detection, ICA
fitting/labeling/application, and report generation, but not epochs or source
analysis.

Use this exact SMN4Lang selector block:

```rst
.. code-block:: groovy

   params.megflow.datasets.docker_input.steps = "meg_ica"
   params.megflow.datasets.docker_input.meg_import = [
       subject_id: ["02"],
       session_id: null,
       task: ["RDR"],
       run_id: ["1"],
       raw_include_keywords: null,
       raw_exclude_keywords: null
   ]
```

Explain that BIDS prefixes are omitted, then use this exact command:

```rst
.. code-block:: bash

   docker run --rm -it \
     -v /path/to/SMN4Lang:/input \
     -v /path/to/SMN4Lang_megflow:/output \
     -v /path/to/quickstart.config:/config/quickstart.config:ro \
     cplmeg/megflow:1.0.0 \
     --config /config/quickstart.config \
     --input /input \
     --output /output \
     --resume
```

Explain `:ro`, explain why the command omits `--steps`, and link the advanced
SMN profile with:

```rst
:download:`advanced SMN4Lang profile
<../../../nextflow/nextflow_for_smn4lang.config>`
```

The result section must point to the dashboard, `preprocessed/`, Nextflow
report, and timeline, followed immediately by these three links:

```rst
:doc:`report guide <../tutorial/reports>`
:doc:`complete output guide <../tutorial/outputs>`
:doc:`pipeline details <../details/pipeline_details>`
```

Display and download the starter file, then link the defaults using exactly:

```rst
:download:`Download ``quickstart.config``
<../../../nextflow/quickstart.config>`

.. literalinclude:: ../../../nextflow/quickstart.config
   :language: groovy
   :caption: nextflow/quickstart.config

:download:`authoritative Docker defaults
<../../../nextflow/nextflow_for_docker.config>`
```

Explain overlay precedence: the image base loads first, the project overlay
changes only named fields, omitted values inherit defaults, and an explicit
single-dataset CLI `--steps` overrides the overlay stage for that run. Tell the
reader to mount the overlay under `/config` and not overwrite
`/program/nextflow/nextflow.config`.

The goal-oriented section must include these exact operational examples:

```groovy
// Recording selection.
params.megflow.datasets.docker_input.meg_import = [
    subject_id: ["01", "02"],
    session_id: ["01"],
    task: ["rest"],
    run_id: null,
    raw_include_keywords: null,
    raw_exclude_keywords: null
]

// Fixed-length resting epochs.
params.megflow.datasets.docker_input.steps = "meg_epochs"
params.megflow.datasets.docker_input.epochs = [
    task_type: "resting",
    resting: [fixed_length_duration: 2.0],
    epochs: [event_id: null, tmin: 0.0, tmax: 2.0,
             baseline: null, reject_by_annotation: true]
]

// Task events from BIDS events.tsv.
params.megflow.datasets.docker_input.steps = "meg_epochs"
params.megflow.datasets.docker_input.epochs = [
    task_type: "task",
    event_source: "event_file",
    event_time_shift_sec: 0.0,
    event_file: [trial_type: [target: 1, standard: 2]],
    epochs: [event_id: [1, 2], tmin: -0.2, tmax: 0.8,
             baseline: [null, 0.0], reject_by_annotation: true]
]

// Continuous preprocessing for 60 Hz line noise.
params.megflow.datasets.docker_input.preproc = [
    steps: [
        [filter: [l_freq: 1.0, h_freq: 100.0, method: "iir",
                  iir_params: [order: 5, ftype: "butter"]]],
        [notch_filter: [freqs: "60 120"]],
        [resample: [sfreq: 250]]
    ]
]

// Disable DeepReject.
params.megflow.datasets.docker_input.artifacts = [
    deepreject: [enabled: false]
]

// Disable only the inherited MNE LOF detector.
params.megflow.datasets.docker_input.artifacts = [
    find_bad_channels: [mne: [find_bad_channels_lof: null]]
]

// ICA exclusion categories.
params.megflow.datasets.docker_input.ic_label = [
    ic_ecg: true,
    ic_eog: true,
    ic_outlier: false
]

// Source method after all prerequisites are configured.
params.megflow.datasets.docker_input.steps = "meg_all"
params.megflow.datasets.docker_input.source = [
    source_methods: ["dSPM"]
]
```

Include a stage table for `meg_artifacts`, `meg_ica`, `meg_epochs`, `anatomy`,
`meg_all`, `all`, and `report`. Explain map-detector disabling with `null`,
including `pyprep: null`, `psd: null`, `osl: null`, and
`find_bad_segments: [osl: null]`. Keep the NormMEG-QC 1–100 Hz/250 Hz
comparability warning separate from ordinary `preproc.steps`. Name the
DeepReject switch as `artifacts.deepreject.enabled` so readers can find it in
the reference. Explain that source analysis additionally requires verified
ICA, event/epoch definitions, covariance, anatomy matching, coregistration,
and forward modeling.

Link the recipes to these pages:

```rst
:doc:`dataset configuration <../reference/configuration_datasets>`
:doc:`preprocessing configuration <../reference/configuration_preprocessing>`
:doc:`DeepReject <../reference/deepreject>`
:doc:`source configuration <../reference/configuration_source>`
:doc:`single-dataset examples <../reference/examples_single_dataset>`
:doc:`Full Workflow <../tutorial/full_workflow>`
```

End with the staged progression `meg_ica -> anatomy (if needed) -> meg_epochs
-> meg_all -> report` and links to the full workflow, reports, outputs,
configuration overview, and configuration examples.

- [ ] **Step 3: Add the starter overlay to canonical templates**

Insert before the authoritative Docker-default bullet in
`docs/source/reference/examples.rst`:

```rst
* :download:`quickstart.config <../../../nextflow/quickstart.config>` is the
  recommended first Docker project overlay. It selects all discovered MEG
  recordings and stops at ICA; add only study-specific overrides.
```

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run:

```bash
python scripts/validation/run_unittest_gate.py \
  test_docker_entrypoint_options.DockerEntrypointOptionTests.test_quickstart_ships_a_safe_downloadable_project_overlay \
  test_docker_entrypoint_options.DockerEntrypointOptionTests.test_quickstart_covers_smn4lang_results_and_beginner_goals
```

Expected: `Ran 2 tests` and `OK`.

- [ ] **Step 5: Run the complete Docker entrypoint test module**

Run:

```bash
python scripts/validation/run_unittest_gate.py test_docker_entrypoint_options
```

Expected: every test passes and the module ends with `OK`.

- [ ] **Step 6: Commit only the feature files**

Run:

```bash
git add \
  tests/test_docker_entrypoint_options.py \
  nextflow/quickstart.config \
  docs/source/quickstart/quick_guide.rst \
  docs/source/reference/examples.rst
git commit -m "docs: make quickstart beginner friendly"
```

Expected: one commit containing only those four files.

---

### Task 3: Validate and Visually Review the Built Documentation

**Files:**
- Verify: `docs/source/quickstart/quick_guide.rst`
- Verify: `nextflow/quickstart.config`
- Verify: `docs/source/reference/examples.rst`
- Verify: `tests/test_docker_entrypoint_options.py`

**Interfaces:**
- Consumes: Task 2's committed feature and the pinned docs environment.
- Produces: fresh unit-test, Sphinx-build, rendered-page, and diff evidence.

- [ ] **Step 1: Parse the shipped starter config with Nextflow**

Run in the configured `megprep` conda environment:

```bash
nextflow -C nextflow/quickstart.config config nextflow/megflow.nf -o flat >/tmp/megflow-quickstart-flat.config
```

Expected: exit code 0 and a non-empty
`/tmp/megflow-quickstart-flat.config` containing the flattened starter
configuration.

- [ ] **Step 2: Run routing/configuration contracts**

Run:

```bash
python scripts/validation/run_unittest_gate.py \
  test_nextflow_execution_config \
  test_docker_entrypoint_options
```

Expected: every test passes with `OK`.

- [ ] **Step 3: Build Sphinx strictly in the `megprep` conda environment**

Run:

```bash
sphinx-build -W --keep-going -b html docs/source docs/build/html
```

Expected: exit code 0 and `build succeeded` without warnings promoted to errors.

- [ ] **Step 4: Verify generated downloads and rendered headings**

Run:

```bash
test -f docs/build/html/quickstart/quick_guide.html
find docs/build/html/_downloads -type f -name 'quickstart.config' -print
rg -n \
  'Understand the Docker Paths|Worked Example: SMN4Lang|quickstart.config|What Do I Need to Change' \
  docs/build/html/quickstart/quick_guide.html
```

Expected: the HTML exists, a downloaded `quickstart.config` is printed, and
every required heading or label is found.

- [ ] **Step 5: Inspect the rendered Quickstart at desktop width**

Confirm command blocks preserve line breaks, path and stage tables remain
readable, the literal config is visible, download links are distinct, the
SMN4Lang example precedes recipes, and results links immediately follow the
first result summary.

- [ ] **Step 6: Review whitespace and the feature diff**

Run:

```bash
git diff --check HEAD~1..HEAD
git diff --stat HEAD~1..HEAD
git status --short
```

Expected: `git diff --check` is silent; the feature commit contains only four
intended files; unrelated pre-existing changes are outside the feature commit.
