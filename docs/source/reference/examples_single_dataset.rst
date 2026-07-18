.. _examples-single-dataset:

Single-Dataset Configuration Examples
=====================================

Follow these examples in order: run a first MEG quality pass, prepare anatomy
when needed, then add dataset-specific epoch, covariance, and source settings.

.. _example-first-meg-pass:

Single Dataset: First MEG Pass
------------------------------

This Docker overlay selects one BIDS task and stops after continuous
preprocessing, artifact detection, and ICA cleaning. It avoids event,
covariance, and source-model assumptions during the first quality check.

**Configuration reference:** :doc:`configuration_datasets` for MEG import and
:doc:`configuration_preprocessing` for NormMEG-QC, artifacts, and ICA.

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
     -v /data/study/megflow.config:/config/project.config:ro \
     cplmeg/megflow:1.0.0 \
     --config /config/project.config \
     --input /input \
     --output /output \
     --steps meg_ica \
     --resume

.. _example-anatomy-only:

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
     -v /data/MEG-MASC/anatomy.config:/config/anatomy.config:ro \
     cplmeg/megflow:1.0.0 \
     --config /config/anatomy.config \
     --input /input \
     --output /output \
     --fs_subjects_dir /smri \
     --fs_license_file /fs_license.txt \
     --anatomy_preprocess_method deepprep \
     --steps anatomy \
     --resume

For non-BIDS NIfTI or DICOM input, use ``method: "freesurfer"`` and configure
``t1_input_type`` plus ``t1_dicom_series_glob`` when needed. Pseudo-MRI is a
third option for recordings with usable digitization/headshape points but no
subject T1. See :doc:`configuration_preprocessing` for all anatomy fields and
conditions.

.. _example-full-meg:

Full MEG with Existing Anatomy
------------------------------

Use ``meg_all`` only after the event definition, covariance strategy, subject
matching, and existing FreeSurfer or DeepPrep results have been checked. A full
source run is rarely dataset independent.

**Configuration reference:** :doc:`configuration_datasets` for stage and input
selection, and :doc:`configuration_source` for covariance and source settings.

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
     -v /data/study/megflow.config:/config/project.config:ro \
     cplmeg/megflow:1.0.0 \
     --config /config/project.config \
     --input /input \
     --output /output \
     --fs_subjects_dir /smri \
     --steps meg_all \
     --resume

.. _example-resting-epochs:

Resting-State Epochs
--------------------

Continuous preprocessing and ICA are unchanged for resting-state data. The
optional epoch stage creates fixed-length events from the cleaned recording.

**Configuration reference:** the **Epochs** section in
:doc:`configuration_preprocessing`.

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

.. _example-bids-events:

Task Events from BIDS ``events.tsv``
------------------------------------

Use ``event_source = "event_file"`` when the trial definition is stored in a
BIDS sidecar. Confirm the column name, value mapping, timing correction, epoch
window, and baseline for the specific dataset.

**Configuration reference:** the **Epochs** and **Event Timing Correction**
sections in :doc:`configuration_preprocessing`.

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

.. _example-trigger-events:

Task Events from a Trigger Channel
----------------------------------

Use ``event_source = "find_events"`` for hardware triggers. ``stim_channel``,
``shortest_event``, ``min_duration``, event ids, and timing correction are all
dataset-specific and should be inspected before a full run.

**Configuration reference:** the **Epochs** section in
:doc:`configuration_preprocessing`.

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

.. _example-lcmv-covariance:

dSPM and LCMV Covariance
------------------------

The preceding dSPM-only example produces ``bl-cov.fif`` but does not compute an
LCMV data covariance. To run both methods, add ``LCMV`` and define its data
window. MEGFlow computes ``lcmv-data-cov.fif`` from the exact saved epochs and
passes the same default target rank to both covariance roles and both source
solvers. Both runs write ``resolved-rank.json``; source imaging validates and
consumes that exact dictionary instead of estimating a second default rank.

**Configuration reference:** :doc:`configuration_source` and
:doc:`rank_covariance`.

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

These explicit values override ``rank_policy`` independently. The compatibility
field ``source.LCMV.n_rank: 60`` also remains accepted and is normalized to
``[meg: 60]``. New configurations should normally prefer ``rank_policy`` or
explicit per-function rank dictionaries. See :doc:`rank_covariance` for the
full precedence table.

.. _example-raw-covariance:

Raw or Empty-Room Covariance
----------------------------

``raw_covariance_task_id`` is a pairing mechanism, not a separate empty-room
workflow. The noise recording must first be imported. MEGFlow then takes an
experimental recording name and replaces its BIDS ``task-...`` entity with the
configured task id to locate the paired continuous recording.

**Configuration reference:** the **Covariance** section in
:doc:`configuration_source` and :doc:`rank_covariance`.

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

.. _example-maxwell-tsss:

MEGIN/Elekta Maxwell and tSSS
-----------------------------

Use the OSL stage name ``maxwell_filter`` and MNE parameter names. A positive
``st_duration`` enables tSSS. Site-specific fine-calibration and cross-talk
files normally belong in the dataset profile; a recording override must repeat
the full list because ``preproc.steps`` lists are replaced as a whole.

**Configuration reference:** :ref:`configuration-maxwell-tsss`.

.. code-block:: groovy

   params.megflow.datasets.MEGIN_SITE_A.preproc = [steps: [
     [maxwell_filter: [
       calibration: "/data/site-a/calibration/sss_cal.dat",
       cross_talk: "/data/site-a/calibration/ct_sparse.fif",
       st_duration: 10.0,
       st_correlation: 0.98,
       origin: "auto",
       coord_frame: "head"
     ]],
     [filter: [l_freq: 1.0, h_freq: 100.0]],
     [notch_filter: [freqs: [50, 100]]],
     [resample: [sfreq: 250]]
   ]]

The input Raw must already contain reliable bad-channel markings before this
stage. See :ref:`the full configuration contract
<configuration-maxwell-tsss>` and the downloadable example above before
applying the settings to a new acquisition system.
