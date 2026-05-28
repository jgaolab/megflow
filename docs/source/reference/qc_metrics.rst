Quality Control Metrics
=======================

MEGPrep writes quality control sidecars during processing and packages them
into a portable static HTML report. The current report uses measured values and
static thresholds. It does not yet provide calibrated normative quality scores.

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
   * - ``static_html_report/data/megprep_run_manifest.json``
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
