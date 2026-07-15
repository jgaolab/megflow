Configuration Examples
======================

MEGFlow uses one layered configuration schema for a single dataset, multiple
datasets, and recording-specific behavior. Start from a complete base config and
override only the values that differ for the study.

Canonical Templates
-------------------

Use one of these repository files as the base:

* :download:`nextflow_for_docker.config
  <../../../nextflow/nextflow_for_docker.config>` contains the authoritative
  paths and defaults for the distributed container.
* :download:`nextflow.config <../../../nextflow/nextflow.config>` contains the
  source-run defaults and execution profiles.
* :download:`nextflow_multi_dataset_demo.config
  <../../../nextflow/nextflow_multi_dataset_demo.config>` is a complete,
  runnable source-run example for WAND, SMN4Lang, and MEG-MASC.

For Docker, a small project config can include the full config already present
inside the image:

.. code-block:: groovy

   includeConfig "/program/nextflow/nextflow_for_docker.config"

   // Project-specific overrides follow this line.

Mount that overlay at ``/program/nextflow/nextflow.config``. For a source run,
either copy ``nextflow/nextflow.config`` and edit it or include it with a path
that is valid from the project config's location.

Single Dataset: First MEG Pass
------------------------------

This Docker overlay selects one BIDS task and stops after continuous
preprocessing, artifact detection, and ICA cleaning. It avoids event,
covariance, and source-model assumptions during the first quality check.

.. code-block:: groovy

   includeConfig "/program/nextflow/nextflow_for_docker.config"

   params.megflow.datasets.docker_input.meg_import = [
     subject_id: "first:10",
     session_id: null,
     task: ["rest"],
     run_id: null,
     raw_include_keywords: null,
     raw_exclude_keywords: null
   ]

.. code-block:: bash

   docker run --rm -it \
     -v /data/study/bids:/input \
     -v /data/study/megflow:/output \
     -v /data/study/megflow.config:/program/nextflow/nextflow.config \
     cmrlab/megflow:1.0.0 \
     -i /input -o /output --steps meg_ica --resume

Full MEG with Existing Anatomy
------------------------------

Use ``meg_all`` only after the event definition, covariance strategy, subject
matching, and existing FreeSurfer or DeepPrep results have been checked. A full
source run is rarely dataset independent.

.. code-block:: groovy

   includeConfig "/program/nextflow/nextflow_for_docker.config"

   params.megflow.datasets.docker_input.meg_import = [
     subject_id: "first:10",
     session_id: null,
     task: ["RDR"],
     run_id: ["1"],
     raw_include_keywords: null,
     raw_exclude_keywords: null
   ]
   params.megflow.datasets.docker_input.epochs = [
     task_type: "task",
     event_source: "event_file",
     event_time_shift_sec: -10.6105,
     event_file: [trial_type: [char: 1]],
     epochs: [event_id: 1, tmin: -0.2, tmax: 0.8,
              baseline: [null, 0.0], reject_by_annotation: true]
   ]
   params.megflow.datasets.docker_input.covariance = [
     type: "epochs",
     event_source: "event_file",
     event_time_shift_sec: -10.6105,
     event_file: [trial_type: [char: 1]],
     epochs: [event_id: 1, tmin: -0.2, tmax: 0.0,
              baseline: [null, 0.0], reject_by_annotation: true]
   ]
   params.megflow.datasets.docker_input.forward = [epoch_label: "char_onset"]
   params.megflow.datasets.docker_input.source = [
     epoch_label: "char_onset",
     source_methods: ["dSPM"]
   ]

.. code-block:: bash

   docker run --rm -it \
     -v /data/study/bids:/input \
     -v /data/study/megflow:/output \
     -v /data/study/smri:/smri \
     -v /data/study/megflow.config:/program/nextflow/nextflow.config \
     cmrlab/megflow:1.0.0 \
     -i /input -o /output --fs_subjects_dir /smri \
     --steps meg_all --resume

dSPM and LCMV Covariance
------------------------

The preceding dSPM-only example produces ``bl-cov.fif`` but does not compute an
LCMV data covariance. To run both methods, add ``LCMV`` and define its data
window. MEGFlow computes ``lcmv-data-cov.fif`` from the exact saved epochs and
passes the same default target rank to both covariance roles and both source
solvers. Both runs write ``resolved-rank.json``; source imaging validates and
consumes that exact dictionary instead of estimating a second default rank.

.. code-block:: groovy

   params.megflow.datasets.docker_input.rank_policy = "auto"
   params.megflow.datasets.docker_input.source = [
     type: "epochs",
     source_methods: ["dSPM", "LCMV"],
     data_type: "meg",
     LCMV: [
       data_covariance: [tmin: 0.01, tmax: 0.40, method: "auto"],
       make_lcmv: [
         reg: 0.05,
         pick_ori: null,
         weight_norm: "unit-noise-gain-invariant"
       ]
     ]
   ]

For continuous beamforming, set ``source.type = "raw"``. The data covariance
and source solver then consume the exact analysis-ready Raw associated with the
epoch branch; they do not reopen the original imported recording.

Function-level rank values remain available when a validated study-specific
override is required. Use MNE dictionaries for direct ``rank`` fields:

.. code-block:: groovy

   params.megflow.datasets.docker_input.source.LCMV = [
     data_covariance: [tmin: 0.01, tmax: 0.40, rank: [meg: 60]],
     make_lcmv: [reg: 0.05, rank: [meg: 60]]
   ]

These explicit values override ``rank_policy`` independently. The legacy
``source.LCMV.n_rank: 60`` remains accepted and is normalized to ``[meg: 60]``,
but new configurations should prefer ``rank_policy`` or explicit per-function
rank dictionaries. See :doc:`rank_covariance` for the full precedence table.

Structural MRI Only
-------------------

Use ``steps = "anatomy"`` when only structural processing is required. DeepPrep
currently expects BIDS T1w input in MEGFlow. The FreeSurfer license must be
mounted and passed through the entrypoint; the CLI value is mapped to the
effective ``anatomy.fs_license_file`` field.

.. code-block:: groovy

   includeConfig "/program/nextflow/nextflow_for_docker.config"

   params.megflow.datasets.docker_input.mri_import = [
     subject_id: ["05", "09", "11", "14", "15", "17", "18", "23", "24", "25"],
     session_id: null,
     task: null,
     run_id: null
   ]
   params.megflow.datasets.docker_input.anatomy = [
     method: "deepprep",
     is_bids: true,
     deepprep_device: "cpu"
   ]

.. code-block:: bash

   docker run --rm -it \
     -v /data/MEG-MASC:/input \
     -v /data/MEG-MASC/anatomy_run:/output \
     -v /data/MEG-MASC/smri:/smri \
     -v /data/license.txt:/fs_license.txt:ro \
     -v /data/MEG-MASC/anatomy.config:/program/nextflow/nextflow.config:ro \
     cmrlab/megflow:1.0.0 \
     -i /input -o /output \
     --fs_subjects_dir /smri \
     --fs_license_file /fs_license.txt \
     --anatomy_preprocess_method deepprep \
     --steps anatomy --resume

For non-BIDS NIfTI or DICOM input, use ``method: "freesurfer"`` and configure
``t1_input_type`` plus ``t1_dicom_series_glob`` when needed. Pseudo-MRI is a
third option for recordings with usable digitization/headshape points but no
subject T1. See :doc:`configuration` for all anatomy fields and conditions.

Resting-State Epochs
--------------------

Continuous preprocessing and ICA are unchanged for resting-state data. The
optional epoch stage creates fixed-length events from the cleaned recording.

.. code-block:: groovy

   params.megflow.datasets.docker_input.epochs = [
     task_type: "resting",
     resting: [fixed_length_duration: 2.0],
     epochs: [
       event_id: null,
       tmin: 0.0,
       tmax: 2.0,
       reject_by_annotation: true,
       picks: "meg",
       baseline: null,
       preload: true,
       detrend: null
     ]
   ]

Task Events from BIDS ``events.tsv``
------------------------------------

Use ``event_source = "event_file"`` when the trial definition is stored in a
BIDS sidecar. Confirm the column name, value mapping, timing correction, epoch
window, and baseline for the specific dataset.

.. code-block:: groovy

   params.megflow.datasets.docker_input.epochs = [
     task_type: "task",
     event_source: "event_file",
     event_time_shift_sec: 0.0395,
     event_file: [trial_type: [target: 1, standard: 2]],
     epochs: [
       event_id: [1, 2],
       tmin: -0.2,
       tmax: 0.8,
       baseline: [null, 0.0],
       reject_by_annotation: true
     ]
   ]

Task Events from a Trigger Channel
----------------------------------

Use ``event_source = "find_events"`` for hardware triggers. ``stim_channel``,
``shortest_event``, ``min_duration``, event ids, and timing correction are all
dataset-specific and should be inspected before a full run.

.. code-block:: groovy

   params.megflow.datasets.docker_input.epochs = [
     task_type: "task",
     event_source: "find_events",
     event_time_shift_sec: 0.04858,
     find_events: [
       stim_channel: "STI101",
       shortest_event: 1,
       min_duration: 0.0
     ],
     epochs: [event_id: 1, tmin: -0.1, tmax: 0.5,
              baseline: [null, 0.0], reject_by_annotation: true]
   ]

Raw or Empty-Room Covariance
----------------------------

``raw_covariance_task_id`` is a pairing mechanism, not a separate empty-room
workflow. The noise recording must first be imported. MEGFlow then takes an
experimental recording name and replaces its BIDS ``task-...`` entity with the
configured task id to locate the paired continuous recording.

.. code-block:: groovy

   params.megflow.datasets.docker_input.meg_import = [
     subject_id: "first:10",
     session_id: null,
     task: ["aef", "emptyroom"],
     run_id: null,
     raw_include_keywords: null,
     raw_exclude_keywords: null
   ]
   params.megflow.datasets.docker_input.covariance = [
     type: "raw",
     raw_covariance_task_id: "emptyroom",
     compute_raw_covariance: [
       tmin: 0,
       tmax: null,
       method: "auto",
       reject: [mag: 4e-12],
       reject_by_annotation: true
     ]
   ]

For example, ``sub-01_task-aef_run-01_meg.fif`` is paired with
``sub-01_task-emptyroom_run-01_meg.fif``. Other entities still need to match.
If the noise file uses a different naming relationship, rename or organize it
to satisfy this mechanism before running raw covariance. MEGFlow waits for the
paired recording's ICA-clean output and does not probe a predicted filename, so
parallel scheduling cannot select a stale covariance input. The empty-room
record is cleaned but does not continue into its own epochs or source model.
Several experimental tasks may reuse the same paired noise recording; a missing
pair stops the full source run with an error.

The default ``rank_policy: "auto"`` is resolved from the experimental target,
not from the empty-room covariance. Both inputs are restricted to common good
channels in target order, and the raw noise input must have enough empirical
rank to support the target rank. This compatibility check does not establish
that independently fitted ICA operators are identical.

The covariance override may also be recording specific. In this example only
the experimental task requests raw covariance; the noise task can keep the
dataset's default covariance configuration and is still recognized as the
requested reference:

.. code-block:: groovy

   params.megflow.datasets.docker_input.recordings = [
     experiment: [
       match: [task: ["aef", "vef"]],
       covariance: [type: "raw", raw_covariance_task_id: "emptyroom"]
     ],
     empty_room: [
       match: [task: "emptyroom"]
     ]
   ]

Dataset-Specific DeepReject
---------------------------

DeepReject can be tuned per dataset without duplicating the rest of the artifact
configuration:

.. code-block:: groovy

   params.megflow.datasets.MEG_MASC_word.artifacts = [
     meg_vendor: "kit",
     deepreject: [mode: "lenient"]
   ]

The inherited ``enabled``, device, fold, and resource values remain unchanged.
``lenient`` changes BadSegNet interval post-processing; it does not switch model
weights. See :doc:`deepreject` before setting low-level thresholds.

Recording-Specific Overrides
----------------------------

Use ``recordings`` when imported files from the same dataset require different
post-import settings. Match fields are case-insensitive, fields within one
``match`` map are combined with AND, and list values within a field are combined
with OR. Exactly zero or one profile may match a recording; multiple matches are
an error.

.. code-block:: groovy

   params.megflow.datasets.LanguageStudy = [
     dataset_dir: "/data/LanguageStudy",
     fs_subjects_dir: "/data/LanguageStudy/smri",
     steps: "meg_all",
     meg_import: [task: ["auditory", "visual"]],
     recordings: [
       auditory_task: [
         match: [task: "auditory"],
         epochs: [
           event_source: "find_events",
           event_time_shift_sec: 0.0395,
           find_events: [stim_channel: "STI101"],
           epochs: [event_id: 1, tmin: -0.1, tmax: 0.6]
         ],
         covariance: [event_time_shift_sec: 0.0395]
       ],
       visual_run_two: [
         match: [task: "visual", run: "2"],
         artifacts: [deepreject: [mode: "strict"]],
         epochs: [
           event_source: "event_file",
           event_file: [trial_type: [target: 1]],
           epochs: [event_id: 1, tmin: -0.2, tmax: 0.8]
         ]
       ]
     ]
   ]

Recording profiles are resolved only after MEG import. They can specialize
``rank_policy``, ``megqc``, continuous preprocessing, digitization, artifacts, ICA, epochs,
covariance, coregistration, forward modeling, source reconstruction, or reduce
an already enabled MEG stage. They cannot change file discovery, import a file
excluded by ``meg_import``, create an anatomy plan, alter dataset paths, or
change dataset-level report thresholds. Put those settings in the dataset
profile. See :ref:`configuration-profile-resolution` for every match field.

Three-Level OPM-COG Task Example
--------------------------------

:download:`nextflow_opm_cog_task_overrides_example.config
<../../../nextflow/nextflow_opm_cog_task_overrides_example.config>`
demonstrates all three configuration levels in one runnable source-mode file:

* ``defaults`` defines shared epoch, covariance, forward, and source policies.
* ``datasets.OPM_COG`` defines OPM vendor settings, import selectors, and the
  event convention shared by the dataset.
* ``datasets.OPM_COG.recordings`` matches AEF, VEF, TAP, and SSVEF tasks and
  gives each task its own epoch window, covariance baseline, output label, and
  source visualization target.

All task names must also be present in ``meg_import.task`` because recording
profiles are applied after discovery. Edit the example paths and selectors,
then run the command shown at the top of the config file.

Docker Corpus with Different Dataset Settings
---------------------------------------------

In Docker corpus mode, ``/input`` must contain one immediate child directory per
dataset. Name each profile after its child directory and omit ``dataset_dir``;
the entrypoint sets ``corpus_root`` from ``--input`` and preserves these named
profiles and dataset filters.

.. code-block:: text

   /data/corpus/
   |-- WAND_Extracted/
   |-- SMN4Lang/
   `-- MEG-MASC/

Example ``corpus.config``:

.. code-block:: groovy

   includeConfig "/program/nextflow/nextflow_for_docker.config"

   params.megflow.dataset_include = ["WAND_Extracted", "SMN4Lang", "MEG-MASC"]
   params.megflow.dataset_exclude = []
   params.megflow.defaults.steps = "meg_ica"
   params.megflow.defaults.meg_import.subject_id = "first:10"

   params.megflow.datasets = [
     WAND_Extracted: [
       meg_import: [session_id: ["01"], task: ["visual"]],
       megqc: [meg_vendor: "ctf"],
       artifacts: [meg_vendor: "ctf"],
       epochs: [
         event_source: "find_events",
         find_events: [stim_channel: "UPPT001"],
         epochs: [event_id: 1, tmin: -0.2, tmax: 1.0]
       ]
     ],
     SMN4Lang: [
       rank_policy: [meg: 50],
       meg_import: [task: ["RDR"], run_id: ["1"]],
       megqc: [meg_vendor: "elekta"],
       epochs: [
         event_source: "event_file",
         event_time_shift_sec: -10.6105,
         event_file: [trial_type: [char: 1]],
         epochs: [event_id: 1, tmin: -0.2, tmax: 0.8]
       ]
     ],
     "MEG-MASC": [
       dataset_format: "bids",
       file_suffix: ".con",
       meg_import: [session_id: ["0"], task: ["0"]],
       megqc: [meg_vendor: "kit"],
       artifacts: [meg_vendor: "kit", deepreject: [mode: "lenient"]]
     ]
   ]

Run it with:

.. code-block:: bash

   docker run --rm -it \
     -v /data/corpus:/input \
     -v /data/corpus_megflow:/output \
     -v /data/corpus_smri:/smri \
     -v /data/corpus.config:/program/nextflow/nextflow.config:ro \
     cmrlab/megflow:1.0.0 \
     -i /input -o /output --fs_subjects_dir /smri \
     --corpus --resume

Omitting ``--steps`` keeps the stage policy from the config. Passing
``--steps meg_ica`` would change the shared corpus default while preserving any
explicit dataset-level ``steps`` overrides.

Runnable Three-Dataset Source Demo
----------------------------------

``nextflow/nextflow_multi_dataset_demo.config`` is the complete runnable
example. It uses three named profiles with explicit paths:

* ``WAND_visual`` uses CTF settings, ``UPPT001`` trigger events, and a visual
  source label.
* ``SMN4Lang_RDR`` uses Elekta settings, BIDS event-file mapping, a measured
  event-time correction, a dataset-level validated ``[meg: 50]`` rank policy,
  and a language source label.
* ``MEG_MASC_word`` uses KIT digitization sidecars, customized fine coregistration,
  word-event filtering, and lenient DeepReject segment post-processing.

Edit only the path and subject-selection fields needed for the target server,
then run:

.. code-block:: bash

   bash run_MultiDatasets_sourcecode.sh

The source runner uses host Nextflow, derives the log and work paths from the
configured ``params.megflow.output_dir``, and defaults to
``-profile local,strict -resume``. Useful overrides include:

.. code-block:: bash

   CONDA_ENV=megflow bash run_MultiDatasets_sourcecode.sh
   PROFILE=slurm,strict bash run_MultiDatasets_sourcecode.sh
   RESUME=false DRY_RUN=true bash run_MultiDatasets_sourcecode.sh

Do not pass ``--steps`` to this source-mode command. Change
``params.megflow.defaults.steps`` or a named dataset profile's ``steps`` in the
demo config instead.

The file also demonstrates process-specific ``maxForks`` limits. Adjust those
limits according to available CPU, RAM, GPU, and storage throughput; they
control concurrency but do not change scientific parameters.

Cluster Execution
-----------------

Dataset profiles are independent of the executor. Keep the same
``params.megflow`` content and launch with the composable Slurm and Singularity
profiles:

.. code-block:: bash

   nextflow -log "$MEGFLOW_DRIVER_LOG" \
     -C nextflow/my_project.config \
     run nextflow/megflow.nf \
     -profile slurm,singularity,lenient \
     -resume

See :doc:`../tutorial/tutorial_cluster` for filesystem, SIF, scheduler, and
environment-variable requirements.
