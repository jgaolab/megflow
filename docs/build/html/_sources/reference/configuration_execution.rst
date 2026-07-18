.. _configuration-execution:

Execution and Resource Configuration
====================================

This page covers multi-dataset Docker execution and advanced source,
Docker-profile, Slurm, and Singularity launch settings.

Multi-Dataset Docker Example
----------------------------

For Docker, start from the corpus overlay in :doc:`examples`. Mount the corpus
root once, keep each dataset's scientific settings in a named profile, and let
the entrypoint assign container-visible dataset and output paths:

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

The repository also provides
`nextflow_multi_dataset_demo.config
<https://github.com/jgaolab/megflow/blob/main/nextflow/nextflow_multi_dataset_demo.config>`__
for a WAND, SMN4Lang, and MEG-MASC source-mode run. It contains site-specific
host paths and process resources and is launched by
``run_MultiDatasets_sourcecode.sh`` after those paths are checked. See
:doc:`examples` for both workflows and for recording-level task overrides.

**Worked examples:** :ref:`example-docker-corpus` and
:ref:`example-source-multi-dataset`.

Source and HPC Execution
------------------------

This section is for developers running from a source checkout and for HPC
sites that launch Nextflow directly. Users of the distributed Docker command
shown at the top of this page do not need these launcher options. The Docker
image already runs Nextflow inside the container with the local executor; do
not add a Nextflow ``docker`` profile to that command.

Source launches should use Nextflow 24.10 or newer. The repository integration
suite currently validates the workflow with Nextflow 24.10.3.

The main source configuration defines the execution layer as well as
``params.megflow``. Runtime observability files are stored inside the final
report package. Single-dataset runs use ``static_html_report/nextflow/`` and
corpus runs use ``corpus_static_html_report/nextflow/``:

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

Nextflow initializes its launcher log before it loads pipeline configuration.
A custom source launcher should therefore pass the configured log path through
the top-level ``-log`` option:

.. code-block:: bash

   mkdir -p /data/project/megflow_run/static_html_report/nextflow
   nextflow -log /data/project/megflow_run/static_html_report/nextflow/nextflow.log \
     -C nextflow/my_project.config \
     run nextflow/megflow.nf \
     -profile local,strict \
     -resume

The base ``process`` scope assigns conservative defaults and then overrides
CPU, memory, time, and retry limits with selectors that match current process
names in ``megflow.nf``. Memory-heavy stages use
``task.attempt``-dependent memory, so a resource-related retry requests more
memory. Slurm ``queueSize`` limits how many tasks Nextflow keeps submitted to
the scheduler; it is not a per-process concurrency limit. Use ``maxForks`` in a
project-specific process selector when one stage needs its own cap.

Two failure policies are available:

``lenient``
   Apply exit-code-based policies. Most processes retry exit codes 137-140 and
   ignore other failures after their retry policy. Coregistration also retries
   exit codes 1 and 134-136. Covariance and source reconstruction terminate on
   exit code 2, retry exit code 1 and 137-140, and may ignore other nonzero
   exits. MRI/MEG import and report generation always terminate. These rules do
   not infer whether an error is scientifically recoverable. Missing branches
   from ignored recording failures are allowed to close at the forward/source
   joins; dataset and corpus reports are then generated with the available
   outputs so the incomplete recordings remain auditable.

``strict``
   Terminate on the first process failure and set ``workflow.failOnIgnore``.
   Immediate termination does not guarantee report submission; use lenient
   mode when a partial-run report is required.

The following execution profiles are defined in ``nextflow.config``:

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Profile
     - Behavior
   * - ``local``
     - Run tasks directly on the current workstation or server.
   * - ``docker``
     - Keep the Nextflow driver on the host and run each workflow task in
       ``cmrlab/megflow:1.0.0``. The image contains DeepPrep.
   * - ``slurm``
     - Submit each task to Slurm using process-specific CPU, memory, and time
       directives.
   * - ``singularity``
     - Keep the Nextflow driver on the host and run each task in the MEGFlow
       SIF image. Compose it with ``slurm`` on HPC.
   * - ``lenient`` / ``strict``
     - Select the failure policy independently of the executor.
   * - ``debug``
     - Enable DEBUG logging and set ``maxForks = 1`` for each process. Different
       process definitions can still run concurrently when dependencies allow.

Docker, Slurm, and Singularity site settings for source launches are provided
through environment variables instead of anatomy parameters or hard-coded
cluster names:

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
     - Maximum tasks kept in the Slurm submission queue; default 100.
   * - ``MEGFLOW_SLURM_WORKDIR``
     - Shared task work directory; defaults to ``<output_dir>/work_slurm``.
   * - ``MEGFLOW_SIF``
     - MEGFlow SIF path.
   * - ``MEGFLOW_SINGULARITY_CACHE``
     - Shared image cache directory.
   * - ``MEGFLOW_SINGULARITY_RUN_OPTIONS``
     - Site-specific bind and runtime options, such as ``-B /data:/data``.

These variables apply to direct Nextflow launches. The repository helper
``run_MultiDatasets_sourcecode.sh`` passes its own ``-w`` and ``-log`` values,
derived from the configured output root; override those with the helper's
``WORK_DIR`` and ``LOG_FILE`` environment variables.

For Slurm with Singularity:

.. code-block:: bash

   export MEGFLOW_SLURM_PARTITION=cpu
   export MEGFLOW_SLURM_ACCOUNT=my_account
   export MEGFLOW_SIF=/shared/containers/cmrlab_megflow_1.0.0.sif
   export MEGFLOW_SINGULARITY_RUN_OPTIONS='-B /data:/data'

   nextflow -log /data/project/megflow_run/static_html_report/nextflow/nextflow.log \
     -C nextflow/my_project.config \
     run nextflow/megflow.nf \
     -profile slurm,singularity,lenient \
     -resume

When Nextflow is launched from source with the ``docker`` profile, the host
driver starts a separate MEGFlow container for each task. This is distinct from
invoking the distributed image directly, where both the driver and local tasks
run inside the outer container:

.. code-block:: bash

   export MEGFLOW_DOCKER_RUN_OPTIONS='-v /data:/data -v /path/license.txt:/fs_license.txt:ro'
   nextflow -C nextflow/project.config run nextflow/megflow.nf \
     -profile docker,strict -resume

The effective ``anatomy.fs_license_file`` must name the container-visible path
(``/fs_license.txt`` above). See :doc:`../tutorial/tutorial_cluster` for shared
filesystems, SIF setup, scheduler requirements, and site-specific examples.

**Worked example:** :ref:`example-cluster-execution`.
