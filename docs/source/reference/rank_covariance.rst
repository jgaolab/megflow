Rank, Covariance, and Source Imaging
====================================

MEGFlow resolves one default rank from the final experimental recording and
uses it consistently for noise covariance, optional LCMV data covariance, and
source reconstruction. This page describes that default contract and the
advanced function-level overrides that remain available.

Processing Contract
-------------------

The source branch uses the following order:

.. code-block:: text

   final experimental Raw or saved Epochs
       -> select data_type and exclude bad channels
       -> intersect with the noise input in target-channel order
       -> resolve the target rank
       -> write resolved-rank.json
       -> compute bl-cov.fif
       -> compute lcmv-data-cov.fif only when LCMV is requested
       -> validate covariance, forward, rank, and source channel contracts
       -> run minimum norm and/or LCMV

For ``source.type = "epochs"``, the target is the exact ``*-epo.fif`` written
by the epoch process. Rejection, interpolation, and optional analysis
preprocessing are therefore retained. MEGFlow does not recreate source epochs
inside the covariance or source process. For ``source.type = "raw"``, the
target is the exact analysis-ready Raw associated with those epochs.

Default Rank Policy
-------------------

Set ``rank_policy`` at the defaults, dataset, or recording level. The default
is ``"auto"``.

.. list-table::
   :header-rows: 1
   :widths: 22 26 52

   * - Value
     - Resolution
     - When to use it
   * - ``"auto"``
     - Calls ``mne.compute_rank(target, rank=None)`` after final channel
       restriction and passes the resulting dictionary downstream.
     - Recommended default. It can reflect numerical rank loss after ICA or
       epoch interpolation even when that loss is not represented by an MNE
       projector in ``Info``.
   * - ``"info"``
     - Calls ``mne.compute_rank(target, rank="info")`` and shares the resolved
       dictionary.
     - Use when the rank encoded by projectors and Maxwell/SSS metadata is the
       intended model. It may not represent rank loss from directly applied
       ICA or interpolation.
   * - ``"full"``
     - Resolves the full channel-space rank.
     - Advanced use when no rank reduction should be modeled.
   * - dictionary
     - Uses an explicit MNE rank dictionary, for example ``[meg: 60]``.
     - Use only when a validated rank is known for that dataset or recording.
   * - ``null``
     - Treated as the MEGFlow default ``"auto"`` at policy level.
     - Useful when clearing an inherited dataset policy.

Example:

.. code-block:: groovy

   params.megflow.defaults.rank_policy = "auto"

   params.megflow.datasets.MyDataset.recordings = [
     known_sss_rank: [
       match: [task: "auditory", run: "01"],
       rank_policy: [meg: 60]
     ]
   ]

The rank describes the linear sensor subspace used by the analysis. Noise and
data covariance are different statistical matrices, but they use the same
default target rank. MEGFlow does not infer the source rank from a regularized
covariance matrix.

Covariance Roles
----------------

``compute_covariance.py`` owns both covariance roles. They are generated in
one keyed Nextflow task for each experimental recording:

.. list-table::
   :header-rows: 1
   :widths: 28 22 50

   * - Output
     - Required for
     - Input
   * - ``bl-cov.fif``
     - All minimum-norm and LCMV methods
     - Baseline epochs when ``covariance.type = "epochs"``; otherwise the
       paired continuous noise recording selected by
       ``raw_covariance_task_id``.
   * - ``lcmv-data-cov.fif``
     - LCMV only
     - The exact final experimental Raw or saved Epochs selected by
       ``source.type`` and the window in ``source.LCMV.data_covariance``.
   * - ``resolved-rank.json``
     - All source methods
     - The explicit target-rank dictionary, ordered common-channel list, and
       source mode resolved by the covariance task.

A dSPM/MNE/sLORETA/eLORETA-only run does not compute or route an LCMV data
covariance. If ``LCMV`` is included in ``source_methods``, a missing or empty
data-covariance file is a deterministic error before the beamformer runs.
Every source run consumes ``resolved-rank.json``; it does not estimate a second
default rank. The source task verifies that its aligned channels exactly match
the ordered channel list in that file before passing the stored dictionary to
MNE. The Nextflow workflow always routes this artifact.

``resolved-rank.json`` is a generated internal derivative, not another user
setting. Do not edit or route it manually in a normal workflow; change
``rank_policy`` or an explicit function-level override and let Nextflow rebuild
the affected covariance/source lineage.

.. code-block:: groovy

   source: [
     source_methods: ["dSPM", "LCMV"],
     type: "epochs",
     data_type: "meg",
     LCMV: [
       data_covariance: [
         tmin: 0.01,
         tmax: 0.40,
         method: "auto"
       ],
       make_lcmv: [
         reg: 0.05,
         pick_ori: null,
         weight_norm: "unit-noise-gain-invariant"
       ]
     ]
   ]

The ``data_covariance`` map is passed to ``mne.compute_covariance`` for Epochs
or ``mne.compute_raw_covariance`` for Raw. ``make_lcmv`` is passed separately
to ``mne.beamformer.make_lcmv``.

Function-Level Rank Settings
----------------------------

Each covariance or source-imaging function can use its standard MNE ``rank``
argument. When set, this function-level value takes precedence over the shared
``rank_policy``; otherwise, MEGFlow supplies the resolved target rank.

.. list-table::
   :header-rows: 1
   :widths: 34 40 26

   * - Consumer
     - Function-level setting
     - Default
   * - Raw noise covariance
     - ``covariance.compute_raw_covariance.rank``
     - ``rank_policy``
   * - Epoch noise covariance
     - ``covariance.covariance.rank``
     - ``rank_policy``
   * - LCMV data covariance
     - ``source.LCMV.data_covariance.rank``
     - ``rank_policy``
   * - LCMV solver
     - ``source.LCMV.make_lcmv.rank``
     - ``rank_policy``
   * - Minimum-norm inverse
     - ``source.<method>.inverse_operator.rank``
     - ``rank_policy``

An explicit function-level ``rank: null`` is preserved and asks that MNE
function to perform its own local automatic rank handling. It does not mean
the same thing as a top-level null policy. Integers are rejected in direct MNE
``rank`` fields; use a dictionary instead.

Function-level settings can intentionally make consumers use different ranks,
so use them only when that distinction has been validated for the analysis.
MNE may reject inconsistent data/noise covariance ranks during LCMV
construction.

Raw and Empty-Room Noise
------------------------

For ``covariance.type = "raw"``, pairing still uses
``covariance.raw_covariance_task_id``. MEGFlow replaces only the experimental
file's ``task-...`` entity and requires all other recording entities to match.
The current-run noise output is a channel dependency, so scheduling cannot
silently select an old file from a previous run.

The experimental and noise inputs are restricted to their common good channels
in experimental-channel order. The default rank is resolved from the
experimental input, not from the empty-room covariance. MEGFlow also verifies
that the empirical rank of the routed raw noise input is at least the target
rank; otherwise it stops with a message to inspect channel matching,
preprocessing, and ICA exclusions.

This check does not prove that independently applied ICA operators span the
same linear subspace. Equal channel names and equal rank values are necessary
compatibility checks, not evidence that two different ICA decompositions are
the same projection. Studies that require an identical explicit projection
must design and validate that preprocessing policy separately.

Routing and Failure Checks
--------------------------

Before source reconstruction, MEGFlow verifies all of the following:

* dataset and recording identity match across forward and covariance branches;
* effective configurations and clean-input lineage match;
* covariance was computed from the exact Raw/Epochs hash expected by
  ``source.type``;
* the routed rank artifact hash is part of source cache lineage, and its
  channel order matches the aligned source input;
* noise and LCMV data covariance channel names and order match;
* every covariance channel exists in the source data and forward solution;
* ``lcmv-data-cov.fif`` exists only as a required input when LCMV is enabled.

Configuration, routing, channel-contract, and missing-output failures use a
non-retryable error path even in lenient mode. Resource-related failures retain
the configured retry behavior.

See the MNE documentation for `compute_rank
<https://mne.tools/stable/generated/mne.compute_rank.html>`_,
`compute_raw_covariance
<https://mne.tools/stable/generated/mne.compute_raw_covariance.html>`_,
`compute_covariance
<https://mne.tools/stable/generated/mne.compute_covariance.html>`_,
`make_inverse_operator
<https://mne.tools/stable/generated/mne.minimum_norm.make_inverse_operator.html>`_,
and `make_lcmv
<https://mne.tools/stable/generated/mne.beamformer.make_lcmv.html>`_.
