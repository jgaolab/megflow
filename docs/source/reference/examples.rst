.. _configuration-examples:

Configuration Examples
======================

MEGFlow uses one layered configuration schema for a single dataset, multiple
datasets, and recording-specific behavior. Start from a complete base config and
override only the values that differ for the study.

Example Sequence
----------------

Start with the single-dataset page for first-pass QC, anatomy, epochs,
covariance, and source reconstruction. Use the second page for recording
overrides, heterogeneous corpora, source-mode demos, and cluster execution.

1. :doc:`examples_single_dataset`: first MEG pass, anatomy, events, covariance,
   source reconstruction, and Maxwell/tSSS.
2. :doc:`examples_profiles`: per-dataset and per-recording overrides, corpus
   execution, the runnable multi-dataset demo, and cluster launch.

.. toctree::
   :maxdepth: 1

   examples_single_dataset
   examples_profiles

.. _example-canonical-templates:

Canonical Templates
-------------------

Use one of these repository files as the base:

* :download:`quickstart.config <../../../nextflow/quickstart.config>` is the
  recommended first Docker project overlay. It selects all discovered MEG
  recordings and stops at ICA; add only study-specific overrides.
* :download:`nextflow_for_docker.config
  <../../../nextflow/nextflow_for_docker.config>` contains the authoritative
  paths and defaults for the distributed container.
* `nextflow.config on GitHub
  <https://github.com/jgaolab/megflow/blob/main/nextflow/nextflow.config>`__
  contains the source-run defaults and execution profiles. It is a deployment
  config, so replace its site paths before using it elsewhere.
* `nextflow_multi_dataset_demo.config on GitHub
  <https://github.com/jgaolab/megflow/blob/main/nextflow/nextflow_multi_dataset_demo.config>`__
  is a complete source-run example for WAND, SMN4Lang, and MEG-MASC. Its data,
  output, and code paths are site-specific.
* `nextflow_maxwell_tsss_example.config on GitHub
  <https://github.com/jgaolab/megflow/blob/main/nextflow/nextflow_maxwell_tsss_example.config>`__
  demonstrates
  MEGIN/Elekta Maxwell filtering and tSSS at default, dataset, and recording
  configuration levels without enabling it in the shared defaults.

For Docker, a small project config contains only study-specific overrides. The
entrypoint automatically loads the full config already present inside the image
before applying this file with Nextflow ``-c``:

.. code-block:: groovy

   // Project-specific overrides start immediately.
   params.megflow.defaults.steps = "meg_ica"

Mount that overlay at a container path such as ``/config/project.config`` and
pass the path through ``--config``. This keeps the project file visibly
separate from the defaults bundled with the image. For a source run, either
copy ``nextflow/nextflow.config`` and edit it or include it with a path that is
valid from the project config's location.
