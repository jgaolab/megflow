# Standard OPM to FIF Conversion Demos

This folder contains a vendor-neutral example workflow for converting OPM-MEG
data into MNE-Python FIF files.

The main converter is:

```bash
python3 standard_opm_matrix_to_fif.py
```

It does not parse proprietary acquisition formats directly. Instead, each
dataset is first organized into a small set of standard inputs:

```text
MEG matrix + sensor table + events/triggers + optional optical scan PLY
```

Two demo datasets are included:

```text
examples/quanmag_hr80_s02
examples/quspin_rier2024_sub001
```

The example data are distributed separately on OSF:

```text
https://osf.io/qe93s/overview
```

Download `opm-examples.7z` from that OSF project and extract it in this folder
so that the `examples/` directory sits next to the Python scripts:

```text
opm-demos/
  standard_opm_matrix_to_fif.py
  test_hr80_s02_standard_conversion.py
  test_rier2024_standard_conversion.py
  examples/
    quanmag_hr80_s02/
    quspin_rier2024_sub001/
```

## 1. Requirements

Install the Python dependencies with:

```bash
cd opm-demos
python3 -m pip install -r requirements.txt
```

The required packages are listed in:

```text
requirements.txt
```

Main packages:

```text
mne         FIF writing, Raw/Epochs/Evoked objects, events, PSD, sensor plots
numpy       matrix handling
pandas      TSV/CSV table handling
scipy       reading .mat MEG matrices
matplotlib  figure generation in the demo tests
pyvista     optional/recommended PLY mesh decimation
```

`pyvista` is recommended for mesh decimation, but the converter has a fallback
PLY vertex reader and deterministic point sampler if PyVista is unavailable or
cannot decimate a specific mesh.

## 2. Standard Input Format

### MEG Matrix

The MEG data matrix must have shape:

```text
(n_channels, n_samples)
```

Supported files:

```text
.npy, .npz, .mat, .csv, .tsv, .txt
```

For `.npz` or `.mat`, use `--meg-key` to select the array.

The data unit is declared explicitly:

```bash
--meg-unit T
--meg-unit fT
--meg-unit pT
--meg-unit nT
```

The converter writes MEG channels to FIF in Tesla.

### Sensor Table

The sensor file must be a `.tsv` or `.csv` table with columns:

```text
name,x,y,z,ox,oy,oz,pos_unit,status
```

Meaning:

```text
name      Channel name. Row order must match the MEG matrix row order.
x,y,z     Sensor position.
ox,oy,oz  Sensor measurement direction vector.
pos_unit  mm, cm, or m.
status    good or bad.
```

Each OPM channel is written as:

```text
ch_type     = mag
coil_type   = FIFFV_COIL_POINT_MAGNETOMETER
coord_frame = head/device with identity dev_head_t
unit        = Tesla
```

The converter creates the full 12-value MNE `loc` field:

```text
loc[0:3]   = sensor position in meters
loc[3:12]  = 3x3 orientation matrix
loc[9:12]  = normalized measurement direction
```

Rows with `status=bad` are added to `raw.info["bads"]`.

### Events

The recommended event input is an event table:

```bash
--events events.tsv
```

Required columns:

```text
sample,event_id,event_type
```

Rules:

```text
sample      0-based sample index in the final Raw object.
event_id    Positive integer written into STI101.
event_type  Human-readable label. It is not written into FIF metadata.
```

The converter creates one stim channel named `STI101`:

```text
STI101[sample : sample + event_pulse_width] = event_id
```

Default pulse width:

```bash
--event-pulse-width 1
```

Constraints:

```text
Only one event_id is allowed at the same sample.
Event pulses must not overlap.
Adjacent event pulses must leave at least one zero-valued sample between them.
```

This keeps the output compatible with:

```python
events = mne.find_events(raw, stim_channel="STI101")
```

### Sparse Trigger Table

If the acquisition system stores sparse trigger state changes, use:

```bash
--triggers triggers.tsv
```

Required columns:

```text
sample,value
```

Example:

```text
sample,value
100,10
120,0
500,8
520,0
```

This expands to:

```text
STI101[100:120] = 10
STI101[500:520] = 8
all other samples = 0
```

`--events` and `--triggers` are mutually exclusive.

### Optical Scan PLY

An optical scan can be written into `raw.info["dig"]` as headshape points:

```bash
--ply face.ply --ply-unit mm
```

By default, the converter avoids writing dense PLY point clouds into FIF:

```bash
--ply-decimate-factor 0.995
--ply-max-points 500
```

If PyVista is available, the mesh is triangulated and decimated first. If
PyVista decimation fails, the converter falls back to reading PLY vertices and
uniformly sampling points with a fixed random seed. This keeps the output
stable across environments.

Use this to keep all points after decimation:

```bash
--ply-max-points 0
```

Optional fiducials can be supplied with:

```bash
--fiducials fiducials.tsv
```

Required columns:

```text
name,x,y,z,unit
```

Names must be:

```text
NAS,LPA,RPA
```

## 3. Generic Conversion Command

Minimal conversion with events:

```bash
python3 standard_opm_matrix_to_fif.py \
  --meg path/to/meg.npy \
  --sensors path/to/sensors.tsv \
  --events path/to/events.tsv \
  --sfreq 1000 \
  --meg-unit T \
  --event-pulse-width 1 \
  --out path/to/output_raw.fif \
  --overwrite
```

Conversion with optical scan:

```bash
python3 standard_opm_matrix_to_fif.py \
  --meg path/to/meg.npy \
  --sensors path/to/sensors.tsv \
  --events path/to/events.tsv \
  --sfreq 1000 \
  --meg-unit T \
  --event-pulse-width 1 \
  --ply path/to/face.ply \
  --ply-unit mm \
  --ply-max-points 500 \
  --out path/to/output_raw.fif \
  --overwrite
```

Conversion from a `.mat` matrix:

```bash
python3 standard_opm_matrix_to_fif.py \
  --meg path/to/meg.mat \
  --meg-key meg \
  --sensors path/to/sensors.tsv \
  --events path/to/events.tsv \
  --sfreq 1200 \
  --meg-unit fT \
  --out path/to/output_raw.fif \
  --overwrite
```

## 4. Quanmag HR80 S02 Demo

Input directory:

```text
examples/quanmag_hr80_s02
```

Files:

```text
meg.npy       MEG matrix, shape (80, n_samples), unit T
sensors.tsv   HR80 sensor positions and orientations
events.tsv    Event table used to synthesize STI101 pulses
triggers.tsv  Sparse trigger-change table
face.ply      Optical scan point cloud
```

Run the full test:

```bash
cd opm-demos
python3 test_hr80_s02_standard_conversion.py
```

The test creates two FIF files:

```text
examples/quanmag_hr80_s02/outputs/S02_standard_events_raw.fif
examples/quanmag_hr80_s02/outputs/S02_standard_triggers_raw.fif
```

It verifies:

```text
mne.find_events() recovers the standard events
80 OPM MEG channels are present
STI101 is present
coil_type is FIFFV_COIL_POINT_MAGNETOMETER
channel loc values are finite and have nonzero measurement directions
raw.info["dig"] contains optical-scan headshape points
PSD can be computed
2D and 3D sensor layouts can be drawn
evoked response can be generated from all events
```

Generated figures:

```text
examples/quanmag_hr80_s02/outputs/figures/events_psd.png
examples/quanmag_hr80_s02/outputs/figures/events_sensors_2d.png
examples/quanmag_hr80_s02/outputs/figures/events_sensors_3d.png
examples/quanmag_hr80_s02/outputs/figures/events_evoked_all_events.png
```

Important plotting note:

The Quanmag demo writes `face.ply` into FIF as headshape points. This is useful
for preserving optical-scan information, but a face-only PLY can bias MNE's
automatic head-sphere fit in topomap-style plots. The test therefore uses a
fixed plotting sphere:

```python
sphere = (0.0, 0.0, 0.0, 0.095)
```

This does not change the FIF data. It only makes PSD, sensor layout, and
evoked inset plots stable.

## 5. QuSpin Rier2024 Demo

Input directory:

```text
examples/quspin_rier2024_sub001
```

Files:

```text
meg.mat      MEG matrix variable named "meg", shape (189, n_samples), unit fT
sensors.tsv  QuSpin triaxial sensor positions and orientations
events.tsv   Standardized event table
```

Run the full test:

```bash
cd opm-demos
python3 test_rier2024_standard_conversion.py
```

The test creates:

```text
examples/quspin_rier2024_sub001/outputs/rier2024_standard_events_raw.fif
```

It verifies:

```text
mne.find_events() recovers the standardized events
189 OPM MEG channels are present
STI101 is present
bad channels from sensors.tsv are preserved in raw.info["bads"]
coil_type is FIFFV_COIL_POINT_MAGNETOMETER
channel loc values are finite and have nonzero measurement directions
raw.info["dig"] is None because no PLY is provided
PSD can be computed
2D and 3D sensor layouts can be drawn
a sensor-level beta TFR figure can be generated
```

Generated figures:

```text
examples/quspin_rier2024_sub001/outputs/figures/rier2024_psd.png
examples/quspin_rier2024_sub001/outputs/figures/rier2024_sensors_2d.png
examples/quspin_rier2024_sub001/outputs/figures/rier2024_sensors_3d.png
examples/quspin_rier2024_sub001/outputs/figures/rier2024_kg_z_d2_d5_beta_tfr.png
```

The Rier2024 event mapping used by the demo is:

```text
event_id=3  Start_index  D2 / index finger trial onset
event_id=4  Start_pinky  D5 / little finger trial onset
event_id=5  individual_stim, an intra-trial tactile stimulus pulse
```

The TFR demo intentionally uses the fixed sensor `KG Z` for both conditions:

```text
D2 = Start_index / event_id=3
D5 = Start_pinky / event_id=4
```

The figure shows fractional power change relative to the `2.5-3.0 s` baseline
and highlights the `13-30 Hz` beta band. It is a sensor-level qualitative check,
not a source reconstruction.

## 6. Manual Inspection in Python

After conversion, inspect the FIF file with MNE:

```python
import mne

raw = mne.io.read_raw_fif("examples/quanmag_hr80_s02/outputs/S02_standard_events_raw.fif",
                          preload=False)
events = mne.find_events(raw, stim_channel="STI101")

print(raw)
print(raw.info["bads"])
print(len(raw.info["dig"]) if raw.info["dig"] is not None else 0)
print(events[:5])
```

For QuSpin:

```python
raw = mne.io.read_raw_fif(
    "examples/quspin_rier2024_sub001/outputs/rier2024_standard_events_raw.fif",
    preload=False,
)
events = mne.find_events(raw, stim_channel="STI101")
```

## 7. Troubleshooting

### PyVista PLY Decimation Error

Some PLY files are not pure triangle meshes. The converter triangulates meshes
before PyVista decimation and falls back to vertex sampling if decimation fails.
If needed, skip mesh decimation and use only point capping:

```bash
--ply-decimate-factor 0 --ply-max-points 500
```

### Topomap or Evoked Inset Looks Shifted

If optical-scan points are face-only or poorly centered, MNE's automatic sphere
fit may be biased. Use an explicit sphere for visualization:

```python
sphere = (0.0, 0.0, 0.0, 0.095)
```

This affects plotting only, not the data stored in FIF.

### Events Are Not Recovered

Check that:

```text
sample is 0-based
event_id is a positive integer
there is only one event per sample
event pulses do not overlap
there is at least one zero sample between adjacent pulses
```

Then verify:

```python
events = mne.find_events(raw, stim_channel="STI101", shortest_event=1)
```
