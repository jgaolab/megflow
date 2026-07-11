Quality Control Metrics
=======================

MEGFlow writes quality-control sidecars during processing and packages them
into a portable static HTML report. The report combines measured artifact,
ICA, epoch, and coregistration values with NormMEG-QC outputs when
``megqc.enabled = true``. NormMEG-QC converts minimally preprocessed MEG
recordings into an interpretable Normative MEG Data Quality (NMDQ) score.

The configuration block is still named ``megqc`` for compatibility with
existing ``nextflow.config`` files. In user-facing reports and documentation,
the framework is referred to as **NormMEG-QC** and the final 0-100 score is the
**NMDQ score**.

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

NormMEG-QC and the NMDQ Score
-----------------------------

When ``megqc.enabled = true``, MEGFlow scores each imported MEG recording
before the main preprocessing chain. The output is saved under
``preprocessed/quality_control/<recording>/`` and copied into the static
report. The NMDQ score assumes the bundled reference-aligned NormMEG-QC
preprocessing, including the fixed 1-100 Hz band-pass filter. Changing that
band-pass changes the metric distribution and makes the score less comparable
to the normative reference.

.. list-table::
   :header-rows: 1
   :widths: 28 32 40

   * - Output
     - Source file
     - Interpretation
   * - NMDQ score
     - ``*.summary.json``
     - Overall 0-100 score. Higher is better.
   * - Processing gate status
     - ``passed_processing_threshold`` in ``*.summary.json``
     - ``true`` when the score is at least ``megqc.min_score``. Recordings
       below this threshold are skipped for downstream MEG processing.
   * - Metric family scores
     - ``family_scores`` in ``*.summary.json``
     - Domain-level summaries, such as temporal, spectral, statistical, or
       fractal score families.
   * - Component scores
     - ``*.component_scores.csv``
     - Per-metric raw value, reference quantiles, direction of improvement, and
       component score.
   * - Family-score figure
     - ``*.normative_quality_score.png``
     - Fixed 0-100 figure showing each metric-family score and the overall
       NMDQ score. Exact values remain available in the family-score table.

Use these two thresholds for different purposes:

.. list-table::
   :header-rows: 1
   :widths: 26 32 42

   * - Parameter
     - Pipeline effect
     - Report effect
   * - ``megqc.min_score``
     - Blocks downstream MEG processing below this score.
     - The subject page reports that later processing was skipped by the
       quality gate.
   * - ``megqc.alarm_score``
     - Does not block processing.
     - Flags recordings below this score in the subject report and dataset
       dashboard.

For example, setting ``megqc.min_score`` to ``70.0`` only allows recordings
with scores of 70 or higher to continue into artifact detection, ICA, epochs,
covariance, coregistration, forward modeling, and source reconstruction. Setting
``megqc.min_score`` to ``0.0`` keeps all successfully scored recordings. If
scoring fails while NormMEG-QC is enabled, the recording does not pass the
score gate.

The dataset dashboard includes an interactive quality-score filter. It can show
recordings at or above a temporary cutoff, below a temporary cutoff, or with
missing scores without rerunning the pipeline.

NormMEG-QC Metric Families
--------------------------

The bundled NormMEG-QC scoring profile groups low-level channel-type metrics
into eight metric families, scores each family against the selected normative
reference, and averages available family scores into the final ``score_0_100``.
The default score scale is 0-100 and higher is better.

Metrics are computed separately for available magnetometer and gradiometer
channels. For one channel type, let :math:`X_{i,t}` be the reference-aligned
continuous signal for channel :math:`i` at sample :math:`t`, after the fixed
NormMEG-QC preprocessing. The default policy keeps channels marked in
``raw.info['bads']`` and keeps ``BAD`` annotated spans during scoring so the
recording is compared with the same assumptions used by the reference cohort.

.. list-table::
   :header-rows: 1
   :widths: 16 26 32 26

   * - Domain
     - Quality metric
     - Mathematical definition
     - What it captures
   * - Temporal
     - Max absolute difference, absolute Q95
     - For each channel, :math:`d_i = \max_t |X_{i,t+1} - X_{i,t}|`.
       The component value is :math:`Q_{0.95}(|d_i|)` across channels.
     - Extreme sample-to-sample jumps, spikes, and high-frequency transients.
   * - Temporal
     - Max absolute difference, Q75
     - Uses the same :math:`d_i` and reports :math:`Q_{0.75}(d_i)` across
       channels.
     - Upper-quartile transient instability with less emphasis on the most
       extreme channels.
   * - Temporal
     - Max absolute difference, IQR
     - Uses the same :math:`d_i` and reports
       :math:`Q_{0.75}(d_i) - Q_{0.25}(d_i)` across channels.
     - Spread of fast sample-to-sample instability across channels.
   * - Temporal
     - Max absolute difference, mean
     - Uses the same :math:`d_i` and reports :math:`\mathrm{mean}(d_i)` across
       channels.
     - Overall temporal roughness across the channel group.
   * - Spectral
     - Spectral amplitude skewness
     - For each channel, compute the amplitude spectrum from the first half of
       :math:`|\mathrm{FFT}(X_i / n)|` with the DC component set to zero, then
       compute :math:`E[(A-\mu)^3] / \sigma^3`. The component value is the
       channel mean.
     - Spectral asymmetry; high values suggest that a few frequencies dominate
       the spectrum.
   * - Spectral
     - Spectral amplitude kurtosis
     - Uses the same amplitude spectrum :math:`A` and computes
       :math:`E[(A-\mu)^4] / \sigma^4`; the component value is the channel
       mean.
     - Spectral peakiness, including narrow-band interference and anomalous
       frequency components.
   * - Statistical
     - Peak-to-peak amplitude, absolute Q95
     - For each channel, :math:`p_i = \max_t X_{i,t} - \min_t X_{i,t}`. The
       component value is :math:`Q_{0.95}(|p_i|)` across channels.
     - Large oscillations, drift, saturating channels, or abnormal amplitude
       ranges.
   * - Fractal
     - DFA exponent
     - Detrended Fluctuation Analysis is computed per channel. By default,
       MEGFlow averages per-channel DFA values within fixed-length segments and
       then averages the segment values.
     - Long-range correlation and non-stationary temporal structure.

For the current bundled profile, all eight families use ``lower_is_better``:
unusually large values often indicate noise, transient artifacts, abnormal
dynamic range, or spectral peaks. The ``direction`` column in
``*.component_scores.csv`` should still be used as the source of truth because
future NormMEG-QC profiles may mix ``lower_is_better``, ``higher_is_better``,
and ``near q50 is better`` metrics.

NMDQ Component Score Columns
----------------------------

``*.component_scores.csv`` contains one row per scored metric component. Metrics
are often duplicated by channel type, for example ``mag`` and ``grad`` rows for
the same family when both are available.

Each raw metric value is compared with the selected reference interval. For the
default ``lower_is_better`` direction, the component score is:

.. math::

   1 - \mathrm{clip}\left(\frac{x - q_{0.05}}{q_{0.95} - q_{0.05}}, 0, 1\right)

where :math:`x` is the recording metric value and :math:`q_{0.05}` and
:math:`q_{0.95}` are the reference 5th and 95th percentiles. Family scores are
the average of available magnetometer and gradiometer component scores for that
family. The NMDQ score is the mean of available family scores multiplied by
100.

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Column
     - Meaning
   * - ``domain``
     - Broad metric domain such as Temporal, Statistical, Spectral, or Fractal.
   * - ``family``
     - Metric family name. Family-level scores shown in the static report are
       averages of valid component scores in the same family.
   * - ``family_display_label``
     - Human-readable quality-metric name used in the score figure and family
       score table.
   * - ``component_type``
     - Channel-type component contributing to the family score, normally
       ``MAG`` or ``GRAD``.
   * - ``metric``
     - Exact metric component name, usually including channel type such as
       ``mag`` or ``grad``.
   * - ``raw_value``
     - Metric value measured from the current recording after the fixed
       NormMEG-QC reference preprocessing.
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

Static Report QC Alerts
-----------------------

The static report classifies each subject as ``PASS``, ``WARN``, or ``FAIL``
using simple QC alert rules:

.. list-table::
   :header-rows: 1
   :widths: 30 24 46

   * - QC alert
     - Default threshold
     - Severity and meaning
   * - Bad-channel count above threshold
     - ``bad_channel_threshold = 30``
     - Warning. Review sensor quality and detector settings.
   * - Bad-segment count above threshold
     - ``bad_segment_threshold = 50``
     - Warning. Review raw trace plots and bad-segment annotations.
   * - NMDQ score below warning threshold
     - ``megqc.alarm_score`` in the config; reported internally as
       ``megqc_alarm_score``
     - Warning. The recording has a low NMDQ score but may still have been
       processed if it is above ``megqc.min_score``.
   * - Quality gate skipped downstream processing
     - ``megqc.min_score``
     - Danger. The score was below the required processing minimum, so
       downstream MEG steps were not run for that recording.
   * - Missing expected ICA outputs
     - Stage dependent
     - Warning when the selected ``steps`` mode should have produced ICA files.
   * - No ECG-related ICA components detected
     - ``alert_missing_ecg_components = true``
     - Optional warning. Set the report option to ``false`` when the recording
       is not expected to contain a detectable ECG component.
   * - No EOG-related ICA components detected
     - ``alert_missing_eog_components = true``
     - Optional warning. Set the report option to ``false`` when the recording
       is not expected to contain a detectable EOG component.
   * - Missing expected coregistration outputs
     - Stage dependent
     - Warning when the selected ``steps`` mode should have produced
       coregistration files.
   * - Mean coregistration distance above threshold
     - ``coreg_mean_threshold = 5.0`` mm
     - Danger. Usually requires reviewing fiducials, head-shape points, or MRI
       subject matching.
   * - Maximum coregistration distance above threshold
     - ``coreg_max_threshold = 10.0`` mm
     - Danger. Often indicates outlier head-shape points or poor alignment.
   * - Epoch rejection rate above threshold
     - ``epoch_reject_rate_threshold = 0.30``
     - Warning. Check event definitions, reject thresholds, and bad annotations.

``FAIL`` is assigned when a subject has at least one danger alarm or three or
more alarms. ``WARN`` is assigned when there is at least one warning alarm.
``PASS`` means no alarms under the current static thresholds.

These two ICA presence checks affect only static-report QC alerts. They do not
disable ICA fitting, component classification, component removal, or ICA
results in the report. Configure them under ``report``:

.. code-block:: groovy

   report: [
     alert_missing_ecg_components: false,
     alert_missing_eog_components: false
   ]

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
     - NMDQ score summary with ``score_0_100``, selected reference
       device/category/scope, family scores, preprocessing metadata, and
       quality-gate status.
   * - ``static_html_report/files/<recording>/quality_score/*.component_scores.csv``
     - Per-component NormMEG-QC metric table with raw values, reference
       quantiles, direction, component scores, status, and interpretation.
   * - ``static_html_report/files/<recording>/quality_score/*.normative_quality_score.png``
     - Family-score and overall-score figure used by the subject page.
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
