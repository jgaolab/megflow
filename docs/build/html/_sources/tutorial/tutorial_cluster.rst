Cluster
================

MEGFlow provides composable ``slurm`` and ``singularity`` profiles. The Slurm
driver stays lightweight; each MEGFlow process is submitted as its own job with
the CPU, memory, time, retry, and error policy defined in ``nextflow.config``.
The work directory and all datasets must be visible from the login and compute
nodes at the same paths.

Build the SIF image once on a host that can access the Docker image:

.. code-block:: bash

   singularity build cmrlab_megflow_1.0.0.sif \
     docker-daemon://cmrlab/megflow:1.0.0

Set site-specific scheduler and container values without editing the project
configuration:

.. code-block:: bash

   export MEGFLOW_SLURM_PARTITION=cpu1,cpu2,fat
   export MEGFLOW_SLURM_ACCOUNT=my_account
   export MEGFLOW_SLURM_QOS=normal
   export MEGFLOW_SLURM_QUEUE_SIZE=100
   export MEGFLOW_SLURM_WORKDIR=/lustre/project/megflow/work
   export MEGFLOW_SIF=/lustre/project/containers/cmrlab_megflow_1.0.0.sif
   export MEGFLOW_SINGULARITY_CACHE=/lustre/project/.singularity
   export MEGFLOW_SINGULARITY_RUN_OPTIONS='-B /lustre:/lustre'
   export MEGFLOW_DRIVER_LOG=/lustre/project/megflow/logs/nextflow.log
   mkdir -p "$(dirname "$MEGFLOW_DRIVER_LOG")"

Launch the workflow directly from the login node or from a small Slurm driver
job:

.. code-block:: bash

   nextflow -log "$MEGFLOW_DRIVER_LOG" \
     -C nextflow/nextflow_for_smn4lang.config \
     run nextflow/megflow.nf \
     -profile slurm,singularity,lenient \
     -resume

Use ``strict`` instead of ``lenient`` when any failed recording should stop the
whole run. ``lenient`` retries resource-related exits using the process-specific
``maxRetries`` setting and then allows other recordings to continue.

If the cluster requires additional ``sbatch`` flags, put them in
``MEGFLOW_SLURM_EXTRA``. Do not request a GPU globally: add an accelerator or
site option only for processes that actually use one. Likewise, do not place
``queueSize`` inside a process selector; MEGFlow configures it in the Nextflow
``executor`` scope.

The ``singularity`` profile enables automatic mounts, but site filesystems may
still require explicit binds through ``MEGFLOW_SINGULARITY_RUN_OPTIONS``. Bind
the project, dataset, output, FreeSurfer, and license roots at the same absolute
paths used by the dataset profile.
