Local Docker Run
================

Use the distributed Docker image for workstation or single-server execution.
Keep study-specific parameters in a small project config and mount data,
outputs, anatomy, and the FreeSurfer license separately.

Example
-------

The command below runs the full MEG branch with existing FreeSurfer/DeepPrep
anatomy. Event, covariance, coregistration, and source settings must already be
defined for the dataset. For a first dataset check, use ``--steps meg_ica`` and
omit the anatomy mounts instead.

.. code-block:: bash

   docker run --rm -it \
     -v /data/study/meg:/input \
     -v /data/study/megflow:/output \
     -v /data/study/smri:/smri \
     -v /data/license.txt:/fs_license.txt:ro \
     -v /data/study/project.config:/config/project.config:ro \
     cplmeg/megflow:1.0.0 \
     --config /config/project.config \
     --input /input \
     --output /output \
     --fs_license_file /fs_license.txt \
     --fs_subjects_dir /smri \
     --steps meg_all \
     --resume

Command Structure
-----------------

.. list-table::
   :header-rows: 1
   :widths: 36 64

   * - Argument
     - Purpose
   * - ``--rm -it``
     - Removes the stopped container and keeps an interactive terminal attached.
   * - ``/input`` mount
     - Container-visible MEG dataset root.
   * - ``/output`` mount
     - Processing derivatives, work cache, and static report output.
   * - ``/smri`` mount
     - Existing or generated FreeSurfer ``SUBJECTS_DIR``.
   * - ``/fs_license.txt`` mount
     - Read-only FreeSurfer license used by anatomy-dependent stages.
   * - ``/config/project.config`` mount
     - Project overlay selected explicitly by ``--config``.
   * - ``--steps``
     - Temporary stage override. Omit it to retain the stage in the project
       config.
   * - ``--resume``
     - Reuse valid Nextflow work-cache entries from the same output/work tree.

The entrypoint prepares the mounted output directory, then runs Nextflow with
the host UID/GID inferred from ``/input``. Report-only runs infer ownership from
``/output``. If neither mount has the desired owner, add
``-e LOCAL_UID="$(id -u)" -e LOCAL_GID="$(id -g)"`` before the volume mounts.

This command runs the Nextflow driver and local tasks inside the distributed
container. It is different from launching Nextflow from a source checkout with
``-profile docker``, where the driver remains on the host and starts one
container per task.

See :doc:`../quickstart/quick_guide` for the first-pass workflow,
:doc:`full_workflow` for anatomy and source stages, and
:doc:`../reference/configuration` for the ordered configuration reference.
