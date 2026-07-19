# Quickstart Redesign Design

## Goal

Rebuild the MEGFlow Quickstart around a beginner's first successful run. A new
user should understand the Docker command, run through ICA on their own data,
inspect the main results, and know exactly where to make the first common
configuration changes without reading the full parameter reference first.

## Audience and Success Criteria

The primary reader has MEG data but may be unfamiliar with Docker volume
mounts, container paths, Nextflow stage names, or MEGFlow's layered
configuration.

The redesigned page succeeds when the reader can:

1. distinguish a host path from its fixed container alias;
2. identify every value they normally need to edit in the first Docker run;
3. explain how `-v`, `-i`, `-o`, `--steps`, and `--resume` relate;
4. run a conservative first pass through ICA;
5. adapt a concrete SMN4Lang example for one subject, task, and run;
6. find the static report and the detailed output reference;
7. download and edit a small `quickstart.config` overlay;
8. find the authoritative Docker defaults when a setting is not in that
   overlay; and
9. locate a copyable recipe for subject/task selection, stage selection,
   epochs, source analysis, artifact or ICA switches, and preprocessing.

## Information Architecture

The page will follow the order in which a beginner encounters decisions:

1. **Choose paths.** Introduce the required host input and output directories,
   and defer anatomy until a later source-level run.
2. **Understand the command.** Explain Docker options separately from MEGFlow
   options. Show the `HOST_PATH:CONTAINER_PATH` model before asking the reader
   to run anything.
3. **Run the first dataset.** Provide one generic Docker command that stops at
   `meg_ica`, followed by an explicit "change these values" checklist.
4. **Follow a worked example.** Show SMN4Lang `sub-02`, task `RDR`, run `1`,
   including the selector changes and complete Docker command.
5. **Inspect results.** Point first to the dataset dashboard, then to the
   processed data, and link to the full report and output guides.
6. **Start configuring.** Display and offer a download of
   `nextflow/quickstart.config`, explain overlay inheritance, and link the
   authoritative `nextflow/nextflow_for_docker.config` defaults.
7. **Change the workflow by goal.** Provide short, copyable recipes organized
   by the user's intent rather than by the internal configuration schema.
8. **Progress safely.** Recommend `meg_ica -> anatomy -> meg_epochs -> meg_all`
   and link the full-workflow tutorial.

## Docker Command Teaching Model

The command explanation will use a two-column mapping:

| Host path, edited by the user | Container alias, normally unchanged |
| --- | --- |
| `/path/to/bids_or_raw_meg` | `/input` |
| `/path/to/output` | `/output` |
| `/path/to/quickstart.config` | `/config/quickstart.config` |

The text will explicitly state that `-v` creates the mapping and that `-i` and
`-o` pass the container-side aliases to MEGFlow. It will also distinguish
Docker flags (`--rm`, `-it`, and `-v`) from MEGFlow entrypoint flags (`-i`,
`-o`, `--config`, `--steps`, and `--resume`). The generic command will say that
the host paths to the left of each colon are the values normally changed.

The first run will use `--steps meg_ica`. The page will explain that this
includes import, continuous preprocessing, artifact detection, ICA fitting and
labeling, ICA application, and the static report, while intentionally avoiding
event, covariance, anatomy, and source-model assumptions.

## Starter Configuration Contract

Create `nextflow/quickstart.config` as a valid Docker project overlay. It will
be short enough for a new user to understand and safe to run without enabling
dataset-specific epoch or source assumptions. Its active settings will:

- stop at `meg_ica`; and
- expose the complete first-pass MEG selectors for subject, session, task,
  run, and raw filename inclusion or exclusion.

The Quickstart will render the file from the repository rather than duplicate
its contents manually, and will provide a download link. This keeps the shown
example identical to the tested file.

The page will explain these configuration rules next to the file:

- the Docker image loads its complete base configuration first;
- `quickstart.config` overrides only the fields it contains;
- omitted parameters continue to inherit image defaults;
- users add a block only when their study needs to change it; and
- `nextflow/nextflow_for_docker.config` is the authoritative complete Docker
  configuration and is linked for comparison, not presented as the normal
  project file to copy wholesale.

## Worked SMN4Lang Example

The worked example will assume a local SMN4Lang dataset directory and select:

- subject `02` (without the BIDS `sub-` prefix in the config);
- task `RDR`; and
- run `1`.

It will show the exact `meg_import` changes and a complete Docker command that
mounts the dataset, a separate output directory, and the user's copy of
`quickstart.config`. The example remains a first-pass `meg_ica` run. It will
not copy site-specific `/data/liaopan/...` paths into the public command; host
paths will make clear which SMN4Lang directories the reader substitutes.

The existing full SMN4Lang source configuration remains the advanced example
for epochs, covariance, anatomy, and source reconstruction. The Quickstart
will link onward rather than implying that its timing correction or source
settings are universal.

## Goal-Oriented Recipes

The "What Do I Need to Change?" section will become a set of beginner-facing
goals. Each recipe will name the setting, give a minimal snippet where safe,
state the matching `steps` value, and link to the detailed reference.

Required recipes are:

1. **Select recordings:** `meg_import.subject_id`, `session_id`, `task`, and
   `run_id`, including the absence of BIDS prefixes and the `first:N` selector.
2. **Stop at a milestone:** a compact table for `meg_artifacts`, `meg_ica`,
   `meg_epochs`, `anatomy`, `meg_all`, `all`, and `report`.
3. **Create epochs:** separate resting-state fixed-length and task-event
   guidance. Dataset-specific event source, event ids, timing, baseline, and
   rejection settings must be checked before running.
4. **Change continuous preprocessing:** filter, notch, and resample settings,
   with the NormMEG-QC comparability warning kept separate from the main
   preprocessing block.
5. **Control artifact detection:** show the supported DeepReject enable switch
   and direct readers to detector-specific configuration for bad channels and
   bad segments rather than inventing a generic boolean for map-based
   detectors.
6. **Control ICA exclusions:** show the ECG, EOG, and outlier category switches
   and distinguish them from classifier-method switches.
7. **Prepare source analysis:** identify the prerequisite chain—verified ICA,
   events/epochs, covariance, anatomy matching, coregistration, forward model,
   and source method—and link the full workflow plus source configuration.
8. **Rebuild results only:** use `--steps report` against existing output.

No recipe will imply that task event ids, timing shifts, covariance choices,
or source parameters are safe universal defaults.

## Results Navigation

The result section will retain the immediate paths needed after a first run:

- `<output>/static_html_report/index.html` for the main QC dashboard;
- `<output>/preprocessed/` for processing derivatives;
- the packaged Nextflow report and timeline for execution diagnostics.

It will then link directly to:

- `tutorial/reports` for interpreting static and interactive reports;
- `tutorial/outputs` for the full directory layout and important sidecars; and
- `details/pipeline_details` for what each processing stage does.

This creates a short first check without reducing all results to the
`preprocessed` directory.

## Files and Scope

Planned documentation changes are limited to:

- modify `docs/source/quickstart/quick_guide.rst` for the redesigned page;
- create `nextflow/quickstart.config` as the downloadable starter overlay;
- update `docs/source/reference/examples.rst` so the starter overlay appears
  alongside the canonical templates; and
- add a focused contract test that checks the starter overlay, its Quickstart
  display/download references, the authoritative-default link, the SMN4Lang
  selector example, and the detailed results links.

Pipeline behavior, scientific defaults, and existing site-specific run scripts
are out of scope. Existing unrelated working-tree changes must remain
untouched.

## Validation

Validation will cover both content correctness and build integrity:

1. parse or load `nextflow/quickstart.config` through the repository's
   available Nextflow/config validation path;
2. run focused tests that cover Docker configuration precedence or docs-facing
   configuration contracts when applicable;
3. build the Sphinx documentation with warnings treated as errors;
4. verify every new `:doc:`, `:download:`, reference, and literal-include path;
5. inspect the rendered Quickstart for code-block wrapping, table readability,
   heading hierarchy, and visible download/default-config links; and
6. review the final diff to confirm no unrelated files were changed.
