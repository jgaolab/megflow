Local
========================

Run MEGFlow
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The example below runs the default full MEG workflow with an existing
FreeSurfer/DeepPrep ``SUBJECTS_DIR``. Add ``--steps all`` if structural MRI
processing should run in the same command.

.. code-block:: bash

    docker run --rm -it \
        -v /data/datasets/SMN4Lang:/input \
        -v /data/datasets/SMN4Lang/megflow_out:/output \
        -v /data/datasets/SMN4Lang/smri:/smri \
        -v /data/megflow/license.txt:/fs_license.txt \
        -v /data/nextflow.config:/program/nextflow/nextflow.config \
        cmrlab/megflow:1.0.0 \
        -i /input \
        -o /output \
        --fs_license_file /fs_license.txt \
        --fs_subjects_dir /smri \
        --steps meg_all \
        --resume

In this command:


+ ``-it``
   Run in interactive mode, allowing users to interact within the container.  

+ ``--rm``
   This option automatically removes the container after it exits, ensuring no residual containers remain.

+ Output ownership
   The container entrypoint starts as root only long enough to prepare mounted
   output permissions, then runs Nextflow as the host UID/GID inferred from
   ``/input``. Report-only runs that only mount ``/output`` infer ownership
   from ``/output`` instead. You do not need Docker's ``--user`` flag or a
   pre-created output directory. If neither mount has the desired output owner,
   add ``-e LOCAL_UID="$(id -u)" -e LOCAL_GID="$(id -g)"`` to the
   ``docker run`` command.

+ ``-v /data/datasets/SMN4Lang:/input``
   This option creates a volume mount, mapping the host directory `/data/datasets/SMN4Lang` to the container's `/input` directory, allowing the container to access input data.

+ ``-v /data/datasets/SMN4Lang/megflow_out:/output``
   This maps the output directory in the host to the container's `/output` directory for saving processed data.

+ ``-v /data/datasets/SMN4Lang/smri:/smri``
   This mounts a directory containing SMRI data(T1w, Freesurfer's SUBJECTS_DIR) to the container's `/smri` directory for application use.

+ ``-v /data/megflow/license.txt:/fs_license.txt``  
   This mounts the FreeSurfer license file into the container, ensuring it has access to the necessary permissions.  

+ ``-v /data/nextflow.config:/program/nextflow/nextflow.config``
   This mounts the Nextflow configuration file so the program inside the container can use it.  

+ ``cmrlab/megflow:1.0.0``  
    This specifies the Docker image and version to run, where `megflow` is the image name, and `1.0.0` is the version.  

+ ``-i /input``  
    This is a parameter passed to the program, specifying the input data directory as `/input`.  

+ ``-o /output``  
    This parameter specifies the output data directory as `/output`.  

+ ``--fs_license_file /fs_license.txt``  
    This passes the path to the FreeSurfer license file to the program, ensuring it can be recognized correctly.  

+ ``--fs_subjects_dir /smri``
    This specifies the separate SMRI data directory for use by the program.

+ ``--steps meg_all``
    This selects full MEG processing using the existing anatomy in
    ``/smri``. See :doc:`../reference/configuration` for all stage options.

+ ``--resume``
    This flag allows the process to resume execution from the last completed step, which is useful for long-running tasks to avoid re-running completed steps.
