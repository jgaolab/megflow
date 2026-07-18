Installation
============

MEGFlow is officially distributed as a container image. The containerized
workflow is recommended because it provides the most reproducible runtime and
avoids most local dependency conflicts.

If Docker cannot be installed, the Docker daemon is unavailable, or the image
cannot be pulled in your network environment, use the local development
installation workflow. The local workflow installs MEGFlow from source and can
run without a Docker image, but local system libraries and package versions may
affect reproducibility.

Recommended: Containerized One-Click Install
--------------------------------------------

The scripts under ``scripts/install/`` install or reuse a container runtime,
pull ``cplmeg/megflow:<version>``, and verify the installation by running the
MEGFlow help command.

Linux:

.. code-block:: bash

   bash scripts/install/install_megflow_linux.sh
   bash scripts/install/install_megflow_linux.sh 1.0.0

macOS:

.. code-block:: bash

   bash scripts/install/install_megflow_macos.sh
   bash scripts/install/install_megflow_macos.sh 1.0.0

Windows PowerShell:

.. code-block:: powershell

   powershell -ExecutionPolicy Bypass -File .\scripts\install\install_megflow_windows.ps1
   powershell -ExecutionPolicy Bypass -File .\scripts\install\install_megflow_windows.ps1 -ImageTag 1.0.0

On Linux, the installer can use Docker or Apptainer/Singularity:

.. code-block:: bash

   bash scripts/install/install_megflow_linux.sh 1.0.0 docker
   bash scripts/install/install_megflow_linux.sh 1.0.0 apptainer

The first Linux argument is the image tag and the optional second argument is
``auto``, ``docker``, or ``apptainer``. With no arguments, the installer uses
``latest`` and ``auto``; with only ``1.0.0``, runtime selection remains
automatic. In ``auto`` mode, a usable Docker daemon is preferred and the
installer otherwise selects Apptainer/Singularity.

When Apptainer or Singularity is already available, the installer pulls a SIF
from ``docker://cplmeg/megflow:<version>`` and runs the image entrypoint with
``-h``. If neither runtime is installed, package-manager installation is
best-effort because package availability differs among Linux distributions and
HPC sites. Install the runtime through the site's supported repository first
when the automatic attempt is unavailable.

See ``scripts/install/README.md`` for installer options and troubleshooting.

Manual Docker Installation
--------------------------

Install Docker according to your operating system. For detailed installation
instructions, visit the `Docker official website <https://docs.docker.com/get-docker/>`_.

Check Docker:

.. code-block:: bash

   docker info

Pull the MEGFlow image:

.. code-block:: bash

   docker pull cplmeg/megflow:<version>

Replace ``<version>`` with a release tag such as ``1.0.0`` or ``latest``.

Alternative: Local Installation Without Docker
----------------------------------------------

The scripts under ``scripts/install-dev/`` provide a source-based local
installation path for Linux environments where container installation is not
available or image pulling is blocked. This workflow installs or reuses Conda,
Nextflow, FreeSurfer, and MEGFlow source dependencies in a local installation
directory.

.. code-block:: bash

   bash scripts/install-dev/install_megflow_dev_linux.sh
   bash scripts/install-dev/install_megflow_dev_linux.sh --install-dir /data/megflow-dev
   bash scripts/install-dev/install_megflow_dev_linux.sh --no-freesurfer

After installation, load the generated environment:

.. code-block:: bash

   source <install-dir>/env.sh

See ``scripts/install-dev/README.md`` for the full local installation workflow.

Docker Entry Point Options
--------------------------

Use ``--steps`` as the primary way to choose the pipeline stage. For example,
use ``--steps anatomy`` for structural MRI only and ``--steps meg_all`` for the
full MEG workflow with existing anatomy.

.. code-block:: bash

   docker run --rm -it cplmeg/megflow:<version> -h

Docker runs do not require Docker's ``--user`` flag. The container entrypoint
prepares mounted output permissions, then drops to the host UID/GID inferred
from ``/input`` before running Nextflow. Report-only runs that only mount
``/output`` infer ownership from ``/output``. If that inference is not
appropriate, pass ``-e LOCAL_UID="$(id -u)" -e LOCAL_GID="$(id -g)"`` to choose
the output owner explicitly.

.. code-block:: text

   Usage: /program/nextflow/run.sh [options]
   Options:
     -c, --config          Project configuration file
     -i, --input           MEG dataset or corpus input directory
     -o, --output          MEGFlow output directory
     -s, --steps           Pipeline stage override, for example all or meg_all
     -r, --view-report     Run Streamlit to view the report and do not run Nextflow
     --corpus              Process immediate input children as separate datasets
     --fs_license_file     FreeSurfer license path inside the container
     --fs_subjects_dir     FreeSurfer SUBJECTS_DIR inside the container
     --t1_dir              Single-dataset structural MRI input root
     --resume              Resume the previous Nextflow execution
     -h, --help             Show this help message

Common ``--steps`` values are ``meg_all`` for full MEG processing with existing
anatomy, ``all`` for anatomy plus full MEG, ``anatomy`` for structural MRI only,
and ``report`` for static report regeneration. See
:doc:`../reference/configuration` for all modes and modifiers.
The entrypoint maps ``--fs_license_file`` into the effective
``anatomy.fs_license_file`` setting. In ``--corpus`` mode it also preserves
named dataset profiles from the mounted config, including dataset-specific
processing blocks and ``dataset_include`` / ``dataset_exclude`` filters.

In single-dataset mode, ``--t1_dir`` explicitly overrides
``datasets.docker_input.t1_dir``. When it is omitted, the entrypoint preserves
the configured value and MEGFlow ultimately falls back to the dataset input
directory. ``--t1_dir`` is rejected with ``--corpus`` because each corpus
dataset can have a different MRI root; set ``t1_dir`` in each named profile.

Scientific and report behavior is configured only in ``params.megflow``.
Set ``anatomy.method``, ``anatomy.t1_input_type``,
``anatomy.t1_dicom_series_glob``, ``report.static_task_log_mode``, and
``report.static_artifact_overview_duration`` under shared defaults or the
matching dataset profile. This keeps the effective values reviewable in the
saved runtime config and allows heterogeneous corpus datasets to differ.
