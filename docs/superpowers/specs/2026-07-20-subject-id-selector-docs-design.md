# Subject ID Selector Documentation Design

## Goal

Explain every supported `subject_id` value form where new users first encounter
`"first:10"`, while keeping the Quickstart concise and placing detailed rules and
limitations in the dataset configuration reference.

## Scope

This is a documentation-only change. It updates:

- `docs/source/quickstart/quick_guide.rst` with a compact selector table and a
  practical example;
- `docs/source/reference/configuration_datasets.rst` with the complete public
  contract for subject selection.

It does not change selector parsing, add new selectors, or modify configuration
defaults.

## Quickstart Content

The existing “Select Subjects, Sessions, Tasks, or Runs” section will retain its
short explanation of BIDS entity filters and add a four-row table:

| Value | Meaning |
|---|---|
| `null` | Do not filter subjects; process every discovered subject that matches the other filters. |
| `"01"` | Process one subject. |
| `["01", "02"]` | Process an explicit set of subjects. |
| `"first:10"` | Process up to the first ten subjects returned by BIDS discovery. |

The section will state that subject values omit the `sub-` prefix. It will also
recommend an explicit list when the exact subjects matter, and link to the
dataset configuration reference for full limitations.

## Reference Content

The dataset configuration reference will define the following public contract
for both `meg_import.subject_id` and `mri_import.subject_id`:

- accepted forms are `null`, a single subject string, an explicit list of
  subject strings, and the `"first:N"` shortcut;
- subject labels omit the BIDS `sub-` prefix;
- `N` is a positive integer;
- if fewer than `N` subjects are discovered, all discovered subjects are
  selected;
- selection follows the order returned by BIDS discovery, so an explicit list
  is preferred when a reproducible subject set is required;
- `last:N`, numeric ranges, slice syntax, and wildcards are not supported;
- subject entity filtering applies to BIDS input; non-BIDS input should use
  `raw_include_keywords` and `raw_exclude_keywords`.

The existing MEG import field table will link readers to this explanation rather
than repeating incomplete rules. The MRI import section will point to the same
contract so the two import paths cannot appear to have different syntax.

## Verification

Build the Sphinx documentation in strict mode and check the edited RST files for
formatting errors, broken cross-references, and statements that conflict with the
current parsers in `megflow/meg_import_dataset.py` and
`megflow/mri_import_dataset.py`.

