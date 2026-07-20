Quickstart
==========

This page takes you from an MEG dataset to a first quality-control report. You
do not need to understand every configuration field before starting. The
recommended first run stops after ICA cleaning:

.. code-block:: text

   MEG data -> preprocessing -> artifact detection -> ICA cleaning -> QC report

Epochs, covariance, coregistration, and source reconstruction depend on the
study's events, anatomy, and analysis choices. Configure those only after the
first report looks reasonable. See :doc:`Full Workflow
<../tutorial/full_workflow>` for that progression.

Before You Start
----------------

Choose two directories on the computer where Docker is running:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Host path
     - What it contains
   * - ``/path/to/bids_or_raw_meg``
     - Your input MEG dataset. BIDS is recommended, but the default
       configuration can also discover raw FIF files.
   * - ``/path/to/output``
     - The directory where MEGFlow will write results. It may be new or may
       contain an earlier run that you want to resume.

An anatomy directory is not needed for this first ICA run. Add structural MRI
or pseudo-MRI settings later, before source-level analysis.

Understand the Docker Paths
---------------------------

Docker cannot see an arbitrary host directory until ``-v`` mounts it into the
container. Every mount has this form:

.. code-block:: text

   -v HOST_PATH:CONTAINER_PATH

For example, ``-v /path/to/bids_or_raw_meg:/input`` means:

.. list-table::
   :header-rows: 1
   :widths: 35 25 40

   * - Part
     - Where it exists
     - What to do
   * - ``/path/to/bids_or_raw_meg``
     - Your computer
     - Replace it with the real dataset path.
   * - ``/input``
     - Inside the container
     - Keep this fixed alias unless you also update ``-i``.

The same rule applies to output: the host output directory is mounted as the
container alias ``/output``. MEGFlow's ``-i /input`` and ``-o /output`` then
refer to those aliases, not directly to the host paths.

Create writable host-side directories **before** ``docker run``. If a bind-mount
source does not exist, Docker may create it as ``root:root``; after MEGFlow
drops to the dataset owner's user ID, a structural workflow can then fail while
creating a subject under ``/smri``. For a run that mounts both output and
anatomy directories, prepare and check them with:

.. code-block:: bash

   mkdir -p /path/to/output /path/to/smri
   test -w /path/to/output \
     && echo "OK: /path/to/output is writable" \
     || echo "FAILED: /path/to/output is not writable"
   test -w /path/to/smri \
     && echo "OK: /path/to/smri is writable" \
     || echo "FAILED: /path/to/smri is not writable"

The ``test -w`` command is normally silent; the attached messages make its
result visible. Both checks must print ``OK``.
If either check prints ``FAILED``, do not start the container yet. Correct that
directory's host ownership or permissions, then run the checks again.

The first ICA command below does not mount anatomy, so only
``/path/to/output`` is needed. Create ``/path/to/smri`` before later adding
``-v /path/to/smri:/smri`` for anatomy or source-level processing.

Run One Command
---------------

For the first run, replace only the two host paths to the **left** of the
colons. Keep ``/input`` and ``/output`` unchanged:

.. code-block:: bash

   docker run --rm -it \
     -v /path/to/bids_or_raw_meg:/input \
     -v /path/to/output:/output \
     cplmeg/megflow:1.0.0 \
     -i /input \
     -o /output \
     --steps meg_ica \
     --resume

What each part means:

.. list-table::
   :header-rows: 1
   :widths: 27 73

   * - Option
     - Meaning
   * - ``docker run``
     - Start a container from the image named later in the command.
   * - ``--rm``
     - Remove the stopped container. Results remain in the mounted host output
       directory.
   * - ``-it``
     - Keep the terminal interactive so progress and errors are visible.
   * - ``-v``
     - Create a ``HOST_PATH:CONTAINER_PATH`` mapping. Edit the host side.
   * - ``cplmeg/megflow:1.0.0``
     - The MEGFlow image and version.
   * - ``-i``, ``--input``
     - Pass the mounted input alias, here ``/input``, to MEGFlow.
   * - ``-o``, ``--output``
     - Pass the mounted output alias, here ``/output``, to MEGFlow.
   * - ``--steps meg_ica``
     - Import data, preprocess continuously, detect artifacts, fit and label
       ICA, apply ICA, and build the report. It does not run epochs or source
       analysis.
   * - ``--resume``
     - Reuse valid Nextflow work from an earlier run instead of recomputing it.

Worked Example: SMN4Lang
------------------------

Suppose SMN4Lang is stored at ``/path/to/SMN4Lang`` and you want a small first
run for ``sub-02``, task ``RDR``, run ``1``. Download the starter config shown
below, save it as ``/path/to/quickstart.config``, and change its selector block
to:

.. code-block:: groovy

   params {
     megflow {
       datasets {
         docker_input {
           steps = "meg_ica"
           meg_import = [
               subject_id: ["02"],
               session_id: null,
               task: ["RDR"],
               run_id: ["1"],
               raw_include_keywords: null,
               raw_exclude_keywords: null
           ]
         }
       }
     }
   }

BIDS entity values do not include their prefixes in the config: use ``"02"``,
not ``"sub-02"``. Then run:

.. code-block:: bash

   docker run --rm -it \
     -v /path/to/SMN4Lang:/input \
     -v /path/to/SMN4Lang_megflow:/output \
     -v /path/to/quickstart.config:/config/quickstart.config:ro \
     cplmeg/megflow:1.0.0 \
     --config /config/quickstart.config \
     --input /input \
     --output /output \
     --resume

Here ``:ro`` makes the mounted config read-only. The command omits
``--steps`` so ``steps = "meg_ica"`` in the config remains effective. For the
dataset-specific event timing, covariance, anatomy, and source settings required
by a full analysis, continue with :doc:`Running the Full Workflow
<../tutorial/full_workflow>` and the :doc:`configuration examples
<../reference/examples>` after this first pass.

Check the Results
-----------------

When the run finishes, open:

.. code-block:: text

   /path/to/output/static_html_report/index.html

Start with the dataset dashboard. Sort by alarms, bad channels, bad segments,
ICA components, or missing steps, then open a recording's detail page.

.. list-table::
   :header-rows: 1
   :widths: 42 58

   * - Path
     - What to look for
   * - ``<output>/static_html_report/index.html``
     - Main MEGFlow quality-control dashboard.
   * - ``<output>/preprocessed/``
     - Continuous preprocessed data, artifact sidecars, ICA models and cleaned
       files, plus later-stage derivatives when those stages run.
   * - ``<output>/static_html_report/nextflow/report.html``
     - Execution summary, process resource use, and failures.
   * - ``<output>/static_html_report/nextflow/timeline.html``
     - Process timing and concurrency.

Continue with the :doc:`report guide <../tutorial/reports>` to interpret the
dashboard and review pages, the :doc:`complete output guide <../tutorial/outputs>`
for every output directory and important sidecar, and the
:doc:`pipeline details <../details/pipeline_details>` for what each stage does.

Start from ``quickstart.config``
--------------------------------

:download:`Download quickstart.config <../../../nextflow/quickstart.config>`
and keep it with your study. This is a small project **overlay**, not a second
copy of all MEGFlow defaults:

.. literalinclude:: ../../../nextflow/quickstart.config
   :language: groovy
   :caption: nextflow/quickstart.config

The image loads its complete base configuration first and then applies this
file. A field omitted here continues to use the image default. Add or replace
only the blocks your study needs, which keeps your scientific choices visible
and avoids freezing unrelated defaults in a copied file.

The :download:`authoritative Docker defaults <../../../nextflow/nextflow_for_docker.config>`
contain every available base block and value. Use that file for comparison,
then copy only the setting you intend to override into ``quickstart.config``.
The detailed :doc:`configuration overview <../reference/configuration>`
explains how base, dataset, recording, and command-line values are combined.

Mount the overlay and pass its container path with ``--config``. Do not replace
the config bundled inside ``/program/nextflow``:

.. code-block:: bash

   docker run --rm -it \
     -v /path/to/bids_or_raw_meg:/input \
     -v /path/to/output:/output \
     -v /path/to/quickstart.config:/config/quickstart.config:ro \
     cplmeg/megflow:1.0.0 \
     --config /config/quickstart.config \
     --input /input \
     --output /output \
     --resume

An explicit command-line ``--steps`` value overrides the single-dataset
``steps`` value in the overlay for that run.

What Do I Need to Change?
-------------------------

Choose the goal below and add only that change to ``quickstart.config``.

Select Subjects, Sessions, Tasks, or Runs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Edit ``meg_import.subject_id``, ``session_id``, ``task``, and ``run_id``.
Use BIDS values without ``sub-``, ``ses-``, ``task-``, or ``run-`` prefixes.
``subject_id`` accepts these forms:

.. list-table:: ``subject_id`` forms
   :header-rows: 1
   :widths: 28 72

   * - Value
     - Meaning
   * - ``null``
     - Process every discovered subject that matches the other filters.
   * - ``"01"``
     - Process one subject.
   * - ``["01", "02"]``
     - Process exactly the listed subjects.
   * - ``"first:10"``
     - Process up to the first ten subjects returned by BIDS discovery.

Use an explicit list when exact subject membership matters. See the
:ref:`complete subject selection rules <bids-subject-selection>`:

.. code-block:: groovy

   params {
     megflow {
       datasets {
         docker_input {
           meg_import = [
               subject_id: ["01", "02"],
               session_id: ["01"],
               task: ["rest"],
               run_id: null,
               raw_include_keywords: null,
               raw_exclude_keywords: null
           ]
         }
       }
     }
   }

See :doc:`dataset configuration <../reference/configuration_datasets>` for
BIDS selection and non-BIDS filename filters.

Stop at the Stage You Need
~~~~~~~~~~~~~~~~~~~~~~~~~~

Set ``params.megflow.datasets.docker_input.steps`` in the overlay, or pass a
temporary ``--steps`` override on the command line:

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Value
     - Result
   * - ``meg_artifacts``
     - Preprocessing, artifact detection, and report; no ICA.
   * - ``meg_ica``
     - Through ICA fitting, labeling, application, and report. Recommended
       first run.
   * - ``meg_epochs``
     - Through epoch generation and report. Configure events first.
   * - ``anatomy``
     - Structural MRI processing only.
   * - ``meg_all``
     - Complete MEG workflow using already prepared anatomy.
   * - ``all``
     - Anatomy plus the complete MEG workflow.
   * - ``report``
     - Rebuild the static report from existing outputs.

Create Resting-State or Task Epochs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For fixed-length resting-state epochs:

.. code-block:: groovy

   params {
     megflow {
       datasets {
         docker_input {
           steps = "meg_epochs"
           epochs = [
               task_type: "resting",
               resting: [fixed_length_duration: 2.0],
               epochs: [
                   event_id: null,
                   tmin: 0.0,
                   tmax: 2.0,
                   baseline: null,
                   reject_by_annotation: true
               ]
           ]
         }
       }
     }
   }

For task events stored in BIDS ``events.tsv``:

.. code-block:: groovy

   params {
     megflow {
       datasets {
         docker_input {
           steps = "meg_epochs"
           epochs = [
               task_type: "task",
               event_source: "event_file",
               event_time_shift_sec: 0.0,
               event_file: [trial_type: [target: 1, standard: 2]],
               epochs: [
                   event_id: [1, 2],
                   tmin: -0.2,
                   tmax: 0.8,
                   baseline: [null, 0.0],
                   reject_by_annotation: true
               ]
           ]
         }
       }
     }
   }

The labels, event ids, timing shift, window, baseline, and rejection threshold
are study-specific. For trigger-channel events, use
``event_source = "find_events"`` and configure the stimulus channel. See the
epoch section of :doc:`preprocessing configuration
<../reference/configuration_preprocessing>` and the copyable
:doc:`single-dataset examples <../reference/examples_single_dataset>`.

Change Filtering, Notch Frequency, or Sampling Rate
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Replace the continuous ``preproc.steps`` list, preserving operation order:

.. code-block:: groovy

   params {
     megflow {
       datasets {
         docker_input {
           preproc = [
               steps: [
                   [filter: [l_freq: 1.0, h_freq: 100.0, method: "iir",
                             iir_params: [order: 5, ftype: "butter"]]],
                   [notch_filter: [freqs: "60 120"]],
                   [resample: [sfreq: 250]]
               ]
           ]
         }
       }
     }
   }

This example changes line-noise removal to 60/120 Hz. NormMEG-QC uses its own
``megqc.preproc`` reference preprocessing. Keep its 1--100 Hz band-pass and
250 Hz sampling rate unchanged when you need scores comparable with the
normative reference. See :doc:`preprocessing configuration
<../reference/configuration_preprocessing>`.

Turn Artifact Detectors On or Off
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

DeepReject has an explicit ``artifacts.deepreject.enabled`` switch:

.. code-block:: groovy

   params {
     megflow {
       datasets {
         docker_input {
           artifacts = [
               deepreject: [enabled: false]
           ]
         }
       }
     }
   }

Bad-channel and bad-segment methods are enabled by configuration maps rather
than one shared Boolean. Override an inherited method with ``null`` to disable
only that method. For example, disable MNE LOF while keeping the other default
bad-channel detectors:

.. code-block:: groovy

   params {
     megflow {
       datasets {
         docker_input {
           artifacts = [
               find_bad_channels: [
                   mne: [find_bad_channels_lof: null]
               ]
           ]
         }
       }
     }
   }

Likewise, ``pyprep: null``, ``psd: null``, or ``osl: null`` disables that
named bad-channel method, and ``find_bad_segments: [osl: null]`` disables the
default OSL bad-segment method. See :doc:`preprocessing configuration
<../reference/configuration_preprocessing>` and :doc:`DeepReject
<../reference/deepreject>` before changing thresholds or enabling additional
methods.

Control Which ICA Components Are Removed
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Category switches decide whether detected ECG, EOG, or other outlier
components may enter the final automatic exclusion list:

.. code-block:: groovy

   params {
     megflow {
       datasets {
         docker_input {
           ic_label = [
               ic_ecg: true,
               ic_eog: true,
               ic_outlier: false
           ]
         }
       }
     }
   }

Classifier switches such as ``mne_icalabel``, ``megnet_retrained``,
``mne_algorithm``, and ``rules_algorithm`` decide which methods run. A category
must be enabled as well as detected by an enabled method before it is removed.
Review the ICA report before accepting automatic exclusions. See the ICA
section of :doc:`preprocessing configuration
<../reference/configuration_preprocessing>`.

Prepare a Source-Level Run
~~~~~~~~~~~~~~~~~~~~~~~~~~

Do not switch directly from an unchecked dataset to ``meg_all``. First verify
ICA, define events and epochs, choose a covariance strategy, match each MEG
recording to anatomy, inspect coregistration, and then choose the forward and
source settings. The source-method choice itself is configured as:

.. code-block:: groovy

   params {
     megflow {
       datasets {
         docker_input {
           steps = "meg_all"
           source = [
               source_methods: ["dSPM"]
           ]
         }
       }
     }
   }

This snippet is not a complete source-analysis design. Follow :doc:`Full
Workflow <../tutorial/full_workflow>`, then configure covariance, BEM,
coregistration, forward modeling, rank, and source parameters using
:doc:`source configuration <../reference/configuration_source>`.

Rebuild Only the Report
~~~~~~~~~~~~~~~~~~~~~~~

Reuse an existing output mount and run with ``--steps report``. Do not point
``/output`` at an empty directory because report mode reads the derivatives
already present there.

Next Steps
----------

For a new dataset, progress in this order:

.. code-block:: text

   meg_ica -> anatomy (if needed) -> meg_epochs -> meg_all -> report

At each step, inspect the new report before enabling the next dataset-specific
stage. Continue with:

* :doc:`Full Workflow <../tutorial/full_workflow>` for the staged analysis.
* :doc:`report guide <../tutorial/reports>` for QC interpretation.
* :doc:`complete output guide <../tutorial/outputs>` for derivative files.
* :doc:`configuration overview <../reference/configuration>` for every field.
* :doc:`configuration examples <../reference/examples>` for complete study
  patterns.
