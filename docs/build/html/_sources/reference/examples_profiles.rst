.. _examples-profiles:

Multi-Dataset and Override Examples
===================================

These examples show dataset and recording overrides, heterogeneous Docker
corpus execution, the runnable source demo, and cluster launch patterns.

.. _example-deepreject:

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

**Configuration reference:** the **Artifact Detection** section in
:doc:`configuration_preprocessing`.

.. _example-recording-overrides:

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

The complete ``match`` semantics, including ``"*"``, ``suffix``, and
``filename_contains``, are defined in the **Recording Matching** section of
:doc:`configuration_datasets`.

.. _example-opm-task-overrides:

Three-Level OPM-COG Task Example
--------------------------------

`nextflow_opm_cog_task_overrides_example.config on GitHub
<https://github.com/jgaolab/megflow/blob/main/nextflow/nextflow_opm_cog_task_overrides_example.config>`__
demonstrates all three configuration levels in one source-mode file. Replace
its site paths before running it in another environment:

* ``defaults`` defines shared epoch, covariance, forward, and source policies.
* ``datasets.OPM_COG`` defines OPM vendor settings, import selectors, and the
  event convention shared by the dataset.
* ``datasets.OPM_COG.recordings`` matches AEF, VEF, TAP, and SSVEF tasks and
  gives each task its own epoch window, covariance baseline, output label, and
  source visualization target.

All task names must also be present in ``meg_import.task`` because recording
profiles are applied after discovery. Edit the example paths and selectors,
then run the command shown at the top of the config file.

**Configuration reference:** :doc:`configuration_datasets` for matching and
:doc:`configuration_source` for task-specific covariance/source settings.

.. _example-docker-corpus:

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
     -v /data/corpus.config:/config/corpus.config:ro \
     cmrlab/megflow:1.0.0 \
     --config /config/corpus.config \
     --input /input \
     --output /output \
     --fs_subjects_dir /smri \
     --corpus \
     --resume

Omitting ``--steps`` keeps the stage policy from the config. Passing
``--steps meg_ica`` would change the shared corpus default while preserving any
explicit dataset-level ``steps`` overrides.

**Configuration reference:** the **Dataset Discovery** section in
:doc:`configuration_datasets` and :doc:`configuration_execution`.

.. _example-source-multi-dataset:

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

**Configuration reference:** follow the ordered pages from
:doc:`configuration_datasets` through :doc:`configuration_execution`.

.. _example-cluster-execution:

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

**Configuration reference:** :doc:`configuration_execution`.
