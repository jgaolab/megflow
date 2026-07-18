.. _configuration-datasets:

Dataset and Stage Configuration
===============================

This page defines how MEGFlow resolves profiles, discovers datasets and recordings, selects processing stages, and imports MRI and MEG inputs. Read it before changing scientific processing parameters.

.. _configuration-profile-resolution:

Profile Resolution
------------------

Configuration is resolved in three levels:

1. ``params.megflow.defaults`` defines the shared processing policy.
2. ``params.megflow.datasets.<dataset_name>`` overrides the defaults for one
   dataset.
3. ``recordings`` entries inside a dataset override the effective dataset
   config for recordings whose BIDS entities match the ``match`` block.

MEGFlow applies a deep merge at each level. Nested maps merge recursively;
scalars and lists replace the inherited value; an explicit ``null`` replaces
the inherited value with null rather than deleting the key. For example, a
dataset can replace only ``preproc.steps`` while inheriting ``megqc``, ``ica``,
and all later modules.

Not every field is meaningful at every scope:

.. list-table::
   :header-rows: 1
   :widths: 24 28 48

   * - Scope
     - Typical fields
     - Important limits
   * - Global ``params.megflow``
     - ``code_dir``, ``output_dir``, ``corpus_root``, dataset filters,
       ``fs_subjects_root``, ``error_mode``
     - Controls discovery and roots for the complete run.
   * - ``defaults``
     - Shared ``steps``, ``rank_policy``, and all processing module blocks
     - Applied before each dataset profile.
   * - Dataset profile
     - Paths, import filters, anatomy, ``steps``, and any processing module
     - This is the correct scope for discovery, MRI processing, report
       thresholds, and the broadest stage that the dataset should run.
   * - Recording profile
     - ``rank_policy``, ``megqc``, ``preproc``, ``digitization``, ``artifacts``, ``ica``,
       ``ic_label``, ``epochs``, ``covariance``, ``coreg``, ``forward``,
       ``source``, and MEG-stage reduction
     - Applied only after MEG import. It cannot change which files were
       discovered, create a missing anatomy plan, or change dataset-level report
       thresholds or BEM construction.

Output Directory Contract
-------------------------

Only the run and dataset roots are public output settings. Change
``params.megflow.output_dir`` to relocate the complete run, or set the
top-level ``output_dir`` inside one dataset profile to relocate that dataset.
Dataset output roots must be unique and non-overlapping. Changing a root starts
a new output/work tree by default, so an earlier run's ``-resume`` cache is not
expected to follow it automatically.

Process subdirectories are part of MEGFlow's internal output contract and are
not user parameters:

.. list-table::
   :header-rows: 1
   :widths: 32 28 40

   * - Module
     - Fixed directory
     - Reason
   * - ICA
     - ``ica_report``
     - Shared by ICA fitting, labeling, application, and reports.
   * - Epochs
     - ``epochs``
     - Routed to covariance, forward/source processing, and reports.
   * - Coregistration
     - ``trans``
     - Holds transforms and report figures.
   * - Covariance
     - ``covariance``
     - Holds covariance, rank, and diagnostic artifacts.
   * - Forward solution
     - ``forward_solution``
     - Routed directly to source reconstruction and reports.
   * - Source reconstruction
     - ``source_recon``
     - Holds source estimates, routing metadata, and figures.

Do not add ``output_dir`` inside ``ica``, ``epochs``, ``coreg``,
``covariance``, ``forward``, or ``source``. Existing configurations that repeat
the corresponding fixed value remain accepted, but any different value fails
before processing with an explanation to change the run- or dataset-level
``output_dir`` instead.

Keep ``meg_import``, ``mri_import``, ``anatomy``, ``bem``, dataset paths, and
the primary dataset stage in the dataset profile. MEGFlow rejects these fields
inside a recording profile because they are resolved before recordings are
matched. A recording-level ``steps`` override can reduce or specialize an
already enabled MEG path, but it cannot exceed the dataset MEG stage or turn an
anatomy-only or report-only dataset into a full MEG run.

Recording Matching
------------------

``recordings`` is a named map inside a dataset profile. MEGFlow extracts BIDS
entities from each imported path and applies the one profile whose ``match``
block succeeds.

.. list-table::
   :header-rows: 1
   :widths: 29 22 49

   * - Match field
     - Accepted value
     - Behavior
   * - ``subject``
     - string, list, ``null``/``[]``, ``"*"``
     - Case-insensitive exact match for the value after ``sub-``. The complete
       value ``"*"`` removes this field's constraint, including when the entity
       is absent.
   * - ``session``
     - string, list, ``null``/``[]``, ``"*"``
     - Case-insensitive exact match for the value after ``ses-``. ``"*"``
       removes this field's constraint.
   * - ``task``
     - string, list, ``null``/``[]``, ``"*"``
     - Case-insensitive exact match for the basename ``task-`` entity.
       ``"*"`` removes this field's constraint.
   * - ``run``
     - string, list, ``null``/``[]``, ``"*"``
     - Case-insensitive exact match for the basename ``run-`` entity.
       ``"*"`` removes this field's constraint.
   * - ``suffix``
     - string, list, ``null``/``[]``, ``"*"``
     - Matches the final BIDS-like token, such as ``meg`` in ``*_meg.fif`` or
       ``*_meg.ds``. This is not the file extension. ``"*"`` removes this
       field's constraint.
   * - ``filename_contains``
     - string or list
     - Case-insensitive substring search against the basename, including its
       extension. A list uses OR. Here ``"*"`` is a literal asterisk, not a
       wildcard.

Multiple values within one field use OR logic, while different fields use AND
logic. An omitted, ``null``, or empty entity field is not a constraint. Only
the complete entity value ``"*"`` has wildcard behavior; values such as
``"aud*"`` are compared literally and do not perform glob matching.

Entity labels in filenames must use lowercase ``sub-``, ``ses-``, ``task-``,
and ``run-``. Extracted values are then compared case-insensitively. Subject
and session may also be inferred from parent directories; task and run are
read from the basename.

A recording profile must contain at least one nonblank selector. A missing,
empty, or wholly blank ``match`` block is a configuration error. Zero matching
profiles is valid and leaves the dataset-level configuration unchanged;
exactly one match is recursively merged. If two profiles match the same file,
MEGFlow stops instead of applying an ambiguous merge. Unknown match keys are
also errors.

.. code-block:: groovy

   recordings: [
     auditory_run_01: [
       match: [task: "aef", run: ["01", "1"]],
       epochs: [
         event_time_shift_sec: 0.04858,
         epochs: [tmin: -0.1, tmax: 0.5]
       ],
       artifacts: [deepreject: [mode: "strict"]]
     ],
     visual: [
       match: [task: "vef"],
       epochs: [epochs: [tmin: -0.2, tmax: 0.6]]
     ],
     kit_rest_meg: [
       // suffix is "meg"; filename_contains searches the complete basename.
       match: [suffix: "meg", filename_contains: ["task-rest", ".con"]],
       artifacts: [meg_vendor: "kit"]
     ],
     any_task_meg: [
       // "*" means that task may be present or absent; it is not a glob.
       match: [task: "*", filename_contains: "_meg.fif"],
       source: [visualization: [mode: "peak"]]
     ]
   ]

``filename_contains`` is useful when a meaningful distinction is not encoded
as a supported BIDS entity, for example a vendor extension, acquisition token,
or naming convention. Keep profiles mutually exclusive: the two broad example
profiles above should not be enabled together for the same files.

**Worked examples:** :ref:`example-recording-overrides` and
:ref:`example-opm-task-overrides`.

Dataset Discovery
-----------------

There are two ways to define datasets. At least one explicit profile with a
``dataset_dir`` or a valid ``corpus_root`` is required.

Explicit dataset profiles:

.. code-block:: groovy

   params.megflow.datasets = [
     LanguageStudy: [
       dataset_dir: "/data/studies/LanguageStudy",
       fs_subjects_dir: "/data/studies/LanguageStudy/smri"
     ]
   ]

Corpus discovery:

.. code-block:: groovy

   params.megflow.corpus_root = "/data/corpus"
   params.megflow.dataset_include = ["DatasetA", "DatasetB", "DatasetC"]
   params.megflow.dataset_exclude = []

When ``corpus_root`` is set, every immediate child directory is a candidate
dataset. ``dataset_include`` and ``dataset_exclude`` filter candidates by
directory or profile name; ``[]`` means no include restriction and ``"*"`` can
be used as a wildcard. Exclusion wins over inclusion. A matching entry in
``datasets`` can contain only overrides and may omit ``dataset_dir``. Profile
keys are matched case-insensitively after punctuation is normalized.

An explicit profile that contains ``dataset_dir`` is also a candidate, even
when ``corpus_root`` is set. In a container corpus run, profiles intended to
customize children under ``/input`` should normally omit ``dataset_dir`` so the
discovered container path is retained.

Resolved dataset names must be unique after normalization. MEGFlow also rejects
duplicate or nested ``output_dir`` and ``preproc_dir`` trees across datasets,
including a preprocessed tree placed inside another dataset's output tree.
Within one dataset, imported raw files must produce unique recording basenames;
two files that would write to the same ``preprocessed/<recording>/`` directory
are rejected before preprocessing starts.

**Worked example:** :ref:`example-docker-corpus`.

Stage Selection
---------------

Set the shared ``steps`` value in ``defaults`` and override it in a dataset
profile when datasets intentionally stop at different milestones. Recording
overrides should only specialize an already enabled MEG path as described
above.

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Value
     - Behavior
   * - ``meg_all``
     - Full MEG workflow using an existing ``fs_subjects_dir``.
   * - ``all``
     - Structural MRI workflow plus the full MEG workflow.
   * - ``anatomy``
     - Structural MRI workflow only.
   * - ``meg_artifacts``
     - MEG import, continuous preprocessing, artifact detection, and report.
   * - ``meg_ica``
     - ``meg_artifacts`` plus ICA fitting, labeling, and application.
   * - ``meg_epochs``
     - Through epoch generation, then report.
   * - ``report``
     - Rebuild the static HTML report from existing outputs.

Aliases are accepted: ``meg`` maps to ``meg_all``, ``artifacts`` maps to
``meg_artifacts``, ``ica`` maps to ``meg_ica``, and ``epochs`` maps to
``meg_epochs``.

Optional modifiers are comma-separated. ``meg_epochs,skip_ica`` creates epochs
from OSL-preprocessed raw files instead of ICA-clean raw files. ``with_anatomy``
can be used with ``meg_artifacts``, ``meg_ica``, or ``meg_epochs`` when anatomy
should run in the same workflow. The structural and MEG branches may execute
concurrently; anatomy becomes a MEG dependency only when downstream
coregistration and source modeling require it.

**Worked examples:** :ref:`example-first-meg-pass`,
:ref:`example-anatomy-only`, and :ref:`example-full-meg`.

Input and Output Fields
-----------------------

.. list-table::
   :header-rows: 1
   :widths: 25 20 20 35

   * - Field
     - Scope
     - Docker default / requirement
     - Meaning
   * - ``code_dir``
     - ``params.megflow``
     - ``/program/megflow``; required
     - Directory containing MEGFlow Python scripts. Source runs normally point
       to the repository ``megflow`` directory.
   * - ``output_dir``
     - global or dataset
     - ``/output``
     - Output root. In corpus mode, dataset outputs default to
       ``<output_dir>/datasets/<dataset_name>``.
   * - ``report_scope``
     - ``params.megflow``
     - ``dataset``
     - Run-level report layout. Use ``dataset`` for one dataset and ``corpus``
       for ``corpus_root`` or multi-dataset runs. Supplied launchers and example
       configs set this automatically.
   * - ``error_mode``
     - ``params.megflow``
     - ``lenient``
     - ``lenient`` applies process-specific exit-code retry and ignore rules;
       it is not semantic error classification. Validation failures, import
       and report failures, and covariance/source exit code 2 terminate.
       ``strict`` terminates on every process failure. See
       :doc:`configuration_execution` for the complete policy.
   * - ``fs_subjects_root``
     - ``params.megflow``
     - unset; optional
     - Corpus-level FreeSurfer root. Dataset subjects directories
       default to ``<fs_subjects_root>/<dataset_name>`` when this is set.
   * - ``corpus_root``
     - ``params.megflow``
     - empty string
     - Directory whose immediate children are candidate datasets.
   * - ``dataset_include`` / ``dataset_exclude``
     - ``params.megflow``
     - empty lists
     - Dataset-name filters used with ``corpus_root``.
   * - ``defaults``
     - ``params.megflow``
     - required map
     - Shared processing policy merged into every dataset.
   * - ``datasets``
     - ``params.megflow``
     - ``docker_input`` placeholder
     - Named dataset profile map. The entrypoint preserves named profiles in
       corpus mode and merges runtime paths into ``docker_input`` in single mode.
   * - ``name``
     - dataset
     - profile key
     - Optional output-facing dataset name. Unsafe punctuation is normalized.
   * - ``dataset_dir``
     - dataset
     - conditionally required
     - MEG dataset root. May be omitted for a corpus-discovered profile.
   * - ``output_dir``
     - dataset
     - derived
     - Per-dataset output override. A single dataset uses the global output;
       corpus datasets use ``<global>/datasets/<name>``.
   * - ``preproc_dir``
     - dataset
     - derived
     - Main derivative directory. Defaults to
       ``<dataset_output_dir>/preprocessed``.
   * - ``fs_subjects_dir``
     - dataset
     - derived
     - FreeSurfer subjects directory used by coregistration, BEM, forward
       solution, and source reconstruction. It defaults to the corpus
       ``fs_subjects_root`` or ``<global_output>/smri/<dataset_name>``.
   * - ``t1_dir``
     - dataset
     - ``dataset_dir``
     - Structural MRI input root when anatomy processing is enabled.
   * - ``dataset_format``
     - defaults or dataset
     - ``auto``
     - MEG discovery format: ``auto``, ``bids``, or ``raw``.
   * - ``file_suffix``
     - defaults or dataset
     - ``.fif``
     - File or directory suffix used by raw discovery.
   * - ``is_bids``
     - defaults or dataset
     - ``true``
     - General BIDS assumption. ``anatomy.is_bids`` is the authoritative
       anatomy-specific value.
   * - ``visualize``
     - defaults or dataset
     - ``true``
     - Shared visualization fallback; module-level values take precedence.
   * - ``rank_policy``
     - defaults, dataset, or recording
     - ``auto``
     - Shared default rank policy for covariance and source imaging. Allowed:
       ``auto``, ``info``, ``full``, an MNE rank dictionary, or null.
   * - ``seeds.osl`` / ``seeds.ica``
     - defaults or dataset
     - ``2025`` / ``2025``
     - Reproducibility seeds for continuous preprocessing and ICA.

MRI Import
----------

``mri_import`` filters structural BIDS files before FreeSurfer or DeepPrep.
``subject_id``, ``session_id``, ``task``, and ``run_id`` accept null, a string,
or a list, using entity values without BIDS prefixes. All default to null. The
special ``"first:N"`` subject selector is supported. Optional
``t1_patterns`` and ``t1_exclude_keywords`` narrow T1 selection when a dataset
contains multiple structural derivatives. MRI import is used only for
anatomy-enabled datasets whose configured method requires a real T1 image.

**Worked example:** :ref:`example-anatomy-only`.

MEG Import
----------

MEG input discovery is configured by ``meg_import``. BIDS datasets use MNE-BIDS
entities; raw datasets are discovered by suffix and optional filename keywords.

.. list-table::
   :header-rows: 1
   :widths: 28 20 17 35

   * - Field
     - Type
     - Default
     - Meaning
   * - ``dataset_format``
     - ``auto``, ``bids``, ``raw``
     - ``auto``
     - ``auto`` treats a directory with ``dataset_description.json`` as BIDS.
   * - ``file_suffix``
     - string
     - ``.fif``
     - Raw discovery suffix, for example ``.fif``, ``.ds``, or ``c,rfDC``.
   * - ``meg_import.subject_id``
     - null, string, list
     - null
     - BIDS subjects without ``sub-``. ``"first:10"`` selects the first ten
       discovered subjects.
   * - ``meg_import.session_id``
     - null, string, list
     - null
     - BIDS session filter.
   * - ``meg_import.task``
     - null, string, list
     - null
     - BIDS task filter.
   * - ``meg_import.run_id``
     - null, string, list
     - null
     - BIDS run filter.
   * - ``meg_import.raw_include_keywords``
     - null, string, list
     - null
     - Raw input only. Keep candidates whose basename contains at least one
       listed keyword.
   * - ``meg_import.raw_exclude_keywords``
     - null, string, list
     - null
     - Raw input only. Drop candidates whose basename contains a listed
       keyword, such as ``phantom`` or ``emptyroom``.

Import filters are dataset-level because they run before recording profiles are
resolved. For raw covariance, the recording named by
``covariance.raw_covariance_task_id`` must also be imported and processed to an
ICA-clean continuous file. Do not exclude that task from ``meg_import.task``.

**Worked examples:** :ref:`example-first-meg-pass`,
:ref:`example-full-meg`, and :ref:`example-raw-covariance`.
