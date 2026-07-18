.. _configuration-source:

Source and Report Configuration
===============================

This page covers rank resolution, covariance, forward and source modeling,
MNE parameter maps, report settings, and source visualization.

Rank Policy
-----------

``rank_policy`` is a processing-level field and defaults to ``"auto"``. It is
resolved on the exact final experimental Raw or saved Epochs after bad-channel
exclusion and restriction to channels shared with the noise input. The resolved
rank dictionary is then the default for covariance estimation and source
reconstruction. It is written to ``resolved-rank.json`` and routed to source
imaging so all default consumers use the same explicit dictionary rather than
estimating rank again.

Allowed values are ``"auto"`` (empirical target-data rank), ``"info"``,
``"full"``, an MNE rank dictionary such as ``[meg: 60]``, or ``null`` as an
alias for the default automatic policy. Function-level MNE ``rank`` keys and
the compatibility field ``source.LCMV.n_rank`` remain supported as explicit
overrides. See
:doc:`rank_covariance` for precedence, LCMV's two covariance matrices,
empty-room compatibility checks, and examples.

Covariance
----------

.. list-table::
   :header-rows: 1
   :widths: 34 18 48

   * - Field
     - Default
     - Meaning
   * - ``visualize``
     - ``true``
     - Writes covariance matrix and spectrum figures.
   * - ``type``
     - ``epochs``
     - ``epochs`` computes baseline-epoch covariance; ``raw`` uses a paired
       continuous noise recording.
   * - ``raw_covariance_task_id``
     - ``emptr``
     - Task entity used to locate the paired ICA-clean noise recording.
   * - ``event_time_shift_sec``
     - ``0.0``
     - Event correction for epoch-based covariance; normally matches epochs.
   * - ``compute_raw_covariance``
     - tmin 0, tmax null, method auto, mag reject 4e-12,
       reject annotations
     - MNE keyword arguments passed to ``mne.compute_raw_covariance``.
   * - ``events``
     - stim auto, shortest 1, minimum duration 0
     - MNE find-events arguments used for fallback event extraction in epoch
       covariance.
   * - ``epochs``
     - event 1, -0.2 to 0.0 s, mag picks
     - MNE Epochs arguments that define baseline epochs.
   * - ``covariance``
     - tmin null, tmax null
     - MNE keyword arguments passed to ``mne.compute_covariance``.

The ``compute_raw_covariance`` and ``covariance`` maps are passed as kwargs to
their namesake MNE functions. MEGFlow adds the resolved ``rank`` from
``rank_policy`` unless that function-level map explicitly supplies ``rank``.
For epoch covariance, ``covariance.epochs`` follows the same direct
``mne.Epochs`` contract as ``epochs.epochs``.

``bl-cov.fif`` is always produced for a full source run. The same covariance
process also writes ``lcmv-data-cov.fif`` only when the effective
``source.source_methods`` contains ``LCMV``. That data covariance is computed
from the exact final source Raw or saved Epochs, not from newly reconstructed
epochs. Minimum-norm-only runs do not compute it. ``resolved-rank.json`` is
always written and records the target rank and ordered common channels consumed
by source imaging.

For ``type: raw``, MEGFlow replaces ``task-<experimental>`` in the ICA-clean
continuous filename with ``task-<raw_covariance_task_id>``. The paired task must
have been imported and processed through ICA. The task id may contain letters,
numbers, and hyphens. Pairing retains all other filename entities, so subject,
session, run, acquisition, and suffix must already describe the intended pair.

The paired clean file is a channel dependency, not a path guessed from an
output directory. Covariance therefore waits for the current run's noise record
even when task scheduling finishes the experiment first. A missing pair fails
the full source run instead of silently omitting it, and one noise recording may
serve multiple experimental tasks when their other entities match. A recording
identified as a raw-covariance reference is cleaned through ICA but is excluded
from its own epoch, covariance, forward, and source branches, even when its own
recording profile otherwise inherits epoch covariance. When ``epochs.preproc``
is not empty, the same operations are applied in memory to the paired noise
recording before raw covariance is computed.

Target and noise inputs are restricted to common good channels in target order.
With the default rank policy, rank is resolved from the target experimental
input. For raw noise, MEGFlow also checks that the empirical noise-input rank
can support that target rank. See :doc:`rank_covariance` for the complete
contract and the limitation of independently applied ICA projections.

**Worked examples:** :ref:`example-lcmv-covariance` and
:ref:`example-raw-covariance`.

BEM, Coregistration, Forward, and Source
----------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 37 18 45

   * - Field
     - Default
     - Meaning
   * - ``bem.ico``
     - ``4``
     - BEM surface subdivision grade.
   * - ``bem.conductivity``
     - ``[0.3]``
     - Single-layer MEG BEM conductivity.
   * - ``coreg.visualize``
     - ``true``
     - Generates transform-alignment figures.
   * - ``coreg.omit_head_shape_points``
     - ``1`` mm
     - Distance used to omit headshape points before fitting.
   * - ``coreg.grow_hair``
     - ``0.0`` mm
     - Scalp expansion used by MNE coregistration.
   * - ``coreg.icp``
     - 200 iterations; fiducial/HSP/HPI weights from the Docker config
     - Initial MNE ICP fit.
   * - ``coreg.finetune_icp``
     - 200 iterations; HSP-only weight 10
     - Fine-tuning ICP fit.
   * - ``coreg.supplied_trans_file``
     - unset
     - Reuses a supplied transform instead of fitting a new one.
   * - ``forward.epoch_label``
     - ``wdonset``
     - Label used in forward output naming.
   * - ``forward.surface`` / ``forward.spacing``
     - ``white`` / ``ico4``
     - Cortical surface and source-space spacing.
   * - ``source.type``
     - ``epochs``
     - Source input mode: ``epochs`` or ``raw``.
   * - ``source.visualize``
     - ``true``
     - Generates source figures.
   * - ``source.source_methods``
     - ``["dSPM"]``
     - Any implemented inverse methods: MNE-family methods and/or ``LCMV``.
   * - ``source.data_type``
     - ``meg``
     - Channel type selected for evoked/source input.
   * - ``source.spacing`` / ``source.epoch_label``
     - ``ico4`` / ``wdonset``
     - Source-space spacing and output label.
   * - ``source.<method>.make_inverse_operator``
     - loose auto, depth 0.8, fixed auto
     - Passed to ``mne.minimum_norm.make_inverse_operator``.
       ``inverse_operator`` remains a compatible alias.
   * - ``source.<method>.apply_inverse``
     - lambda2 1/9, method dSPM, normal orientation
     - Passed to ``mne.minimum_norm.apply_inverse`` for epoched source data.
   * - ``source.<method>.apply_inverse_raw``
     - falls back to ``apply_inverse``; lambda2 defaults to 1/9
     - Passed to ``mne.minimum_norm.apply_inverse_raw`` for continuous source
       data. Use it for raw-only arguments such as ``start``, ``stop``, and
       ``buffer_size``.
   * - ``source.LCMV.data_covariance``
     - tmin 0.01, tmax 0.4, method auto
     - Passed to ``mne.compute_covariance`` for Epochs or
       ``mne.compute_raw_covariance`` for Raw. Used only when LCMV is selected.
   * - ``source.LCMV.make_lcmv``
     - reg 0.05, pick_ori null, unit-noise-gain-invariant normalization
     - Passed to ``mne.beamformer.make_lcmv``.
   * - ``source.LCMV.apply_lcmv`` / ``apply_lcmv_raw``
     - empty
     - Passed to the matching epoched or continuous MNE LCMV application
       function.
   * - ``source.LCMV.n_rank``
     - unset
     - Compatibility integer/string/dictionary override used after the
       corresponding function-level ``rank`` and before ``rank_policy``.
   * - ``source.visualization``
     - peak, both hemispheres, lateral view
     - Peak- or label/time-based visualization selection.

Coregistration is implemented with MNE
`Coregistration <https://mne.tools/stable/generated/mne.coreg.Coregistration.html>`_.
Source kwargs correspond to
`make_inverse_operator
<https://mne.tools/stable/generated/mne.minimum_norm.make_inverse_operator.html>`_
and `make_lcmv <https://mne.tools/stable/generated/mne.beamformer.make_lcmv.html>`_.
The complete rank precedence and conditional covariance behavior are described
in :doc:`rank_covariance`.

**Worked examples:** :ref:`example-full-meg` and
:ref:`example-lcmv-covariance`.

MNE Parameter Passthrough Example
---------------------------------

The following representative settings use MNE argument names directly. MEGFlow
routes Raw/Epochs/events inputs, removes its own control fields, injects the
resolved default rank where appropriate, and forwards the remaining maps to the
named MNE functions. They may be placed in ``defaults``, a dataset profile, or
a recording profile. Maps are recursively merged across those levels.

.. code-block:: groovy

   epochs: [
     event_source: "find_events",
     find_events: [stim_channel: "STI 014", shortest_event: 1],
     epochs: [
       event_id: 1, tmin: -0.2, tmax: 0.8, baseline: [null, 0.0],
       picks: "meg", preload: true, proj: false, decim: 2,
       reject: [mag: 4e-12], reject_tmin: -0.1, reject_tmax: 0.6,
       reject_by_annotation: true, event_repeated: "merge"
     ]
   ],

   covariance: [
     type: "epochs",
     epochs: [event_id: 1, tmin: -0.2, tmax: 0.0,
              baseline: null, picks: "meg", preload: true],
     covariance: [
       keep_sample_mean: true, tmin: null, tmax: null,
       method: "empirical", cv: 3, n_jobs: 1
     ],
     compute_raw_covariance: [
       tmin: 0.0, tmax: null, tstep: 0.2,
       method: "empirical", reject_by_annotation: true, n_jobs: 1
     ]
   ],

   source: [
     type: "epochs",
     source_methods: ["dSPM", "LCMV"],
     dSPM: [
       make_inverse_operator: [
         loose: "auto", depth: 0.8, fixed: "auto", use_cps: true
       ],
       apply_inverse: [
         lambda2: 0.1111111111111111, method: "dSPM", pick_ori: "normal"
       ],
       apply_inverse_raw: [
         lambda2: 0.1111111111111111, method: "dSPM",
         start: null, stop: null, buffer_size: 1000
       ]
     ],
     LCMV: [
       data_covariance: [tmin: 0.01, tmax: 0.4, method: "empirical"],
       make_lcmv: [
         reg: 0.05, pick_ori: null,
         weight_norm: "unit-noise-gain-invariant", inversion: "matrix"
       ],
       apply_lcmv: [verbose: "INFO"],
       apply_lcmv_raw: [start: null, stop: null, verbose: "INFO"]
     ]
   ]

These are API passthrough capabilities, not universal scientific defaults.
Filter bands, epoch windows, rejection limits, covariance intervals, inverse
orientation, and beamformer regularization must still be selected for the
dataset and hypothesis. MEGFlow 1.0.0 pins MNE 1.8.0; validate new kwargs against
that runtime even when consulting newer MNE stable documentation.

For an actual OSL-Ephys stage that is not part of the default recipe, see
:ref:`configuration-osl-passthrough`.

Report
------

.. list-table::
   :header-rows: 1
   :widths: 38 18 44

   * - Field
     - Docker default
     - Meaning
   * - ``bad_channel_threshold``
     - ``30``
     - Bad-channel count alarm.
   * - ``bad_segment_threshold``
     - ``50``
     - Bad-segment count alarm.
   * - ``coreg_mean_threshold``
     - ``5.0`` mm
     - Mean coregistration-distance alarm.
   * - ``coreg_max_threshold``
     - ``20.0`` mm
     - Maximum coregistration-distance alarm.
   * - ``epoch_reject_rate_threshold``
     - ``0.90``
     - Rejected-epoch fraction alarm.
   * - ``static_artifact_overview_duration``
     - ``200.0`` s
     - Time span represented by detailed artifact overview images.
   * - ``alert_missing_ecg_components``
     - ``true``
     - Warns when no ECG component is reported.
   * - ``alert_missing_eog_components``
     - ``true``
     - Warns when no EOG component is reported.
   * - ``static_task_log_mode``
     - ``all-command-log``
     - ``all-command-log``, ``failed``, or ``none`` controls packaged Nextflow
       task logs.

Source Visualization
--------------------

Source reconstruction figures use the maximal-activation peak by default. To
inspect a predefined response window, set ``source.visualization`` with a
time point and an anatomical ROI. MEGFlow selects the nearest source-estimate
sample at that time, restricts the search to matching FreeSurfer ``aparc``
labels, and saves figures with the selection name in the filename.

.. code-block:: groovy

   source: [
     visualize: true,
     epoch_label: "char_onset",
     source_methods: ["dSPM"],
     visualization: [
       name: "temporal_124ms",
       mode: "label",
       roi: "temporal",
       time: 0.124,
       hemi: "both"
     ]
   ]

Common ROI aliases include ``temporal`` or ``auditory`` for temporal-lobe
responses and ``occipital`` or ``visual`` for occipital responses. ``hemi`` can
be ``lh``, ``rh``, or ``both``. Leaving ``visualization`` unset preserves the
default peak-based figure names. When ``views`` is omitted, MEGFlow selects a
``lateral``, ``medial``, or ``ventral`` view from the anatomical label of the
selected vertex so that its marker remains visible. Set ``views`` explicitly to
override this behavior.
