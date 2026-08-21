.. _configuration-preprocessing:

Preprocessing Configuration
===========================

This page follows the preprocessing order used by MEGFlow: structural
processing, NormMEG-QC, continuous preprocessing, digitization, artifact
detection, ICA, and optional epoch construction.

Processing Modules
------------------

Each module block is passed to the corresponding MEGFlow script as JSON/YAML.
Fields that match MNE-Python, MNE-BIDS, PyPREP, OSL-Ephys, FreeSurfer, or
DeepPrep are passed through with their upstream meaning.

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Block
     - Used by
   * - ``seeds``
     - Reproducibility seeds for OSL preprocessing and ICA.
   * - ``anatomy`` / ``mri_import``
     - Structural input selection and FreeSurfer, DeepPrep, or pseudo-MRI.
   * - ``megqc``
     - NormMEG-QC scoring, NMDQ score thresholds, and optional processing gate.
   * - ``preproc``
     - OSL continuous preprocessing. Use ``steps`` for the ordered OSL
       operation list.
   * - ``digitization``
     - Optional BIDS sidecar/headshape integration after continuous
       preprocessing.
   * - ``artifacts``
     - DeepReject, PyPREP, PSD, OSL, and MNE bad-channel/bad-segment detection.
   * - ``ica``
     - ICA output directory, component count, and explained-variance option.
   * - ``ic_label``
     - Original MNE-ICALabel MEGNet, optional retrained MEGNet, MNE ECG/EOG,
       rule-based component labeling, and category master switches.
   * - ``epochs``
     - Resting or task epoch generation.
   * - ``bem``
     - BEM surface conductivity and ico grade.
   * - ``covariance``
     - Noise covariance from baseline epochs or paired raw recordings.
   * - ``coreg``
     - Fiducial fitting, ICP, fine-tuned ICP, and coregistration figures.
   * - ``forward``
     - Source space/forward-solution parameters.
   * - ``source``
     - Source reconstruction mode and methods such as ``dSPM`` and ``LCMV``.
   * - ``report``
     - Static HTML report thresholds and task-log packaging.

Direct upstream kwargs retain the MNE-Python meaning. Relevant API references
include `Raw filtering and resampling
<https://mne.tools/stable/generated/mne.io.Raw.html>`_,
`MNE Epochs <https://mne.tools/stable/generated/mne.Epochs.html>`_,
`find_events <https://mne.tools/stable/generated/mne.find_events.html>`_,
`find_bad_channels_lof
<https://mne.tools/stable/generated/mne.preprocessing.find_bad_channels_lof.html>`_,
`compute_raw_covariance
<https://mne.tools/stable/generated/mne.compute_raw_covariance.html>`_, and
`compute_covariance
<https://mne.tools/stable/generated/mne.compute_covariance.html>`_.

Anatomy
-------

Anatomy runs only when the effective dataset ``steps`` enables anatomy. Select
the method with ``anatomy.method``.

.. list-table::
   :header-rows: 1
   :widths: 30 20 18 32

   * - Field
     - Allowed values
     - Docker default
     - Meaning
   * - ``anatomy.method``
     - ``freesurfer``, ``deepprep``, ``pseudomri``
     - ``freesurfer``
     - Structural reconstruction branch.
   * - ``anatomy.is_bids``
     - boolean
     - ``true``
     - Uses BIDS MRI import. DeepPrep currently requires BIDS input.
   * - ``anatomy.select_tag``
     - string
     - empty
     - Suffix used when matching MEG subjects to a selected anatomy subject.
   * - ``anatomy.t1_input_type``
     - ``nifti`` or ``dicom``
     - ``nifti``
     - Non-BIDS FreeSurfer input type.
   * - ``anatomy.t1_dicom_series_glob``
     - relative glob or empty
     - empty
     - Limits DICOM conversion to matching series directories.
   * - ``anatomy.fs_license_file``
     - file path
     - ``/fs_license.txt``
     - FreeSurfer license visible inside the MEGFlow runtime and passed to
       DeepPrep.
   * - ``anatomy.deepprep_device``
     - ``cpu`` or backend-supported device
     - ``cpu``
     - DeepPrep device argument.
   * - ``anatomy.pseudomri_template_dir``
     - directory path
     - ``/program/megflow/tools/pseudomri``
     - Directory containing the pseudo-MRI template assets.
   * - ``anatomy.pseudomri_template_subject``
     - template subject name
     - ``mni_icbm152_nlin_sym_09a``
     - Template used to create a subject-specific pseudo T1.

``pseudomri`` requires usable digitization/headshape points in the imported MEG
recording. ``freesurfer`` supports BIDS T1w input and non-BIDS NIfTI or DICOM
input. ``deepprep`` imports BIDS T1w records and writes reconstructions into the
dataset ``fs_subjects_dir``. DeepPrep is part of the MEGFlow image and its
internal entrypoint is not configurable. Do not put container image, command,
backend, or SIF paths in the anatomy block. Run the outer MEGFlow image, use the
source ``docker`` profile, or compose ``singularity`` with the appropriate
executor. A plain host ``local`` profile cannot run the DeepPrep branch unless
it is already executing inside the MEGFlow image. ``bem.ico`` and
``bem.conductivity`` default to ``4`` and ``[0.3]`` and are passed to MNE BEM
model generation.

**Worked example:** :ref:`example-anatomy-only`.

NormMEG-QC
----------

The ``megqc`` block controls NormMEG-QC and the NMDQ score.

.. list-table::
   :header-rows: 1
   :widths: 31 18 18 33

   * - Field
     - Type / values
     - Docker default
     - Meaning
   * - ``enabled``
     - boolean
     - ``true``
     - Runs NormMEG-QC before continuous preprocessing.
   * - ``min_score``
     - number, 0-100
     - ``0.0``
     - Processing gate. Lower-scoring or unscored recordings do not continue.
   * - ``alarm_score``
     - number, 0-100
     - ``70.0``
     - Report warning threshold; it does not control processing.
   * - ``meg_vendor``
     - ``auto``, ``elekta``, ``ctf``, ``kit``, ``4d``, ``opm``
     - ``auto``
     - Reference device family.
   * - ``category``
     - ``auto``, ``rest``, ``task``, ``ALL``
     - ``auto``
     - Reference recording category.
   * - ``reference_scope``
     - ``device_category``, ``category``, ``global``
     - ``device_category``
     - Reference grouping used for scoring.
   * - ``min_reference_n``
     - positive integer
     - ``20``
     - Minimum reference records required by the selected scope.
   * - ``freq_max_samples``
     - non-negative integer
     - ``0``
     - Optional spectral sample limit; zero uses all available samples.
   * - ``dfa_max_samples``
     - positive integer
     - ``20000``
     - Maximum samples used by DFA computation.
   * - ``dfa_method``
     - ``msqms`` or ``sampled``
     - ``msqms``
     - DFA implementation.
   * - ``skip_dfa``
     - boolean
     - ``false``
     - Skips DFA when true.
   * - ``keep_bad_annotations``
     - boolean
     - ``true``
     - Keeps samples carrying existing bad annotations in the QC policy.
   * - ``omit_bad_channels``
     - boolean
     - ``false``
     - Excludes channels already listed in ``raw.info['bads']`` when true.
   * - ``seg_length``
     - positive number
     - ``100``
     - Segment length used by the configured score components.
   * - ``preproc``
     - ordered operation list
     - 1-100 Hz, 50 Hz notch, then 250 Hz resampling
     - QC-only preprocessing. Preserve the reference-aligned band-pass and
       target sampling rate.

The default reference-aligned operation order is:

.. code-block:: groovy

   params {
     megflow {
       defaults {
         megqc {
           preproc = [
             [filter: [l_freq: 1.0, h_freq: 100.0, method: "iir",
                       iir_params: [order: 5, ftype: "butter"]]],
             [notch_filter: [freqs: 50]],
             [resample: [sfreq: 250]]
           ]
         }
       }
     }
   }

The scorer also carries this sequence as its internal fallback. Omitting
``megqc.preproc`` or setting it to an empty list therefore still applies the
reference-aligned defaults. Set ``megqc.preproc = false`` only for diagnostic
runs that intentionally disable reference preprocessing; resulting scores
are not directly comparable with the bundled normative reference.

See :doc:`qc_metrics` for component definitions, NMDQ score construction,
threshold interpretation, and output files.

**Worked example:** :ref:`example-first-meg-pass`.

Continuous Preprocessing
------------------------

``preproc.steps`` is a convenience spelling for the native OSL-Ephys
``preproc`` operation list. The Docker default is:

.. code-block:: groovy

   params {
     megflow {
       defaults {
         preproc {
           steps = [
             [filter: [l_freq: 1.0, h_freq: 100.0, method: "iir",
                       iir_params: [order: 5, ftype: "butter"]]],
             [notch_filter: [freqs: "50 100"]],
             [resample: [sfreq: 250]]
           ]
         }
       }
     }
   }

Operations run from top to bottom. A dataset- or recording-level
``preproc.steps`` list replaces the inherited list, so repeat every operation
that the override still needs. Nested maps inside the other modules are deep
merged instead. ``filter`` resolves to MNE Raw filtering, ``notch_filter``
resolves through the OSL wrapper to Raw notch filtering, and ``resample``
resolves through the OSL wrapper to Raw resampling. The bundled notch wrapper
accepts an MNE-style numeric list, a scalar, or the historical whitespace-
separated string. OSL-supported operations such as Maxwell/tSSS can be inserted
in the same ordered list when the required calibration and cross-talk inputs
are available.

.. _configuration-osl-passthrough:

OSL-Ephys Recipe Passthrough
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``preproc.steps`` is an OSL batch recipe, not keyword arguments for
``run_proc_batch`` itself. MEGFlow renames ``steps`` to OSL's native
``preproc`` list, adds digitization metadata for its own post-processing, then
removes only that MEGFlow-only key before calling OSL. Each recipe item must be
a map containing exactly one stage name.

This example adds ``bad_segments``, an OSL-native Generalized ESD stage that is
not part of the shipped filter/notch/resample recipe:

.. code-block:: groovy

   params {
     megflow {
       defaults {
         preproc {
           steps = [
             [filter: [
               l_freq: 2.0, h_freq: 40.0, method: "iir",
               iir_params: [order: 3, ftype: "butter"]
             ]],
             [bad_segments: [
               picks: "meg",
               segment_len: 500,
               significance_level: 0.01,
               metric: "kurtosis",
               detect_zeros: false
             ]],
             [resample: [sfreq: 200, npad: "auto", window: "boxcar"]]
           ]
         }
       }
     }
   }

This list replaces the inherited list, so the default notch stage is omitted
intentionally. OSL resolves each stage in this order: an OSL wrapper, an MNE
wrapper, then a method on the selected MNE object. ``bad_segments`` therefore
uses OSL's wrapper, while direct MNE stages retain MNE argument names.

MEGFlow fixes ``run_proc_batch`` execution controls such as ``files``,
``outdir``, ``overwrite``, ``dask_client``, and ``random_seed``. They are not
passthrough config fields. Cross-recording OSL group statistics also belong
outside this per-recording preprocessing process.

**Worked examples:** :ref:`example-first-meg-pass` and
:ref:`example-maxwell-tsss`.

.. _configuration-maxwell-tsss:

Maxwell Filtering and tSSS
~~~~~~~~~~~~~~~~~~~~~~~~~~

MEGIN/Elekta recordings can run MNE Maxwell filtering as an OSL preprocessing
stage named ``maxwell_filter``. OSL resolves that name to its
``run_mne_maxwell_filter`` wrapper and forwards the nested arguments to
``mne.preprocessing.maxwell_filter``. Setting ``st_duration`` to a positive
duration in seconds enables temporal signal-space separation (tSSS); setting it
to ``null`` performs SSS without the temporal extension.

.. code-block:: groovy

   params {
     megflow {
       defaults {
         preproc {
           steps = [
             [maxwell_filter: [
               origin: "auto",
               int_order: 8,
               ext_order: 3,
               calibration: "/data/site-a/calibration/sss_cal.dat",
               cross_talk: "/data/site-a/calibration/ct_sparse.fif",
               st_duration: 10.0,
               st_correlation: 0.98,
               coord_frame: "head",
               destination: null,
               regularize: "in",
               bad_condition: "warning",
               st_fixed: true,
               st_only: false,
               skip_by_annotation: ["edge", "bad_acq_skip"]
             ]],
             [filter: [
               l_freq: 1.0, h_freq: 100.0, method: "iir",
               iir_params: [order: 5, ftype: "butter"]
             ]],
             [notch_filter: [freqs: [50, 100]]],
             [resample: [sfreq: 250]]
           ]
         }
       }
     }
   }

This ordering applies Maxwell/tSSS before temporal filtering, notch filtering,
and resampling. ``calibration`` and ``cross_talk`` are site/system-specific;
their paths must be readable in the source environment or mounted at the same
paths inside the container. ``destination`` and head-position inputs should be
set only when a validated movement-compensation policy is available.

MNE requires bad MEG channels to be marked before Maxwell filtering so that
their artifacts are not spread during reconstruction. The later MEGFlow
``detect_artifacts`` process cannot satisfy that precondition: this stage sees
only bad channels already present in the imported Raw or marked by an earlier,
validated OSL operation.

Use the MNE argument names shown above. Older OSL MaxFilter command-line
names ``tsss``, ``st``, and ``corr`` belong to a different interface and are not
valid arguments for this OSL/MNE stage. MEGFlow 1.0.0 pins MNE 1.8.0, so do not
copy parameters introduced by newer MNE releases without checking the pinned
signature. See the `MNE Maxwell filter API
<https://mne.tools/1.8/generated/mne.preprocessing.maxwell_filter.html>`_ for
the complete supported parameter set.

Maxwell/tSSS is deliberately absent from the shared defaults because it is
device- and site-specific. For corpus processing, place calibration and
cross-talk paths in the dataset profile. If a recording profile changes the
tSSS window or threshold, repeat the complete ordered ``preproc.steps`` list:
lists replace inherited lists rather than merging item by item. The
`three-level Maxwell/tSSS example on GitHub
<https://github.com/jgaolab/megflow/blob/main/nextflow/nextflow_maxwell_tsss_example.config>`__
demonstrates default, dataset, and recording scopes; replace its site paths
before running it elsewhere.

**Worked example:** :ref:`example-maxwell-tsss`.

For task data, MEGFlow finds stimulation-channel events before optional
``epochs.preproc`` resampling and remaps samples through MNE. Nevertheless,
continuous resampling choices should be validated against trigger precision for
the dataset.

Digitization
------------

``digitization`` controls optional sidecar digitization merged after OSL
preprocessing.

.. list-table::
   :header-rows: 1
   :widths: 34 18 18 30

   * - Field
     - Type
     - Default
     - Meaning
   * - ``enabled``
     - boolean
     - ``true``
     - Enables sidecar lookup. Existing embedded digitization is retained when
       no matching files are found.
   * - ``coordsystem_file_pattern``
     - string
     - ``{prefix}_coordsystem.json``
     - BIDS coordinate-system sidecar pattern.
   * - ``hsp_file_pattern``
     - string or null
     - ``{prefix}_headshape.pos``
     - Headshape point pattern.
   * - ``elp_file_pattern``
     - string or null
     - null
     - Optional fiducial/electrode-position pattern.
   * - ``override_embedded``
     - boolean
     - ``false``
     - Replaces valid embedded digitization instead of only filling missing
       information.

``{prefix}`` is resolved from progressively shorter BIDS-like filename
prefixes. Dataset profiles should override these patterns for vendor-specific
sidecar conventions, as demonstrated by the KIT profile in the runnable
multi-dataset example.

Artifact Detection
------------------

``artifacts.find_bad_channels`` enables any combination of the following
methods. Their outputs are de-duplicated and detector provenance is retained.

.. list-table::
   :header-rows: 1
   :widths: 38 25 37

   * - Field
     - Docker default
     - Meaning
   * - ``pyprep.deviation``
     - ``deviation_threshold: 5.0``
     - Robust amplitude-deviation outliers.
   * - ``pyprep.snr``
     - enabled with defaults
     - Low signal-to-noise channels.
   * - ``pyprep.nan_flat``
     - enabled with defaults
     - NaN-containing and flat channels.
   * - ``pyprep.hfnoise``
     - disabled
     - High-frequency-noise detector; provide its PyPREP kwargs to enable it.
   * - ``pyprep.ransac``
     - disabled
     - Reconstruction-correlation detector; computationally expensive.
   * - ``pyprep.correlation``
     - disabled
     - Windowed inter-channel correlation and dropout detector.
   * - ``psd.std_multiplier``
     - ``6``
     - Flags mean channel PSD above the across-channel mean plus this many
       standard deviations.
   * - ``osl``
     - ``ref_meg: auto``, ``significance_level: 0.05``
     - Runs OSL bad-channel detection separately for magnetometers and
       gradiometers when present.
   * - ``mne.find_bad_channels_lof``
     - 20 neighbors, mag picks, Euclidean metric, threshold 1.5
     - MNE local-outlier-factor bad-channel detector.

``artifacts.find_bad_segments`` supports OSL ``detect_badsegments`` and MNE
``annotate_muscle_zscore``, ``annotate_amplitude``, and ``annotate_break``.
The Docker default enables OSL with ``segment_len: 1000`` samples. Set
``keep_existing_annotations: true`` to merge pre-existing input annotations;
the explicit Docker default is ``false``, which clears them before running the
configured bad-segment detectors.

.. list-table::
   :header-rows: 1
   :widths: 35 18 47

   * - Field
     - Default
     - Meaning
   * - ``interpolate_bads``
     - ``false``
     - Interpolates detected channels in the preprocessed raw and resets
       ``raw.info['bads']`` when true.
   * - ``artifact_images_enabled``
     - ``false``
     - Enables detailed waveform and overview image sets. The compact artifact
       mask heatmap is generated regardless of this value.
   * - ``artifact_image_n_jobs``
     - ``auto``
     - Worker limit for detailed image generation. ``auto`` uses the
       ``detect_artifacts`` CPU allocation; explicit values are capped at that
       same process budget.
   * - ``meg_vendor``
     - ``auto``
     - Plotting scale/vendor assumptions. Automatic inference is recommended
       for mixed corpora.
   * - ``deepreject``
     - enabled, ``mode: default``
     - Deep-learning-based BadChnNet and BadSegNet branch. See
       :doc:`deepreject`.

DeepReject
~~~~~~~~~~

DeepReject uses BadChnNet followed by BadSegNet. The ``default``, ``strict``,
and ``lenient`` modes alter BadSegNet interval post-processing, while explicit
low-level values override the selected mode. See :doc:`deepreject` for the
algorithm order, mathematical definitions, all supported fields, exact mode
thresholds, input preprocessing requirements, and outputs.

**Worked examples:** :ref:`example-first-meg-pass` and
:ref:`example-deepreject`.

ICA and Component Labeling
--------------------------

ICA derivatives use the fixed internal ``ica_report`` directory.
``ica.num_components`` defaults to ``0.9999`` and is passed directly as MNE ICA
``n_components``. A float between 0 and 1 selects enough principal components
to exceed that cumulative explained-variance fraction; values closer to 1
usually retain more components. An integer such as ``60`` remains supported
when a fixed component count is required. ``ica.compute_explained_variance``
defaults to false because per-component figure computation is expensive. ICA
uses FastICA, the configured ``seeds.ica``, excludes bad channels, and fits
with ``reject_by_annotation=True``.

The ``ic_label`` block has two control layers. Method switches select which
detectors may run. The ``ic_ecg``, ``ic_eog``, and ``ic_outlier`` category
master switches then decide which detected classes may enter any operational
JSON output, ``marked_components.txt``, or ICA exclusion. A component is
selected only when both its method and its detected category are enabled.

The original and retrained MEGNet classifiers have independent method switches
and may be enabled at the same time:

.. code-block:: groovy

   params {
     megflow {
       defaults {
         ic_label {
           ic_ecg = true
           ic_eog = true
           ic_outlier = false
           mne_icalabel = true
           megnet_retrained = false
           mne_algorithm = true
           rules_algorithm = true
         }
       }
     }
   }

.. list-table::
   :header-rows: 1
   :widths: 30 18 52

   * - Field
     - Default
     - Meaning
   * - ``mne_icalabel``
     - ``true``
     - Enables the original MNE-ICALabel MEGNet classifier.
   * - ``megnet_retrained``
     - ``false``
     - Enables the independently retrained ONNX MEGNet classifier. Its
       artifact components are added to the final union.
   * - ``mne_algorithm``
     - ``true``
     - Enables MNE EOG, ECG, and muscle component detection.
   * - ``rules_algorithm``
     - ``true``
     - Enables the custom rule/template classifier.
   * - ``ic_ecg``
     - ``true``
     - Master switch for cardiac components from every enabled method.
   * - ``ic_eog``
     - ``true``
     - Master switch for eye-blink and eye-movement components from every
       enabled method.
   * - ``ic_outlier``
     - ``false``
     - Master switch for MNE muscle detections and non-ECG/non-EOG rule
       outliers. The MEGNet models do not define an outlier class.
   * - ``find_bads_eog``
     - threshold auto, 1-10 Hz, z-score
     - Passed to MNE ICA EOG detection. ``ch_name`` may be null for automatic
       channel selection.
   * - ``find_bads_ecg``
     - threshold auto, CTPS, 8-16 Hz, z-score
     - Passed to MNE ICA ECG detection.
   * - ``find_bads_muscle``
     - threshold 0.5, 7-45 Hz
     - Passed to MNE ICA muscle detection.
   * - ``ICA_classify.meg_vendor``
     - ``auto``
     - Template/rule vendor family.
   * - ``ICA_classify.explained_var``
     - threshold 0.1, channel type mag
     - Rule threshold used only when explained-variance outputs exist.

MNE-Python calls ``find_bads_ecg``, ``find_bads_eog``, and
``find_bads_muscle`` only for enabled categories. Rule-based results pass
through the same category gates. MEGNet is a multiclass model: it runs once per
enabled model when at least one of ECG or EOG is enabled, but a winning class
that is disabled is ignored rather than reassigned from its second-highest
probability. Both MEGNet models are skipped when ECG and EOG are both disabled.

For example, this configuration keeps the method setting available but
produces no automatic ICA exclusions:

.. code-block:: groovy

   params {
     megflow {
       defaults {
         ic_label {
           ic_ecg = false
           ic_eog = false
           ic_outlier = false
           mne_icalabel = true
           megnet_retrained = false
           mne_algorithm = false
           rules_algorithm = false
         }
       }
     }
   }

All enabled-category indices are normalized and de-duplicated before ICA
application. ``ecg_eog_scores.json`` writes ``ecg_indices``, ``eog_indices``,
``outlier_indices``, and the recording's resolved ``category_switches``; a
disabled category is represented by an empty array.
When several methods assign the same component to ECG or EOG, the summary
stores the maximum score. When ECG and EOG are both enabled, each MEGNet method
also retains its complete four-class labels and probabilities under
``methods``. If either category is disabled, the method entry contains only
enabled-category detections and omits the unfiltered label/probability matrix.

The JSON ``marked_components.auto_indices`` field is the sorted union of the
three category arrays. In automatic mode, it equals both
``marked_components.written_indices`` and the contents of
``marked_components.txt``. If a safe Nextflow refresh preserves a manually
edited text file, ``auto_indices`` remains the newly detected union while
``written_indices`` exactly records the preserved text-file contents. ICA
application consumes that same text file.

Static reports read the recording-level ``category_switches`` sidecar, with the
run manifest as a fallback for older outputs. A disabled ECG or EOG category
does not trigger a misleading ``No ... components detected`` warning;
missing-component alarms remain active for categories that were actually
enabled. This remains correct when recordings in one dataset use different
``ic_label`` overrides.

The former ``ica_label`` boolean has been removed and is not accepted as a
compatibility alias; use ``mne_icalabel``. The retrained model operates only
on an in-memory ICA-source object. ``megnet_retrained`` accepts only a Boolean;
the former ``[enabled: ...]`` mapping form is not accepted. Sources above 250
Hz are temporarily downsampled to 250 Hz, while sources at or below 250 Hz are
used unchanged.
The input raw, ICA, and ICA-source FIF files are never modified, and the
training passband of 1-100 Hz is not enforced as a runtime restriction.

If retrained-model preprocessing, model loading, or inference fails, its
method entry records ``status: failed`` plus the exception type and message.
Other enabled detectors continue and ``run_ic_label`` still writes their
results. A shared raw/ICA read failure or final-output write failure remains a
task-level error.

**Worked example:** :ref:`example-first-meg-pass`.

Epochs
------

.. list-table::
   :header-rows: 1
   :widths: 32 20 18 30

   * - Field
     - Type / values
     - Default
     - Meaning
   * - ``preproc``
     - ordered list
     - empty
     - Optional analysis-specific filter/notch/resample operations.
   * - ``task_type``
     - ``task`` or ``resting``
     - ``task``
     - Event-based or fixed-length epoching.
   * - ``resting.fixed_length_duration``
     - positive seconds
     - ``2.0``
     - Fixed event spacing for resting recordings.
   * - ``event_source``
     - ``event_file`` or ``find_events``
     - ``event_file``
     - BIDS ``events.tsv`` or stimulation-channel events.
   * - ``event_time_shift_sec``
     - number
     - ``0.0``
     - Signed event correction applied before epoch creation.
   * - ``event_file``
     - map
     - ``trial_type: null``
     - Column filters and optional label-to-id mapping for tabular events.
   * - ``find_events``
     - MNE kwargs
     - stim auto, shortest 1, minimum duration 0
     - Passed to ``mne.find_events``.
   * - ``exclude_event_id``
     - integer or list
     - unset
     - Removes selected event ids before epoching.
   * - ``autoreject``
     - boolean
     - ``false``
     - Enables optional global rejection-threshold estimation.
   * - ``interpolate_bads``
     - boolean
     - ``false``
     - Interpolates bad channels in epochs.
   * - ``drop_bad_channels``
     - boolean
     - ``false``
     - Drops bad channels from epochs instead of retaining metadata.
   * - ``epochs``
     - MNE Epochs kwargs
     - event 1, -0.2 to 0.8 s
     - Includes ``event_id``, ``tmin``, ``tmax``,
       ``reject_by_annotation``, ``picks``, ``baseline``, ``reject``,
       ``preload``, and ``detrend``.

Every key inside ``epochs.epochs`` is passed to ``mne.Epochs`` after MEGFlow
supplies ``raw`` and ``events``. This supports other MNE arguments such as
``flat``, ``proj``, ``decim``, ``reject_tmin``, ``reject_tmax``, ``on_missing``,
and ``event_repeated`` without a MEGFlow-specific rename. Do not place ``raw``
or ``events`` in the configuration because they are routed by the workflow.
Because the outer MEGFlow module has the same name, write the inner argument
map as ``epochs = [event_id: ..., tmin: ..., tmax: ...]``. Do not nest a second
``epochs { ... }`` closure: Nextflow's configuration DSL can merge fields from
the outer scope into that inner block.

The default task epoch block is only a template. Event source, event ids,
timing, baseline, and rejection thresholds must be validated for each dataset
before ``meg_epochs``, ``meg_all``, or ``all`` is expected to complete.

**Worked examples:** :ref:`example-resting-epochs`,
:ref:`example-bids-events`, and :ref:`example-trigger-events`.

Optional Analysis Preprocessing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``epochs.preproc`` optionally filters or resamples the cleaned continuous Raw
recording immediately before events are converted into epochs. It is empty by
default, so existing configurations keep their original data and do not create
an additional continuous file. Supported operations are ``filter``,
``notch_filter``, and ``resample``.

Operations run from top to bottom. ``l_freq`` and ``h_freq`` set the analysis
band in Hz, while ``sfreq`` sets the final sampling rate in Hz. A configured
list replaces the inherited list at that dataset or recording scope, so include
every operation that the override still needs.

When configured, MEGFlow writes an ``*_analysis-raw.fif`` file beside the epoch
output and uses that same continuous recording for epoch-based covariance. This
keeps the epochs and noise covariance in the same analysis band. Trigger events
found from a stimulation channel are detected before resampling and remapped by
MNE; BIDS event onsets and annotations are converted using the final sampling
rate.

**Example: change the epoch analysis range to 1–40 Hz and 250 Hz**

Replace the default empty list with the following configuration. This filters
the ICA-cleaned continuous recording to 1–40 Hz and then resamples it to
250 Hz before constructing epochs:

.. code-block:: groovy

   params {
     megflow {
       defaults {
         epochs {
           preproc = [
             [filter: [l_freq: 1.0, h_freq: 40.0, method: "iir",
                       iir_params: [order: 5, ftype: "butter"]]],
             [resample: [sfreq: 250]]
           ]
           event_source = "event_file"
           epochs = [
             event_id: 1,
             tmin: -0.2,
             tmax: 0.8
           ]
         }
       }
     }
   }

Use ``preproc = []`` or omit the key to preserve the cleaned Raw without any
analysis-specific preprocessing.

Event Timing Correction
~~~~~~~~~~~~~~~~~~~~~~~

Task events can be shifted before epoching with ``event_time_shift_sec`` in the
``epochs`` block. Positive values move event samples later in time and are
intended for stable trigger-to-stimulus delays. When covariance is estimated
from baseline epochs, set the same value in ``covariance.event_time_shift_sec``.
The parameter is a MEGFlow-level setting and should be placed next to
``event_source``, not inside the nested MNE ``epochs`` argument map.
Use the net correction required by the MEG recording. For example, if an
``events.tsv`` file has already been shifted for fMRI alignment, that offset
should be removed before adding any MEG stimulus-delivery delay.

.. code-block:: groovy

   params {
     megflow {
       defaults {
         epochs {
           event_source = "event_file"
           event_time_shift_sec = 0.0395
           epochs = [
             event_id: 1,
             tmin: -0.2,
             tmax: 0.8
           ]
         }
         covariance {
           event_source = "event_file"
           event_time_shift_sec = 0.0395
           epochs = [
             event_id: 1,
             tmin: -0.2,
             tmax: 0.0
           ]
         }
       }
     }
   }
