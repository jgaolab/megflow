MEGFlow Documentation
=====================

`MEGFlow <https://github.com/jgaolab/megflow>`_ is a reproducible Nextflow
pipeline for large-scale MEG preprocessing, built on MNE-Python and designed
for containerized local, cluster, and corpus-scale workflows.

It provides configurable continuous preprocessing, automated artifact
detection, ICA-based cleaning, task or resting-state epoching, MEG-MRI
coregistration, source reconstruction, and static quality-control reports.

.. grid:: 1 1 2 4
   :gutter: 2
   :class-container: megflow-home-links

   .. grid-item-card:: :material-regular:`rocket_launch;1.4em` Install
      :link: quickstart/installation.html
      :class-card: megflow-nav-card

      Container, Apptainer/Singularity, and local source installation paths.

   .. grid-item-card:: :material-regular:`bolt;1.4em` Quickstart
      :link: quickstart/quick_guide.html
      :class-card: megflow-nav-card

      Run your first dataset with default settings and inspect the report.

   .. grid-item-card:: :material-regular:`account_tree;1.4em` Workflow
      :link: details/pipeline_details.html
      :class-card: megflow-nav-card

      Step-by-step execution order, branch conditions, inputs, and outputs.

   .. grid-item-card:: :material-regular:`settings;1.4em` Config
      :link: reference/configuration.html
      :class-card: megflow-nav-card

      Formal ``nextflow.config`` reference with parameter meanings and defaults.

Core Capabilities
-----------------

.. grid:: 1 1 2 3
   :gutter: 2
   :class-container: megflow-feature-grid

   .. grid-item-card:: Reproducible Execution
      :class-card: megflow-feature-card

      Docker and Apptainer/Singularity workflows keep runtime environments
      consistent across workstations, servers, and clusters.

   .. grid-item-card:: Configurable Preprocessing
      :class-card: megflow-feature-card

      Filtering, notch filtering, resampling, Maxwell filtering, artifact
      detection, ICA, epoching, and source settings are configured in one file.

   .. grid-item-card:: Automated QC
      :class-card: megflow-feature-card

      Bad channels, bad segments, ICA components, coregistration distances,
      epoch rejection, NormMEG-QC outputs, and workflow completeness are
      summarized for review.

   .. grid-item-card:: Task and Resting Data
      :class-card: megflow-feature-card

      The continuous preprocessing core is task independent, while optional
      epoching supports fixed-length resting windows, trigger events, or BIDS
      event files.

   .. grid-item-card:: Anatomy and Source Modeling
      :class-card: megflow-feature-card

      FreeSurfer or DeepPrep outputs can be reused or generated before BEM,
      coregistration, forward modeling, and source reconstruction.

   .. grid-item-card:: Portable Reports
      :class-card: megflow-feature-card

      Static HTML reports bundle subject pages, figures, sidecars, CSV files,
      JSON summaries, workflow metadata, and the effective config snapshot.

Report Preview
--------------

MEGFlow reports are designed to support dataset-level triage first, then
subject-level review and interactive edits when needed. See
:doc:`tutorial/reports` for the full static and interactive report tour.

.. grid:: 1 1 2 2
   :gutter: 2
   :class-container: megflow-screenshot-grid

   .. grid-item-card:: Dataset dashboard
      :link: tutorial/reports.html
      :class-card: megflow-screenshot-card

      .. image:: _static/static_reports/megflow_dataset_overview.png
         :alt: Dataset-level MEGFlow static report dashboard.
         :class: megflow-card-image

      Aggregate NMDQ scores, bad-channel and bad-segment counts,
      coregistration metrics, epoch rejection, and alarm totals.

   .. grid-item-card:: Workflow provenance
      :link: tutorial/reports.html
      :class-card: megflow-screenshot-card

      .. image:: _static/static_reports/megflow_workflow.png
         :alt: MEGFlow workflow diagram in the static report.
         :class: megflow-card-image

      The selected ``steps`` mode is rendered as a stage diagram from the run
      manifest and effective configuration.

Where to Go Next
----------------

.. grid:: 1 1 2 4
   :gutter: 2
   :class-container: megflow-next-grid

   .. grid-item-card:: Run Locally
      :link: tutorial/tutorial_local.html
      :class-card: megflow-next-card

      Docker command structure, mounts, and common runtime options.

   .. grid-item-card:: Run on a Cluster
      :link: tutorial/tutorial_cluster.html
      :class-card: megflow-next-card

      SLURM and Singularity/Apptainer execution notes.

   .. grid-item-card:: Full Workflow
      :link: tutorial/full_workflow.html
      :class-card: megflow-next-card

      Anatomy, epochs, covariance, coregistration, and source-level runs.

   .. grid-item-card:: Read QC Metrics
      :link: reference/qc_metrics.html
      :class-card: megflow-next-card

      How report metrics are computed and how to interpret alarms.

.. toctree::
   :hidden:
   :maxdepth: 2
   :caption: Quickstart

   quickstart/installation
   quickstart/quick_guide.rst
   tutorial/full_workflow.rst

.. toctree::
   :hidden:
   :maxdepth: 2
   :caption: Tutorials

   tutorial/tutorial_local.rst
   tutorial/tutorial_cluster.rst
   tutorial/reports.rst
   tutorial/outputs.rst

.. toctree::
   :hidden:
   :maxdepth: 2
   :caption: Pipeline Details

   details/pipeline_details.rst

.. toctree::
   :hidden:
   :maxdepth: 2
   :caption: Reference

   reference/configuration.rst
   reference/rank_covariance.rst
   reference/deepreject.rst
   reference/qc_metrics.rst
   reference/examples.rst
   reference/opm_conversion.rst
   reference/validation.rst
