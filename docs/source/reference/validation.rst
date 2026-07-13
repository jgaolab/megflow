Validation and Regression Testing
=================================

MEGFlow includes two complementary test layers. Python unit tests exercise
event handling, analysis preprocessing, DeepReject inputs, NMDQ score/report
rendering, source-input resolution, and static configuration contracts.
Nextflow integration tests use ``-stub-run`` to execute the real workflow graph
without starting FreeSurfer, DeepPrep, or numerical MNE processing.

Run the Test Suite
------------------

Set ``MEGFLOW_NEXTFLOW`` to the same Nextflow executable used in production so
the integration suite is enabled:

.. code-block:: bash

   export MEGFLOW_NEXTFLOW="$(command -v nextflow)"
   python -m unittest discover -s tests -p 'test_*.py' -v

Without that variable, the Nextflow integration class is skipped and the
Python/static tests still run. A production release should also parse every
shipped config with the production Nextflow version and build the Sphinx docs
with warnings treated as errors.

The repository CI performs those lightweight checks with Nextflow 24.10.3 on
each pull request and on pushes to the main branch. Keep the version pinned to
the production runtime; evaluate a Nextflow upgrade in a separate change.

Integration Matrix
------------------

The stub suite verifies the following workflow contracts:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Area
     - Covered behavior
   * - Stage selection
     - ``report``, ``anatomy``, ``meg_artifacts``, ``meg_ica``,
       ``meg_epochs``, ``meg_epochs,skip_ica``, ``meg_all``, and ``all``;
       recording-level stage reduction is checked independently.
   * - Structural processing
     - BIDS FreeSurfer, DeepPrep, pseudo-MRI, non-BIDS NIfTI, DICOM conversion,
       and simultaneous anatomy plus MEG are traversed with placeholder outputs
       only; no long reconstruction runs.
   * - Profile isolation
     - Multiple datasets and recording profiles use distinct epoch,
       covariance, forward, and source directories and retain their own
       effective configuration.
   * - Source routing
     - Forward and covariance FIF paths are joined by
       ``[dataset, recording]`` identity. Missing, duplicate, or mismatched
       lineage fails instead of silently dropping source outputs.
   * - Raw covariance
     - Delayed noise branches, recording-specific covariance overrides,
       missing pairs, cross-dataset isolation, and several experimental tasks
       sharing one noise recording are covered.
   * - Validation
     - Unknown match keys, overlapping recording profiles, ineffective
       recording-scope fields, excessive recording stages, duplicate recording
       basenames, and overlapping dataset output trees fail early.
   * - Resume behavior
     - Event edits rerun only event-dependent stages; a newly added raw creates
       only a new branch; changing one raw reruns that recording while another
       remains cached; changing the processing implementation invalidates all
       affected task branches.

What Stub Tests Do Not Prove
----------------------------

Stub tests validate orchestration, identity, configuration propagation, output
contracts, and cache invalidation. They do not validate numerical correctness,
vendor-specific readers, actual FreeSurfer/DeepPrep completion, GPU behavior,
or scientific suitability of event and inverse-model parameters.

Before a release, run a small real-data smoke set with at least one supported
vendor, one task recording with inspected events, one resting recording, one
raw-covariance pair, and one previously reconstructed anatomy. Run a full
structural reconstruction less frequently on a fixed canary subject and compare
the expected BEM, transform, forward, covariance, source, and report outputs.
Test a Nextflow upgrade separately from a MEGFlow code release; do not silently
replace the production runtime during validation.
