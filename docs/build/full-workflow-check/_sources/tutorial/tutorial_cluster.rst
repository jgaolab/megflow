Cluster Execution
=================

MEGFlow provides composable ``slurm`` and ``singularity`` profiles for source
launches. Nextflow runs on the login or driver node and submits each MEGFlow
process as a separate Slurm job. The project config, datasets, output root,
FreeSurfer files, container, and work directory must be visible at the same
absolute paths from every compute node.

Prerequisites
-------------

Use Nextflow 24.10 or newer; the repository integration suite currently tests
24.10.3. Build the SIF once on a host with registry access:

.. code-block:: bash

   singularity build cplmeg_megflow_1.0.0.sif \
     docker://cplmeg/megflow:1.0.0

If the Docker image is already present in the local Docker daemon,
``docker-daemon://cplmeg/megflow:1.0.0`` is an alternative source URI.

Site Settings
-------------

Keep scientific settings in a user-owned config such as
``nextflow/my_project.config``. Supply scheduler and filesystem details with
environment variables:

The launch command below uses Nextflow ``-C``. The project config must therefore
be complete or include the repository base with
``includeConfig "nextflow.config"``. For a small additive project overlay, use
``-c`` instead. See :ref:`configuration-cli-flags` for the distinction between
Nextflow's ``-c`` and ``-C`` and the Docker entrypoint's ``--config``.

.. code-block:: bash

   export MEGFLOW_SLURM_PARTITION=cpu
   export MEGFLOW_SLURM_ACCOUNT=my_account
   export MEGFLOW_SLURM_QOS=normal
   export MEGFLOW_SLURM_QUEUE_SIZE=100
   export MEGFLOW_SLURM_WORKDIR=/shared/project/megflow/work
   export MEGFLOW_SIF=/shared/project/containers/cplmeg_megflow_1.0.0.sif
   export MEGFLOW_SINGULARITY_CACHE=/shared/project/.singularity
   export MEGFLOW_SINGULARITY_RUN_OPTIONS='-B /shared:/shared'
   export MEGFLOW_DRIVER_LOG=/shared/project/megflow/report/nextflow/nextflow.log

``MEGFLOW_SLURM_EXTRA`` can carry additional ``sbatch`` options such as a site
constraint. Request GPU resources only in selectors for processes that use a
GPU; do not add them globally.

Launch
------

Create the driver-log directory before starting Nextflow because ``-log`` is
resolved before the workflow config is loaded:

.. code-block:: bash

   mkdir -p "$(dirname "$MEGFLOW_DRIVER_LOG")"

   nextflow -log "$MEGFLOW_DRIVER_LOG" \
     -C nextflow/my_project.config \
     run nextflow/megflow.nf \
     -profile slurm,singularity,strict \
     -resume

This command may run directly on the login node when site policy permits, or
inside a small Slurm driver job. The Nextflow driver itself remains outside the
SIF; each submitted task runs inside it.

Resources and Concurrency
-------------------------

MEGFlow defines process-specific ``cpus``, ``memory``, ``time``, and retry
limits. Override them with ``withName`` selectors in the project config. Keep
thread counts aligned with ``task.cpus`` so several concurrent recordings do
not oversubscribe a node.

``MEGFLOW_SLURM_QUEUE_SIZE`` limits the number of tasks Nextflow keeps submitted
to Slurm. It does not cap one process type. Use ``maxForks`` for a per-process
limit, for example:

.. code-block:: groovy

   process {
     withName: run_deepprep {
       cpus = 8
       memory = "32 GB"
       maxForks = 2
     }
     withName: source_imaging {
       cpus = 4
       memory = "16 GB"
       maxForks = 4
     }
   }

The ``debug`` profile sets ``maxForks = 1`` for each process definition;
different process types can still overlap when their dependencies allow.

Failure Policy
--------------

Use ``strict`` for validation and production runs where any failed recording
must stop the workflow. ``lenient`` uses process-specific, exit-code-based
retry and ignore rules so independent records may continue. It does not infer
whether an error is scientifically recoverable. Import and report failures
always terminate, while covariance and source reconstruction reserve exit code
2 for deterministic contract failures that also terminate in lenient mode.

See :doc:`../reference/configuration_execution` for the complete profile,
environment-variable, and failure-policy reference, and
:ref:`example-cluster-execution` for the matching configuration example.
