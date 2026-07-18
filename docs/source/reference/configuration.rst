Configuration Reference
=======================

MEGFlow is configured through ``params.megflow`` in a Nextflow configuration
file. Most users should run the distributed Docker image and provide a small
project config. The image base config is loaded automatically before that
project overlay, so only settings that differ for the study need to be repeated.

Configuration Sequence
----------------------

Read the reference in workflow order. The overview below explains how a project
config is loaded; the linked pages then move from dataset selection through
preprocessing, source analysis, reporting, and execution resources.

1. :doc:`configuration_datasets`: resolve profiles, match recordings, discover
   inputs, and select stages.
2. :doc:`configuration_preprocessing`: configure anatomy, NormMEG-QC,
   continuous cleaning, ICA, and epochs in execution order.
3. :doc:`configuration_source`: configure rank, covariance, forward/source
   modeling, report thresholds, and source visualization.
4. :doc:`configuration_execution`: choose Docker/source/HPC execution and
   resource or failure policies.

.. toctree::
   :maxdepth: 1

   configuration_datasets
   configuration_preprocessing
   configuration_source
   configuration_execution

Using a Config with Docker
--------------------------

Create a host file such as ``/data/study/project.config`` and add only
project-specific overrides. The Docker entrypoint passes it to Nextflow with
``-c`` after the image's project-level ``nextflow.config`` has been loaded.
This example selects resting-state recordings and stops after continuous
cleaning so the first quality-control report can be checked before configuring
epochs or source reconstruction:

.. code-block:: groovy

   params.megflow.datasets.docker_input.steps = "meg_ica"
   params.megflow.datasets.docker_input.meg_import = [
     subject_id: null,
     session_id: null,
     task: ["rest"],
     run_id: null,
     raw_include_keywords: null,
     raw_exclude_keywords: null
   ]

Mount that file at any readable container path and identify it with
``--config``. The paths before each colon are host paths; ``/input``,
``/output``, and ``/config/project.config`` are the corresponding paths inside
the container:

.. code-block:: bash

   docker run --rm -it \
     -v /data/study/bids:/input \
     -v /data/study/megflow:/output \
     -v /data/study/project.config:/config/project.config:ro \
     cplmeg/megflow:1.0.0 \
     --config /config/project.config \
     --input /input \
     --output /output \
     --resume

The command deliberately omits ``--steps`` so
``datasets.docker_input.steps`` from the project config remains effective. Add
``--steps <value>`` only when a run should temporarily override that setting.
The entrypoint writes the runtime config file to ``<output>/nextflow.config``.
It records the project settings and command-line path overrides appended for
the run; Nextflow first loads the image base config and then applies this file.

For multiple datasets, mount the directory that contains the dataset folders
and add ``--corpus``. Named profiles in the project config must match the
immediate child directory names. Each profile can then define its own import,
preprocessing, epoch, covariance, and source settings:

.. code-block:: bash

   docker run --rm -it \
     -v /data/corpus:/input \
     -v /data/corpus_megflow:/output \
     -v /data/corpus.config:/config/corpus.config:ro \
     cplmeg/megflow:1.0.0 \
     --config /config/corpus.config \
     --input /input \
     --output /output \
     --corpus \
     --resume

See :doc:`examples` for complete single-dataset, anatomy-only, source-imaging,
and heterogeneous corpus configs.

Docker CLI and Configuration Precedence
---------------------------------------

Use the Docker command line for container mounts and run-level choices. Keep
scientific parameters in the project config so they remain reviewable and can
vary by dataset or recording.

.. list-table::
   :header-rows: 1
   :widths: 28 32 40

   * - Concern
     - Recommended location
     - Examples
   * - Host/container paths
     - Docker volume mounts and entrypoint options
     - Input, output, FreeSurfer subjects, license, T1 input, and project config.
   * - Run selection
     - Entrypoint options when a temporary override is useful
     - ``--corpus``, ``--resume``, and optional ``--steps``.
   * - Shared processing policy
     - ``params.megflow.defaults``
     - Rank, filtering, artifact detection, ICA, epochs, covariance, and source.
   * - Dataset differences
     - ``params.megflow.datasets.<name>``
     - Vendor, import selectors, events, timing, anatomy, and source labels.
   * - Recording differences
     - Dataset ``recordings`` profiles
     - Task- or run-specific epochs, covariance, DeepReject, and source settings.

There are two separate and intentional resolution chains:

1. The image's ``nextflow_for_docker.config`` supplies complete container
   defaults, the mounted project config overrides them, and explicit Docker
   entrypoint options append run-level path or stage overrides.
2. Within the effective ``params.megflow`` map, MEGFlow resolves
   ``defaults`` first, then the matching dataset, then at most one matching
   recording profile.

Consequently, ``--steps meg_ica`` overrides a config's shared or
``docker_input`` stage for that run, but it does not replace unrelated
preprocessing settings. In corpus mode, it changes the shared default while
preserving an explicit ``steps`` value in a named dataset profile.

Command-line options map as follows:

.. list-table::
   :header-rows: 1
   :widths: 24 36 40

   * - Docker option
     - Effective config target
     - Notes
   * - ``-c``, ``--config``
     - Project configuration file
     - A path visible inside the container. It defaults to
       ``/program/nextflow/nextflow.config``; explicit ``--config`` is clearer
       for a mounted project overlay.
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
     - Single-dataset structural MRI input root. It is rejected in corpus mode;
       set ``t1_dir`` in each named dataset profile instead.
   * - ``--resume``
     - Nextflow ``-resume``
     - Reuses valid cached tasks.
   * - ``-r``, ``--view-report``
     - Report viewer mode
     - Starts Streamlit without launching preprocessing.

Processing and report policy is intentionally not exposed through the Docker
entrypoint. Configure ``anatomy.method``, ``anatomy.t1_input_type``,
``anatomy.t1_dicom_series_glob``, ``report.static_task_log_mode``, and
``report.static_artifact_overview_duration`` in ``params.megflow.defaults`` or
the matching dataset profile. MEGFlow validates the effective values after
defaults and dataset settings are merged, before submitting any process.

Canonical Configuration Structure
---------------------------------

The authoritative container defaults are defined in
``nextflow/nextflow_for_docker.config``. The source-run defaults in
``nextflow/nextflow.config`` use the same ``params.megflow`` schema, with
host-specific paths and execution profiles.

The profile system has one canonical structure for single-dataset,
corpus-level, and mixed-task runs:

.. code-block:: groovy

   params {
     megflow = [
       code_dir: "/program/megflow",
       output_dir: "/output",
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
         docker_input: [
           dataset_dir: "/input",
           fs_subjects_dir: "/smri",
           meg_import: [subject_id: "first:10", task: ["rest"]]
         ]
       ]
     ]
   }
