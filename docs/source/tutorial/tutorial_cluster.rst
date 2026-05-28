Cluster
========================
If you're using a computing cluster with SLURM as the resource manager, make sure to adjust the nextflow.config file to set the appropriate executor. You can then submit the job using the following command:

**Singularity Convert**

.. code-block:: bash

    container_name=cmrlab/megprep
    version=0.0.3
    singularity build ${container_name}_${version}.sif docker-daemon://${container_name}:${version}

**Run MEGPrep on Slurm**

.. code-block:: bash

    #!/bin/bash

    #SBATCH --job-name=multi
    #SBATCH --partition=cpu1,cpu2,fat

    #SBATCH --nodes=1
    #SBATCH --ntasks=1

    #SBATCH --mem=4G
    #SBATCH --cpus-per-task=4

    #SBATCH --output=%x.%j.out
    #SBATCH --error=%x.%j.err

    nextflow run megprep.nf -c nextflow.config -resume

This command will run the MegPrep pipeline on the cluster while managing resource allocation automatically.


**nextflow.config**

.. code-block:: groovy

    //megprep.slurm.cpu.config

    // Define the working directory for Nextflow
    workDir = "/lustre/grp/gjhlab/liaop/datasets/SMN4Lang/output_dir_v3/work"

    singularity.enabled = true
    singularity.autoMounts = true
    singularity.runOptions = '-e \
        --env NUMBA_CACHE_DIR=/tmp/NUMBA_CACHE_DIR \
        --env MPLCONFIGDIR=/tmp/MPLCONFIGDIR/ \
        --env DISPLAY=99 \
        --env QT_QPA_PLATFORM=xcb \
        --env MESA_GLSL_VERSION_OVERRIDE=150 \
        --env MESA_GL_VERSION_OVERRIDE=3.2 \
        --env XDG_RUNTIME_DIR=/tmp/NUMBA_CACHE_DIR \
        -B /lustre/grp/gjhlab/liaop/ \
        -B /lustre/grp/gjhlab/liaop/datasets/SMN4Lang/smri/ \
        -B /lustre/grp/gjhlab/liaop/license.txt:/fs_license.txt \
    '



    process {

        executor = 'slurm'

        queue = 'cpu1,cpu2,fat'

        clusterOptions = { " --chdir=${workDir}" }

        container = '/lustre/grp/gjhlab/liaop/codes/megprep/megprep_0.0.3.sif'
    }


    // ------------------------------
    // Global Parameters Configuration
    // ------------------------------
    params {
        dataset_dir = "/lustre/grp/gjhlab/liaop/datasets/SMN4Lang" // "/input"   // Input data directory
        output_dir = "/lustre/grp/gjhlab/liaop/datasets/SMN4Lang/output_dir_v3" //"/output" // nextflow logs directory
        preproc_dir = "${params.output_dir}/preprocessed" // Output results directory

        code_dir = "/program/megprep"   // all codes for preprocessing.
        t1_input_type = "nifti"                      // 'dicom' or 'nifti'
        is_bids = true                     // Whether the data is in BIDS format

        do_fs = true
        anatomy_preprocess_method = "deepprep"
        fs_subjects_dir = "/lustre/grp/gjhlab/liaop/datasets/SMN4Lang/smri_v3" //"/smri"

        //deepprep
        deepprep_device = "cpu"
        t1_bids_dir = "${dataset_dir}"
        fs_license = "/lustre/grp/gjhlab/liaop/license.txt"
        ...
