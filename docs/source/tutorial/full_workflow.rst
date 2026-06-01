Full Workflow
=============

The Quickstart intentionally stops at ``meg_ica`` because later stages are
dataset-specific. A full source-level run needs correct event definitions,
noise covariance choices, anatomy matching, and coregistration settings. This
page explains when to run each broader workflow mode and what to check before
using it.

Docker output ownership is handled by the MEGFlow entrypoint. It prepares
mounted output permissions as root, then drops to the host UID/GID inferred
from ``/input`` before running Nextflow. Report-only runs that only mount
``/output`` infer ownership from ``/output`` instead. The host output directory
does not need to be created in advance. Use
``-e LOCAL_UID="$(id -u)" -e LOCAL_GID="$(id -g)"`` if neither mount is owned by
the desired output user.

Recommended Progression
-----------------------

For a new dataset, use this order:

.. code-block:: text

   1. meg_ica      -> verify continuous preprocessing, artifacts, and ICA QC
   2. anatomy      -> prepare or verify structural MRI outputs, if needed
   3. meg_epochs   -> verify events and epoch rejection
   4. meg_all      -> run covariance, coregistration, forward, and source
   5. report       -> regenerate the static report when outputs already exist

You can run ``all`` when the anatomy and MEG settings are already known and you
want structural MRI processing plus full MEG processing in one execution.

Run Anatomy Only
----------------

Use ``--steps anatomy`` when you only want to prepare structural MRI outputs.
This is useful when MEG and MRI are processed at different times, or when you
want to inspect FreeSurfer/DeepPrep outputs before source reconstruction.

For a BIDS dataset with T1w images:

.. code-block:: bash

   docker run --rm -it \
     -v /path/to/bids_dataset:/input \
     -v /path/to/output:/output \
     -v /path/to/smri:/smri \
     -v /path/to/license.txt:/fs_license.txt \
     cmrlab/megflow:1.0.0 \
     -i /input \
     -o /output \
     --fs_subjects_dir /smri \
     --fs_license_file /fs_license.txt \
     --steps anatomy \
     --resume

This writes or updates anatomy derivatives under ``/path/to/smri`` and the
MEGFlow output directory. After anatomy is ready and the MEG preprocessing QC
looks reasonable, run MEG processing with the same ``--fs_subjects_dir``.

Run Through Epochs
------------------

Use ``--steps meg_epochs`` after you have checked how events should be created.
This stage is where dataset assumptions usually matter most.

For resting-state data, confirm:

* ``epoch_config.task_type = "resting"``
* ``resting.fixed_length_duration``
* epoch length, rejection by annotation, and optional rejection thresholds

For task data, confirm:

* whether events come from ``mne.find_events`` or BIDS ``events.tsv``
* the correct stimulus channel, event ids, and event labels
* ``tmin`` and ``tmax`` for the intended analysis
* baseline, channel picks, and reject thresholds

Example command:

.. code-block:: bash

   docker run --rm -it \
     -v /path/to/bids_or_raw_meg:/input \
     -v /path/to/output:/output \
     -v /path/to/my_nextflow.config:/program/nextflow/nextflow.config \
     cmrlab/megflow:1.0.0 \
     -i /input \
     -o /output \
     --steps meg_epochs \
     --resume

Run Full MEG with Existing Anatomy
----------------------------------

Use ``--steps meg_all`` when:

* ``meg_ica`` QC looks reasonable.
* epoch settings have been checked.
* anatomy outputs already exist under ``fs_subjects_dir``.
* MEG recording ids can be matched to anatomy subject ids.
* covariance, coregistration, and source settings are ready.

.. code-block:: bash

   docker run --rm -it \
     -v /path/to/bids_or_raw_meg:/input \
     -v /path/to/output:/output \
     -v /path/to/smri:/smri \
     -v /path/to/license.txt:/fs_license.txt \
     -v /path/to/my_nextflow.config:/program/nextflow/nextflow.config \
     cmrlab/megflow:1.0.0 \
     -i /input \
     -o /output \
     --fs_subjects_dir /smri \
     --fs_license_file /fs_license.txt \
     --steps meg_all \
     --resume

Run Anatomy and Full MEG Together
---------------------------------

Use ``--steps all`` only when the structural MRI selection and MEG settings are
both ready. This mode runs anatomy first, then the full MEG workflow.

.. code-block:: bash

   docker run --rm -it \
     -v /path/to/bids_dataset:/input \
     -v /path/to/output:/output \
     -v /path/to/smri:/smri \
     -v /path/to/license.txt:/fs_license.txt \
     -v /path/to/my_nextflow.config:/program/nextflow/nextflow.config \
     cmrlab/megflow:1.0.0 \
     -i /input \
     -o /output \
     --fs_subjects_dir /smri \
     --fs_license_file /fs_license.txt \
     --steps all \
     --resume

Full Workflow Checklist
-----------------------

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Stage
     - Dataset-specific detail to confirm
   * - MEG import
     - Subject/session/task/run filters and raw-file exclusion keywords.
   * - Continuous preprocessing
     - Line-noise frequency, sampling rate, filtering range, and whether
       Maxwell/tSSS is required for the device.
   * - Artifact detection
     - Bad-channel detector sensitivity, bad-segment detector window length,
       and whether bad channels should be interpolated.
   * - ICA
     - Number of components, ECG/EOG channel availability, ICLabel/rule-based
       settings, and manual review expectations.
   * - Epochs
     - Resting fixed-length windows or task events, trigger channel, event ids,
       BIDS ``events.tsv`` labels, epoch time window, baseline, and rejection
       thresholds.
   * - Covariance
     - Baseline epochs versus paired raw noise/empty-room recordings. For raw
       covariance, set ``covar_type = "raw"`` and ``raw_covariance_task_id``.
   * - Anatomy matching
     - FreeSurfer/DeepPrep subject ids, ``anatomy_select_tag`` if needed, and
       whether anatomy was generated in this run or reused.
   * - Coregistration
     - Fiducial quality, head-shape quality, HPI availability, and whether the
       default ICP weights are appropriate.
   * - Forward and source reconstruction
     - Source spacing, source method, ``src_type``, epoch label, inverse or
       beamformer parameters, and the intended output interpretation.

After a Full Run
----------------

Open:

.. code-block:: text

   /path/to/output/static_html_report/index.html

Review the workflow diagram first, then check subject-level alarms. For a full
run, pay special attention to epoch rejection rate, covariance figures,
coregistration distance, final ICP images, forward/head-model outputs, and
source reconstruction figures.
