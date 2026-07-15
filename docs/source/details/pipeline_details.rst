Pipeline Details
================

MEGFlow is a Nextflow workflow that combines structural MRI processing,
continuous MEG preprocessing, artifact detection, ICA cleaning, optional
epoching, covariance estimation, MEG-MRI coregistration, forward modeling,
source reconstruction, and static quality-control reporting.

The main workflow is implemented in ``nextflow/megflow.nf``.
Configuration is supplied through ``nextflow.config`` and can be overridden by
selected command-line options. See :doc:`../reference/configuration` for the
complete configuration reference.

Execution Modes
---------------

The workflow is controlled by ``params.megflow.defaults.steps`` and optional
dataset- or recording-level ``steps`` overrides:

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

The complete ``meg_all`` or ``all`` dependency graph is:

.. code-block:: text

   MEG import
     -> continuous preprocessing
     -> artifact detection
     -> ICA fit
     -> ICA labeling
     -> ICA application
     -> epoching
          |-> noise covariance -------------------------|
          |-> LCMV data covariance (only for LCMV) -----|-> source reconstruction
          |-> forward solution <- coregistration -------|
     -> static HTML report

Covariance and coregistration may execute concurrently after their own inputs
are ready. Forward modeling waits for both the recording's epoch file and its
coregistration transform. Source reconstruction is a strict keyed join of that
recording's exact forward file, noise covariance, and conditional LCMV data
covariance. The covariance branch also carries the hash of the exact source
Raw/Epochs used to compute it; an unmatched, duplicate, or inconsistent key is
an error rather than a silently skipped source result.

When anatomy is enabled, structural processing runs before the downstream
coregistration and source reconstruction steps:

.. code-block:: text

   MRI import
     -> FreeSurfer or DeepPrep reconstruction
     -> head surface
     -> BEM model
     -> MEG-MRI coregistration dependencies

When ``anatomy.method = "pseudomri"``, MEGFlow first imports MEG
files to access digitization/headshape points, generates a pseudo T1 image, and
then reuses the normal FreeSurfer and BEM stages:

.. code-block:: text

   MEG import
     -> pseudo-MRI generation
     -> FreeSurfer reconstruction
     -> BEM model
     -> MEG-MRI coregistration dependencies

Continuous Core Preprocessing
-----------------------------

The continuous MEG core is task independent and applies to both resting-state
and task-based recordings.

1. ``import_meg_dataset`` discovers input recordings.
   BIDS input is filtered by ``meg_import`` entities. Raw input is
   selected by ``file_suffix`` and optional ``raw_include_keywords`` /
   ``raw_exclude_keywords``. Raw discovery matches both files and directories,
   so CTF ``.ds`` folders are supported.

2. ``meg_basic_preproc`` calls ``meg_preproc_osl.py``, which passes the
   effective ``preproc`` block to OSL-Ephys ``run_proc_batch``. The listed preprocessing
   steps are executed in order. Common steps include Maxwell/tSSS for
   Elekta/MEGIN data, band-pass filtering, notch filtering, and resampling.
   Resampling is the current configurable downsampling mechanism.

3. ``detect_artifacts`` calls ``meg_detect_artifacts.py``. It detects bad
   channels and bad time spans using the configured PyPREP, PSD, OSL, MNE, and
   optional DeepReject methods. Within DeepReject, BadChnNet runs first; its bad
   channels are masked before BadSegNet predicts bad time windows. Results from
   all enabled detectors are merged into ``*_bad_channels.txt`` and
   ``*_bad_segments.txt``. The process also writes detector provenance and a
   recording-wide artifact-mask heatmap. Detailed waveform images are optional.

4. ``run_ica`` loads the preprocessed raw file plus the artifact sidecars. Bad
   channels are excluded from picks, and bad annotations are ignored during ICA
   fitting through ``reject_by_annotation=True``.

5. ``run_ic_label`` labels artifact-related ICA components using the configured
   ECG, EOG, MNE-ICLabel, and rule-based settings.

6. ``apply_ica`` loads the marked components, applies the ICA solution, and
   saves ``*_clean_raw.fif``. The cleaned continuous file keeps the bad-channel
   and bad-segment metadata.

Interactive Edits and Resume
----------------------------

Some sidecar files can be edited after a Nextflow run through the interactive
reports. MEGFlow includes content hashes of those files in the relevant
Nextflow task inputs so ``-resume`` can invalidate only the affected downstream
tasks:

* Adding or removing a raw input invalidates dataset import. Existing unchanged
  recordings remain cacheable, while newly discovered recordings create new
  task branches.
* Changing one raw recording invalidates QC and all processing for that
  recording without invalidating other recordings.
* Changing a BIDS ``events.tsv`` sidecar invalidates epoching, epoch-based
  covariance, forward modeling, and source reconstruction for that recording;
  continuous preprocessing and ICA remain cacheable.
* Editing ``artifact_report/*/*_bad_channels.txt`` or
  ``artifact_report/*/*_bad_segments.txt`` invalidates ICA fitting and later
  steps for that recording.
* Editing ``ica_report/*/marked_components.txt`` invalidates ICA application
  and later steps for that recording.
* Editing ``trans/*/coreg-trans.fif`` invalidates forward modelling and source
  reconstruction for that recording.
* Changing a T1 input or reconstructed anatomy invalidates the relevant
  structural/BEM lineage and downstream coregistration or forward tasks.
* Changing the MEGFlow processing implementation invalidates cached tasks
  through an implementation fingerprint; Python cache files are deliberately
  excluded.

This downstream hash mechanism is separate from published-output deletion.
Normal Nextflow ``-resume`` reuses the work cache for unchanged tasks and
invalidates tasks when their inputs, scripts, or configuration change. Editable
sidecars such as bad-channel lists, bad-segment lists, marked ICA components,
and coregistration transforms are hashed from their published locations, so
manual edits are preserved and invalidate downstream tasks as above. Deleting a
published result should be handled by an explicit pre-resume guard when that
deletion is intended to force the producing step to recompute.

.. _bad-segment-marking:

Bad Segments: Marking vs Exclusion
----------------------------------

Artifact detection marks bad segments as MNE annotations. This does not cut
samples out of the continuous raw file. Downstream steps decide whether the
annotations should exclude data:

* ICA fitting ignores annotated spans when estimating ICA components.
* ICA application writes a cleaned raw file with annotations attached.
* Epoching drops epochs overlapping annotations only when
  ``epochs.epochs.reject_by_annotation`` is true.
* Additional epoch rejection can come from ``epochs.epochs.reject`` or
  optional ``autoreject``.

By default, ``artifacts.find_bad_segments.keep_existing_annotations`` is
``false``. Artifact detection therefore starts from an empty annotation set and
writes only annotations produced during the current run. Set it to ``true``
when existing input annotations are trusted and should be retained alongside
new detector annotations. This setting controls annotation merging, not sample
deletion.

DeepReject intervals use the annotation description ``BAD_deepreject``. See
:doc:`../reference/deepreject` for the BadChnNet and BadSegNet decision rules,
mode thresholds, and provenance output.

Resting-State and Task-Based Epochs
-----------------------------------

Epoching is optional and happens after the continuous core. The effective
``epochs`` block
selects how epochs are built:

* ``task_type: resting`` creates fixed-length events with
  ``resting.fixed_length_duration``.
* ``task_type: task`` with ``event_source: find_events`` uses MNE
  ``find_events`` and the ``find_events`` config block.
* ``task_type: task`` with ``event_source: event_file`` reads BIDS
  ``*_events.tsv`` files and applies the ``event_file`` filters or label-to-id
  mappings. If the inferred event path is not a tabular ``.tsv`` event file
  (for example a non-BIDS raw ``.fif`` input), MEGFlow falls back to
  ``mne.find_events`` so raw datasets are not parsed as text.
* ``exclude_event_id`` can be set to one id or a list of ids to remove those
  events before epoching. With ``epochs.event_id: null``, MEGFlow keeps all
  remaining event ids.
* ``event_time_shift_sec`` can be set in the ``epochs`` block to shift all
  task events before epoching. Positive values move event samples later, for
  example to compensate for a stable auditory or visual stimulus delivery
  delay after the hardware trigger.
* ``epochs.preproc`` can optionally filter, notch-filter, or resample the
  cleaned continuous Raw recording before events are converted into epochs.
  The default is empty and preserves the existing continuous data unchanged.

The resulting epoch FIF file and rejection log are written under
``preprocessed/epochs/<recording>/``. When ``epochs.preproc`` is configured,
the same directory also contains ``*_analysis-raw.fif``; epoch-based covariance
uses this exact analysis-ready continuous recording.

Covariance and Empty-Room Style Records
---------------------------------------

Covariance is computed only in the full MEG stage. Two modes are available:

* ``covariance.type = "epochs"`` estimates noise covariance from baseline epochs
  created from each cleaned experimental recording.
* ``covariance.type = "raw"`` estimates noise covariance from a continuous raw
  recording selected by ``covariance.raw_covariance_task_id``.

Both modes write ``bl-cov.fif``. The same ``compute_covariance`` task writes
``lcmv-data-cov.fif`` only when the effective ``source.source_methods`` contains
LCMV. That matrix is computed from the exact ``*-epo.fif`` when
``source.type = "epochs"`` or the exact analysis-ready Raw when
``source.type = "raw"``. dSPM and other minimum-norm-only runs do not perform
this extra calculation.

When analysis preprocessing is configured for epochs, raw covariance applies
the same operations in memory to the paired baseline recording. Empty
``epochs.preproc`` configurations retain the original covariance behavior.

When covariance is estimated from epochs, ``covariance.event_time_shift_sec``
uses the same sign convention as the epoching stage so baseline epochs remain
aligned with the corrected event timing.

For raw covariance, MEGFlow pairs experimental recordings with a noise or
baseline recording by replacing the BIDS ``task-...`` part of the filename with
``task-${covariance.raw_covariance_task_id}``. This is the current mechanism for
empty-room or empty-room-like recordings. For example, if
``covariance.raw_covariance_task_id = "emptyroom"``, an experimental file with
``task-aef`` is paired with a file whose matching name contains
``task-emptyroom`` while every other filename entity remains unchanged.

The pairing is performed between current-run clean-recording channels. It waits
for the noise branch instead of checking whether a predicted output path happens
to exist, and its clean-file fingerprint participates in the covariance cache
lineage. A single noise recording may feed multiple experimental recordings.
Reference recordings complete continuous preprocessing and ICA, then skip their
own epoch/source branches. If a requested pair is absent, the strict downstream
join fails the run instead of producing an incomplete source set.

Before covariance estimation, target and noise inputs are restricted to common
good channels in target-channel order. ``rank_policy`` is resolved from the
final experimental target and provides the default rank for noise covariance,
LCMV data covariance, and source reconstruction. For raw noise, MEGFlow also
requires its empirical rank to be at least the target rank. This detects an
insufficient empty-room input, but equal ranks do not prove that independently
fitted ICA operators describe the same linear subspace. See
:doc:`../reference/rank_covariance` for configuration precedence and this
compatibility boundary.

The covariance task writes the resolved dictionary and its ordered target
channels to ``resolved-rank.json``. Source reconstruction consumes that file,
verifies the channel order after alignment with covariance and forward inputs,
and passes the stored dictionary to the configured MNE functions. It does not
derive a second default rank.

Coregistration, Forward Model, and Source Reconstruction
--------------------------------------------------------

``coregistration`` or ``coregistrations`` aligns MEG sensor space to the
subject anatomy. The process uses fiducial fitting, ICP, and a fine-tuned ICP
stage controlled by the effective ``coreg`` block. It writes ``coreg-trans.fif``,
coregistration figures, and distance summaries.

``forward_solution`` builds the forward model using the keyed epoch file,
transform, anatomy fingerprint, FreeSurfer subject directory, and the effective
``forward`` block. The emitted tuple carries the exact generated forward FIF
path rather than reconstructing that path later from directory names.

``source_imaging`` consumes either epochs or raw data according to
``source.type``.
It receives and loads the exact forward model, noise covariance, and optional
LCMV data covariance selected by the workflow. It verifies that covariance
channel names and order match the source data and forward model, consumes the
routed default-rank artifact, and then applies the configured source methods.
LCMV never recomputes a covariance inside ``source_localization.py``. Deterministic
rank, routing, channel-contract, or missing-output errors terminate rather than
being retried and ignored as a successful partial run.

Static Processing and QC Report
-------------------------------

At the end of each selected MEG milestone, ``generate_static_html_report`` scans
the existing outputs and writes a portable report under
``<dataset_output_dir>/static_html_report``. The report includes a workflow
manifest, a config snapshot when available, subject pages, dataset summaries,
and evidence files. See :doc:`../tutorial/reports` and
:doc:`../reference/qc_metrics` for details.

Multi-Dataset Profiles
----------------------

``params.megflow.corpus_root`` can point to a directory containing multiple
datasets. ``dataset_include`` and ``dataset_exclude`` select the children to
run. Each dataset can override any default module block under
``params.megflow.datasets``. A dataset can also define ``recordings`` entries
with BIDS-entity ``match`` rules for task- or run-specific settings. This allows
one workflow run to give WAND, SMN4Lang, and MEG-MASC different event
definitions, preprocessing, artifact settings, and source labels. The runnable
example is documented in :doc:`../reference/examples`.

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
     - Bad-channel text and provenance JSON, bad-segment annotations,
       ``deepreject_summary.json`` when enabled, the artifact-mask heatmap, and
       optional detailed review images.
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
     - ``bl-cov.fif`` and its diagnostic figures; conditional
       ``lcmv-data-cov.fif`` and diagnostics when LCMV is requested.
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
