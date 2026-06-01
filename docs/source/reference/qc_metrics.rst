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

MEGQC Metric Families
---------------------

The default MEGQC model is ``lowcost_quota_T4_S2_Stat1_Fr1``. It groups
low-level channel-type metrics into metric families, scores each family against
the selected Normative Reference, and averages available family scores into the
final ``score_0_100``. The default score scale is 0-100 and higher is better.

.. list-table::
   :header-rows: 1
   :widths: 18 32 50

   * - Domain
     - Metric family
     - What it captures
   * - Temporal
     - ``tsfel.max_abs_diff.abs_q95``
     - High quantile of maximum absolute adjacent-sample change across
       channels. Sensitive to spikes, jumps, and high-frequency transients.
   * - Temporal
     - ``tsfel.max_abs_diff.q75``
     - Upper-quartile adjacent-sample change. Captures sustained transient
       instability with less emphasis on the most extreme samples.
   * - Temporal
     - ``tsfel.max_abs_diff.iqr``
     - Interquartile spread of adjacent-sample changes. Captures variability of
       fast sample-to-sample changes.
   * - Temporal
     - ``tsfel.max_abs_diff.mean``
     - Mean adjacent-sample change. Captures overall temporal roughness.
   * - Spectral
     - ``freq_domain.skewness_amplitude``
     - Skewness of the spectral amplitude distribution. High values can indicate
       dominance by a few frequencies or artifact peaks.
   * - Spectral
     - ``freq_domain.kurtosis_amplitude``
     - Kurtosis of the spectral amplitude distribution. Sensitive to narrow-band
       interference and anomalous spectral peaks.
   * - Statistic
     - ``tsfel.ptp_amp.abs_q95``
     - High quantile of peak-to-peak amplitude. Captures large oscillations,
       drift, or abnormal channel amplitude ranges.
   * - Fractal
     - ``fractal_domain.DFA``
     - Detrended Fluctuation Analysis. Captures long-range correlation and
       non-stationary structure.

Most default families use ``lower_is_better`` because unusually large values
often indicate noise, transient artifacts, abnormal dynamic range, or spectral
peaks. The ``direction`` column in ``*.component_scores.csv`` should be used as
the source of truth for each metric because future models may mix
``lower_is_better``, ``higher_is_better``, and ``near q50 is better`` metrics.

MEGQC Component Score Columns
-----------------------------

``*.component_scores.csv`` contains one row per scored metric component. Metrics
are often duplicated by channel type, for example ``mag`` and ``grad`` rows for
the same family when both are available.

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Column
     - Meaning
   * - ``domain``
     - Broad metric domain such as Temporal, Spectral, Statistic, or Fractal.
   * - ``family``
     - Metric family name. Family-level scores shown in the static report are
       averages of valid component scores in the same family.
   * - ``metric``
     - Exact metric component name, usually including channel type such as
       ``mag`` or ``grad``.
   * - ``raw_value``
     - Metric value measured from the current recording after the fixed MEGQC
       reference preprocessing.
   * - ``mode`` / ``direction``
     - How to interpret the raw metric. ``lower_is_better`` rewards lower
       values, ``higher_is_better`` rewards higher values, and ``near q50 is
       better`` rewards values close to the reference median.
   * - ``q05``, ``q50``, ``q95``
     - Normative Reference 5th percentile, median, and 95th percentile used for
       the selected reference pool.
   * - ``reference_position_q05_0_q95_1``
     - Position of the recording relative to the reference interval. ``0`` is
       q05, ``0.5`` is q50, and ``1`` is q95. Values below 0 or above 1 are
       outside the typical reference band.
   * - ``component_score_0_1``
     - Per-metric score on a 0-1 scale. Higher is better. The static report
       displays this as 0-100.
   * - ``status``
     - ``within_q05_q95``, ``below_q05``, ``above_q95``, ``missing``, or
       ``no_reference``.
   * - ``reference_scope_used``
     - Actual reference scope selected after fallback, such as
       ``device_category``, ``category``, or ``global``.
   * - ``reference_device`` / ``reference_category``
     - Device family and recording category used to look up reference
       quantiles.
   * - ``interpretation``
     - Human-readable description of what the family tends to reflect.

The reference-position figure uses the same component rows. The green band is
the typical reference interval from q05 to q95. For the default
``lower_is_better`` families, values above q95 are usually worse; values below
q05 may be better or unusually low depending on the metric. Always combine the
``status``, ``direction``, component score, and interpretation columns when
reviewing a suspicious recording.

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
   * - ``static_html_report/files/<recording>/quality_score/*.summary.json``
     - Normative Reference QC summary with ``score_0_100``, selected reference
       device/category/scope, family scores, preprocessing metadata, and quality
       gate status.
   * - ``static_html_report/files/<recording>/quality_score/*.component_scores.csv``
     - Per-component MEGQC metric table with raw values, reference quantiles,
       direction, component scores, status, and interpretation.
   * - ``static_html_report/files/<recording>/quality_score/*.reference_position.png``
     - Reference-relative plot used by the subject page when available.
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
