Outputs
========

MEGFlow writes Nextflow execution files under ``params.megflow.output_dir`` and
processing derivatives under the dataset ``preproc_dir``. By default:

.. code-block:: text

   preproc_dir = <dataset_output_dir>/preprocessed

Top-Level Output Layout
-----------------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Path
     - Description
   * - ``<output_dir>/work/``
     - Nextflow work directory.
   * - ``<output_dir>/report.html``
     - Nextflow execution report when run through the Docker entrypoint.
   * - ``<output_dir>/timeline.html``
     - Nextflow timeline when run through the Docker entrypoint.
   * - ``<output_dir>/trace.txt``
     - Nextflow process trace. The static report uses it to populate per-subject
       ``Task Details`` when available.
   * - ``<output_dir>/nextflow.config``
     - Effective config copied from the Docker run config.
   * - ``<output_dir>/static_html_report/``
     - Portable MEGFlow QC report. Depending on ``static_task_log_mode``, this
       may include packaged Nextflow ``.command*`` log excerpts.
   * - ``<output_dir>/preprocessed/``
     - MEGFlow processing derivatives.

Corpus Output Layout
--------------------

With Docker ``--corpus`` or a source config that sets ``corpus_root``, every
dataset receives an isolated output tree. Dataset names are sanitized for use as
directory names, while the corpus report retains the configured display name.

.. code-block:: text

   <output_dir>/
   |-- datasets/
   |   |-- <dataset_a>/
   |   |   |-- preprocessed/
   |   |   `-- static_html_report/
   |   `-- <dataset_b>/
   |       |-- preprocessed/
   |       `-- static_html_report/
   |-- corpus_static_html_report/
   |-- corpus_report.html
   |-- corpus_timeline.html
   |-- corpus_trace.txt
   `-- nextflow.config

``corpus_static_html_report/index.html`` is the cross-dataset entry point. It
links the dataset reports and provides sortable recording and dataset summaries
for comparison, outlier discovery, and prioritizing manual review. The
``corpus_report.html``, ``corpus_timeline.html``, and ``corpus_trace.txt`` files
describe Nextflow execution rather than signal quality.

Preprocessed Directory
----------------------

.. list-table::
   :header-rows: 1
   :widths: 32 68

   * - Path
     - Contents
   * - ``preprocessed/<recording>/``
     - Continuous preprocessed raw files, ICA-clean raw files, and selected QA
       plots.
   * - ``preprocessed/artifact_report/<recording>/``
     - Bad-channel files, detector provenance, bad-segment annotation files,
       DeepReject provenance when enabled, a recording-wide mask heatmap, and
       optional detailed artifact review images.
   * - ``preprocessed/ica_report/<recording>/``
     - ICA model, component labels, ECG/EOG score files, component figures, and
       overlay/PSD plots.
   * - ``preprocessed/epochs/<recording>/``
     - Epoch FIF files, rejection logs, and epoch-level figures.
   * - ``preprocessed/covariance/<recording>/``
     - Noise covariance FIF file and covariance visualization figures.
   * - ``preprocessed/trans/<recording>/``
     - MEG-MRI transform, coregistration distance CSV, and staged
       coregistration figures.
   * - ``preprocessed/forward_solution/<recording>/``
     - Forward model outputs and head model figures.
   * - ``preprocessed/source_recon/<recording>/``
     - Source reconstruction outputs and visualization figures.
   * - ``preprocessed/logs/``
     - Nextflow log, MEGFlow run manifest, and config snapshots when available.
   * - ``preprocessed/deepprep/``
     - DeepPrep outputs when ``anatomy.method = "deepprep"`` and
       anatomy processing is enabled.

Important Sidecar Files
-----------------------

.. list-table::
   :header-rows: 1
   :widths: 36 64

   * - File pattern
     - Meaning
   * - ``*_preproc-raw.fif``
     - Continuous output from OSL preprocessing.
   * - ``*_bad_channels.txt``
     - One bad channel name per line.
   * - ``*_bad_channels_description.json``
     - Per-channel detector provenance showing which enabled method marked each
       final bad channel.
   * - ``*_bad_segments.txt``
     - MNE annotation file containing bad time spans.
   * - ``deepreject_summary.json``
     - DeepReject input preprocessing, folds, thresholds, channel probabilities,
       bad-channel decisions, bad intervals, and runtime settings. It is written
       only when the DeepReject branch runs successfully.
   * - ``check_imgs/artifact_mask_heatmap.jpg``
     - Whole-recording channel-by-time mask overview. This compact image is
       generated even when ``artifact_images_enabled`` is false.
   * - ``*_ica.fif``
     - Fitted ICA model.
   * - ``marked_components.txt``
     - ICA component indices selected for exclusion.
   * - ``ecg_eog_scores.json``
     - ECG/EOG candidate indices and scores when produced by ICA labeling.
   * - ``*_clean_raw.fif``
     - Continuous raw file after ICA application.
   * - ``*-epo.fif``
     - Epoch output.
   * - ``*_reject_epoch_log.txt``
     - Rejected epoch indices and estimated remaining epoch count.
   * - ``bl-cov.fif``
     - Noise covariance estimate.
   * - ``dists.csv``
     - Coregistration distance summary in mm.
   * - ``coreg-trans.fif``
     - MEG-MRI transform used by forward modeling.
   * - ``megflow_run_manifest.json``
     - Pipeline mode, selected stages, path snapshot, and runtime metadata.

The exact set of outputs depends on the effective ``steps`` value in
``params.megflow``. For example,
``meg_artifacts`` does not produce ICA, epoch, covariance, forward, or source
outputs, while ``report`` only rebuilds the static report from existing files.

Artifact Image Policy
---------------------

``artifacts.artifact_images_enabled`` controls detailed waveform and detector
review figures; it does not disable the compact artifact-mask heatmap. The
heatmap gives reports a consistent recording-wide summary without incurring the
cost of all detailed figures. ``artifact_image_n_jobs`` controls parallel image
generation only and does not change artifact decisions.

Bad-segment sidecars contain annotations, not shortened data. Samples remain in
the continuous FIF. ICA fitting and epoch construction exclude annotated spans
according to their own ``reject_by_annotation`` behavior. See
:ref:`bad-segment-marking` for the exact distinction between marking and later
exclusion.
