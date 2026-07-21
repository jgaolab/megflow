OPM Data Conversion
===================

MEGFlow provides a vendor-neutral demonstration for converting standardized
OPM-MEG data into an MNE-Python FIF recording. This is a data-preparation
utility that runs before MEGFlow input discovery; it is not a Nextflow process
and does not belong to the ``nextflow.config`` configuration hierarchy.

Use the converter when an OPM dataset has been exported as a numerical MEG
matrix with separate sensor and event metadata. If the acquisition software
already produces an MNE-readable recording with complete channel geometry and
events, this conversion step can be skipped.

Code and Example Data
---------------------

* The `OPM conversion example directory on GitHub
  <https://github.com/jgaolab/megflow/tree/main/examples/opm_conversion>`__
  contains the converter, dependency list, full input-format reference, and
  executable validation scripts.
* The `MEGFlow OSF archive
  <https://doi.org/10.17605/OSF.IO/QE93S>`__ contains the corresponding OPM
  example inputs. Download ``opm-examples.7z`` and extract it into the
  ``examples/opm_conversion`` directory before running the demos.

Expected Inputs
---------------

The converter combines the following standardized inputs:

* A channel-by-sample MEG matrix in ``.npy``, ``.npz``, ``.mat``, ``.csv``,
  ``.tsv``, or ``.txt`` format. The sampling frequency and physical unit must
  be supplied explicitly.
* A ``.tsv`` or ``.csv`` sensor table whose row order matches the matrix. Each
  row defines the channel name, three-dimensional position, measurement
  direction, position unit, and good/bad status.
* An event table or sparse trigger-change table. The converter creates a
  standard ``STI101`` stimulus channel so that events can be recovered with
  `MNE-Python's mne.find_events
  <https://mne.tools/stable/generated/mne.find_events.html>`_.
* Optionally, an optical-scan ``.ply`` file and fiducial table for preserving
  digitization and headshape information.

The output uses Tesla for MEG values, point-magnetometer channel metadata, and
finite MNE ``loc`` fields containing sensor position and orientation. Channels
marked bad in the sensor table are preserved in ``raw.info["bads"]``.

Minimal Conversion
------------------

Install the example dependencies from a repository checkout:

.. code-block:: bash

   cd examples/opm_conversion
   python3 -m pip install -r requirements.txt

A minimal conversion with an event table is:

.. code-block:: bash

   python3 standard_opm_matrix_to_fif.py \
     --meg path/to/meg.npy \
     --sensors path/to/sensors.tsv \
     --events path/to/events.tsv \
     --sfreq 1000 \
     --meg-unit T \
     --event-pulse-width 1 \
     --out path/to/output_raw.fif \
     --overwrite

Use ``--meg-key`` when loading a named array from ``.npz`` or ``.mat``. Add
``--ply``, ``--ply-unit``, and ``--ply-max-points`` when an optical scan
should be included. The example README documents all supported arguments and
table columns.

Run the Demonstrations
----------------------

After extracting the OSF data into the layout described by the example
README, run both validation workflows:

.. code-block:: bash

   cd examples/opm_conversion
   python3 test_hr80_s02_standard_conversion.py
   python3 test_rier2024_standard_conversion.py

The Quanmag HR80 example exercises event- and trigger-based conversion with an
optical scan. The QuSpin Rier2024 example exercises a ``.mat`` MEG matrix,
triaxial sensor metadata, standardized events, and bad-channel preservation.
The validation scripts read the generated FIF files with MNE-Python and check
event recovery, channel metadata, sensor geometry, digitization, spectral
analysis, sensor plots, and evoked or time-frequency outputs as applicable.

Using the Converted Recording
-----------------------------

Inspect the generated ``*_raw.fif`` file and its events before starting a
pipeline run. Once verified, place the recording in the dataset layout used
by the study and configure MEGFlow input discovery for that layout. Conversion
only creates and validates the FIF input; it does not choose preprocessing,
epoch, covariance, or source-reconstruction parameters. See
:doc:`configuration` for those settings.
