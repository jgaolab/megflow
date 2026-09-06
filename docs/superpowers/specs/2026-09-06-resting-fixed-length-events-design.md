# Resting Fixed-Length Event Configuration

## Goal

Expose every argument of MNE 1.8.0 `mne.make_fixed_length_events` through
MEGFlow's `epochs.resting` configuration while keeping the existing
`fixed_length_duration` field and its 2-second default unchanged.

## Public configuration

```groovy
resting {
    fixed_length_id = 1
    fixed_length_start = 0.0
    fixed_length_stop = null
    fixed_length_duration = 2.0
    fixed_length_first_samp = true
    fixed_length_overlap = 0.0
}
```

The fields map directly to MNE as follows:

| MEGFlow field | MNE argument |
| --- | --- |
| `fixed_length_id` | `id` |
| `fixed_length_start` | `start` |
| `fixed_length_stop` | `stop` |
| `fixed_length_duration` | `duration` |
| `fixed_length_first_samp` | `first_samp` |
| `fixed_length_overlap` | `overlap` |

No unprefixed aliases are introduced. Existing configurations containing only
`fixed_length_duration` retain their current behavior because all other fields
resolve to MNE's existing defaults.

## Runtime behavior

When `epochs.task_type` is `resting`, MEGFlow resolves the six fields and passes
them explicitly to `mne.make_fixed_length_events`. MNE remains responsible for
validating the values, including the requirement that
`0 <= fixed_length_overlap < fixed_length_duration`. Task-based event handling
is unchanged.

`fixed_length_duration` and `fixed_length_overlap` control event placement.
They do not set the extracted epoch window; `epochs.epochs.tmin` and
`epochs.epochs.tmax` continue to control that window.

## Configuration and documentation updates

Update every shipped Nextflow configuration that defines `epochs.resting` so
the six defaults are visible. Update the Quickstart resting example, the
single-dataset example, the preprocessing configuration reference, pipeline
details, and the full-workflow tutorial. Link the reference text to the
official MNE 1.8.0 API page.

## Verification

Add tests that use real MNE objects to verify:

- legacy duration-only configuration is unchanged;
- all six custom values affect event ids and sample positions correctly;
- `first_samp` behavior works with a non-zero Raw first sample;
- overlapping events use the requested spacing;
- shipped configurations and documentation expose all six field names; and
- the existing epoch, covariance, Nextflow configuration, and documentation
  contract suites remain green.
