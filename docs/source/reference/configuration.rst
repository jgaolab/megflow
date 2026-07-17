Configuration Reference
=======================

MEGFlow is configured through ``params.megflow`` in a Nextflow configuration
file. The authoritative container defaults are defined in
``nextflow/nextflow_for_docker.config``. The source-run defaults in
``nextflow/nextflow.config`` use the same schema, with host-specific paths and
resource settings.

The profile system has one canonical structure for single-dataset,
corpus-level, and mixed-task runs:

.. code-block:: groovy

   params {
     megflow = [
       code_dir: "/data/liaopan/megprep/megflow",
       output_dir: "/data/project/megflow_run",
       report_scope: "dataset",
       corpus_root: "",
       dataset_include: [],
       dataset_exclude: [],

       defaults: [
         steps: "meg_all",
         rank_policy: "auto",
         meg_import: [:],
         preproc: [:],
         artifacts: [:],
         ica: [:],
         ic_label: [:],
         epochs: [:],
         covariance: [:],
         coreg: [:],
         forward: [:],
         source: [:],
         report: [:]
       ],

       datasets: [
         MyDataset: [
           dataset_dir: "/data/project/MyDataset",
           fs_subjects_dir: "/data/project/MyDataset/smri",
           meg_import: [subject_id: "first:10", task: ["RDR"]]
         ]
       ]
     ]
   }

Execution and Resource Profiles
-------------------------------

The main configuration also defines the Nextflow execution layer. Runtime
observability files are stored inside the final report package. Single-dataset
runs use ``static_html_report/nextflow/`` and corpus runs use
``corpus_static_html_report/nextflow/``:

.. list-table::
   :header-rows: 1
   :widths: 28 32 40

   * - Output
     - Default path
     - Purpose
   * - Nextflow log
     - ``<report_package>/nextflow/nextflow.log``
     - Driver messages, task submissions, retries, and failures.
   * - Execution report
     - ``<report_package>/nextflow/report.html``
     - CPU, memory, duration, and task-level resource utilization.
   * - Timeline
     - ``<report_package>/nextflow/timeline.html``
     - Chronological task scheduling and concurrency.
   * - Trace
     - ``<report_package>/nextflow/trace.txt``
     - Machine-readable task status and resource accounting.

Nextflow initializes its main launcher log before it loads pipeline
configuration. MEGFlow launch commands therefore pass the same configured path
through the top-level ``-log`` option. Custom source launchers should do the
same:

.. code-block:: bash

   mkdir -p /data/project/megflow_run/static_html_report/nextflow
   nextflow -log /data/project/megflow_run/static_html_report/nextflow/nextflow.log \
     -C nextflow/my_project.config \
     run nextflow/megflow.nf \
     -resume

The base ``process`` scope assigns conservative defaults and then overrides
CPU, memory, time, and retry limits with selectors that match the current
process names in ``megflow.nf``. Memory-heavy stages use
``task.attempt``-dependent memory, so a resource-related retry requests more
memory. ``queueSize`` is an executor setting; per-process concurrency should be
limited with ``maxForks`` in a project-specific override when necessary.

Two failure policies are available:

``lenient``
   Retry resource-related exits up to the process-specific ``maxRetries`` and
   then ignore an eligible failed recording so the remaining dataset can
   continue. Deterministic configuration, rank, channel-contract, and missing
   covariance/source-output errors terminate immediately.

``strict``
   Terminate on the first process failure and set ``workflow.failOnIgnore``.

The following execution profiles are defined in ``nextflow.config``:

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Profile
     - Behavior
   * - ``local``
     - Run tasks directly on the current workstation or server.
   * - ``docker``
     - Run the complete workflow in ``cmrlab/megflow:1.0.0`` when Nextflow is
       launched from source. The image already contains DeepPrep.
   * - ``slurm``
     - Submit each task to Slurm using the process-specific CPU, memory, and
       time directives.
   * - ``singularity``
     - Run tasks in the MEGFlow SIF image. Compose it with ``slurm`` on HPC.
   * - ``lenient`` / ``strict``
     - Select the failure policy independently of the executor.
   * - ``debug``
     - Enable DEBUG logging and serialize tasks with ``maxForks = 1``.

Docker, Slurm, and Singularity site settings are provided through environment
variables instead of anatomy-module parameters or hard-coded cluster names:

.. list-table::
   :header-rows: 1
   :widths: 38 62

   * - Variable
     - Meaning
   * - ``MEGFLOW_DOCKER_IMAGE``
     - Complete MEGFlow image used by the source ``docker`` profile; defaults
       to ``cmrlab/megflow:1.0.0``.
   * - ``MEGFLOW_DOCKER_RUN_OPTIONS``
     - Docker bind/runtime options; defaults to ``-v /data:/data``.
   * - ``MEGFLOW_SLURM_PARTITION``
     - Slurm partition or comma-separated partition list.
   * - ``MEGFLOW_SLURM_ACCOUNT`` / ``MEGFLOW_SLURM_QOS``
     - Optional account and QoS flags.
   * - ``MEGFLOW_SLURM_EXTRA``
     - Additional ``sbatch`` options, for example a site constraint.
   * - ``MEGFLOW_SLURM_QUEUE_SIZE``
     - Maximum number of tasks kept in the Slurm submission queue; default 100.
   * - ``MEGFLOW_SLURM_WORKDIR``
     - Shared task work directory; defaults to ``<output_dir>/work_slurm``.
   * - ``MEGFLOW_SIF``
     - MEGFlow SIF path.
   * - ``MEGFLOW_SINGULARITY_CACHE``
     - Shared image cache directory.
   * - ``MEGFLOW_SINGULARITY_RUN_OPTIONS``
     - Site-specific bind and runtime options, such as ``-B /data:/data``.

Example:

.. code-block:: bash

   export MEGFLOW_SLURM_PARTITION=cpu
   export MEGFLOW_SLURM_ACCOUNT=my_account
   export MEGFLOW_SIF=/shared/containers/cmrlab_megflow_1.0.0.sif
   export MEGFLOW_SINGULARITY_RUN_OPTIONS='-B /data:/data'

   nextflow -log /data/project/megflow_run/static_html_report/nextflow/nextflow.log \
     -C nextflow/nextflow_for_smn4lang.config \
     run nextflow/megflow.nf \
     -profile slurm,singularity,lenient \
     -resume

The Docker image is a different execution model: Nextflow already runs inside
the MEGFlow container and therefore uses the local executor there. Do not enable
Nextflow's per-process Docker scope in ``nextflow_for_docker.config``. The image
entrypoint prepares output ownership and drops to the mounted data UID/GID before
starting Nextflow. When Nextflow itself is launched from a source checkout, use
``-profile docker,strict`` to containerize the complete workflow instead of
starting a second container from inside ``run_deepprep``. For example:

.. code-block:: bash

   export MEGFLOW_DOCKER_RUN_OPTIONS='-v /data:/data -v /path/license.txt:/fs_license.txt:ro'
   nextflow -C nextflow/project.config run nextflow/megflow.nf \
     -profile docker,strict -resume

The effective ``anatomy.fs_license_file`` must name the container-visible path
(``/fs_license.txt`` above). A license already located below ``/data`` can use
its unchanged path through the default ``/data:/data`` bind.

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
``covariance``, ``forward``, or ``source``. Legacy configurations that repeat
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
~~~~~~~~~~~~~~~~~~

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
     - string, list, ``"*"``
     - Matches the value after ``sub-`` without the prefix.
   * - ``session``
     - string, list, ``"*"``
     - Matches the value after ``ses-`` without the prefix.
   * - ``task``
     - string, list, ``"*"``
     - Matches the filename ``task-`` entity.
   * - ``run``
     - string, list, ``"*"``
     - Matches the filename ``run-`` entity.
   * - ``suffix``
     - string, list, ``"*"``
     - Matches the final BIDS-like suffix before the extension, such as
       ``meg``.
   * - ``filename_contains``
     - string or list
     - Matches when at least one value occurs in the basename.

Entity comparisons are case-insensitive. Multiple values within one field use
OR logic, while different fields use AND logic. An omitted field is not a
constraint. An empty or missing ``match`` block never matches. If two recording
profiles match the same file, MEGFlow stops with an error instead of applying
an ambiguous merge. Unknown match keys are also errors; the accepted keys are
exactly ``subject``, ``session``, ``task``, ``run``, ``suffix``, and
``filename_contains``.

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
     ]
   ]

Dataset Discovery
-----------------

There are two ways to define datasets. At least one explicit profile with a
``dataset_dir`` or a valid ``corpus_root`` is required.

Explicit dataset profiles:

.. code-block:: groovy

   params.megflow.datasets = [
     SMN4Lang: [
       dataset_dir: "/data/liaopan/datasets/SMN4Lang",
       fs_subjects_dir: "/data/liaopan/datasets/SMN4Lang_smri"
     ]
   ]

Corpus discovery:

.. code-block:: groovy

   params.megflow.corpus_root = "/data/liaopan/datasets"
   params.megflow.dataset_include = ["WAND_Extracted", "SMN4Lang", "OPM-COG.v1"]
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
should run before the selected MEG milestone.

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
     - ``lenient`` ignores eligible recoverable process failures after retries;
       deterministic configuration and data-contract errors still terminate.
       ``strict`` terminates on every process failure and sets
       ``workflow.failOnIgnore``.
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

Processing Modules
------------------

Each module block is passed to the corresponding MEGFlow script as JSON/YAML.
Fields that match MNE-Python, MNE-BIDS, PyPREP, OSL-Ephys, FreeSurfer, or
DeepPrep are passed through with their upstream meaning.

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Block
     - Used by
   * - ``seeds``
     - Reproducibility seeds for OSL preprocessing and ICA.
   * - ``anatomy`` / ``mri_import``
     - Structural input selection and FreeSurfer, DeepPrep, or pseudo-MRI.
   * - ``megqc``
     - NormMEG-QC scoring, NMDQ score thresholds, and optional processing gate.
   * - ``preproc``
     - OSL continuous preprocessing. Use ``steps`` for the ordered OSL
       operation list.
   * - ``digitization``
     - Optional BIDS sidecar/headshape integration after continuous
       preprocessing.
   * - ``artifacts``
     - DeepReject, PyPREP, PSD, OSL, and MNE bad-channel/bad-segment detection.
   * - ``ica``
     - ICA output directory, component count, and explained-variance option.
   * - ``ic_label``
     - MegNet, MNE, ECG/EOG, and rule-based component labeling.
   * - ``epochs``
     - Resting or task epoch generation.
   * - ``bem``
     - BEM surface conductivity and ico grade.
   * - ``covariance``
     - Noise covariance from baseline epochs or paired raw recordings.
   * - ``coreg``
     - Fiducial fitting, ICP, fine-tuned ICP, and coregistration figures.
   * - ``forward``
     - Source space/forward-solution parameters.
   * - ``source``
     - Source reconstruction mode and methods such as ``dSPM`` and ``LCMV``.
   * - ``report``
     - Static HTML report thresholds and task-log packaging.

Direct upstream kwargs retain the MNE-Python meaning. Relevant API references
include `Raw filtering and resampling
<https://mne.tools/stable/generated/mne.io.Raw.html>`_,
`MNE Epochs <https://mne.tools/stable/generated/mne.Epochs.html>`_,
`find_events <https://mne.tools/stable/generated/mne.find_events.html>`_,
`find_bad_channels_lof
<https://mne.tools/stable/generated/mne.preprocessing.find_bad_channels_lof.html>`_,
`compute_raw_covariance
<https://mne.tools/stable/generated/mne.compute_raw_covariance.html>`_, and
`compute_covariance
<https://mne.tools/stable/generated/mne.compute_covariance.html>`_.

Anatomy
-------

Anatomy runs only when the effective dataset ``steps`` enables anatomy. Select
the method with ``anatomy.method``.

.. list-table::
   :header-rows: 1
   :widths: 30 20 18 32

   * - Field
     - Allowed values
     - Docker default
     - Meaning
   * - ``anatomy.method``
     - ``freesurfer``, ``deepprep``, ``pseudomri``
     - ``freesurfer``
     - Structural reconstruction branch.
   * - ``anatomy.is_bids``
     - boolean
     - ``true``
     - Uses BIDS MRI import. DeepPrep currently requires BIDS input.
   * - ``anatomy.select_tag``
     - string
     - empty
     - Suffix used when matching MEG subjects to a selected anatomy subject.
   * - ``anatomy.t1_input_type``
     - ``nifti`` or ``dicom``
     - ``nifti``
     - Non-BIDS FreeSurfer input type.
   * - ``anatomy.t1_dicom_series_glob``
     - relative glob or empty
     - empty
     - Limits DICOM conversion to matching series directories.
   * - ``anatomy.fs_license_file``
     - file path
     - ``/fs_license.txt``
     - FreeSurfer license visible inside the MEGFlow runtime and passed to
       DeepPrep.
   * - ``anatomy.deepprep_device``
     - ``cpu`` or backend-supported device
     - ``cpu``
     - DeepPrep device argument.
   * - ``anatomy.pseudomri_template_dir``
     - directory path
     - ``/program/megflow/tools/pseudomri``
     - Directory containing the pseudo-MRI template assets.
   * - ``anatomy.pseudomri_template_subject``
     - template subject name
     - ``mni_icbm152_nlin_sym_09a``
     - Template used to create a subject-specific pseudo T1.

``pseudomri`` requires usable digitization/headshape points in the imported MEG
recording. ``freesurfer`` supports BIDS T1w input and non-BIDS NIfTI or DICOM
input. ``deepprep`` imports BIDS T1w records and writes reconstructions into the
dataset ``fs_subjects_dir``. DeepPrep is part of the MEGFlow image and its
internal entrypoint is not configurable. Do not put container image, command,
backend, or SIF paths in the anatomy block. Run the outer MEGFlow image, use the
source ``docker`` profile, or compose ``singularity`` with the appropriate
executor. A plain host ``local`` profile cannot run the DeepPrep branch unless
it is already executing inside the MEGFlow image. ``bem.ico`` and
``bem.conductivity`` default to ``4`` and ``[0.3]`` and are passed to MNE BEM
model generation.

NormMEG-QC
----------

The ``megqc`` block controls NormMEG-QC and the NMDQ score.

.. list-table::
   :header-rows: 1
   :widths: 31 18 18 33

   * - Field
     - Type / values
     - Docker default
     - Meaning
   * - ``enabled``
     - boolean
     - ``true``
     - Runs NormMEG-QC before continuous preprocessing.
   * - ``min_score``
     - number, 0-100
     - ``0.0``
     - Processing gate. Lower-scoring or unscored recordings do not continue.
   * - ``alarm_score``
     - number, 0-100
     - ``70.0``
     - Report warning threshold; it does not control processing.
   * - ``meg_vendor``
     - ``auto``, ``elekta``, ``ctf``, ``kit``, ``4d``, ``opm``
     - ``auto``
     - Reference device family.
   * - ``category``
     - ``auto``, ``rest``, ``task``, ``ALL``
     - ``auto``
     - Reference recording category.
   * - ``reference_scope``
     - ``device_category``, ``category``, ``global``
     - ``device_category``
     - Reference grouping used for scoring.
   * - ``min_reference_n``
     - positive integer
     - ``20``
     - Minimum reference records required by the selected scope.
   * - ``freq_max_samples``
     - non-negative integer
     - ``0``
     - Optional spectral sample limit; zero uses all available samples.
   * - ``dfa_max_samples``
     - positive integer
     - ``20000``
     - Maximum samples used by DFA computation.
   * - ``dfa_method``
     - ``msqms`` or ``sampled``
     - ``msqms``
     - DFA implementation.
   * - ``skip_dfa``
     - boolean
     - ``false``
     - Skips DFA when true.
   * - ``keep_bad_annotations``
     - boolean
     - ``true``
     - Keeps samples carrying existing bad annotations in the QC policy.
   * - ``omit_bad_channels``
     - boolean
     - ``false``
     - Excludes channels already listed in ``raw.info['bads']`` when true.
   * - ``seg_length``
     - positive number
     - ``100``
     - Segment length used by the configured score components.
   * - ``preproc``
     - ordered operation list
     - 1-100 Hz, 50 Hz notch, then 250 Hz resampling
     - QC-only preprocessing. Preserve the reference-aligned band-pass and
       target sampling rate.

The default reference-aligned operation order is:

.. code-block:: groovy

   megqc: [
     preproc: [
       [filter: [l_freq: 1.0, h_freq: 100.0, method: "iir",
                 iir_params: [order: 5, ftype: "butter"]]],
       [notch_filter: [freqs: 50]],
       [resample: [sfreq: 250]]
     ]
   ]

The scorer also carries this sequence as its internal fallback. Omitting
``megqc.preproc`` or setting it to an empty list therefore still applies the
reference-aligned defaults. Set ``megqc.preproc = false`` only for diagnostic
runs that intentionally disable reference preprocessing; resulting scores
are not directly comparable with the bundled normative reference.

See :doc:`qc_metrics` for component definitions, NMDQ score construction,
threshold interpretation, and output files.

Continuous Preprocessing
------------------------

``preproc.steps`` is a convenience spelling for the native OSL-Ephys
``preproc`` operation list. The Docker default is:

.. code-block:: groovy

   preproc: [
     steps: [
       [filter: [l_freq: 1.0, h_freq: 100.0, method: "iir",
                 iir_params: [order: 5, ftype: "butter"]]],
       [notch_filter: [freqs: "50 100"]],
       [resample: [sfreq: 250]]
     ]
   ]

Operations run from top to bottom. A dataset- or recording-level
``preproc.steps`` list replaces the inherited list, so repeat every operation
that the override still needs. Nested maps inside the other modules are deep
merged instead. ``filter`` resolves to MNE Raw filtering, ``notch_filter``
resolves through the OSL wrapper to Raw notch filtering, and ``resample``
resolves through the OSL wrapper to Raw resampling. The bundled notch wrapper
accepts an MNE-style numeric list, a scalar, or the historical whitespace-
separated string. OSL-supported operations such as Maxwell/tSSS can be inserted
in the same ordered list when the required calibration and cross-talk inputs
are available.

MEGFlow removes only its own ``digitization`` block before invoking
``osl_ephys.preprocessing.run_proc_batch``. Other native OSL recipe fields are
retained. For example, the following expanded form is equivalent to using
``steps`` while also supplying OSL metadata:

.. code-block:: groovy

   preproc: [
     meta: [event_codes: null],
     steps: [
       [filter: [l_freq: 1.0, h_freq: 100.0, method: "iir",
                 iir_params: [order: 5, ftype: "butter"], phase: "zero"]],
       [notch_filter: [freqs: [50, 100]]],
       [resample: [sfreq: 250, npad: "auto"]]
     ],
     group: null
   ]

OSL resolves each operation by checking its wrappers before falling back to a
method on the selected MNE object. Consequently, kwargs inside a direct MNE
operation keep their MNE names. A native ``group`` block is preserved, but each
MEGFlow preprocessing process normally contains one recording; cohort-level
group statistics should therefore be implemented outside this per-recording
hook.

.. _configuration-maxwell-tsss:

Maxwell Filtering and tSSS
~~~~~~~~~~~~~~~~~~~~~~~~~~

MEGIN/Elekta recordings can run MNE Maxwell filtering as an OSL preprocessing
stage named ``maxwell_filter``. OSL resolves that name to its
``run_mne_maxwell_filter`` wrapper and forwards the nested arguments to
``mne.preprocessing.maxwell_filter``. Setting ``st_duration`` to a positive
duration in seconds enables temporal signal-space separation (tSSS); setting it
to ``null`` performs SSS without the temporal extension.

.. code-block:: groovy

   preproc: [
     steps: [
       [maxwell_filter: [
         origin: "auto",
         int_order: 8,
         ext_order: 3,
         calibration: "/data/site-a/calibration/sss_cal.dat",
         cross_talk: "/data/site-a/calibration/ct_sparse.fif",
         st_duration: 10.0,
         st_correlation: 0.98,
         coord_frame: "head",
         destination: null,
         regularize: "in",
         bad_condition: "warning",
         st_fixed: true,
         st_only: false,
         skip_by_annotation: ["edge", "bad_acq_skip"]
       ]],
       [filter: [
         l_freq: 1.0, h_freq: 100.0, method: "iir",
         iir_params: [order: 5, ftype: "butter"]
       ]],
       [notch_filter: [freqs: [50, 100]]],
       [resample: [sfreq: 250]]
     ]
   ]

This ordering applies Maxwell/tSSS before temporal filtering, notch filtering,
and resampling. ``calibration`` and ``cross_talk`` are site/system-specific;
their paths must be readable in the source environment or mounted at the same
paths inside the container. ``destination`` and head-position inputs should be
set only when a validated movement-compensation policy is available.

MNE requires bad MEG channels to be marked before Maxwell filtering so that
their artifacts are not spread during reconstruction. The later MEGFlow
``detect_artifacts`` process cannot satisfy that precondition: this stage sees
only bad channels already present in the imported Raw or marked by an earlier,
validated OSL operation.

Use the MNE argument names shown above. The legacy OSL MaxFilter command-line
names ``tsss``, ``st``, and ``corr`` belong to a different interface and are not
valid arguments for this OSL/MNE stage. MEGFlow 1.0.0 pins MNE 1.8.0, so do not
copy parameters introduced by newer MNE releases without checking the pinned
signature. See the `MNE Maxwell filter API
<https://mne.tools/1.8/generated/mne.preprocessing.maxwell_filter.html>`_ for
the complete supported parameter set.

Maxwell/tSSS is deliberately absent from the shared defaults because it is
device- and site-specific. For corpus processing, place calibration and
cross-talk paths in the dataset profile. If a recording profile changes the
tSSS window or threshold, repeat the complete ordered ``preproc.steps`` list:
lists replace inherited lists rather than merging item by item. The downloadable
:download:`three-level Maxwell/tSSS example
<../../../nextflow/nextflow_maxwell_tsss_example.config>` demonstrates default,
dataset, and recording scopes.

For task data, MEGFlow finds stimulation-channel events before optional
``epochs.preproc`` resampling and remaps samples through MNE. Nevertheless,
continuous resampling choices should be validated against trigger precision for
the dataset.

Digitization
------------

``digitization`` controls optional sidecar digitization merged after OSL
preprocessing.

.. list-table::
   :header-rows: 1
   :widths: 34 18 18 30

   * - Field
     - Type
     - Default
     - Meaning
   * - ``enabled``
     - boolean
     - ``true``
     - Enables sidecar lookup. Existing embedded digitization is retained when
       no matching files are found.
   * - ``coordsystem_file_pattern``
     - string
     - ``{prefix}_coordsystem.json``
     - BIDS coordinate-system sidecar pattern.
   * - ``hsp_file_pattern``
     - string or null
     - ``{prefix}_headshape.pos``
     - Headshape point pattern.
   * - ``elp_file_pattern``
     - string or null
     - null
     - Optional fiducial/electrode-position pattern.
   * - ``override_embedded``
     - boolean
     - ``false``
     - Replaces valid embedded digitization instead of only filling missing
       information.

``{prefix}`` is resolved from progressively shorter BIDS-like filename
prefixes. Dataset profiles should override these patterns for vendor-specific
sidecar conventions, as demonstrated by the KIT profile in the runnable
multi-dataset example.

Artifact Detection
------------------

``artifacts.find_bad_channels`` enables any combination of the following
methods. Their outputs are de-duplicated and detector provenance is retained.

.. list-table::
   :header-rows: 1
   :widths: 38 25 37

   * - Field
     - Docker default
     - Meaning
   * - ``pyprep.deviation``
     - ``deviation_threshold: 5.0``
     - Robust amplitude-deviation outliers.
   * - ``pyprep.snr``
     - enabled with defaults
     - Low signal-to-noise channels.
   * - ``pyprep.nan_flat``
     - enabled with defaults
     - NaN-containing and flat channels.
   * - ``pyprep.hfnoise``
     - disabled
     - High-frequency-noise detector; provide its PyPREP kwargs to enable it.
   * - ``pyprep.ransac``
     - disabled
     - Reconstruction-correlation detector; computationally expensive.
   * - ``pyprep.correlation``
     - disabled
     - Windowed inter-channel correlation and dropout detector.
   * - ``psd.std_multiplier``
     - ``6``
     - Flags mean channel PSD above the across-channel mean plus this many
       standard deviations.
   * - ``osl``
     - ``ref_meg: auto``, ``significance_level: 0.05``
     - Runs OSL bad-channel detection separately for magnetometers and
       gradiometers when present.
   * - ``mne.find_bad_channels_lof``
     - 20 neighbors, mag picks, Euclidean metric, threshold 1.5
     - MNE local-outlier-factor bad-channel detector.

``artifacts.find_bad_segments`` supports OSL ``detect_badsegments`` and MNE
``annotate_muscle_zscore``, ``annotate_amplitude``, and ``annotate_break``.
The Docker default enables OSL with ``segment_len: 1000`` samples. Set
``keep_existing_annotations: true`` to merge pre-existing input annotations;
the explicit Docker default is ``false``, which clears them before running the
configured bad-segment detectors.

.. list-table::
   :header-rows: 1
   :widths: 35 18 47

   * - Field
     - Default
     - Meaning
   * - ``interpolate_bads``
     - ``false``
     - Interpolates detected channels in the preprocessed raw and resets
       ``raw.info['bads']`` when true.
   * - ``artifact_images_enabled``
     - ``false``
     - Enables detailed waveform and overview image sets. The compact artifact
       mask heatmap is generated regardless of this value.
   * - ``artifact_image_n_jobs``
     - ``8``
     - Worker limit for detailed image generation.
   * - ``meg_vendor``
     - ``auto``
     - Plotting scale/vendor assumptions. Automatic inference is recommended
       for mixed corpora.
   * - ``deepreject``
     - enabled, ``mode: default``
     - Deep-learning-based BadChnNet and BadSegNet branch. See
       :doc:`deepreject`.

ICA and Component Labeling
--------------------------

ICA derivatives use the fixed internal ``ica_report`` directory.
``ica.num_components`` defaults to ``60`` and is passed as MNE ICA
``n_components``; ``ica.compute_explained_variance`` defaults to false because
per-component figure computation is expensive. ICA uses FastICA, the configured
``seeds.ica``, excludes bad channels, and fits with
``reject_by_annotation=True``.

The ``ic_label`` block combines three selector families:

.. list-table::
   :header-rows: 1
   :widths: 30 18 52

   * - Field
     - Default
     - Meaning
   * - ``ica_label``
     - ``true``
     - Enables the bundled learned component classifier.
   * - ``mne_algorithm``
     - ``true``
     - Enables MNE EOG, ECG, and muscle component detection.
   * - ``rules_algorithm``
     - ``true``
     - Enables the custom rule/template classifier.
   * - ``ic_ecg`` / ``ic_eog`` / ``ic_outlier``
     - true / true / false
     - Additive category switches retained for compatibility.
   * - ``find_bads_eog``
     - threshold auto, 1-10 Hz, z-score
     - Passed to MNE ICA EOG detection. ``ch_name`` may be null for automatic
       channel selection.
   * - ``find_bads_ecg``
     - threshold auto, CTPS, 8-16 Hz, z-score
     - Passed to MNE ICA ECG detection.
   * - ``find_bads_muscle``
     - threshold 0.5, 7-45 Hz
     - Passed to MNE ICA muscle detection.
   * - ``ICA_classify.meg_vendor``
     - ``auto``
     - Template/rule vendor family.
   * - ``ICA_classify.explained_var``
     - threshold 0.1, channel type mag
     - Rule threshold used only when explained-variance outputs exist.

All selected component indices are normalized, de-duplicated, and written to
``marked_components.txt`` before ICA application.

Epochs
------

.. list-table::
   :header-rows: 1
   :widths: 32 20 18 30

   * - Field
     - Type / values
     - Default
     - Meaning
   * - ``preproc``
     - ordered list
     - empty
     - Optional analysis-specific filter/notch/resample operations.
   * - ``task_type``
     - ``task`` or ``resting``
     - ``task``
     - Event-based or fixed-length epoching.
   * - ``resting.fixed_length_duration``
     - positive seconds
     - ``2.0``
     - Fixed event spacing for resting recordings.
   * - ``event_source``
     - ``event_file`` or ``find_events``
     - ``event_file``
     - BIDS ``events.tsv`` or stimulation-channel events.
   * - ``event_time_shift_sec``
     - number
     - ``0.0``
     - Signed event correction applied before epoch creation.
   * - ``event_file``
     - map
     - ``trial_type: null``
     - Column filters and optional label-to-id mapping for tabular events.
   * - ``find_events``
     - MNE kwargs
     - stim auto, shortest 1, minimum duration 0
     - Passed to ``mne.find_events``.
   * - ``exclude_event_id``
     - integer or list
     - unset
     - Removes selected event ids before epoching.
   * - ``autoreject``
     - boolean
     - ``false``
     - Enables optional global rejection-threshold estimation.
   * - ``interpolate_bads``
     - boolean
     - ``false``
     - Interpolates bad channels in epochs.
   * - ``drop_bad_channels``
     - boolean
     - ``false``
     - Drops bad channels from epochs instead of retaining metadata.
   * - ``epochs``
     - MNE Epochs kwargs
     - event 1, -0.2 to 0.8 s
     - Includes ``event_id``, ``tmin``, ``tmax``,
       ``reject_by_annotation``, ``picks``, ``baseline``, ``reject``,
       ``preload``, and ``detrend``.

Every key inside ``epochs.epochs`` is passed to ``mne.Epochs`` after MEGFlow
supplies ``raw`` and ``events``. This supports other MNE arguments such as
``flat``, ``proj``, ``decim``, ``reject_tmin``, ``reject_tmax``, ``on_missing``,
and ``event_repeated`` without a MEGFlow-specific rename. Do not place ``raw``
or ``events`` in the configuration because they are routed by the workflow.

The default task epoch block is only a template. Event source, event ids,
timing, baseline, and rejection thresholds must be validated for each dataset
before ``meg_epochs``, ``meg_all``, or ``all`` is expected to complete.

Rank Policy
-----------

``rank_policy`` is a processing-level field and defaults to ``"auto"``. It is
resolved on the exact final experimental Raw or saved Epochs after bad-channel
exclusion and restriction to channels shared with the noise input. The resolved
rank dictionary is then the default for covariance estimation and source
reconstruction. It is written to ``resolved-rank.json`` and routed to source
imaging so all default consumers use the same explicit dictionary rather than
estimating rank again.

Allowed values are ``"auto"`` (empirical target-data rank), ``"info"``,
``"full"``, an MNE rank dictionary such as ``[meg: 60]``, or ``null`` as an
alias for the default automatic policy. Function-level MNE ``rank`` keys and
the legacy ``source.LCMV.n_rank`` remain supported as explicit overrides. See
:doc:`rank_covariance` for precedence, LCMV's two covariance matrices,
empty-room compatibility checks, and examples.

Covariance
----------

.. list-table::
   :header-rows: 1
   :widths: 34 18 48

   * - Field
     - Default
     - Meaning
   * - ``visualize``
     - ``true``
     - Writes covariance matrix and spectrum figures.
   * - ``type``
     - ``epochs``
     - ``epochs`` computes baseline-epoch covariance; ``raw`` uses a paired
       continuous noise recording.
   * - ``raw_covariance_task_id``
     - ``emptr``
     - Task entity used to locate the paired ICA-clean noise recording.
   * - ``event_time_shift_sec``
     - ``0.0``
     - Event correction for epoch-based covariance; normally matches epochs.
   * - ``compute_raw_covariance``
     - tmin 0, tmax null, method auto, mag reject 4e-12,
       reject annotations
     - MNE keyword arguments passed to ``mne.compute_raw_covariance``.
   * - ``events``
     - stim auto, shortest 1, minimum duration 0
     - MNE find-events arguments used for fallback event extraction in epoch
       covariance.
   * - ``epochs``
     - event 1, -0.2 to 0.0 s, mag picks
     - MNE Epochs arguments that define baseline epochs.
   * - ``covariance``
     - tmin null, tmax null
     - MNE keyword arguments passed to ``mne.compute_covariance``.

The ``compute_raw_covariance`` and ``covariance`` maps are passed as kwargs to
their namesake MNE functions. MEGFlow adds the resolved ``rank`` from
``rank_policy`` unless that function-level map explicitly supplies ``rank``.
For epoch covariance, ``covariance.epochs`` follows the same direct
``mne.Epochs`` contract as ``epochs.epochs``.

``bl-cov.fif`` is always produced for a full source run. The same covariance
process also writes ``lcmv-data-cov.fif`` only when the effective
``source.source_methods`` contains ``LCMV``. That data covariance is computed
from the exact final source Raw or saved Epochs, not from newly reconstructed
epochs. Minimum-norm-only runs do not compute it. ``resolved-rank.json`` is
always written and records the target rank and ordered common channels consumed
by source imaging.

For ``type: raw``, MEGFlow replaces ``task-<experimental>`` in the ICA-clean
continuous filename with ``task-<raw_covariance_task_id>``. The paired task must
have been imported and processed through ICA. The task id may contain letters,
numbers, and hyphens. Pairing retains all other filename entities, so subject,
session, run, acquisition, and suffix must already describe the intended pair.

The paired clean file is a channel dependency, not a path guessed from an
output directory. Covariance therefore waits for the current run's noise record
even when task scheduling finishes the experiment first. A missing pair fails
the full source run instead of silently omitting it, and one noise recording may
serve multiple experimental tasks when their other entities match. A recording
identified as a raw-covariance reference is cleaned through ICA but is excluded
from its own epoch, covariance, forward, and source branches, even when its own
recording profile otherwise inherits epoch covariance. When ``epochs.preproc``
is not empty, the same operations are applied in memory to the paired noise
recording before raw covariance is computed.

Target and noise inputs are restricted to common good channels in target order.
With the default rank policy, rank is resolved from the target experimental
input. For raw noise, MEGFlow also checks that the empirical noise-input rank
can support that target rank. See :doc:`rank_covariance` for the complete
contract and the limitation of independently applied ICA projections.

BEM, Coregistration, Forward, and Source
----------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 37 18 45

   * - Field
     - Default
     - Meaning
   * - ``bem.ico``
     - ``4``
     - BEM surface subdivision grade.
   * - ``bem.conductivity``
     - ``[0.3]``
     - Single-layer MEG BEM conductivity.
   * - ``coreg.visualize``
     - ``true``
     - Generates transform-alignment figures.
   * - ``coreg.omit_head_shape_points``
     - ``1`` mm
     - Distance used to omit headshape points before fitting.
   * - ``coreg.grow_hair``
     - ``0.0`` mm
     - Scalp expansion used by MNE coregistration.
   * - ``coreg.icp``
     - 200 iterations; fiducial/HSP/HPI weights from the Docker config
     - Initial MNE ICP fit.
   * - ``coreg.finetune_icp``
     - 200 iterations; HSP-only weight 10
     - Fine-tuning ICP fit.
   * - ``coreg.supplied_trans_file``
     - unset
     - Reuses a supplied transform instead of fitting a new one.
   * - ``forward.epoch_label``
     - ``wdonset``
     - Label used in forward output naming.
   * - ``forward.surface`` / ``forward.spacing``
     - ``white`` / ``ico4``
     - Cortical surface and source-space spacing.
   * - ``source.type``
     - ``epochs``
     - Source input mode: ``epochs`` or ``raw``.
   * - ``source.visualize``
     - ``true``
     - Generates source figures.
   * - ``source.source_methods``
     - ``["dSPM"]``
     - Any implemented inverse methods: MNE-family methods and/or ``LCMV``.
   * - ``source.data_type``
     - ``meg``
     - Channel type selected for evoked/source input.
   * - ``source.spacing`` / ``source.epoch_label``
     - ``ico4`` / ``wdonset``
     - Source-space spacing and output label.
   * - ``source.<method>.make_inverse_operator``
     - loose auto, depth 0.8, fixed auto
     - Passed to ``mne.minimum_norm.make_inverse_operator``.
       ``inverse_operator`` remains a compatible alias.
   * - ``source.<method>.apply_inverse``
     - lambda2 1/9, method dSPM, normal orientation
     - Passed to ``mne.minimum_norm.apply_inverse`` for epoched source data.
   * - ``source.<method>.apply_inverse_raw``
     - falls back to ``apply_inverse``; lambda2 defaults to 1/9
     - Passed to ``mne.minimum_norm.apply_inverse_raw`` for continuous source
       data. Use it for raw-only arguments such as ``start``, ``stop``, and
       ``buffer_size``.
   * - ``source.LCMV.data_covariance``
     - tmin 0.01, tmax 0.4, method auto
     - Passed to ``mne.compute_covariance`` for Epochs or
       ``mne.compute_raw_covariance`` for Raw. Used only when LCMV is selected.
   * - ``source.LCMV.make_lcmv``
     - reg 0.05, pick_ori null, unit-noise-gain-invariant normalization
     - Passed to ``mne.beamformer.make_lcmv``.
   * - ``source.LCMV.apply_lcmv`` / ``apply_lcmv_raw``
     - empty
     - Passed to the matching epoched or continuous MNE LCMV application
       function.
   * - ``source.LCMV.n_rank``
     - unset
     - Legacy integer/string/dictionary override used after the corresponding
       function-level ``rank`` and before ``rank_policy``.
   * - ``source.visualization``
     - peak, both hemispheres, lateral view
     - Peak- or label/time-based visualization selection.

Coregistration is implemented with MNE
`Coregistration <https://mne.tools/stable/generated/mne.coreg.Coregistration.html>`_.
Source kwargs correspond to
`make_inverse_operator
<https://mne.tools/stable/generated/mne.minimum_norm.make_inverse_operator.html>`_
and `make_lcmv <https://mne.tools/stable/generated/mne.beamformer.make_lcmv.html>`_.
The complete rank precedence and conditional covariance behavior are described
in :doc:`rank_covariance`.

MNE and OSL Parameter Passthrough Example
-----------------------------------------

The following representative settings use MNE argument names directly. They
may be placed in ``defaults``, a dataset profile, or a recording profile. Maps
are recursively merged across those levels; operation lists such as
``preproc.steps`` are replaced as a whole.

.. code-block:: groovy

   preproc: [
     steps: [
       [filter: [
         l_freq: 1.0, h_freq: 80.0, method: "iir",
         iir_params: [order: 4, ftype: "butter"],
         phase: "zero", pad: "reflect_limited"
       ]],
       [notch_filter: [freqs: [50, 100], method: "fir"]],
       [resample: [sfreq: 250, npad: "auto", window: "boxcar"]]
     ]
   ],

   epochs: [
     event_source: "find_events",
     find_events: [stim_channel: "STI 014", shortest_event: 1],
     epochs: [
       event_id: 1, tmin: -0.2, tmax: 0.8, baseline: [null, 0.0],
       picks: "meg", preload: true, proj: false, decim: 2,
       reject: [mag: 4e-12], reject_tmin: -0.1, reject_tmax: 0.6,
       reject_by_annotation: true, event_repeated: "merge"
     ]
   ],

   covariance: [
     type: "epochs",
     epochs: [event_id: 1, tmin: -0.2, tmax: 0.0,
              baseline: null, picks: "meg", preload: true],
     covariance: [
       keep_sample_mean: true, tmin: null, tmax: null,
       method: "empirical", cv: 3, n_jobs: 1
     ],
     compute_raw_covariance: [
       tmin: 0.0, tmax: null, tstep: 0.2,
       method: "empirical", reject_by_annotation: true, n_jobs: 1
     ]
   ],

   source: [
     type: "epochs",
     source_methods: ["dSPM", "LCMV"],
     dSPM: [
       make_inverse_operator: [
         loose: "auto", depth: 0.8, fixed: "auto", use_cps: true
       ],
       apply_inverse: [
         lambda2: 0.1111111111111111, method: "dSPM", pick_ori: "normal"
       ],
       apply_inverse_raw: [
         lambda2: 0.1111111111111111, method: "dSPM",
         start: null, stop: null, buffer_size: 1000
       ]
     ],
     LCMV: [
       data_covariance: [tmin: 0.01, tmax: 0.4, method: "empirical"],
       make_lcmv: [
         reg: 0.05, pick_ori: null,
         weight_norm: "unit-noise-gain-invariant", inversion: "matrix"
       ],
       apply_lcmv: [verbose: "INFO"],
       apply_lcmv_raw: [start: null, stop: null, verbose: "INFO"]
     ]
   ]

These are API passthrough capabilities, not universal scientific defaults.
Filter bands, epoch windows, rejection limits, covariance intervals, inverse
orientation, and beamformer regularization must still be selected for the
dataset and hypothesis. MEGFlow 1.0.0 pins MNE 1.8.0; validate new kwargs against
that runtime even when consulting newer MNE stable documentation.

Report
------

.. list-table::
   :header-rows: 1
   :widths: 38 18 44

   * - Field
     - Docker default
     - Meaning
   * - ``bad_channel_threshold``
     - ``30``
     - Bad-channel count alarm.
   * - ``bad_segment_threshold``
     - ``50``
     - Bad-segment count alarm.
   * - ``coreg_mean_threshold``
     - ``5.0`` mm
     - Mean coregistration-distance alarm.
   * - ``coreg_max_threshold``
     - ``20.0`` mm
     - Maximum coregistration-distance alarm.
   * - ``epoch_reject_rate_threshold``
     - ``0.90``
     - Rejected-epoch fraction alarm.
   * - ``static_artifact_overview_duration``
     - ``200.0`` s
     - Time span represented by detailed artifact overview images.
   * - ``alert_missing_ecg_components``
     - ``true``
     - Warns when no ECG component is reported.
   * - ``alert_missing_eog_components``
     - ``true``
     - Warns when no EOG component is reported.
   * - ``static_task_log_mode``
     - ``all-command-log``
     - ``all-command-log``, ``failed``, or ``none`` controls packaged Nextflow
       task logs.

Source Visualization
--------------------

Source reconstruction figures use the maximal-activation peak by default. To
inspect a predefined response window, set ``source.visualization`` with a
time point and an anatomical ROI. MEGFlow selects the nearest source-estimate
sample at that time, restricts the search to matching FreeSurfer ``aparc``
labels, and saves figures with the selection name in the filename.

.. code-block:: groovy

   source: [
     visualize: true,
     epoch_label: "char_onset",
     source_methods: ["dSPM"],
     visualization: [
       name: "temporal_124ms",
       mode: "label",
       roi: "temporal",
       time: 0.124,
       hemi: "both"
     ]
   ]

Common ROI aliases include ``temporal`` or ``auditory`` for temporal-lobe
responses and ``occipital`` or ``visual`` for occipital responses. ``hemi`` can
be ``lh``, ``rh``, or ``both``. Leaving ``visualization`` unset preserves the
default peak-based figure names. When ``views`` is omitted, MEGFlow selects a
``lateral``, ``medial``, or ``ventral`` view from the anatomical label of the
selected vertex so that its marker remains visible. Set ``views`` explicitly to
override this behavior.

Optional Analysis Preprocessing
-------------------------------

``epochs.preproc`` optionally filters or resamples the cleaned continuous Raw
recording immediately before events are converted into epochs. It is empty by
default, so existing configurations keep their original data and do not create
an additional continuous file. Supported operations are ``filter``,
``notch_filter``, and ``resample``.

When configured, MEGFlow writes an ``*_analysis-raw.fif`` file beside the epoch
output and uses that same continuous recording for epoch-based covariance. This
keeps the epochs and noise covariance in the same analysis band. Trigger events
found from a stimulation channel are detected before resampling and remapped by
MNE; BIDS event onsets and annotations are converted using the final sampling
rate.

.. code-block:: groovy

   epochs: [
     preproc: [
       [filter: [l_freq: 1.0, h_freq: 30.0, method: "iir",
                 iir_params: [order: 5, ftype: "butter"]]],
       [resample: [sfreq: 250]]
     ],
     event_source: "event_file",
     epochs: [event_id: 1, tmin: -0.2, tmax: 0.8]
   ]

Use ``preproc: []`` or omit the key to preserve the cleaned Raw without any
analysis-specific preprocessing.

Event Timing Correction
-----------------------

Task events can be shifted before epoching with ``event_time_shift_sec`` in the
``epochs`` block. Positive values move event samples later in time and are
intended for stable trigger-to-stimulus delays. When covariance is estimated
from baseline epochs, set the same value in ``covariance.event_time_shift_sec``.
The parameter is a MEGFlow-level setting and should be placed next to
``event_source``, not inside the nested MNE ``epochs`` argument map.
Use the net correction required by the MEG recording. For example, if an
``events.tsv`` file has already been shifted for fMRI alignment, that offset
should be removed before adding any MEG stimulus-delivery delay.

.. code-block:: groovy

   epochs: [
     event_source: "event_file",
     event_time_shift_sec: 0.0395,
     epochs: [event_id: 1, tmin: -0.2, tmax: 0.8]
   ],
   covariance: [
     event_source: "event_file",
     event_time_shift_sec: 0.0395,
     epochs: [event_id: 1, tmin: -0.2, tmax: 0.0]
   ]

DeepReject
----------

DeepReject uses BadChnNet followed by BadSegNet. The ``default``, ``strict``,
and ``lenient`` modes alter BadSegNet interval post-processing, while explicit
low-level values override the selected mode. See :doc:`deepreject` for the
algorithm order, mathematical definitions, all supported fields, exact mode
thresholds, input preprocessing requirements, and outputs.

Runnable Multi-Dataset Example
------------------------------

The repository's runnable
:download:`nextflow_multi_dataset_demo.config
<../../../nextflow/nextflow_multi_dataset_demo.config>` contains the complete
defaults and process resources for WAND, SMN4Lang, and MEG-MASC. It demonstrates
different import filters, vendors, event sources, event timing, source labels,
digitization patterns, coregistration settings, and a dataset-specific lenient
DeepReject mode. Edit its paths and subject filters before running it:

.. code-block:: bash

   nextflow run nextflow/megflow.nf \
     -c nextflow/nextflow_multi_dataset_demo.config \
     -resume

See :doc:`examples` for a guided walkthrough, a container corpus version, and
recording-level task overrides.

Docker Mapping
--------------

The Docker entrypoint copies the mounted v2 config and appends runtime path
overrides. In single-dataset mode it merges those fields into the existing
``datasets.docker_input`` profile and preserves its module settings. In corpus
mode it removes only the image's placeholder ``docker_input`` profile and
preserves all named user profiles, ``dataset_include``, and
``dataset_exclude``.

Command-line options map as follows:

.. list-table::
   :header-rows: 1
   :widths: 24 36 40

   * - Docker option
     - Profile target
     - Notes
   * - ``-i``, ``--input``
     - ``datasets.docker_input.dataset_dir`` or ``corpus_root``
     - With ``--corpus``, the input is treated as a corpus root.
   * - ``-o``, ``--output``
     - ``params.megflow.output_dir``
     - Also controls Nextflow report, timeline, trace, and work paths.
   * - ``-s``, ``--steps``
     - ``datasets.docker_input.steps`` or ``defaults.steps``
     - Single mode overrides ``docker_input``. Corpus mode changes the shared
       default while preserving explicit dataset-level ``steps`` overrides.
   * - ``--corpus``
     - ``params.megflow.corpus_root``
     - Treats immediate input children as datasets and writes isolated outputs
       under ``<output>/datasets`` plus a corpus report.
   * - ``--fs_subjects_dir``
     - dataset ``fs_subjects_dir`` or global ``fs_subjects_root``
     - Single mode uses the exact directory; corpus mode appends each dataset
       name under this root.
   * - ``--fs_license_file``
     - ``anatomy.fs_license_file``
     - Merged into ``docker_input.anatomy`` in single mode or
       ``defaults.anatomy`` in corpus mode.
   * - ``--t1_dir``
     - ``datasets.docker_input.t1_dir``
     - Single-dataset structural MRI input root. Corpus datasets should set
       ``t1_dir`` in their named profiles when it differs from ``dataset_dir``.
   * - ``--t1_input_type``
     - single profile or corpus default ``anatomy.t1_input_type``
     - ``nifti`` or ``dicom`` for non-BIDS FreeSurfer anatomy.
   * - ``--t1_dicom_series_glob``
     - single profile or corpus default anatomy block
     - Relative DICOM series selection glob.
   * - ``--anatomy_preprocess_method``
     - single profile or corpus default ``anatomy.method``
     - ``freesurfer``, ``deepprep``, or ``pseudomri``.
   * - ``--static_task_log_mode``
     - ``defaults.report.static_task_log_mode``
     - ``all-command-log``, ``failed``, or ``none``.
   * - ``--static_artifact_overview_duration``
     - ``defaults.report.static_artifact_overview_duration``
     - Positive duration in seconds.
   * - ``--resume``
     - Nextflow ``-resume``
     - Reuses valid cached tasks.
   * - ``-c``, ``--config``
     - input configuration file
     - Defaults to ``/program/nextflow/nextflow.config`` in the image.
   * - ``-r``, ``--view-report``
     - report viewer mode
     - Starts Streamlit without launching preprocessing.

The generated effective config is copied to ``<output>/nextflow.config`` after
a successful single-dataset or corpus run and is also snapshotted by the static
report.
