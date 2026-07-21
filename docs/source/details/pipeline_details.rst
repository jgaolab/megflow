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
       from the OSL preprocessed raw files instead of ICA-clean raw files. The
       detected bad-channel and bad-segment sidecars are loaded before epochs
       are constructed.
   * - ``meg_all``
     - Full MEG workflow using an existing ``fs_subjects_dir``.
   * - ``all``
     - Structural MRI workflow plus full MEG workflow.
   * - ``report``
     - Static HTML report only, using existing outputs.

Aliases ``meg``, ``artifacts``, ``ica``, and ``epochs`` map to ``meg_all``,
``meg_artifacts``, ``meg_ica``, and ``meg_epochs``. The optional
``with_anatomy`` modifier can accompany ``meg_artifacts``, ``meg_ica``, or
``meg_epochs``; ``skip_ica`` is valid with ``meg_epochs``. A recording-level
stage may reduce an enabled dataset MEG path but cannot add anatomy or exceed
the dataset stage.

High-Level Flow
---------------

The complete ``meg_all`` or ``all`` dependency graph is:

.. code-block:: text

   MEG import
     -> NormMEG-QC scoring (when enabled)
     -> NMDQ min_score gate
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

When ``megqc.enabled`` is false, imported recordings bypass both the scoring
process and its gate. When enabled, an unscored recording or one below
``megqc.min_score`` does not enter continuous preprocessing.

Covariance and coregistration may execute concurrently after their own inputs
are ready. Forward modeling waits for both the recording's epoch file and its
coregistration transform. Source reconstruction is a strict keyed join of that
recording's exact forward file, noise covariance, and conditional LCMV data
covariance. The covariance branch also carries the hash of the exact source
Raw/Epochs used to compute it; an unmatched, duplicate, or inconsistent key is
an error rather than a silently skipped source result.

With ``covariance.type = "raw"``, the recording selected by
``raw_covariance_task_id`` follows the same continuous preprocessing and ICA
path, then feeds the experimental recording's noise-covariance branch. It does
not create its own epochs, forward model, or source estimate.

When anatomy is enabled, its branch can run concurrently with MEG
preprocessing. The branches join only when coregistration, forward modeling, or
source reconstruction requires anatomy:

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
and task-based recordings. NormMEG-QC, when enabled, is a preflight gate before
this core rather than one of its signal-processing operations.

1. ``import_meg_dataset`` discovers input recordings.
   BIDS input is filtered by ``meg_import`` entities. Raw input is
   selected by ``file_suffix`` and optional ``raw_include_keywords`` /
   ``raw_exclude_keywords``. Raw discovery matches both files and directories,
   so CTF ``.ds`` folders are supported.

2. ``score_meg_quality`` runs NormMEG-QC when enabled, writes the NMDQ score
   sidecars, and applies ``megqc.min_score`` before downstream processing.

3. ``meg_basic_preproc`` calls ``meg_preproc_osl.py``, which passes the
   effective ``preproc`` block to OSL-Ephys ``run_proc_batch``. The listed
   preprocessing steps are executed in order. Common steps include Maxwell/tSSS for
   Elekta/MEGIN data, band-pass filtering, notch filtering, and resampling.
   Resampling is the current configurable downsampling mechanism.

4. ``detect_artifacts`` calls ``meg_detect_artifacts.py``. It detects bad
   channels and bad time spans using the configured PyPREP, PSD, OSL, MNE, and
   optional DeepReject methods. Within DeepReject, BadChnNet runs first; its bad
   channels are masked before BadSegNet predicts bad time windows. Results from
   all enabled detectors are merged into ``*_bad_channels.txt`` and
   ``*_bad_segments.txt``. The process also writes detector provenance and a
   recording-wide artifact-mask heatmap. Detailed waveform images are optional.

5. ``run_ica`` loads the preprocessed raw file plus the artifact sidecars. Bad
   channels are excluded from picks, and bad annotations are ignored during ICA
   fitting through ``reject_by_annotation=True``.

6. ``run_ic_label`` labels artifact-related ICA components using configured MNE
   ECG/EOG detection, the original MNE-ICALabel MEGNet model, the independently
   optional retrained MEGNet model, and rule-based settings. Method switches
   determine which detectors may run; ``ic_ecg``, ``ic_eog``, and
   ``ic_outlier`` are category master switches applied to every method. The
   automatic union therefore contains only detections whose method and category
   are both enabled. A failure isolated to the optional retrained model is
   recorded without blocking the other methods. Category results and
   automatic/manual component provenance are stored in
   ``ecg_eog_scores.json``.

7. ``apply_ica`` loads the marked components, applies the ICA solution, and
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
Each required external result has a task-local symbolic-link cache guard that
Nextflow records as a ``path`` output. This includes both
``marked_components.txt`` and ``ecg_eog_scores.json`` for ICA labeling. An
unchanged target keeps the owner task cacheable. If the published target is
deleted, the guard becomes dangling and ``-resume`` reruns the owner task; any
consumer whose effective input fingerprint changes then reruns as well. Other
recordings remain cacheable.

Editable bad-channel, bad-segment, and marked-component sidecars use both
mechanisms deliberately. Deleting one reruns its owner so the required file is
restored. Editing its content leaves the owner cached, preserves the manual
edit, and invalidates only the downstream consumers listed above. Static report
processes use ``cache false`` and therefore regenerate on every completed or
lenient run.

If configuration, labeling code, or the retrained model changes, Nextflow
safely refreshes the labeling task. A ``marked_components.txt`` file that still
matches the previous automatic result is replaced by the new automatic union.
If its content differs, MEGFlow treats it as a manual edit and leaves it
unchanged while refreshing detector details in ``ecg_eog_scores.json``. The
JSON ``marked_components.mode`` field records ``auto`` or
``preserved_manual``. Its ``auto_indices`` field records the newly detected
category union, while ``written_indices`` always matches the exact contents of
``marked_components.txt`` consumed by ``apply_ica``. Direct script users can
request an unconditional reset with ``run_ica_label.py --overwrite-existing``.

.. _bad-segment-marking:

Bad Segments: Marking vs Exclusion
----------------------------------

Artifact detection marks bad segments as MNE annotations. This does not cut
samples out of the continuous raw file. Downstream steps decide whether the
annotations should exclude data:

* ICA fitting ignores annotated spans when estimating ICA components.
* ICA application writes a cleaned raw file with annotations attached.
* With ``skip_ica``, epoching loads the detected bad-channel and bad-segment
  sidecars directly into the preprocessed raw before constructing epochs.
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
example is documented in :ref:`example-source-multi-dataset`.

Primary Outputs by Step
-----------------------

.. list-table::
   :header-rows: 1
   :widths: 24 32 44

   * - Step
     - Output location
     - Main outputs
   * - NormMEG-QC
     - ``preprocessed/quality_control/<recording>/``
     - ``*.summary.json``, ``*.component_scores.csv``, and
       ``*.normative_quality_score.png`` when enabled.
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
       ``lcmv-data-cov.fif`` and diagnostics when LCMV is requested; and
       ``resolved-rank.json`` for every full source branch.
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
