Outputs
========

MEGPrep writes Nextflow execution files under ``output_dir`` and processing
derivatives under ``preproc_dir``. By default:

.. code-block:: text

   preproc_dir = ${params.output_dir}/preprocessed

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
     - Portable MEGPrep QC report. Depending on ``static_task_log_mode``, this
       may include packaged Nextflow ``.command*`` log excerpts.
   * - ``<output_dir>/preprocessed/``
     - MEGPrep processing derivatives.

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
     - Bad-channel files, bad-segment annotation files, and artifact review
       images.
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
     - Nextflow log, MEGPrep run manifest, and config snapshots when available.
   * - ``preprocessed/deepprep/``
     - DeepPrep outputs when ``anatomy_preprocess_method = "deepprep"`` and
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
   * - ``*_bad_segments.txt``
     - MNE annotation file containing bad time spans.
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
   * - ``megprep_run_manifest.json``
     - Pipeline mode, selected stages, path snapshot, and runtime metadata.

The exact set of outputs depends on ``params.steps``. For example,
``meg_artifacts`` does not produce ICA, epoch, covariance, forward, or source
outputs, while ``report`` only rebuilds the static report from existing files.
