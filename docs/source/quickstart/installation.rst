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
pull ``cmrlab/megflow:<version>``, and verify the installation by running the
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
from ``docker://cmrlab/megflow:<version>`` and runs the image entrypoint with
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

   docker pull cmrlab/megflow:<version>

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

   docker run --rm -it cmrlab/megflow:<version> -h

Docker runs do not require Docker's ``--user`` flag. The container entrypoint
prepares mounted output permissions, then drops to the host UID/GID inferred
from ``/input`` before running Nextflow. Report-only runs that only mount
``/output`` infer ownership from ``/output``. If that inference is not
appropriate, pass ``-e LOCAL_UID="$(id -u)" -e LOCAL_GID="$(id -g)"`` to choose
the output owner explicitly.

.. code-block:: text

   Usage: /program/nextflow/run.sh [options]
   Options:
     -c, --config          Specify the Nextflow config file
     -i, --input           Specify the input directory
     -o, --output          Specify the output directory including report results
     -s, --steps           Pipeline mode, for example all, meg_all, anatomy, report
     -r, --view-report     Run Streamlit to view the report and do not run Nextflow
     --corpus              Treat input children as datasets and preserve named profiles
     --static_task_log_mode failed|all-command-log|none
     --static_artifact_overview_duration Seconds shown by the artifact overview
     --fs_license_file     Specify the FreeSurfer license file
     --fs_subjects_dir     Specify the FreeSurfer SUBJECTS_DIR directory
     --t1_dir              Single-dataset structural MRI input root (defaults to --input)
     --t1_input_type       nifti|dicom for non-BIDS FreeSurfer input
     --t1_dicom_series_glob Quoted relative glob below each non-BIDS T1 DICOM root
     --anatomy_preprocess_method freesurfer|deepprep|pseudomri
     --resume              Resume the previous run

Common ``--steps`` values are ``meg_all`` for full MEG processing with existing
anatomy, ``all`` for anatomy plus full MEG, ``anatomy`` for structural MRI only,
and ``report`` for static report regeneration. See
:doc:`../reference/configuration` for all modes and modifiers.
``--static_task_log_mode`` controls whether the static report bundles only
failed task logs, successful ``.command.log`` files as well, or no command
logs. The entrypoint maps ``--fs_license_file`` into the effective
``anatomy.fs_license_file`` setting. In ``--corpus`` mode it also preserves
named dataset profiles from the mounted config, including dataset-specific
processing blocks and ``dataset_include`` / ``dataset_exclude`` filters.

The structural MRI options have explicit scopes. In single-dataset mode,
``--t1_dir`` sets ``datasets.docker_input.t1_dir`` and defaults to ``--input``
when omitted. It is rejected with ``--corpus`` because each corpus dataset can
have a different MRI root; set ``t1_dir`` in the corresponding named dataset
profile instead. In corpus mode, ``--t1_input_type``,
``--t1_dicom_series_glob``, and ``--anatomy_preprocess_method`` become shared
defaults, while an explicit dataset profile still takes precedence.

``--t1_input_type`` and ``--t1_dicom_series_glob`` apply only to non-BIDS
FreeSurfer processing (``anatomy.method = "freesurfer"`` and
``anatomy.is_bids = false``). The input type must be ``nifti`` or ``dicom``.
The series selector must be relative to each DICOM root; quote the value so the
host shell does not expand it, for example
``--t1_dicom_series_glob '*mprage*'``. DeepPrep requires BIDS anatomy and does
not use these two non-BIDS selectors. See :doc:`../reference/configuration`
for the complete Docker-to-profile mapping.
