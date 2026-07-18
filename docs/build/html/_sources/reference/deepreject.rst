DeepReject Artifact Detection
=============================

Overview
--------

DeepReject is the deep-learning-based artifact-detection branch used by
MEGFlow. The public configuration path is ``artifacts.deepreject``. The
compatibility class is still named ``DeepRejectPredictor``, but current
inference uses two independent final models rather than the earlier shared
two-head network:

* **BadChnNet** predicts bad channels for the whole recording.
* **BadSegNet** predicts bad time windows and converts them into MNE bad
  annotations.

Both models provide five bundled folds, and the default uses all five.
DeepReject results are merged with the enabled PyPREP, PSD, OSL, and MNE
detectors; they do not replace those detectors.

Execution Order
---------------

For each preprocessed recording, MEGFlow performs the following operations:

1. Select data MEG channels. Reference MEG, stimulus, ECG, EOG, EMG, and
   miscellaneous channels are excluded when ``pick_meg_only`` is true.
2. Check the effective input high-pass, low-pass, and sampling frequency against
   the recommended ``1-100 Hz`` and ``250 Hz`` model input.
3. When ``run_bad_channels`` is true, run BadChnNet and combine the selected
   fold predictions into one bad-channel decision per channel.
4. When both models run, mask the BadChnNet channels in the recording passed to
   BadSegNet. If BadChnNet is disabled, BadSegNet receives the selected MEG
   channels without this model-derived mask.
5. When ``run_bad_segments`` is true, run BadSegNet, average the selected fold
   window probabilities, and convert the probability sequence to bad intervals
   with hysteresis and interval post-processing.
6. Merge the DeepReject bad channels and ``BAD_deepreject`` annotations with
   results from the other configured artifact detectors.
7. Write the merged bad-channel and bad-segment sidecars together with a
   ``deepreject_summary.json`` provenance record.

BadChnNet
---------

For channel :math:`i`, let :math:`p_{f,i}` be the predicted bad-channel
probability from fold :math:`f`. MEGFlow calculates the fold mean and standard
deviation:

.. math::

   \bar{p}_i = \frac{1}{F}\sum_{f=1}^{F}p_{f,i}, \qquad
   s_i = \sqrt{\frac{1}{F}\sum_{f=1}^{F}(p_{f,i}-\bar{p}_i)^2}.

The lower-confidence-bound score is

.. math::

   \operatorname{LCB}_i = \bar{p}_i - \lambda s_i,

where ``badchnnet_lambda_lcb`` is :math:`\lambda` and defaults to ``1.0``.
This penalizes channels whose predictions vary strongly across folds.

BadChnNet then derives a robust threshold separately for channel-name sensor
groups: Neuromag-style magnetometers, gradiometers, and a fallback group for
other naming schemes. A group receives its own threshold when it contains at
least ``badchnnet_min_type_channels`` channels. For LCB values :math:`x` in a
sensor group,

.. math::

   T = \max\left(T_{floor},\ \operatorname{median}(x)
       + z\,1.4826\,\operatorname{median}(|x-\operatorname{median}(x)|)\right).

A channel is bad when its LCB score is at least :math:`T`. Sensor types with too
few channels use the threshold computed from all channels. The default values
are ``floor=0.56``, ``z=3.0``, and ``min_type_channels=8``.

BadSegNet
---------

For time window :math:`t`, BadSegNet averages the artifact probabilities from
the selected folds:

.. math::

   p_t = \frac{1}{F}\sum_{f=1}^{F}p_{f,t}.

Hysteresis converts this probability sequence into intervals. A candidate
component consists of consecutive windows with :math:`p_t` at or above the low
threshold, and it is retained only if at least one window reaches the high
threshold. Candidate intervals separated by no more than
``badsegnet_merge_gap_sec`` are merged. Intervals shorter than
``badsegnet_min_duration_sec`` are removed unless their maximum probability
reaches ``badsegnet_short_keep_threshold``.

The model window duration is read from the bundled fold configuration. Output
intervals are converted to seconds and written as ``BAD_deepreject`` MNE
annotations.

Modes
-----

``mode`` changes BadSegNet post-processing only. It does not switch models,
change the input filter, or automatically select a mode from the MEG vendor.

.. list-table::
   :header-rows: 1
   :widths: 14 15 15 18 18 20

   * - Mode
     - High
     - Low
     - Merge gap
     - Minimum duration
     - Short keep
   * - ``default``
     - ``0.89``
     - ``0.18``
     - ``10.0 s``
     - ``0.0 s``
     - ``0.97``
   * - ``strict``
     - ``0.85``
     - ``0.15``
     - ``10.0 s``
     - ``0.0 s``
     - ``0.95``
   * - ``lenient``
     - ``0.99``
     - ``0.95``
     - ``0.0 s``
     - ``0.0 s``
     - ``1.0``

``strict`` generally marks more windows and retains weaker short intervals.
``lenient`` retains only very high-confidence components and does not bridge
gaps. Explicit low-level values such as
``badsegnet_hysteresis_high`` override the selected mode.

Configuration Fields
--------------------

Core controls
~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 31 18 18 33

   * - Field
     - Allowed values
     - Docker default
     - Meaning
   * - ``enabled``
     - boolean
     - ``true``
     - Enables the DeepReject branch.
   * - ``mode``
     - ``default``, ``strict``, ``lenient``
     - ``default``
     - Selects the BadSegNet post-processing preset.
   * - ``device``
     - ``cpu``, ``auto``, ``cuda``, ``cuda:N``, ``gpu``
     - ``cpu``
     - PyTorch inference device. ``auto`` uses CUDA when available.
   * - ``category``
     - ``auto``, ``rest``, ``task``, or model-supported text
     - ``auto``
     - Recording category. ``auto`` infers ``rest`` from names containing
       ``rest``, ``closedeye``, or ``openeye`` and otherwise uses ``task``.
   * - ``dataset``
     - string or null
     - inferred
     - Optional provenance label. The input parent directory is used when
       omitted.
   * - ``run_bad_channels``
     - boolean
     - ``true``
     - Runs BadChnNet.
   * - ``run_bad_segments``
     - boolean
     - ``true``
     - Runs BadSegNet. At least one ``run_bad_*`` field must be true.
   * - ``on_error``
     - ``warn`` or ``raise``
     - ``warn``
     - ``warn`` logs the failure and continues with the other detectors;
       ``raise`` also fails the artifact process. ``error`` and ``fail`` are
       accepted aliases for ``raise``.

Input controls
~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 31 18 18 33

   * - Field
     - Type
     - Default
     - Meaning
   * - ``pick_meg_only``
     - boolean
     - ``true``
     - Creates a temporary FIF containing data MEG channels only.
   * - ``pick_exclude_marked_bads``
     - boolean
     - ``false``
     - Excludes channels already present in ``raw.info['bads']`` from model
       input. With the default, the model can evaluate those channels again.
   * - ``keep_meg_only_input``
     - boolean
     - ``false``
     - Keeps the temporary MEG-only FIF for debugging.
   * - ``filter_l_freq`` / ``filter_h_freq``
     - number or null
     - null
     - Optional internal filtering immediately before inference.
   * - ``resample_sfreq``
     - number or null
     - null
     - Optional internal resampling immediately before inference.

The official Docker preprocessing default already produces ``1-100 Hz`` data
at ``250 Hz``, so the internal filter and resample fields normally remain null.
DeepReject records actual, requested, effective, and recommended values in
``deepreject_summary.json``. It warns when they differ. Filtering or resampling
cannot restore frequencies or temporal resolution that were already removed by
earlier preprocessing.

Inference and resource controls
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 36 18 16 30

   * - Field
     - Type
     - Default
     - Meaning
   * - ``folds``
     - integer list or comma-separated string
     - ``0,1,2,3,4``
     - Ensemble folds to use.
   * - ``fold_workers``
     - positive integer
     - ``5``
     - Concurrent fold workers within one recording.
   * - ``cache_models``
     - boolean
     - ``true``
     - Keeps loaded fold models for repeated inference in the same process.
   * - ``cpu_threads``
     - positive integer or null
     - ``4``
     - PyTorch CPU intra-operation threads.
   * - ``cpu_interop_threads``
     - positive integer or null
     - ``1``
     - PyTorch CPU inter-operation threads.
   * - ``badsegnet_batch_size``
     - positive integer
     - ``32``
     - BadSegNet inference batch size.
   * - ``badsegnet_encoder_chunk_size``
     - positive integer or null
     - null
     - Optional encoder chunk size for memory-constrained runs.
   * - ``badsegnet_edge_k``
     - positive integer
     - ``6``
     - Number of graph neighbors used when constructing BadSegNet input.
   * - ``badchnnet_chunk_windows``
     - positive integer or null
     - model config
     - Number of windows in each BadChnNet recording chunk.
   * - ``badchnnet_chunk_stride``
     - positive integer or null
     - model config
     - Stride between BadChnNet chunks.
   * - ``badchnnet_min_chunk_windows``
     - positive integer or null
     - model config
     - Minimum number of windows retained in a final chunk.
   * - ``badchnnet_chunk_prob_aggregation``
     - ``mean`` or ``max``
     - ``mean``
     - Combines multiple chunk predictions for one channel within a fold.

Post-processing controls
~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 38 18 44

   * - Field
     - Runtime default
     - Meaning
   * - ``badsegnet_hysteresis_high``
     - ``0.89``
     - Probability required to activate a candidate bad interval.
   * - ``badsegnet_hysteresis_low``
     - ``0.18``
     - Probability required to continue the candidate interval.
   * - ``badsegnet_merge_gap_sec``
     - ``10.0``
     - Maximum gap bridged between candidate intervals.
   * - ``badsegnet_min_duration_sec``
     - ``0.0``
     - Minimum interval duration after merging.
   * - ``badsegnet_short_keep_threshold``
     - ``0.97``
     - Maximum probability that allows a short interval to bypass minimum
       duration removal.
   * - ``badchnnet_lambda_lcb``
     - ``1.0``
     - Fold-uncertainty penalty in the LCB score.
   * - ``badchnnet_floor``
     - ``0.56``
     - Minimum bad-channel decision threshold.
   * - ``badchnnet_z``
     - ``3.0``
     - Robust MAD multiplier.
   * - ``badchnnet_min_type_channels``
     - ``8``
     - Minimum channels required for a sensor-type-specific threshold.

Common Configurations
---------------------

Use the calibrated defaults:

.. code-block:: groovy

   artifacts: [
     deepreject: [enabled: true, mode: "default", device: "cpu"]
   ]

Use a conservative bad-segment policy for one dataset:

.. code-block:: groovy

   params.megflow.datasets.MEG_MASC_word.artifacts = [
     meg_vendor: "kit",
     deepreject: [mode: "lenient"]
   ]

Change only one task within a dataset:

.. code-block:: groovy

   recordings: [
     movement_task: [
       match: [task: "movement"],
       artifacts: [deepreject: [mode: "strict"]]
     ]
   ]

Outputs and Interpretation
--------------------------

DeepReject contributes to these artifact outputs:

* ``*_bad_channels.txt``: merged final channel names from all enabled methods.
* ``*_bad_channels_description.json``: detector provenance for each final bad
  channel, including ``DeepReject BadChnNet`` when applicable.
* ``*_bad_segments.txt``: merged MNE annotations; DeepReject intervals use the
  description ``BAD_deepreject``.
* ``deepreject_summary.json``: selected folds, effective thresholds, input
  preprocessing, bad-channel probabilities, channel names, bad intervals, and
  runtime settings.
* ``check_imgs/artifact_mask_heatmap.jpg``: recording-wide bad-channel and
  bad-time mask generated even when detailed artifact images are disabled.

An annotation marks a time range as bad; it does not remove samples from the
continuous FIF. ICA and epoching decide whether to exclude marked samples. See
:ref:`bad-segment-marking` for downstream behavior.
