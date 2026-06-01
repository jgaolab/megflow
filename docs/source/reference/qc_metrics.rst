Quality Control Metrics
=======================

MEGFlow writes quality control sidecars during processing and packages them
into a portable static HTML report. The report combines measured artifact,
ICA, epoch, and coregistration values with Normative Reference MEG QC scores
when ``megqc_enabled = true``.

Subject-Level Metrics
---------------------

.. list-table::
   :header-rows: 1
   :widths: 24 30 46

   * - Metric
     - Source
     - Interpretation
   * - Sampling rate
     - Preprocessed raw file metadata
     - Confirms that filtering and resampling produced the expected output
       sampling frequency.
   * - Channel count
     - Preprocessed raw file metadata
     - Used to contextualize bad-channel counts and ratios.
   * - Recording duration
     - Preprocessed raw file metadata
     - Used to calculate bad-segment duration ratio.
   * - Bad channel count
     - ``artifact_report/<recording>/*_bad_channels.txt``
     - Number of channels marked bad by the configured bad-channel detectors.
   * - Bad channel ratio
     - Bad channel count divided by total channel count
     - Helps compare systems or recordings with different channel counts.
   * - Bad segment count
     - ``artifact_report/<recording>/*_bad_segments.txt``
     - Number of MNE annotations created by bad-segment detectors.
   * - Bad segment duration
     - Sum of annotation durations
     - Total time marked as bad in the continuous recording.
   * - Bad segment ratio
     - Bad duration divided by raw recording duration
     - Fraction of continuous time marked as bad.
   * - ICA marked components
     - ``ica_report/<recording>/marked_components.txt``
     - Components selected for exclusion before ICA is applied.
   * - ECG and EOG candidates
     - ``ica_report/<recording>/ecg_eog_scores.json``
     - Candidate artifact components detected by ECG/EOG scoring.
   * - ICA component review views
     - ``ica_report/<recording>/ica_results/*.png``
     - Topographic and time-series evidence for component review. If
       ``ica_compute_explained_variance`` is enabled, topography filenames and
       report captions include EVAR values; otherwise EVAR is omitted.
   * - Coregistration mean, max, and min distance
     - ``trans/<recording>/dists.csv``
     - Distances in mm between fitted head-shape points and the head surface.
       High mean or max distances indicate poor MEG-MRI alignment.
   * - Epoch rejection rate
     - ``epochs/<recording>/*_reject_epoch_log.txt``
     - Rejected epochs divided by estimated total epochs. Rejections can come
       from bad annotations, MNE reject thresholds, or optional autoreject.
   * - Step completion
     - Presence of expected output files
     - Shows whether artifact, ICA, coregistration, head model, epochs,
       covariance, and source outputs exist for each recording.

Normative Reference QC Score
----------------------------

When ``megqc_enabled = true``, MEGFlow scores each imported MEG recording before
main preprocessing. The output is saved under
``preprocessed/quality_control/<recording>/`` and copied into the static report.
The score assumes the bundled reference-aligned MEGQC preprocessing, including
the fixed 1-100 Hz band-pass filter. Changing that band-pass changes the metric
distribution and makes the score less comparable to the Normative Reference.

.. list-table::
   :header-rows: 1
   :widths: 28 32 40

   * - Output
     - Source file
     - Interpretation
   * - Quality score
     - ``*.summary.json``
     - Overall 0-100 score. Higher is better.
   * - Processing gate status
     - ``passed_processing_threshold`` in ``*.summary.json``
     - ``true`` when the score is at least ``megqc_min_score``. Recordings
       below this threshold are skipped for downstream MEG processing.
   * - Metric family scores
     - ``family_scores`` in ``*.summary.json``
     - Domain-level summaries, such as temporal, spectral, statistical, or
       fractal score families.
   * - Component scores
     - ``*.component_scores.csv``
     - Per-metric raw value, reference quantiles, direction of improvement, and
       component score.
   * - Reference-relative metric positions
     - ``*.reference_position.png``
     - Figure showing where the recording sits relative to the normative
       reference for each contributing metric.

Use these two thresholds for different purposes:

.. list-table::
   :header-rows: 1
   :widths: 26 32 42

   * - Parameter
     - Pipeline effect
     - Report effect
   * - ``megqc_min_score``
     - Blocks downstream MEG processing below this score.
     - The subject page reports that later processing was skipped by the
       quality gate.
   * - ``megqc_alarm_score``
     - Does not block processing.
     - Flags recordings below this score in the subject report and dataset
       dashboard.

For example, setting ``megqc_min_score`` to ``70.0`` only allows recordings
with scores of 70 or higher to continue into artifact detection, ICA, epochs,
covariance, coregistration, forward modeling, and source reconstruction. Setting
``megqc_min_score`` to ``0.0`` keeps all successfully scored recordings. If
scoring fails while MEGQC is enabled, the recording does not pass the score
gate.

The dataset dashboard includes an interactive Quality Score filter. It can show
recordings at or above a temporary cutoff, below a temporary cutoff, or with
missing scores without rerunning the pipeline.

Static Report Alarms
--------------------

The static report classifies each subject as ``PASS``, ``WARN``, or ``FAIL``
using simple alarm rules:

.. list-table::
   :header-rows: 1
   :widths: 30 24 46

   * - Alarm
     - Default threshold
     - Severity and meaning
   * - Bad channels above threshold
     - ``bad_channel_threshold = 30``
     - Warning. Review sensor quality and detector settings.
   * - Bad segments above threshold
     - ``bad_segment_threshold = 50``
     - Warning. Review raw trace plots and bad-segment annotations.
   * - Quality score below warning threshold
     - ``megqc_alarm_score = 70.0`` in Docker configs, configurable
     - Warning. The recording has a low Normative Reference score but may still
       have been processed if it is above ``megqc_min_score``.
   * - Quality gate skipped downstream processing
     - ``megqc_min_score``
     - Danger. The score was below the required processing minimum, so
       downstream MEG steps were not run for that recording.
   * - Missing expected ICA outputs
     - Stage dependent
     - Warning when the selected ``steps`` mode should have produced ICA files.
   * - Missing expected coregistration outputs
     - Stage dependent
     - Warning when the selected ``steps`` mode should have produced
       coregistration files.
   * - Mean coregistration distance above threshold
     - ``coreg_mean_threshold = 5.0`` mm
     - Danger. Usually requires reviewing fiducials, head-shape points, or MRI
       subject matching.
   * - Max coregistration distance above threshold
     - ``coreg_max_threshold = 10.0`` mm
     - Danger. Often indicates outlier head-shape points or poor alignment.
   * - Epoch rejection rate above threshold
     - ``epoch_reject_rate_threshold = 0.30``
     - Warning. Check event definitions, reject thresholds, and bad annotations.

``FAIL`` is assigned when a subject has at least one danger alarm or three or
more alarms. ``WARN`` is assigned when there is at least one warning alarm.
``PASS`` means no alarms under the current static thresholds.

Dataset-Level Outputs
---------------------

The static report writes a dataset dashboard and machine-readable summaries:

.. list-table::
   :header-rows: 1
   :widths: 32 68

   * - File
     - Contents
   * - ``static_html_report/index.html``
     - Dataset-level dashboard with subject table, workflow diagram, aggregate
       metrics, alarms, and links to subject pages.
   * - ``static_html_report/subjects/<recording>.html``
     - Per-recording report with artifacts, ICA, coregistration, epochs,
       covariance, head model, source figures, task trace details, and
       packaged sidecars.
   * - ``static_html_report/files/<recording>/artifacts/artifact_mask_heatmap.png``
     - Artifact mask heatmap showing bad-channel rows and bad-segment time
       spans when artifact image generation is enabled.
   * - ``static_html_report/alarms.html``
     - Searchable list of report alarms.
   * - ``static_html_report/data/dataset_summary.json``
     - Dataset-level metrics, thresholds, workflow metadata, and subject
       summaries.
   * - ``static_html_report/data/subjects.csv``
     - Spreadsheet-friendly subject table.
   * - ``static_html_report/data/subjects/<recording>.json``
     - Full subject summary used to render the subject page.
   * - ``static_html_report/data/nextflow.config.txt``
     - Snapshot of the effective Nextflow config when available.
   * - ``static_html_report/data/megflow_run_manifest.json``
     - Workflow mode and run metadata used to render the report workflow
       diagram.
   * - ``static_html_report/files/<recording>/errors/*.txt``
     - Failed or ignored task ``.command.err``, ``.command.log``, and
       ``.command.out`` excerpts when trace/work-dir logs can be matched.
   * - ``static_html_report/files/<recording>/tasks/*.txt``
     - Optional successful-task ``.command.log`` excerpts when
       ``static_task_log_mode`` is set to ``all-command-log``.

Practical Review Guidance
-------------------------

Start with ``index.html`` and sort the subject table by alarms, bad channels,
bad segments, coregistration distance, or epoch rejection rate. Open subject
pages for high-alarm or high-outlier recordings. For artifact-heavy recordings,
inspect the waveform images and the bad-segment table before changing detector
thresholds. For source reconstruction failures or high coregistration alarms,
inspect the final ICP figures and verify that the MEG recording was matched to
the correct FreeSurfer subject.
