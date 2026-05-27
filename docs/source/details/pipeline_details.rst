Pipeline Details
================

MEGPrep is a Nextflow workflow that combines structural MRI processing,
continuous MEG preprocessing, artifact detection, ICA cleaning, optional
epoching, covariance estimation, MEG-MRI coregistration, forward modeling,
source reconstruction, and static quality-control reporting.

The main workflow is implemented in ``nextflow/meg_anat_pipeline_for_docker.nf``.
Configuration is supplied through ``nextflow.config`` and can be overridden by
selected command-line options. See :doc:`../reference/configuration` for the
complete configuration reference.

Execution Modes
---------------

The workflow is controlled by ``params.steps``:

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Mode
     - Processing scope
   * - ``anatomy``
     - MRI import, FreeSurfer or DeepPrep reconstruction, head surface, and BEM.
   * - ``meg_artifacts``
     - MEG import, continuous preprocessing, bad-channel and bad-segment
       detection, then static report.
   * - ``meg_ica``
     - ``meg_artifacts`` plus ICA fitting, artifact IC labeling, and ICA
       application.
   * - ``meg_epochs``
     - ``meg_ica`` plus epoch generation. With ``skip_ica``, epochs are created
       from the OSL preprocessed raw files instead of ICA-clean raw files.
   * - ``meg_all``
     - Full MEG workflow using an existing ``fs_subjects_dir``.
   * - ``all``
     - Structural MRI workflow plus full MEG workflow.
   * - ``report``
     - Static HTML report only, using existing outputs.

High-Level Flow
---------------

The complete ``meg_all`` or ``all`` execution order is:

.. code-block:: text

   MEG import
     -> continuous preprocessing
     -> artifact detection
     -> ICA fit
     -> ICA labeling
     -> ICA application
     -> epoching
     -> covariance estimation
     -> MEG-MRI coregistration
     -> forward solution
     -> source reconstruction
     -> static HTML report

When anatomy is enabled, structural processing runs before the downstream
coregistration and source reconstruction steps:

.. code-block:: text

   MRI import
     -> FreeSurfer or DeepPrep reconstruction
     -> head surface
     -> BEM model
     -> MEG-MRI coregistration dependencies

Continuous Core Preprocessing
-----------------------------

The continuous MEG core is task independent and applies to both resting-state
and task-based recordings.

1. ``import_MEG_dataset`` discovers input recordings.
   BIDS input is filtered by ``meg_import_config`` entities. Raw input is
   selected by ``file_suffix`` and optional ``raw_include_keywords`` /
   ``raw_exclude_keywords``. Raw discovery matches both files and directories,
   so CTF ``.ds`` folders are supported.

2. ``meg_preproc_osl`` calls ``meg_preproc_osl.py``, which passes
   ``preproc_config`` to OSL-Ephys ``run_proc_batch``. The listed preprocessing
   steps are executed in order. Common steps include Maxwell/tSSS for
   Elekta/MEGIN data, band-pass filtering, notch filtering, and resampling.
   Resampling is the current configurable downsampling mechanism.

3. ``detect_Artifacts`` calls ``meg_detect_artifacts.py``. It detects bad
   channels and bad time spans using the configured PyPREP, PSD, OSL, and MNE
   methods. It writes ``*_bad_channels.txt`` and ``*_bad_segments.txt`` and can
   generate waveform images for manual review.

4. ``run_ICA`` loads the preprocessed raw file plus the artifact sidecars. Bad
   channels are excluded from picks, and bad annotations are ignored during ICA
   fitting through ``reject_by_annotation=True``.

5. ``run_IC_label`` labels artifact-related ICA components using the configured
   ECG, EOG, MNE-ICLabel, and rule-based settings.

6. ``apply_ICA`` loads the marked components, applies the ICA solution, and
   saves ``*_clean_raw.fif``. The cleaned continuous file keeps the bad-channel
   and bad-segment metadata.

Interactive Edits and Resume
----------------------------

Some sidecar files can be edited after a Nextflow run through the interactive
reports. MEGPrep includes content hashes of those files in the relevant
Nextflow task inputs so ``-resume`` can invalidate only the affected downstream
tasks:

* Editing ``artifact_report/*/*_bad_channels.txt`` or
  ``artifact_report/*/*_bad_segments.txt`` invalidates ICA fitting and later
  steps for that recording.
* Editing ``ica_report/*/marked_components.txt`` invalidates ICA application
  and later steps for that recording.
* Editing ``trans/*/coreg-trans.fif`` invalidates forward modelling and source
  reconstruction for that recording.

Bad Segments: Marking vs Exclusion
----------------------------------

Artifact detection marks bad segments as MNE annotations. This does not cut
samples out of the continuous raw file. Downstream steps decide whether the
annotations should exclude data:

* ICA fitting ignores annotated spans when estimating ICA components.
* ICA application writes a cleaned raw file with annotations attached.
* Epoching drops epochs overlapping annotations only when
  ``epoch_config.epochs.reject_by_annotation`` is true.
* Additional epoch rejection can come from ``epoch_config.epochs.reject`` or
  optional ``autoreject``.

Resting-State and Task-Based Epochs
-----------------------------------

Epoching is optional and happens after the continuous core. ``epoch_config``
selects how epochs are built:

* ``task_type: resting`` creates fixed-length events with
  ``resting.fixed_length_duration``.
* ``task_type: task`` with ``event_source: find_events`` uses MNE
  ``find_events`` and the ``find_events`` config block.
* ``task_type: task`` with ``event_source: event_file`` reads BIDS
  ``*_events.tsv`` files and applies the ``event_file`` filters or label-to-id
  mappings.
* ``exclude_event_id`` can be set to one id or a list of ids to remove those
  events before epoching. With ``epochs.event_id: null``, MEGPrep keeps all
  remaining event ids.

The resulting epoch FIF file and rejection log are written under
``preprocessed/epochs/<recording>/``.

Covariance and Empty-Room Style Records
---------------------------------------

Covariance is computed only in the full MEG stage. Two modes are available:

* ``covar_type = "epochs"`` estimates noise covariance from baseline epochs
  created from each cleaned experimental recording.
* ``covar_type = "raw"`` estimates noise covariance from a continuous raw
  recording selected by ``raw_covariance_task_id``.

For raw covariance, MEGPrep pairs experimental recordings with a noise or
baseline recording by replacing the BIDS ``task-...`` part of the filename with
``task-${params.raw_covariance_task_id}``. This is the current mechanism for
empty-room or empty-room-like recordings. For example, if
``raw_covariance_task_id = "emptyroom"``, an experimental file with
``task-aef`` is paired with a file whose matching name contains
``task-emptyroom`` when that file exists.

Coregistration, Forward Model, and Source Reconstruction
--------------------------------------------------------

``coregistration`` or ``coregistrations`` aligns MEG sensor space to the
subject anatomy. The process uses fiducial fitting, ICP, and a fine-tuned ICP
stage controlled by ``core_config``. It writes ``coreg-trans.fif``,
coregistration figures, and distance summaries.

``forward_solution`` builds the forward model using the epoch file, transform,
FreeSurfer subject directory, and ``fwd_config``.

``source_imaging`` consumes either epochs or raw data according to ``src_type``.
It loads the forward model and noise covariance and then applies the configured
source methods in ``src_config``.

Static HTML Report
------------------

At the end of each selected MEG milestone, ``generate_static_html_report`` scans
the existing outputs and writes a portable report under
``params.output_dir/static_html_report``. The report includes a workflow
manifest, a config snapshot when available, subject pages, dataset summaries,
and evidence files. See :doc:`../tutorial/reports` and
:doc:`../reference/qc_metrics` for details.

Primary Outputs by Step
-----------------------

.. list-table::
   :header-rows: 1
   :widths: 24 32 44

   * - Step
     - Output location
     - Main outputs
   * - Continuous preprocessing
     - ``preprocessed/<recording>/``
     - ``*_preproc-raw.fif``
   * - Artifact detection
     - ``preprocessed/artifact_report/<recording>/``
     - Bad-channel text file, bad-segment annotations, review images.
   * - ICA
     - ``preprocessed/ica_report/<recording>/``
     - ICA FIF, source FIF, marked components, ECG/EOG scores, plots.
   * - ICA-clean raw
     - ``preprocessed/<recording>/``
     - ``*_clean_raw.fif``
   * - Epochs
     - ``preprocessed/epochs/<recording>/``
     - ``*-epo.fif``, rejection log, sensor/PSD/topomap figures.
   * - Covariance
     - ``preprocessed/covariance/<recording>/``
     - ``bl-cov.fif``, covariance and spectra figures.
   * - Coregistration
     - ``preprocessed/trans/<recording>/``
     - ``coreg-trans.fif``, distance CSV, alignment figures.
   * - Forward model
     - ``preprocessed/forward_solution/<recording>/``
     - Forward solution FIF and head-model figures.
   * - Source reconstruction
     - ``preprocessed/source_recon/<recording>/``
     - Source estimate files and visualization figures.
   * - Static report
     - ``static_html_report/``
     - Dataset dashboard, subject pages, JSON/CSV summaries.
