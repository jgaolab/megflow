MEGPrep Documentation
=====================

`MEGPrep <https://github.com/LiaoPan/megprep>`_ is a reproducible Nextflow
pipeline for large-scale MEG preprocessing, built on MNE-Python and designed
for containerized local, cluster, and cohort-scale workflows.

It provides configurable continuous preprocessing, automated artifact
detection, ICA-based cleaning, task or resting-state epoching, MEG-MRI
coregistration, source reconstruction, and static quality-control reports.

.. grid:: 1 1 2 4
   :gutter: 2
   :class-container: megprep-home-links

   .. grid-item-card:: :material-regular:`rocket_launch;1.4em` Install
      :link: quickstart/installation.html
      :class-card: megprep-nav-card

      Container, Apptainer/Singularity, and local source installation paths.

   .. grid-item-card:: :material-regular:`bolt;1.4em` Quickstart
      :link: quickstart/quick_guide.html
      :class-card: megprep-nav-card

      Run your first dataset with default settings and inspect the report.

   .. grid-item-card:: :material-regular:`account_tree;1.4em` Workflow
      :link: details/pipeline_details.html
      :class-card: megprep-nav-card

      Step-by-step execution order, branch conditions, inputs, and outputs.

   .. grid-item-card:: :material-regular:`settings;1.4em` Config
      :link: reference/configuration.html
      :class-card: megprep-nav-card

      Formal ``nextflow.config`` reference with parameter meanings and defaults.

Core Capabilities
-----------------

.. grid:: 1 1 2 3
   :gutter: 2
   :class-container: megprep-feature-grid

   .. grid-item-card:: Reproducible Execution
      :class-card: megprep-feature-card

      Docker and Apptainer/Singularity workflows keep runtime environments
      consistent across workstations, servers, and clusters.

   .. grid-item-card:: Configurable Preprocessing
      :class-card: megprep-feature-card

      Filtering, notch filtering, resampling, Maxwell filtering, artifact
      detection, ICA, epoching, and source settings are configured in one file.

   .. grid-item-card:: Automated QC
      :class-card: megprep-feature-card

      Bad channels, bad segments, ICA components, coregistration distances,
      epoch rejection, and workflow completeness are summarized for review.

   .. grid-item-card:: Task and Resting Data
      :class-card: megprep-feature-card

      The continuous preprocessing core is task independent, while optional
      epoching supports fixed-length resting windows, trigger events, or BIDS
      event files.

   .. grid-item-card:: Anatomy and Source Modeling
      :class-card: megprep-feature-card

      FreeSurfer or DeepPrep outputs can be reused or generated before BEM,
      coregistration, forward modeling, and source reconstruction.

   .. grid-item-card:: Portable Reports
      :class-card: megprep-feature-card

      Static HTML reports bundle subject pages, figures, sidecars, CSV files,
      JSON summaries, workflow metadata, and the effective config snapshot.

Where to Go Next
----------------

.. grid:: 1 1 2 4
   :gutter: 2
   :class-container: megprep-next-grid

   .. grid-item-card:: Run Locally
      :link: tutorial/tutorial_local.html
      :class-card: megprep-next-card

      Docker command structure, mounts, and common runtime options.

   .. grid-item-card:: Run on a Cluster
      :link: tutorial/tutorial_cluster.html
      :class-card: megprep-next-card

      SLURM and Singularity/Apptainer execution notes.

   .. grid-item-card:: Full Workflow
      :link: tutorial/full_workflow.html
      :class-card: megprep-next-card

      Anatomy, epochs, covariance, coregistration, and source-level runs.

   .. grid-item-card:: Read QC Metrics
      :link: reference/qc_metrics.html
      :class-card: megprep-next-card

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
   reference/qc_metrics.rst
   reference/examples.rst
