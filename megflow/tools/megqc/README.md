# MEG QC standalone reference-quota scorer

This folder is the deployment-oriented scorer for
`lowcost_quota_T4_S2_Stat1_Fr1`.

Key points:

- No `tsfel` package is imported. The `tsfel.*` names are the canonical metric
  names used during selection; their selected low-cost formulas are implemented
  directly with NumPy.
- No `msqms` package is imported. The required `freq_domain.*` and
  `fractal_domain.DFA` formulas are ported from the local msqms source code to
  avoid package-version drift.
- Metric extraction follows the **process_1** reference cohort by default: all MEG
  channels (including those marked bad) and the full timeline (including BAD
  spans). Use ``--omit-bad-channels`` / ``--omit-bad-annotations`` only for
  ad-hoc diagnostics.
- The reference intervals are bundled in
  `reference_intervals_reference_quota.csv`.

Basic usage:

```bash
python3 score_meg_reference_quota_standalone.py \
  --fif /path/to/new_file.fif \
  --meg-vendor elekta \
  --category task \
  --output-dir ./score_out
```

Outputs:

- `*.summary.json`: final Normative Reference score, 0-100, higher is better.
- `*.component_scores.csv`: raw metric value, q05/q50/q95 reference interval,
  direction, component score, and out-of-range status.
- `*.reference_position.png`: visual position of each metric in the reference
  interval.

Useful options:

```bash
# Fast diagnostic score without DFA
python3 score_meg_reference_quota_standalone.py --fif /path/to/file.fif --skip-dfa

# Optional: omit BAD spans or bad channels (not how the bundled reference was built)
python3 score_meg_reference_quota_standalone.py --fif /path/to/file.fif --omit-bad-annotations --omit-bad-channels

# Use sampled DFA instead of the msqms-style segmented DFA
python3 score_meg_reference_quota_standalone.py --fif /path/to/file.fif --dfa-method sampled --dfa-max-samples 20000
```

Consistency smoke test:

```bash
python3 score_meg_reference_quota_standalone.py --self-test
python3 test_standalone.py
```
