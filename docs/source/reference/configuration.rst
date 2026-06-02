Configuration Reference
=======================

MEGFlow is configured through a Nextflow configuration file, usually
``nextflow.config``. The top-level ``params`` block controls input discovery,
pipeline stage selection, output locations, and the YAML snippets passed to
the Python processing scripts.

Many nested YAML fields are passed directly to MNE-Python, MNE-BIDS, OSL-Ephys,
PyPREP, or FreeSurfer/DeepPrep functions. When a field is a direct pass-through,
MEGFlow preserves the name and meaning used by the upstream API. Useful
upstream references include the MNE-Python documentation for
`Raw objects <https://mne.tools/stable/generated/mne.io.Raw.html>`_,
`Epochs <https://mne.tools/stable/generated/mne.Epochs.html>`_,
`ICA <https://mne.tools/stable/generated/mne.preprocessing.ICA.html>`_,
`compute_raw_covariance <https://mne.tools/stable/generated/mne.compute_raw_covariance.html>`_,
`compute_covariance <https://mne.tools/stable/generated/mne.compute_covariance.html>`_,
and
`find_bad_channels_lof <https://mne.tools/stable/generated/mne.preprocessing.find_bad_channels_lof.html>`_.

Command Line Mapping
--------------------

The Docker entrypoint copies the mounted config to
``/program/nextflow/run_nextflow.config`` and then applies selected command-line
overrides before launching Nextflow.

.. list-table::
   :header-rows: 1
   :widths: 20 28 52

   * - Docker option
     - Config or Nextflow target
     - Notes
   * - ``-c``, ``--config``
     - Input config file
     - Mounted project config. The effective copy is saved to
       ``<output_dir>/nextflow.config`` after the run.
   * - ``-i``, ``--input``
     - ``params.dataset_dir``
     - Root directory used by MEG and MRI import steps.
   * - ``-o``, ``--output``
     - ``params.output_dir``
     - Output root. ``params.preproc_dir`` defaults to
       ``${params.output_dir}/preprocessed``.
   * - ``-s``, ``--steps``
     - Nextflow ``--steps`` / ``params.steps``
     - Overrides the value in the config for this run.
   * - ``--fs_subjects_dir``
     - ``params.fs_subjects_dir``
     - FreeSurfer ``SUBJECTS_DIR`` used for coregistration, BEM, forward model,
       and source reconstruction.
   * - ``--fs_license_file``
     - ``params.fs_license``
     - Used by DeepPrep/FreeSurfer-related execution in the container.
   * - ``--t1_dir``
     - ``params.t1_dir``
     - T1 input root when structural processing is enabled.
   * - ``--t1_input_type``
     - ``params.t1_input_type``
     - ``nifti`` or ``dicom`` for non-BIDS anatomy input.
   * - ``--t1_dicom_series_glob``
     - ``params.t1_dicom_series_glob``
     - Optional relative glob for selecting DICOM series directories under each
       T1 DICOM root, for example ``*T1*`` or ``*mprage*``.
   * - ``--resume``
     - Nextflow ``-resume``
     - Reuses completed Nextflow work directory tasks where possible.
   * - ``--static_task_log_mode``
     - ``params.static_task_log_mode``
     - Controls how much Nextflow ``.command*`` log content is copied into the
       static HTML report. Values are ``failed``, ``all-command-log``, and
       ``none``.

Docker Output Ownership
-----------------------

The Docker image is designed to be run without Docker's ``--user`` flag. The
entrypoint starts as ``root`` only long enough to prepare mounted output
permissions. It then drops privileges with ``gosu`` and runs Nextflow as the
host UID/GID inferred from the mounted ``/input`` directory. Report-only runs
that only mount ``/output`` infer ownership from ``/output`` instead.

This means users do not need to pre-create the host output directory. If Docker
creates the bind-mounted output path as ``root:root`` before the container
starts, MEGFlow changes ownership to the inferred host user before launching the
pipeline.

If neither ``/input`` nor ``/output`` is owned by the user who should own the
outputs, pass the desired IDs explicitly:

.. code-block:: bash

   docker run --rm -it \
     -e LOCAL_UID="$(id -u)" -e LOCAL_GID="$(id -g)" \
     -v /data/bids:/input \
     -v /data/out:/output \
     cmrlab/megflow:<version> \
     -i /input -o /output

Pipeline Stage Selection
------------------------

``params.steps`` is the primary switch for choosing how much of the workflow to
run. It can be set in the config or overridden with ``--steps``.

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Value
     - Behavior
   * - ``meg_all``
     - Default full MEG workflow using an existing ``fs_subjects_dir``:
       MEG import, continuous preprocessing, artifact detection, ICA, epochs,
       covariance, coregistration, forward solution, source reconstruction, and
       static report.
   * - ``all``
     - Structural MRI workflow plus full MEG workflow in one run.
   * - ``anatomy``
     - Structural MRI workflow only.
   * - ``meg_artifacts``
     - MEG import, continuous preprocessing, artifact detection, then static
       report.
   * - ``meg_ica``
     - Through ICA fitting, labeling, ICA application, then static report.
   * - ``meg_epochs``
     - Through epoch generation, then static report.
   * - ``report``
     - Rebuild the static HTML report from existing outputs only.

Aliases are supported: ``meg`` maps to ``meg_all``, ``artifacts`` maps to
``meg_artifacts``, ``ica`` maps to ``meg_ica``, and ``epochs`` maps to
``meg_epochs``.

Optional modifiers are comma-separated. ``skip_ica`` is valid only with
``meg_epochs`` and builds epochs from the OSL preprocessed raw files. It is not
valid for ``meg_all`` or ``all`` because the downstream source reconstruction
path expects ICA-clean raw data. ``with_anatomy`` is valid with
``meg_artifacts``, ``meg_ica``, or ``meg_epochs`` and runs structural MRI
processing before the selected MEG milestone.

Global Paths and Execution Settings
-----------------------------------

.. list-table::
   :header-rows: 1
   :widths: 22 18 22 38

   * - Field
     - Type
     - Default behavior
     - Meaning
   * - ``dataset_dir``
     - path
     - Required
     - Input dataset root for MEG import and, when configured, BIDS anatomy
       import.
   * - ``output_dir``
     - path
     - Required
     - Output root for Nextflow reports, timeline, trace, static HTML report,
       and ``preprocessed`` outputs.
   * - ``preproc_dir``
     - path
     - ``${params.output_dir}/preprocessed``
     - Main MEGFlow derivative directory.
   * - ``code_dir``
     - path
     - Container path ``/program/megflow``
     - Directory containing MEGFlow Python scripts.
   * - ``cohort``
     - boolean
     - ``false``
     - Treat ``dataset_dir`` as a collection root and let Nextflow expand each
       immediate child directory into an independent dataset run.
   * - ``cohort_t1_root``
     - path
     - unset
     - Optional structural MRI collection root for cohort mode. If it contains
       a child directory matching a dataset name, that directory is used as the
       dataset T1 input; otherwise the value is reused for all datasets. When
       unset, each MEG dataset directory is used as its own T1 root.
   * - ``workDir``
     - path
     - ``${params.output_dir}/work``
     - Nextflow work directory.
   * - ``osl_random_seed``
     - integer
     - ``2025``
     - Random seed passed to OSL preprocessing.
   * - ``ICA_random_seed``
     - integer
     - ``2025``
     - Random seed passed to MNE ICA.
   * - ``ica_compute_explained_variance``
     - boolean
     - ``false``
     - Computes per-component ICA explained variance and writes
       ``ica_explained_var.jl``. Disabled by default because this calculation
       is slow and not always useful; when disabled, ICA review figures and
       reports still work but EVAR labels are omitted.
   * - ``meg_visualize``
     - boolean
     - ``true``
     - Enables visualization outputs in coregistration and source
       reconstruction.

Data Import
-----------

MEG input discovery is performed by ``meg_import_dataset.py``. BIDS datasets
are discovered through MNE-BIDS entities. Raw datasets are discovered by
walking the input directory and selecting files by suffix.

.. list-table::
   :header-rows: 1
   :widths: 22 18 22 38

   * - Field
     - Type
     - Allowed values
     - Meaning
   * - ``dataset_format``
     - string
     - ``auto``, ``bids``, ``raw``
     - ``auto`` treats a directory containing ``dataset_description.json`` as
       BIDS; otherwise it uses raw-file discovery.
   * - ``file_suffix``
     - string
     - Any basename ending, usually ``.fif``, ``.ds``, or ``c,rfDC``
     - Used only for raw dataset discovery. Matches files and directories, so
       CTF ``.ds`` folders can be imported. Split FIF continuation files such
       as ``-1.fif`` are excluded.
   * - ``meg_import_config.subject_id``
     - null, string, or list
     - BIDS subject labels without ``sub-``
     - Optional subject filter for BIDS MEG input.
   * - ``meg_import_config.session_id``
     - null, string, or list
     - BIDS session labels
     - Optional session filter.
   * - ``meg_import_config.task``
     - null, string, or list
     - BIDS task labels
     - Optional task filter.
   * - ``meg_import_config.run_id``
     - null, string, or list
     - BIDS run labels
     - Optional run filter.
   * - ``meg_import_config.raw_exclude_keywords``
     - null, string, or list
     - Case-insensitive substrings
     - Raw dataset only. Excludes files or directories whose basename contains
       any listed keyword, for example ``phantom`` or ``emptyroom``.
   * - ``meg_import_config.raw_include_keywords``
     - null, string, or list
     - Case-insensitive substrings
     - Raw dataset only. When set, only files or directories whose basename
       contains at least one listed keyword are imported.

Anatomy Input and Reconstruction
--------------------------------

Structural processing is used by ``steps=anatomy``, ``steps=all``, or selected
MEG milestones with ``with_anatomy``. If structural processing is not selected,
MEGFlow assumes ``fs_subjects_dir`` already contains subject reconstructions.

.. list-table::
   :header-rows: 1
   :widths: 24 18 22 36

   * - Field
     - Type
     - Allowed values
     - Meaning
   * - ``is_bids``
     - boolean
     - ``true`` or ``false``
     - Selects BIDS anatomy import or non-BIDS T1 handling.
   * - ``anatomy_preprocess_method``
     - string
     - ``freesurfer`` or ``deepprep``
     - Backend for anatomical reconstruction when anatomy is run.
   * - ``anatomy_select_tag``
     - string
     - Empty string or suffix such as ``_run-02_T1w``
     - Appended to the MEG-derived subject id when matching anatomy.
   * - ``mri_import_config.*``
     - YAML filters
     - ``subject_id``, ``session_id``, ``task``, ``run_id``
     - BIDS filters used to select T1w images.
   * - ``t1_dir``
     - path
     - Any readable path
     - T1 input root for FreeSurfer and non-BIDS anatomy.
   * - ``t1_input_type``
     - string
     - ``nifti`` or ``dicom``
     - Non-BIDS T1 input format.
   * - ``t1_dicom_series_glob``
     - string
     - unset
     - Optional relative glob for selecting DICOM series directories before
       conversion. When unset, the whole DICOM root is passed to ``dcm2niix``.
   * - ``fs_subjects_dir``
     - path
     - FreeSurfer subjects directory
     - Used for recon outputs, BEM, coregistration, forward model, and source
       reconstruction.
   * - ``deepprep_device``
     - string
     - ``cpu`` or device supported by DeepPrep
     - Device passed to DeepPrep.
   * - ``t1_bids_dir``
     - path
     - BIDS directory
     - T1 BIDS root passed to DeepPrep.
   * - ``fs_license``
     - path
     - FreeSurfer license file
     - Required for FreeSurfer/DeepPrep execution.
   * - ``bem_config.ico``
     - integer
     - MNE ico grade
     - Resolution for BEM surface generation.
   * - ``bem_config.conductivity``
     - list of floats
     - For example ``[0.3]``
     - Conductivity model passed to MNE BEM creation.

Continuous Preprocessing
------------------------

``preproc_config`` is an OSL-Ephys preprocessing chain. Steps are executed in
the order listed. A common chain is Maxwell/tSSS if needed, filtering, line-noise
notch filtering, and resampling.

.. code-block:: yaml

   preproc:
     - maxwell_filter:
         calibration: /path/to/sss_cal.dat
         cross_talk: /path/to/ct_sparse.fif
         st_duration: 10.0
         st_correlation: 0.98
     - filter: {l_freq: 0.5, h_freq: 125, method: iir, iir_params: {order: 5, ftype: butter}}
     - notch_filter: {freqs: 50 100}
     - resample: {sfreq: 250}

The ``filter`` and ``notch_filter`` fields map to MNE raw filtering methods.
``resample`` maps to MNE raw resampling and is the current configurable
downsampling mechanism. Use a target ``sfreq`` that preserves the frequencies
needed for later analyses.

In cohort mode, the same ``preproc_config`` is used as the default for every
dataset. If only line-noise frequency differs across datasets, keep the shared
preprocessing recipe and override only the notch frequencies with
``preproc_notch_freqs_by_dataset``:

.. code-block:: groovy

   preproc_notch_freqs_by_dataset = [
       "US_60Hz_Dataset": "60",
       "US_60Hz_With_Harmonic": "60 120",
       "Dataset_Without_Notch": "none"
   ]

Keys are matched against the dataset directory name and the sanitized cohort
dataset name. A value of ``none``, ``false``, or ``off`` removes the
``notch_filter`` step for that dataset. For rare datasets that need a fully
different preprocessing chain, set ``preproc_config_by_dataset`` to a map whose
values are complete YAML ``preproc`` snippets.

For single-dataset runs, these cohort override maps are optional. You can omit
``preproc_notch_freqs_by_dataset`` and ``preproc_config_by_dataset`` entirely,
or leave them as ``[:]``. The workflow will use ``preproc_config`` directly.

Use the two override levels as follows:

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Parameter
     - Use case
   * - ``preproc_notch_freqs_by_dataset``
     - Per-dataset line-noise differences only. This replaces the
       ``notch_filter`` frequencies while preserving the rest of
       ``preproc_config``.
   * - ``preproc_config_by_dataset``
     - Rare per-dataset preprocessing differences beyond notch frequency, such
       as a different filter range, resampling rate, or Maxwell/tSSS settings.
       Each value must be a complete YAML ``preproc`` block.

Example full override:

.. code-block:: groovy

   preproc_config_by_dataset = [
       "SpecialDataset": """
           preproc:
           - filter: {l_freq: 0.5, h_freq: 100, method: iir, iir_params: {order: 5, ftype: butter}}
           - notch_filter: {freqs: 60 120}
           - resample: {sfreq: 200}
       """
   ]

Normative Reference Quality Scoring
-----------------------------------

Normative Reference MEG QC scoring is enabled with ``megqc_enabled = true``.
When enabled, MEGFlow scores each imported MEG recording before the main
preprocessing chain. The score is on a 0-100 scale where higher is better.

Use ``megqc_min_score`` as a processing gate when low-quality recordings should
not continue into artifact detection, ICA, epochs, source reconstruction, or
other downstream MEG steps:

.. code-block:: groovy

   megqc_enabled = true
   megqc_min_score = 70.0      // skip downstream processing below 70
   megqc_alarm_score = 60.0    // report warning only; does not skip processing

``megqc_min_score = 0.0`` keeps all successfully scored recordings. If scoring
fails or no score is available, the recording does not pass the processing gate
while MEGQC is enabled. Set ``megqc_enabled = false`` to disable both scoring
and this score-based gate.

``megqc_alarm_score`` is only a static-report threshold. Scores below this value
are flagged in the subject report and dataset dashboard, but they still proceed
through the pipeline unless they are also below ``megqc_min_score``.

The dataset-level static report includes the Normative QC score column, warning
counts, and an interactive Quality Score filter so reviewers can temporarily
show recordings above or below a chosen score without regenerating the report.

Key MEGQC parameters:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Parameter
     - Meaning
   * - ``megqc_enabled``
     - Enables Normative Reference scoring before main MEG preprocessing.
   * - ``megqc_min_score``
     - Minimum score required for downstream MEG processing. Use this to block
       low-quality recordings from later analysis.
   * - ``megqc_alarm_score``
     - Static report warning threshold. It highlights low scores but does not
       block processing.
   * - ``megqc_meg_vendor``
     - MEG vendor/reference device family. ``auto`` infers from channel names
       and metadata. Values are case-insensitive; use lowercase in configs for
       consistency. Concrete values include ``all``, ``elekta``, ``neuromag``,
       ``ctf``, ``kit``, ``4d``, ``quanmag``, and ``quspin``.
   * - ``megqc_meg_vendor_by_dataset``
     - Cohort-only override map for datasets whose vendor should be fixed
       explicitly. Single-dataset runs can leave it unset or ``[:]``.
   * - ``megqc_category``
     - Reference category, usually ``auto``, ``rest``, ``task``, or ``ALL``.
   * - ``megqc_reference_scope``
     - Reference pool priority, such as ``device_category``, ``category``, or
       ``global``.
   * - ``megqc_keep_bad_annotations``
     - Keep ``BAD`` annotations during scoring by default to match the bundled
       reference preprocessing.
   * - ``megqc_omit_bad_channels``
     - Keep ``raw.info['bads']`` during scoring by default. Omitting bad
       channels is intended for diagnostics rather than reference-aligned
       scoring.

MEGQC parallelism follows Nextflow process resources. The workflow passes
``task.cpus`` from ``score_MEG_quality`` into the scorer, so there is no separate
``megqc_n_jobs`` parameter. Tune scoring CPU use through the standard process
configuration:

.. code-block:: groovy

   process {
       withName: score_MEG_quality {
           cpus = 4
       }
   }

When ``meg_quality_control.py`` is run outside Nextflow, its standalone
``--n_jobs`` default is ``-1``.

The scoring raw is preprocessed before metrics are computed. This preprocessing
is intentionally visible in Nextflow rather than hidden inside the scorer, but
the 1-100 Hz band-pass filter and filter method are part of the Normative
Reference definition. Do not change ``l_freq``, ``h_freq``, ``method``,
``iir_params.order``, or ``iir_params.ftype`` for routine runs; doing so changes
the score distribution and can seriously reduce QC score accuracy.

.. code-block:: groovy

   megqc_preproc_config = """
       preproc:
       - filter: {l_freq: 1.0, h_freq: 100.0, method: iir, iir_params: {order: 5, ftype: butter}}
       - notch_filter: {freqs: 50}
   """

For single-dataset runs, edit only the ``notch_filter`` frequency in
``megqc_preproc_config`` if the default scoring notch frequency is not
appropriate. Keep the 1-100 Hz band-pass fixed. You do not need to write
``megqc_notch_freqs_by_dataset`` or ``megqc_preproc_config_by_dataset``.

For cohort runs with mixed line-noise frequencies, use
``megqc_notch_freqs_by_dataset`` for the common case:

.. code-block:: groovy

   megqc_notch_freqs_by_dataset = [
       "US_60Hz_Dataset": "60",
       "US_60Hz_With_Harmonic": "60 120",
       "Dataset_Without_Notch": "none"
   ]

For cohort runs with mixed MEG vendors, keep ``megqc_meg_vendor = "auto"`` as
the default and override only datasets that need an explicit reference family.
Vendor values are case-insensitive; examples use lowercase for consistency:

.. code-block:: groovy

   megqc_meg_vendor = "auto"
   megqc_meg_vendor_by_dataset = [
       "SQUID-REST-ClosedEYE": "elekta",
       "CTF_Dataset": "ctf",
       "OPM-Artifacts": "quanmag"
   ]

``megqc_preproc_config_by_dataset`` is reserved for reference maintenance or
controlled method development. Normal runs should leave it as ``[:]``. Use
``megqc_notch_freqs_by_dataset`` when datasets differ only in line-noise
frequency:

.. code-block:: groovy

   megqc_notch_freqs_by_dataset = [
       "US_60Hz_Dataset": "60",
       "US_60Hz_With_Harmonic": "60 120"
   ]

The ``megqc_*_by_dataset`` keys use the same matching rule as main
preprocessing overrides: match either the original child dataset directory name
or the sanitized cohort dataset name. A value of ``none``, ``false``, or
``off`` in ``megqc_notch_freqs_by_dataset`` removes the scoring ``notch_filter``
step for that dataset.

Artifact Detection
------------------

Artifacts are detected after continuous preprocessing and before ICA. The
results are saved as sidecar files under
``preprocessed/artifact_report/<recording>/`` and are also loaded by later ICA
and epoch steps.

.. list-table::
   :header-rows: 1
   :widths: 24 22 54

   * - Config path
     - Method
     - Description
   * - ``find_bad_channels.pyprep.deviation``
     - PyPREP deviation
     - Flags channels whose amplitude distribution deviates from the channel
       population. ``deviation_threshold`` controls sensitivity.
   * - ``find_bad_channels.pyprep.snr``
     - PyPREP SNR
     - Flags low signal-to-noise channels.
   * - ``find_bad_channels.pyprep.nan_flat``
     - PyPREP NaN/flat
     - Flags channels containing NaNs or flat signals.
   * - ``find_bad_channels.pyprep.hfnoise``
     - PyPREP high-frequency noise
     - Flags channels with excessive high-frequency noise.
   * - ``find_bad_channels.pyprep.ransac``
     - PyPREP RANSAC
     - Reconstructs channels from neighboring channels and flags channels with
       poor reconstruction correlation. This can be slow.
   * - ``find_bad_channels.pyprep.correlation``
     - PyPREP correlation
     - Flags channels with low correlation to other channels across windows.
   * - ``find_bad_channels.psd``
     - PSD outlier
     - Computes per-channel mean PSD and flags channels above
       ``mean + std_multiplier * std``.
   * - ``find_bad_channels.osl``
     - OSL ``detect_badchannels``
     - Runs OSL bad-channel detection for magnetometers and, when available,
       gradiometers. Common fields include ``ref_meg`` and
       ``significance_level``.
   * - ``find_bad_channels.mne.find_bad_channels_lof``
     - MNE local outlier factor
     - Passes fields such as ``n_neighbors``, ``picks``, ``metric``, and
       ``threshold`` to MNE's LOF detector.
   * - ``find_bad_segments.osl``
     - OSL ``detect_badsegments``
     - Marks outlier or zero-valued time windows. ``segment_len`` controls the
       detection window length in samples.
   * - ``find_bad_segments.mne.annotate_muscle_zscore``
     - MNE muscle z-score
     - Adds muscle-related annotations using MNE's z-score based detector.
   * - ``find_bad_segments.mne.annotate_amplitude``
     - MNE amplitude annotation
     - Adds annotations for amplitude-based excursions.
   * - ``find_bad_segments.mne.annotate_break``
     - MNE break annotation
     - Marks long breaks between events.

``interpolate_bads`` under ``artifact_config`` controls whether bad channels are
interpolated immediately in the preprocessed raw file. If ``false``, bad
channels are retained in ``raw.info['bads']`` for later exclusion or handling.
``artifact_images_enabled`` controls waveform and overview image generation for
manual review, and ``meg_vendor`` selects vendor-specific plotting assumptions.
Set ``artifact_config.meg_vendor`` to ``auto`` for cohort runs. MEGFlow then
infers the plotting vendor from MEG channel names first and raw metadata second,
using ``elekta``/``neuromag``, ``ctf``, ``kit``, ``4D``/``bti``, and OPM-style
channel naming patterns. If inference fails, artifact detection continues with
generic MNE scaling. A concrete value such as ``elekta``, ``ctf``, ``kit``,
``4D``, or ``opm`` still forces that plotting mode.

``artifact_config.deepreject`` enables optional DeepReject model inference
inside ``meg_detect_artifacts.py``. It is disabled by default because the
runtime needs ONNX Runtime or OpenVINO in addition to the bundled exported
model files. When enabled, DeepReject bad-channel predictions are merged into
``*_bad_channels.txt`` and predicted artifact intervals are added as
``BAD_deepreject`` annotations in ``*_bad_segments.txt``. A
``deepreject_summary.json`` sidecar is also written and bundled into the static
report. The bundled exported model directory and recording category are chosen
automatically, so they do not need user-facing configuration.

.. code-block:: yaml

   deepreject:
     enabled: true
     backend: auto      # auto, onnx, openvino
     device: cpu        # cpu, cuda, gpu
     artifact_prob_threshold: 0.9
     bad_channel_prob_threshold: null
     artifact_merge_gap_sec: 2.0
     artifact_min_duration_sec: 0.5
     on_error: warn     # warn or raise

For ICA rule-based labeling, ``ic_label_config.ICA_classify.meg_vendor`` can be
set to ``auto``. This is the recommended cohort setting because each dataset may
come from a different MEG system. When ``auto`` is used, MEGFlow infers the
template family from the ICA channel names and applies bundled templates only
when they are available. Current ECG/EOG template similarity bundles cover
``elekta``/``neuromag``, ``ctf``, ``4d``/``bti``, and ``kit``. OPM datasets or
unknown channel layouts skip template similarity gracefully and continue with
the other ICA labeling methods.

If the dataset vendor is known, ``meg_vendor_by_dataset`` can override ``auto``
on a per-dataset basis. The key is matched against the ICA file path, so cohort
dataset directory names are usually sufficient:

.. code-block:: yaml

   ICA_classify:
     meg_vendor: auto
     meg_vendor_by_dataset:
       OPM-Artifacts: opm
       Cam-CAN: neuromag
       My-CTF-Dataset: ctf
       default: auto

Dataset-specific mappings take precedence over ``meg_vendor``. If no mapping
matches, MEGFlow falls back to ``meg_vendor``; if that is ``auto``, it uses
channel-name inference. For backward-compatible compact configs,
``ICA_classify.meg_vendor`` may also be a mapping with the same keys, although
``meg_vendor_by_dataset`` is preferred for clarity.

Bad Segment Marking and Exclusion
---------------------------------

MEGFlow separates marking bad time spans from excluding data:

* Artifact detection writes MNE annotations to ``*_bad_segments.txt``. This is
  a marking step.
* ICA fitting loads the annotations and uses ``reject_by_annotation=True`` so
  marked spans are not used for fitting ICA.
* ICA application saves a cleaned continuous raw file with the bad-channel and
  bad-segment metadata attached.
* Epoch exclusion is controlled later by ``epoch_config``. In particular,
  ``epochs.reject_by_annotation`` drops epochs overlapping bad annotations, and
  ``epochs.reject`` applies peak-to-peak rejection thresholds.

Epoching
--------

``epoch_config`` controls optional segmentation after the continuous
preprocessing and ICA stages.

.. list-table::
   :header-rows: 1
   :widths: 24 22 54

   * - Field
     - Allowed values
     - Meaning
   * - ``task_type``
     - ``task`` or ``resting``
     - ``resting`` creates fixed-length events; ``task`` uses event triggers or
       BIDS event files.
   * - ``resting.fixed_length_duration``
     - float seconds
     - Duration used by MNE fixed-length event generation.
   * - ``event_source``
     - ``find_events`` or ``event_file``
     - Selects MNE trigger discovery or BIDS ``events.tsv`` parsing. When
       ``event_file`` is selected but the inferred path is not a ``.tsv`` file,
       non-BIDS raw inputs fall back to ``find_events``.
   * - ``find_events``
     - MNE ``find_events`` kwargs
     - Fields such as ``stim_channel``, ``shortest_event``, and
       ``min_duration``.
   * - ``event_file``
     - YAML mapping
     - Filters and optionally maps BIDS event labels to integer ids.
   * - ``exclude_event_id``
     - integer or list of integers
     - Drops these event ids before epoching. Set ``epochs.event_id: null`` to
       keep all other detected or BIDS events; if ``epochs.event_id`` is also
       set, both the include filter and this exclude filter are applied.
   * - ``epochs``
     - MNE ``Epochs`` kwargs
     - Fields such as ``event_id``, ``tmin``, ``tmax``,
       ``reject_by_annotation``, ``picks``, ``baseline``, ``reject``,
       ``preload``, and ``detrend``.
   * - ``autoreject``
     - boolean
     - If true, MEGFlow estimates global rejection thresholds with
       ``autoreject.get_rejection_threshold`` and calls ``drop_bad``.
   * - ``interpolate_bads``
     - boolean
     - Interpolates bad channels in the epoch object.
   * - ``drop_bad_channels``
     - boolean
     - Drops channels listed in ``epochs.info['bads']``.

Covariance and Empty-Room Style Noise Records
---------------------------------------------

Noise covariance is controlled by ``covar_type`` and ``covar_config``.

``covar_type = "epochs"`` computes covariance from baseline epochs generated
from each cleaned recording. ``covar_config.events`` and
``covar_config.epochs`` define the events and baseline window, and
``covar_config.covariance`` is passed to MNE ``compute_covariance``.

``covar_type = "raw"`` computes covariance from a continuous raw recording with
MNE ``compute_raw_covariance``. The workflow uses ``raw_covariance_task_id`` to
find the paired noise or baseline recording: for each non-noise task file, it
replaces the ``task-...`` entity in the filename with
``task-${params.raw_covariance_task_id}`` and uses that file if it exists. This
is the current mechanism for empty-room or empty-room-like recordings. For
example, set ``raw_covariance_task_id = "emptyroom"`` when the dataset contains
files named with ``task-emptyroom``. These records are not source-localized as
experimental recordings; they are used as covariance input for the paired
experimental recording.

Coregistration, Forward Model, and Source Reconstruction
--------------------------------------------------------

``core_config`` controls automated MEG-MRI coregistration. It contains
pre-cleaning parameters for head-shape points and two ICP stages:
``icp`` and ``finetune_icp``. Weights such as ``nasion_weight``,
``hsp_weight``, and ``hpi_weight`` control how strongly fiducials, head-shape
points, and HPI points influence the fit.

``fwd_config`` controls the forward model. ``surface`` selects the cortical
surface, and ``spacing`` controls source-space spacing such as ``ico4``.

``src_type`` selects whether source reconstruction consumes ``epochs`` or
``raw``. ``src_config.source_methods`` currently supports methods implemented
by ``source_localization.py``, including ``dSPM`` and ``LCMV``. The nested
``dSPM`` and ``LCMV`` blocks are passed to MNE inverse or beamformer functions.

Static Report Thresholds
------------------------

The static report uses simple, configurable thresholds for alarms. These are
not normative or calibrated quality scores.

.. list-table::
   :header-rows: 1
   :widths: 30 18 52

   * - Field
     - Default
     - Meaning
   * - ``bad_channel_threshold``
     - ``30``
     - Warn when detected bad channels exceed this count.
   * - ``bad_segment_threshold``
     - ``50``
     - Warn when detected bad segments exceed this count.
   * - ``coreg_mean_threshold``
     - ``5.0``
     - Danger alarm when mean coregistration distance exceeds this value in mm.
   * - ``coreg_max_threshold``
     - ``10.0``
     - Danger alarm when max coregistration distance exceeds this value in mm.
   * - ``epoch_reject_rate_threshold``
     - ``0.30``
     - Warn when rejected epoch fraction exceeds this value.

Static Report Task Logs
-----------------------

``static_task_log_mode`` controls command-log bundling for the ``Task Details``
and ``Task Failure Details`` sections in the static report.

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Value
     - Meaning
   * - ``all-command-log``
     - Default. Copy ``.command.err``, ``.command.log``, and
       ``.command.out`` excerpts for failed or ignored tasks, and also copy
       ``.command.log`` for successful tasks.
   * - ``failed``
     - Copy command logs only for failed or ignored tasks when a smaller report
       directory is preferred.
   * - ``none``
     - Copy no ``.command*`` logs. Trace-derived task details remain visible.
