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
     cplmeg/megflow:1.0.0 \
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
host paths and process resources. After checking those paths, launch it with
``examples/run_scripts/corpus_source.sh --config nextflow/nextflow_multi_dataset_demo.config``.
See :doc:`examples` for both workflows and for recording-level task overrides.

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
suite currently validates the workflow with Nextflow 24.10.3. Nextflow 26.04
defaults to its stricter v2 syntax parser, while the current MEGFlow DSL2
workflow still uses dynamic Groovy constructs supported by parser v1. The
distributed image selects the compatible parser automatically. For a direct
source launch with Nextflow 26, set it explicitly:

.. code-block:: bash

   export NXF_SYNTAX_PARSER=v1
   nextflow run nextflow/megflow.nf ...

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
the top-level ``-log`` option.

The commands below use ``-C``, so ``my_project.config`` must be a complete
configuration or include the repository base with
``includeConfig "nextflow.config"``. Use ``-c`` instead for a small additive
overlay. See :ref:`configuration-cli-flags` for the exact soft- and
hard-override behavior.

For example:

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
memory.

Local Resource Budgets
----------------------

By default, ``params.megflow.execution.local_cpus``, ``local_memory``, and
``local_max_tasks`` are all ``"auto"``. MEGFlow resolves auto mode from the
CPU and memory resources visible to the Nextflow JVM or outer container. It
then gives those values to the local executor, which accounts each task's
``cpus`` and ``memory`` requests against the shared budgets.

The controls operate at three different levels. ``params.megflow.execution``
provides convenient MEGFlow aliases for the whole local run; ``process``
directives describe one task; and ``maxForks`` adds a cap for one process
definition.

.. list-table:: MEGFlow and native Nextflow resource controls
   :header-rows: 1
   :widths: 24 25 25 26

   * - User question
     - MEGFlow setting
     - Native Nextflow setting
     - Scope
   * - How many CPUs may local tasks share?
     - ``local_cpus``
     - ``executor.$local.cpus``
     - Total local-executor CPU budget.
   * - How much memory may local tasks share?
     - ``local_memory``
     - ``executor.$local.memory``
     - Total local-executor memory budget.
   * - How many local tasks may run at once?
     - ``local_max_tasks``
     - ``executor.$local.queueSize``
     - Global local-executor task ceiling.
   * - What may one task request?
     - A ``withName`` override
     - ``process.cpus`` / ``process.memory``
     - One task instance of the matching process.
   * - How many instances of one stage may overlap?
     - A ``withName`` override
     - ``process.maxForks``
     - One process definition, not the whole workflow.

Set any limit independently in an additive overlay. For example, this
workstation configuration budgets 16 CPUs and 48 GB across at most three
running local tasks:

.. code-block:: groovy

   params {
     megflow {
       execution {
         local_cpus = 16
         local_memory = "48 GB"
         local_max_tasks = 3
       }
     }
   }

The equivalent native Nextflow local-executor configuration is shown below.
Use either the MEGFlow aliases above or the native form in one overlay; there
is no benefit in defining both.

.. code-block:: groovy

   executor {
     $local {
       cpus = 16
       memory = "48 GB"
       queueSize = 3
     }
   }

``queueSize`` is a global ceiling, not a promise that this many tasks will
always run. Actual concurrency can be lower because all of these constraints
must be satisfied simultaneously:

* the executor's ``queueSize``;
* the sum of ready tasks' ``cpus`` and ``memory`` requests;
* the workflow DAG and available inputs; and
* the matching process's ``maxForks``.

A per-process override is useful for an I/O-heavy or otherwise sensitive
stage:

.. code-block:: groovy

   process {
     withName: detect_artifacts {
       cpus = 4
       memory = "16 GB"
       maxForks = 2
     }
   }

With the 16-CPU, three-task whole-run budget above, this selector allows at
most two ``detect_artifacts`` tasks at once. Other process types may still use
the remaining task capacity and resources when their inputs are ready.

The ``cpus`` and ``memory`` values in a process selector are **per task**, not
machine-wide limits. Ensure a fixed whole-run budget can accommodate the
largest task request, including any memory increase on retry. MEGFlow passes
``task.cpus`` into its known parallel worker pools so their effective
parallelism stays inside the declared task budget.

MEGFlow also sets ``OMP_NUM_THREADS``, ``MKL_NUM_THREADS``,
``OPENBLAS_NUM_THREADS``, and ``NUMEXPR_MAX_THREADS`` per task from
``task.cpus``. Processes that already create outer workers use one native
thread per worker; in particular, ``score_meg_quality`` keeps
``--n_jobs ${task.cpus}``. A project may override ``beforeScript`` globally or
in a process selector when a native library has a tested, different threading
requirement.

Local and Slurm ``queueSize``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The distributed Docker command runs Nextflow's **local executor** inside the
outer container. For that path, ``local_max_tasks`` / ``executor.$local.queueSize``
limits the number of local tasks handled concurrently. ``local_cpus`` and
``local_memory`` are scheduling budgets; a bare local operating-system process
can still exceed a declared request. Container runtime ``--cpus`` and
``--memory`` options can additionally enforce an outer Docker limit.

For Slurm, ``executor.$slurm.queueSize`` limits Nextflow's task submission and
management capacity. It does not set the Slurm partition's CPU capacity and it
does not limit a single process type. MEGFlow exposes this setting as
``MEGFLOW_SLURM_QUEUE_SIZE``. A ``maxForks`` selector remains the appropriate
way to cap one process under either executor.

Official Nextflow references
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* `Local executor behavior
  <https://docs.seqera.io/nextflow/executor/local>`__
* `Executor configuration: cpus, memory, and queueSize
  <https://docs.seqera.io/nextflow/reference/config/executor>`__
* `Process cpus directive
  <https://docs.seqera.io/nextflow/reference/process/directives/cpus>`__
* `Process memory directive
  <https://docs.seqera.io/nextflow/reference/process/directives/memory>`__
* `Process maxForks directive
  <https://docs.seqera.io/nextflow/reference/process/directives/max-forks>`__

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
       ``cplmeg/megflow:1.0.0``. The image contains DeepPrep.
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
       to ``cplmeg/megflow:1.0.0``.
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

These variables apply to direct Nextflow launches. The public
``examples/run_scripts/corpus_source.sh`` helper derives its ``-w`` and ``-log``
values from the configured output root; override them with its ``--work-dir``
and ``--log-file`` options.

For Slurm with Singularity:

.. code-block:: bash

   export MEGFLOW_SLURM_PARTITION=cpu
   export MEGFLOW_SLURM_ACCOUNT=my_account
   export MEGFLOW_SIF=/shared/containers/cplmeg_megflow_1.0.0.sif
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
