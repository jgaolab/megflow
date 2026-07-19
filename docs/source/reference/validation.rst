Validation and Regression Testing
=================================

MEGFlow includes three complementary test layers. Python unit tests exercise
event handling, analysis preprocessing, DeepReject inputs, NMDQ score/report
rendering, source-input resolution, rank precedence, and static configuration
contracts. Lightweight MNE/OSL tests write synthetic Raw/Epochs FIF files and
run real OSL filtering/resampling, MNE epoch creation, and covariance
estimation. Source tests bind representative kwargs against the installed MNE
signatures and capture the actual inverse/beamformer calls. Nextflow integration tests use
``-stub-run`` to execute the real workflow graph without starting FreeSurfer,
DeepPrep, or full source reconstruction.

Run the Test Suite
------------------

The fast routing gate used for every GitHub push and pull request is:

.. code-block:: bash

   export MEGFLOW_NEXTFLOW="$(command -v nextflow)"
   bash scripts/validation/run_validation.sh routing-ci

``routing-ci`` first runs every static routing/configuration contract, then a
representative real Nextflow 24.10.3 ``-stub-run`` matrix, and finally parses
every tracked config under ``nextflow/``. The smoke matrix covers recording
stage reduction, anatomy-only and simultaneous anatomy/MEG routing,
defaults/dataset/recording precedence, MNE/OSL parameter passthrough,
dataset-scoped empty-room covariance, conditional LCMV data covariance,
resume invalidation, strict failure, and dataset/corpus report rebuilding.
Static documentation-example checks run here, while exhaustive parsing and
previewing of every embedded Groovy example stays in the full local gate.

Run the complete routing and resume matrix before a release or after broad
workflow changes:

.. code-block:: bash

   export MEGFLOW_NEXTFLOW="$(command -v nextflow)"
   bash scripts/validation/run_validation.sh routing

``routing`` includes all ``routing-ci`` behavior plus complete step aliases and
invalid combinations, required-output deletion matrices, detailed resume
lineage cases, lenient-failure closure, report layout, and every documented
configuration example. These tests use stubs for slow scientific programs, so
FreeSurfer and DeepPrep do not perform real reconstruction, but the large
number of Nextflow launches makes this gate intentionally more time-consuming.

``scientific`` runs the explicit synthetic MNE/OSL, DeepReject-input, NMDQ,
epochs, rank/covariance, MEGNet/ICA-label, source-call, and static-report suites.
``all`` runs the complete ``routing`` and ``scientific`` gates and also builds
the documentation when Sphinx is installed together with all extensions in
``requirements_doc.txt``. A requested gate fails if its dependency is missing,
zero tests are discovered, or any test is skipped; this prevents a missing
executable from producing a misleading green result. The CI-required files are
also checked against ``git ls-files``, so local-only files cannot silently make
a clean GitHub checkout behave differently. A static coverage contract
enumerates every tracked ``tests/test_*.py`` module and fails when a module is
not assigned to a complete local gate.

To reproduce the lightweight scientific CI environment rather than using an
existing MEGFlow environment:

.. code-block:: bash

   python -m venv /tmp/megflow-validation
   /tmp/megflow-validation/bin/python -m pip install -r requirements_validation.txt
   /tmp/megflow-validation/bin/python -m pip install --no-deps -e ./megflow/tools/osl-ephys
   PYTHON=/tmp/megflow-validation/bin/python \
     bash scripts/validation/run_validation.sh scientific

The repository CI performs ``routing-ci`` and ``scientific`` with Nextflow
24.10.3 on every push and pull request. The exhaustive ``routing`` gate remains
local rather than extending routine CI with every resume and output-deletion
matrix. A separate ``windows-latest`` job parses the Windows installer with the
native PowerShell AST parser and fails if that parser is unavailable;
non-Windows runs do not report this platform-specific check as passed or
skipped. The strict documentation build is a fourth job. Keep Nextflow pinned
to the production runtime and evaluate an upgrade in a separate change. The
production Docker image is reserved for less frequent runtime canaries because
its approximately 32.8 GB size is not suitable for every GitHub job.

P0 Release Contract
-------------------

P0 tests protect workflow routing, scientific-configuration propagation, and
the ability to audit incomplete runs. A release candidate is not considered
validated merely because a complete ``meg_all`` example finishes. The
following contracts must be checked independently:

.. list-table::
   :header-rows: 1
   :widths: 10 25 65

   * - ID
     - Area
     - Required assertions
   * - P0-01
     - Step selection
     - Compare the exact trace process set and terminal outputs for ``report``,
       ``anatomy``, ``meg_artifacts``, ``meg_ica``, ``meg_epochs``,
       ``meg_epochs,skip_ica``, ``meg_all``, and ``all``. Also test aliases,
       whitespace/case normalization, ``with_anatomy``, and fail-fast invalid
       combinations. A recording override may stop earlier but may not exceed
       its dataset stage.
   * - P0-02
     - Configuration scope
     - Verify defaults, dataset, and recording precedence; recursive map
       merging; whole-list replacement; dataset isolation; rejected
       dataset-only recording fields; and fixed internal process directories.
   * - P0-03
     - Import and identity
     - Cover BIDS and raw discovery, file and directory recordings such as CTF
       ``.ds``, task/session/run identity, duplicate output ids, empty imports,
       output-tree exclusion, and repeated subject ids across datasets.
   * - P0-04
     - Scientific parameters
     - Bind representative OSL and MNE keyword arguments, run synthetic
       filtering/resampling, epochs, covariance, and source calls, and assert
       numerical or metadata changes rather than configuration parsing alone.
   * - P0-05
     - Quality-score gate
     - Check default-enabled scoring, disabled bypass, exact threshold equality,
       below-threshold exclusion, missing/NaN/failed scores, alarm-versus-gate
       semantics, and case-insensitive per-dataset vendor selection.
   * - P0-06
     - Artifacts and ICA
     - Exercise empty and populated bad-channel/bad-segment files, traditional
       detectors with DeepReject enabled or disabled, ``raw.first_time``
       interval alignment, ICA fit/label/apply lineage, and deterministic seeds.
   * - P0-07
     - Events and epochs
     - Cover ``event_file``, ``find_events``, annotations, and resting events;
       UTF-8 input errors; nonzero first samples; resampling; missing events;
       rejection thresholds; and report generation after epoch failure.
   * - P0-08
     - Anatomy and source
     - Route only the selected FreeSurfer, DeepPrep, pseudo-MRI, NIfTI, or DICOM
       anatomy method. Verify subject matching, existing-anatomy reuse, BEM,
       coregistration, forward, raw/epoch covariance, rank, dSPM, LCMV, and
       dataset-scoped noise pairing.
   * - P0-09
     - Resume lineage
     - After a baseline run, delete one required published QC, preprocessing,
       artifact, ICA, epoch, covariance, transform, forward, source, or anatomy
       result. ICA-label deletion covers both ``marked_components.txt`` and
       ``ecg_eog_scores.json``. Its owner must restore the output; consumers
       rerun when the restored fingerprint changes, while unrelated recordings
       stay cached.
       Separately edit user-controlled artifact or ICA-label sidecars and prove
       that the owner stays cached while consumers rerun. Reports always rerun.
   * - P0-10
     - Failure and channel closure
     - In lenient mode, inject failures at each processing stage, all-recording
       QC exclusion, and mixed success/failure datasets. Dataset and corpus
       report processes must still be submitted without deadlock. Strict-mode
       termination behavior must be tested separately and documented.
   * - P0-11
     - Reports
     - Validate dataset and corpus quality scores, partial/failed step states,
       nested effective-config manifests, disabled-QC handling, derivative-based
       completion, trace/log packaging, interactive corpus navigation,
       report-only rebuilds, responsive static layout, and the no-cache report
       policy.
   * - P0-12
     - Runtime packaging
     - Parse every shipped config, match every process selector, keep stub
       resources within CI capacity, and verify source/Docker CLI precedence and
       output paths with the production Nextflow version.

Run P0 in four gates: static Python/config checks first, Nextflow stub routing
second, synthetic MNE/OSL numerical checks third, and fixed real-data canaries
last. A recommended real-data gate contains one task recording, one resting
recording, one raw-noise covariance pair, and one existing-anatomy source run.
Full FreeSurfer or DeepPrep reconstruction can run periodically on a pinned
subject rather than on every pull request.

Integration Matrix
------------------

The stub suite verifies the following workflow contracts:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Area
     - Covered behavior
   * - Stage selection
     - A declarative matrix compares the exact required and forbidden process
       sets for ``report``, ``anatomy``, ``meg_artifacts``, ``meg_ica``,
       ``meg_epochs``, ``meg_epochs,skip_ica``, ``meg_all``, and ``all``. It
       separately covers aliases and normalization, legal ``with_anatomy``
       combinations, invalid modifiers, and recording-level stage reduction.
   * - Structural processing
     - BIDS FreeSurfer, DeepPrep, pseudo-MRI, non-BIDS NIfTI, DICOM conversion,
       and simultaneous anatomy plus MEG are traversed with placeholder outputs
       only; no long reconstruction runs.
   * - Profile isolation
     - Multiple datasets and recording profiles use distinct epoch,
       covariance, forward, and source directories and retain their own
       effective configuration.
   * - MNE/OSL parameter propagation
     - A three-level defaults/dataset/recording fixture verifies the complete
       effective OSL preprocessing recipe and nested Epochs, covariance,
       minimum-norm, and LCMV kwargs. It checks recursive map merging, whole-list
       replacement, scientific-notation thresholds, and recording isolation.
   * - Source routing
     - Forward and covariance FIF paths are joined by
       ``[dataset, recording]`` identity. Duplicate or internally mismatched
       lineage always fails. Strict mode also rejects missing partners, while
       lenient mode closes branches made incomplete by ignored task failures so
       reports can record them. dSPM-only routes omit LCMV data covariance,
       while raw and epoched LCMV routes require it and verify the exact
       source-input hash.
   * - Raw covariance
     - Delayed noise branches, recording-specific covariance overrides,
       missing pairs, cross-dataset isolation, and several experimental tasks
       sharing one noise recording are covered. The routed noise recording key
       is retained for audit. Combined empty-room plus LCMV cases verify that
       noise covariance comes from the paired recording while data covariance
       comes from the exact target Epochs or analysis Raw.
   * - Rank and covariance numerics
     - Synthetic rank-deficient data distinguish ``auto`` from ``info`` and
       exercise null, full, and dictionary policies. Tests also cover
       explicit/compatibility/default precedence, reject invalid integer MNE
       rank fields, enforce common-channel order, remove stale LCMV output, and
       require raw noise to support the target rank. The persisted rank artifact
       is checked against source channel order. Real epoch-noise, dSPM-only, raw
       LCMV, and saved-Epochs LCMV covariance outputs are read back with MNE 1.8.
   * - Validation
     - Unknown match keys, overlapping recording profiles, ineffective
       recording-scope fields, excessive recording stages, duplicate recording
       basenames, and overlapping dataset output trees fail early.
   * - Resume behavior
     - Event edits rerun only event-dependent stages; a newly added raw creates
       only a new branch; changing one raw reruns that recording while another
       remains cached; changing the processing implementation invalidates all
       affected task branches. Parallel deletion matrices cover required MEG
       and anatomy outputs, verify owner-level recovery, and keep an untouched
       control recording cached.
   * - Failure and report closure
     - Lenient stub failures are injected independently at QC, preprocessing,
       artifacts, ICA fit/label/apply, epochs, covariance, coregistration,
       forward, and source stages. Mixed success, all-failed, and all-QC-
       excluded datasets must still complete every dataset report and the
       corpus report. A strict-mode control must terminate before report
       submission.

MEGNet Model Agreement
----------------------

The retrained-model comparison command is intentionally separate from
``run_ic_label``:

.. code-block:: bash

   python megflow/tools/megnet_retrained/compare_with_mne_megnet.py \
     --raw-file /path/to/preprocessed_raw.fif \
     --ica-file /path/to/ica.fif \
     --ica-sources-file /path/to/ica_sources.fif \
     --output-dir /path/to/model_agreement

``component_comparison.csv`` records both canonical labels, both four-class
probability vectors, and a disagreement flag for every component.
``comparison.json`` records the same predictions, model metadata,
disagreement indices, four-class component agreement, and non-brain artifact
set Jaccard. If both artifact sets are empty, Jaccard is defined as ``1.0``.
These values describe agreement between two models; they are not accuracy
estimates without independently reviewed component labels.

What Stub Tests Do Not Prove
----------------------------

Stub tests validate orchestration, identity, configuration propagation, output
contracts, cache invalidation, and deliberate nonzero process failures. They
run the real Nextflow executable and inspect trace statuses plus created,
deleted, restored, and cached outputs; ``-stub-run`` replaces the expensive
scientific process bodies only. The synthetic MNE/OSL tests validate API
acceptance and local numeric contracts but not whether a parameter is
scientifically appropriate. Mocked source-call tests do not replace a complete
forward/inverse solution on real anatomy. Neither
layer validates vendor-specific readers, actual FreeSurfer/DeepPrep completion,
GPU behavior, identical ICA subspaces between experimental and empty-room
recordings, or scientific suitability of event and inverse-model parameters.

Before a release, run a small real-data smoke set with at least one supported
vendor, one task recording with inspected events, one resting recording, one
raw-covariance pair, and one previously reconstructed anatomy. Run a full
structural reconstruction less frequently on a fixed canary subject and compare
the expected BEM, transform, forward, covariance, source, and report outputs.
Test a Nextflow upgrade separately from a MEGFlow code release; do not silently
replace the production runtime during validation.
