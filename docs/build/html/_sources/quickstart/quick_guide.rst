Quickstart
==========

This page is for a first successful MEGFlow run. You do not need to understand
all configuration fields before starting. For a new dataset, the safest first
run is usually through ICA cleaning and QC:

.. code-block:: text

   MEG data -> preprocessing -> artifact detection -> ICA cleaning -> QC report

The later stages, especially epochs, covariance, coregistration, and source
reconstruction, are more dataset-specific. They often need event definitions,
noise-covariance choices, and anatomy matching to be checked before a full
source-level run. See :doc:`Full Workflow <../tutorial/full_workflow>` when you
are ready for those stages.

Before You Start
----------------

Prepare two required paths on your computer. You may also need an anatomy path
later for source-level analysis:

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Path
     - What it contains
   * - ``/path/to/bids_or_raw_meg``
     - Your MEG dataset. BIDS is recommended, but raw FIF discovery is also
       supported by the default config.
   * - ``/path/to/output``
     - An empty or reusable output directory for MEGFlow results.
   * - ``/path/to/smri``
     - Optional for the first run. FreeSurfer or DeepPrep anatomy outputs are
       required later for coregistration and source reconstruction.

If you do not already have anatomy outputs, start with the preprocessing check
below. Run anatomy or source reconstruction after you confirm how T1 images
should be selected for your dataset.

Run One Command
---------------

Replace only the paths in this command. This first run stops after ICA
cleaning, which avoids dataset-specific event and source-model assumptions:

.. code-block:: bash

   docker run --rm -it \
     -v /path/to/bids_or_raw_meg:/input \
     -v /path/to/output:/output \
     cmrlab/megflow:1.0.0 \
     -i /input \
     -o /output \
     --steps meg_ica \
     --resume

This run imports your MEG files, applies the default continuous preprocessing,
detects bad channels and bad segments, fits and labels ICA, applies ICA, and
generates the static QC report. The Docker paths after the colon are fixed
container paths; normally you only edit the host paths before the colon.

Check the Results
-----------------

When the run finishes, open:

.. code-block:: text

   /path/to/output/static_html_report/index.html

Start with the dataset dashboard. Sort the table by alarms, bad channels, bad
segments, ICA components, missing steps, or, for full runs, coregistration
distance and epoch rejection rate. Click a subject to review its detailed page.

The most useful output locations are:

.. list-table::
   :header-rows: 1
   :widths: 38 62

   * - Path
     - Meaning
   * - ``output/preprocessed/``
     - Processed data, artifact files, ICA outputs, and any later-stage outputs
       produced by the selected ``--steps`` mode.
   * - ``output/static_html_report/index.html``
     - Main quality-control report.
   * - ``output/report.html``
     - Nextflow execution report.
   * - ``output/timeline.html``
     - Nextflow runtime timeline.

What Do I Need to Change?
-------------------------

For the first ``meg_ica`` run, often nothing beyond paths and ``--steps``.
Change the config when one of these applies:

.. list-table::
   :header-rows: 1
   :widths: 32 68

   * - Situation
     - What to change
   * - You want only a subset of subjects, sessions, tasks, or runs.
     - Edit ``params.megflow.defaults.meg_import`` or a dataset profile's
       ``meg_import`` block in ``nextflow.config``.
   * - Your data are resting-state and you only need fixed-length epochs.
     - Before running ``meg_epochs`` or ``meg_all``, edit
       ``params.megflow.defaults.epochs.task_type`` and
       ``params.megflow.defaults.epochs.resting.fixed_length_duration``.
   * - Your task events come from a specific trigger channel or BIDS
       ``events.tsv`` labels.
     - Before running ``meg_epochs`` or ``meg_all``, edit
       the effective ``epochs.find_events`` or ``epochs.event_file`` block.
   * - Your line noise frequency is not 50 Hz.
     - Edit the effective ``preproc.steps`` block. In corpus runs with mixed
       line frequencies, override ``preproc`` only in the relevant dataset
       profiles. Keep the NormMEG-QC 1-100 Hz band-pass fixed; changing it
       breaks comparability with the normative reference.
   * - You want low-quality recordings to stop before later MEG analysis.
     - Set ``megqc.enabled = true`` and raise ``megqc.min_score``. For example,
       ``megqc.min_score = 70.0`` only lets recordings with an NMDQ score of
       70 or higher continue into artifact detection, ICA, epochs, and
       downstream analysis. Use ``megqc.alarm_score`` only for report warnings.
   * - You need a different sampling rate.
     - Edit ``preproc.steps`` and the ``resample.sfreq`` entry.
   * - You have empty-room or noise recordings for covariance.
     - Set ``covariance.type = "raw"`` and
       ``covariance.raw_covariance_task_id``.
   * - You only want to rebuild the report.
     - Set ``steps = "report"`` in the relevant profile. Docker users can pass
       ``--steps report`` to the entrypoint.

Minimal Config Override
-----------------------

Most users should start from the default config. If you only want to select a
task from a BIDS dataset, create a small overlay that first includes the complete
container defaults and then changes only the import filter. The ``includeConfig``
line is important: the remaining required defaults still come from the image.

.. code-block:: groovy

   includeConfig "/program/nextflow/nextflow_for_docker.config"

   params.megflow.datasets.docker_input.meg_import = [
     subject_id: null,
     session_id: null,
     task: ["rest"],
     run_id: null,
     raw_include_keywords: null,
     raw_exclude_keywords: null
   ]

Then run the first QC pass with:

.. code-block:: bash

   docker run --rm -it \
     -v /path/to/bids:/input \
     -v /path/to/output:/output \
     -v /path/to/my_nextflow.config:/program/nextflow/nextflow.config \
     cmrlab/megflow:1.0.0 \
     -i /input -o /output --steps meg_ica --resume

The Docker entrypoint automatically prepares the mounted output directory and
runs the pipeline as the host UID/GID inferred from ``/input``. The output
directory does not need to exist before the command is launched. Report-only
runs that only mount ``/output`` infer ownership from ``/output``. If neither
mount is owned by the desired output user, add
``-e LOCAL_UID="$(id -u)" -e LOCAL_GID="$(id -g)"`` before the volume mounts.

Next Steps
----------

After your first report is generated:

* Read :doc:`../tutorial/reports` to understand the static report.
* Read :doc:`../tutorial/outputs` to find processed files.
* Read :doc:`Full Workflow <../tutorial/full_workflow>` when you are ready to
  run anatomy, epochs, covariance, coregistration, and source reconstruction.
* Read :doc:`../reference/configuration` when you need full parameter details.
* Read :doc:`../reference/examples` for resting-state, task-based, source
  reconstruction, cluster, and empty-room covariance examples.
