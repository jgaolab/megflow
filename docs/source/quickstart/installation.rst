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

The container installers are standalone files. You do not need to clone the
MEGFlow repository: run the matching command from any writable directory. Set
``MEGFLOW_VERSION`` once to download the installer from the same Git release
and pull the matching ``cplmeg/megflow`` image tag. Use the release number
without a leading ``v``, for example ``1.0.0``.

Direct downloads: `Linux installer
<https://raw.githubusercontent.com/jgaolab/megflow/v1.0.0/scripts/install/install_megflow_linux.sh>`_,
`macOS installer
<https://raw.githubusercontent.com/jgaolab/megflow/v1.0.0/scripts/install/install_megflow_macos.sh>`_,
and `Windows installer
<https://raw.githubusercontent.com/jgaolab/megflow/v1.0.0/scripts/install/install_megflow_windows.ps1>`_.

Linux:

.. code-block:: bash

   MEGFLOW_VERSION=1.0.0 && curl -fL -o install_megflow_linux.sh "https://raw.githubusercontent.com/jgaolab/megflow/v${MEGFLOW_VERSION}/scripts/install/install_megflow_linux.sh" && bash install_megflow_linux.sh "${MEGFLOW_VERSION}"

macOS:

.. code-block:: bash

   MEGFLOW_VERSION=1.0.0 && curl -fL -o install_megflow_macos.sh "https://raw.githubusercontent.com/jgaolab/megflow/v${MEGFLOW_VERSION}/scripts/install/install_megflow_macos.sh" && bash install_megflow_macos.sh "${MEGFLOW_VERSION}"

Windows PowerShell:

.. code-block:: powershell

   $MEGFLOW_VERSION = "1.0.0"; $ErrorActionPreference = "Stop"; Invoke-WebRequest -Uri "https://raw.githubusercontent.com/jgaolab/megflow/v${MEGFLOW_VERSION}/scripts/install/install_megflow_windows.ps1" -OutFile "install_megflow_windows.ps1"; powershell -ExecutionPolicy Bypass -File .\install_megflow_windows.ps1 -ImageTag $MEGFLOW_VERSION

On Linux, the optional second argument selects ``auto`` (default), ``docker``,
``apptainer``, or ``singularity``. For example, force Apptainer with:

.. code-block:: bash

   MEGFLOW_VERSION=1.0.0 && curl -fL -o install_megflow_linux.sh "https://raw.githubusercontent.com/jgaolab/megflow/v${MEGFLOW_VERSION}/scripts/install/install_megflow_linux.sh" && bash install_megflow_linux.sh "${MEGFLOW_VERSION}" apptainer

The first Linux argument is the image tag. The last two runtime names select
the same SIF workflow. In ``auto`` mode, a usable Docker daemon is preferred
and the installer otherwise selects Apptainer/Singularity.

When Apptainer or Singularity is available, it downloads the OCI layers from
``docker://cplmeg/megflow:<version>``, translates them into a local SIF, and
runs the image entrypoint with ``-h``. It does not use a Docker daemon or create
a local Docker image. If neither runtime is installed, package-manager
installation is best-effort because package availability differs among Linux
distributions and HPC sites. Install the runtime through the site's supported
repository first when the automatic attempt is unavailable. See the
`Apptainer Docker/OCI guide
<https://apptainer.org/docs/user/latest/docker_and_oci.html>`_ for details of
the OCI-to-SIF translation.

Run the generated SIF with writable host directories bound to the paths used by
the MEGFlow entrypoint. This example processes MEG through ICA:

.. code-block:: bash

   mkdir -p /data/out

   apptainer run --cleanenv \
     --bind /data/bids:/input \
     --bind /data/out:/output \
     ./megflow_1.0.0.sif \
     -i /input -o /output \
     --steps meg_ica --resume

Use ``singularity run`` instead on a SingularityCE system. A custom MEGFlow
configuration can be added with
``--bind /data/megflow/nextflow.config:/program/nextflow/nextflow.config:ro``.
Bind structural MRI and FreeSurfer license paths in the same way when anatomy or
source processing needs them. The SIF root remains read-only; generated runtime
configuration and Nextflow state are written below the bound ``/output`` path.

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

   MEGFLOW_VERSION=1.0.0 && docker pull "cplmeg/megflow:${MEGFLOW_VERSION}"

Alternative: Local Installation Without Docker
----------------------------------------------

.. important::

   This is a source installation. The installer automatically clones or
   updates the GitHub source under ``~/.megflow-dev/src/megflow`` by default.
   You do not need to clone the repository first or run from its root; download
   and execute the installer from any writable directory. Git and access to
   GitHub are required.

This workflow installs or reuses Conda, Nextflow, FreeSurfer, and MEGFlow source
dependencies in a local installation directory.

.. code-block:: bash

   curl -fL -o install_megflow_dev_linux.sh https://raw.githubusercontent.com/jgaolab/megflow/main/scripts/install-dev/install_megflow_dev_linux.sh && bash install_megflow_dev_linux.sh

After downloading it, rerun ``bash install_megflow_dev_linux.sh`` with options
such as ``--install-dir /data/megflow-dev`` or ``--no-freesurfer`` when needed.

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

Before binding writable host directories, create them as the user who will run
MEGFlow. This is especially important for the structural ``/smri`` mount:

.. code-block:: bash

   mkdir -p /data/out /data/smri
   test -w /data/out
   test -w /data/smri

If a bind-mount source is missing, Docker may create the host directory as
``root:root``. MEGFlow prepares the ``/output`` mount at startup, but a
root-owned ``/smri`` can remain unwritable after the container drops to the
host UID/GID and cause anatomy processing to fail. Correct host ownership or
permissions before rerunning if either write check fails.

.. code-block:: text

   Usage: /program/nextflow/run.sh [options]
   Options:
     -c, --config          Project configuration file
     -i, --input           MEG dataset or corpus input directory
     -o, --output          MEGFlow output directory
     -s, --steps           Pipeline stage override, for example all or meg_all
     --anat-method         Anatomy method: freesurfer, deepprep, or pseudomri
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
Use ``--anat-method deepprep`` to override the configured structural method for
one Docker run. The accepted values are ``freesurfer``, ``deepprep``, and
``pseudomri``. When the option is omitted, the configured ``anatomy.method``
remains effective. In corpus mode the option changes the shared default while
an explicit method in a named dataset profile remains authoritative.
The entrypoint maps ``--fs_license_file`` into the effective
``anatomy.fs_license_file`` setting. In ``--corpus`` mode it also preserves
named dataset profiles from the mounted config, including dataset-specific
processing blocks and ``dataset_include`` / ``dataset_exclude`` filters.

In single-dataset mode, ``--t1_dir`` explicitly overrides
``datasets.docker_input.t1_dir``. When it is omitted, the entrypoint preserves
the configured value and MEGFlow ultimately falls back to the dataset input
directory. ``--t1_dir`` is rejected with ``--corpus`` because each corpus
dataset can have a different MRI root; set ``t1_dir`` in each named profile.

Other scientific and report behavior is configured only in ``params.megflow``.
Set ``anatomy.t1_input_type``, ``anatomy.t1_dicom_series_glob``,
``report.static_task_log_mode``, and
``report.static_artifact_overview_duration`` under shared defaults or the
matching dataset profile. This keeps the effective values reviewable in the
saved runtime config and allows heterogeneous corpus datasets to differ.
