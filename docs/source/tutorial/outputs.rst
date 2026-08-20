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
   * - ``<output_dir>/static_html_report/nextflow/report.html``
     - Nextflow execution report for a single-dataset run.
   * - ``<output_dir>/static_html_report/nextflow/timeline.html``
     - Nextflow timeline for a single-dataset run.
   * - ``<output_dir>/static_html_report/nextflow/trace.txt``
     - Nextflow process trace. The static report uses it to populate per-subject
       ``Task Details`` when available.
   * - ``<output_dir>/static_html_report/nextflow/nextflow.log``
     - Nextflow driver log when the launcher supplies the documented ``-log`` path.
   * - ``<output_dir>/nextflow.config``
     - Runtime config copied by the distributed Docker entrypoint. Source
       launches do not create this file automatically.
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
   |   |   `-- static_html_report/       # MEG/report stages
   |   `-- <dataset_b>/
   |       |-- preprocessed/
   |       `-- static_html_report/       # MEG/report stages
   |-- corpus_static_html_report/
   |   |-- index.html
   |   |-- assets/
   |   |-- data/
   |   |   |-- corpus_summary.json
   |   |   `-- datasets.csv
   |   |-- datasets/                     # bundled portable dataset reports
   |   `-- nextflow/
   |       |-- nextflow.log
   |       |-- report.html
   |       |-- timeline.html
   |       `-- trace.txt
   `-- nextflow.config

``corpus_static_html_report/index.html`` is the cross-dataset entry point. It
links the dataset reports and provides sortable recording and dataset summaries
for comparison, outlier discovery, and prioritizing manual review. The files
under ``corpus_static_html_report/nextflow/`` describe the complete
Nextflow invocation rather than one dataset. They are stored once and linked
from the corpus report instead of being copied into every dataset report.
An anatomy-only dataset has derivatives and reconstructed anatomy but no
dataset-level static MEG report unless a later MEG or ``report`` stage creates
one.

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
   * - ``preprocessed/quality_control/<recording>/``
     - NormMEG-QC summary JSON, component-score CSV, and NMDQ score figure when
       ``megqc.enabled`` is true.
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
     - ``bl-cov.fif`` and diagnostics; conditional ``lcmv-data-cov.fif`` and
       diagnostics when LCMV is selected; and the always-present
       ``resolved-rank.json`` source contract.
   * - ``preprocessed/trans/<recording>/``
     - MEG-MRI transform, coregistration distance CSV, and staged
       coregistration figures.
   * - ``preprocessed/forward_solution/<recording>/``
     - Forward model outputs and head model figures.
   * - ``preprocessed/source_recon/<recording>/``
     - Source reconstruction outputs and visualization figures.
   * - ``preprocessed/logs/``
     - ``megflow_run_manifest.json``. Nextflow logs and execution reports live
       under the report package's ``nextflow/`` directory; the Docker runtime
       config is copied to ``<output_dir>/nextflow.config``.
   * - ``preprocessed/deepprep/``
     - DeepPrep outputs when ``anatomy.method = "deepprep"`` and
       anatomy processing is enabled.
   * - ``preprocessed/pseudomri/<subject>/``
     - Generated pseudo T1 input when ``anatomy.method = "pseudomri"``.

FreeSurfer-format anatomy is written to the configured ``fs_subjects_dir``.
In a corpus run without an explicit override this is normally under
``<output_dir>/smri/<dataset_name>/``; it is not a recording derivative.

Important Sidecar Files
-----------------------

.. list-table::
   :header-rows: 1
   :widths: 36 64

   * - File pattern
     - Meaning
   * - ``*_preproc-raw.fif``
     - Continuous output from OSL preprocessing.
   * - ``*.summary.json``
     - NormMEG-QC NMDQ score, score metadata, family scores, and processing-gate
       status.
   * - ``*.component_scores.csv``
     - NormMEG-QC component values and reference-calibrated subscores.
   * - ``*.normative_quality_score.png``
     - NMDQ score and metric-family score figure.
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
     - Final ICA component indices selected for exclusion. In automatic mode
       this is the union of enabled ECG, EOG, and outlier categories; a
       preserved manual review may replace that automatic union.
   * - ``ecg_eog_scores.json``
     - Enabled-category ``ecg_indices``, ``eog_indices``, and
       ``outlier_indices``, the resolved ``category_switches``, and method
       provenance. Its
       ``marked_components.auto_indices`` records the automatic category union,
       while ``written_indices`` exactly matches ``marked_components.txt``.
   * - ``*_clean_raw.fif``
     - Continuous raw file after ICA application.
   * - ``*-epo.fif``
     - Epoch output.
   * - ``*_reject_epoch_log.txt``
     - Rejected epoch indices and estimated remaining epoch count.
   * - ``bl-cov.fif``
     - Noise covariance estimate.
   * - ``lcmv-data-cov.fif``
     - LCMV data covariance from the exact source Raw/Epochs. This file is not
       generated for minimum-norm-only runs.
   * - ``resolved-rank.json``
     - Resolved target-rank dictionary, ordered common-channel list, and source
       input mode shared by covariance and source reconstruction.
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
generation only and does not change artifact decisions. Its automatic value,
and any explicit upper bound, cannot exceed the ``detect_artifacts`` CPU
allocation.

Bad-segment sidecars contain annotations, not shortened data. Samples remain in
the continuous FIF. The normal ICA path carries them into the cleaned raw; the
``meg_epochs,skip_ica`` path loads the bad-channel and bad-segment sidecars into
the preprocessed raw immediately before epoching. ICA fitting and epoch
construction exclude annotated spans according to their own
``reject_by_annotation`` behavior. See :ref:`bad-segment-marking` for the exact
distinction between marking and later exclusion.
