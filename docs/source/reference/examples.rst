Configuration Examples
======================

These examples show the parts of ``nextflow.config`` that are most commonly
changed between studies. Keep the global path settings, container settings, and
cluster settings consistent with your local environment.

Full MEG Preprocessing with Existing Anatomy
--------------------------------------------

Use this when ``fs_subjects_dir`` already contains FreeSurfer or DeepPrep
reconstructions for the MEG subjects.

.. code-block:: groovy

   params {
       dataset_dir = "/input"
       output_dir = "/output"
       preproc_dir = "${params.output_dir}/preprocessed"
       fs_subjects_dir = "/smri"
       steps = "meg_all"

       dataset_format = "auto"
       meg_import_config = """
       subject_id: null
       session_id: null
       task: null
       run_id: null
       """

       preproc_config = """
       preproc:
         - filter: {l_freq: 0.5, h_freq: 125, method: iir, iir_params: {order: 5, ftype: butter}}
         - notch_filter: {freqs: 50 100}
         - resample: {sfreq: 250}
       """
   }

Structural MRI and MEG in One Run
---------------------------------

Use ``steps = "all"`` when MEGPrep should run anatomical reconstruction before
the full MEG pipeline.

.. code-block:: groovy

   params {
       steps = "all"
       is_bids = true
       anatomy_preprocess_method = "freesurfer"
       t1_dir = "/input"
       fs_subjects_dir = "/smri"
       fs_license = "/fs_license.txt"

       mri_import_config = """
       subject_id: null
       session_id: null
       task: null
       run_id: null
       """
   }

Resting-State MEG
-----------------

For resting-state recordings, the continuous preprocessing and ICA stages are
unchanged. The epoching stage creates fixed-length epochs from the cleaned raw
recording.

.. code-block:: groovy

   params {
       steps = "meg_epochs"

       epoch_config = """
       task_type: resting
       resting:
         fixed_length_duration: 2.0
       event_source: find_events
       autoreject: false
       interpolate_bads: false
       drop_bad_channels: false
       exclude_event_id:
         - 255
       epochs:
         event_id: null
         tmin: 0.0
         tmax: 2.0
         reject_by_annotation: true
         picks: meg
         baseline: null
         preload: true
         detrend: null
       """
   }

Task-Based MEG with Trigger Channel Events
------------------------------------------

Use this when events can be recovered from a stimulus channel with
``mne.find_events``.

.. code-block:: groovy

   params {
       steps = "meg_epochs"

       meg_import_config = """
       subject_id:
         - "01"
         - "02"
       session_id: null
       task:
         - aef
       run_id: null
       """

       epoch_config = """
       task_type: task
       event_source: find_events
       autoreject: false
       find_events:
         stim_channel: null
         shortest_event: 1
         min_duration: 0.0
       epochs:
         event_id: null
         tmin: -0.2
         tmax: 0.8
         reject_by_annotation: true
         picks: meg
         baseline: null
         reject:
           mag: 4e-12
         preload: true
         detrend: null
       """
   }

Task-Based MEG with BIDS Events
-------------------------------

Use ``event_source = "event_file"`` when trial definitions should come from
``*_events.tsv`` files.

.. code-block:: groovy

   params {
       epoch_config = """
       task_type: task
       event_source: event_file
       autoreject: false
       event_file:
         trial_type:
           word_onset_01: 1
           phoneme_onset_01: 2
       epochs:
         event_id: null
         tmin: -0.2
         tmax: 1.0
         reject_by_annotation: true
         picks: meg
         baseline: null
         preload: true
         detrend: null
       """
   }

Empty-Room Style Covariance
---------------------------

MEGPrep currently handles empty-room or noise recordings through
``covar_type = "raw"`` and ``raw_covariance_task_id``. The workflow pairs each
experimental recording with a raw recording whose filename has the same BIDS
entities except for the task label.

.. code-block:: groovy

   params {
       steps = "meg_all"
       covar_type = "raw"
       raw_covariance_task_id = "emptyroom"

       covar_config = """
       compute_raw_covariance:
         tmin: 0
         tmax: null
         method: auto
         reject:
           mag: 4e-12
         reject_by_annotation: true
         rank: info
       """
   }

If a dataset contains empty-room files that should not be imported as ordinary
experimental recordings in raw discovery mode, exclude them during import and
use a BIDS-style or task-specific layout for covariance pairing.

.. code-block:: yaml

   raw_include_keywords:
     - task-rest
   raw_exclude_keywords:
     - phantom
     - crosstalk

For CTF raw folders, set ``file_suffix = ".ds"``. For BTI/4D folders whose
primary data file is named ``c,rfDC``, set ``file_suffix = "c,rfDC"``.

Report-Only Run
---------------

Use ``report`` to rebuild the static HTML report without re-running MEG or MRI
processing.

.. code-block:: bash

   docker run -it --rm \
     -v /data/bids:/input \
     -v /data/out:/output \
     -v /data/smri:/smri \
     cmrlab/megprep:0.0.3 \
     -i /input -o /output --fs_subjects_dir /smri --steps report

Docker End-to-End Example
-------------------------

.. code-block:: bash

   docker run -it --rm \
     -v /data/bids:/input \
     -v /data/out:/output \
     -v /data/smri:/smri \
     -v /data/license.txt:/fs_license.txt \
     -v /data/nextflow.config:/program/nextflow/nextflow.config \
     cmrlab/megprep:0.0.3 \
     -i /input \
     -o /output \
     --fs_license_file /fs_license.txt \
     --fs_subjects_dir /smri \
     --steps meg_all \
     --resume

Cluster Example
---------------

On a SLURM cluster, use a Nextflow config profile or process block to select the
SLURM executor and container runtime. The important MEGPrep parameters stay the
same.

.. code-block:: groovy

   workDir = "/scratch/project/megprep_work"

   singularity.enabled = true
   singularity.autoMounts = true

   process {
       executor = "slurm"
       queue = "general"
       cpus = 4
       memory = "16 GB"
       container = "/containers/megprep_0.0.3.sif"
   }

   params {
       dataset_dir = "/project/study/bids"
       output_dir = "/project/study/derivatives/megprep"
       fs_subjects_dir = "/project/study/derivatives/smri"
       steps = "meg_all"
   }
