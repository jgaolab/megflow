# Subject ID Selector Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every supported `subject_id` value form understandable from the Quickstart and document the complete selector contract in the dataset configuration reference.

**Architecture:** Keep onboarding content concise by adding a small value/meaning table to the existing Quickstart section. Add one canonical, cross-referenceable BIDS subject-selection section to the reference page, then point the MEG and MRI import descriptions to it so selector rules are not duplicated inconsistently.

**Tech Stack:** Sphinx, reStructuredText, Groovy/Nextflow configuration examples.

## Global Constraints

- This is a documentation-only change; do not modify selector parsing or defaults.
- Document only the public forms `null`, a single subject string, an explicit subject list, and `"first:N"`.
- State that subject values omit `sub-`, `N` is positive, selection follows BIDS discovery order, and an oversized `N` selects all discovered subjects.
- State that `last:N`, ranges, slices, and wildcards are unsupported.
- Distinguish BIDS entity filtering from non-BIDS filename keyword filtering.

---

### Task 1: Document BIDS subject selection at both levels

**Files:**
- Modify: `docs/source/quickstart/quick_guide.rst:267`
- Modify: `docs/source/reference/configuration_datasets.rst:451`
- Test: Sphinx strict build for `docs/source`

**Interfaces:**
- Consumes: `meg_import.subject_id` and `mri_import.subject_id` behavior from `megflow/meg_import_dataset.py` and `megflow/mri_import_dataset.py`.
- Produces: the `bids-subject-selection` Sphinx reference target used by the Quickstart and import descriptions.

- [ ] **Step 1: Add the Quickstart selector table**

Replace the abbreviated `subject_id` explanation with a `list-table` containing
these four public forms:

```rst
.. list-table:: ``subject_id`` forms
   :header-rows: 1
   :widths: 28 72

   * - Value
     - Meaning
   * - ``null``
     - Process every discovered subject that matches the other filters.
   * - ``"01"``
     - Process one subject.
   * - ``["01", "02"]``
     - Process exactly the listed subjects.
   * - ``"first:10"``
     - Process up to the first ten subjects returned by BIDS discovery.
```

Keep the existing complete configuration example. Add a short recommendation to
use an explicit list when exact subject membership matters and link with:

```rst
:ref:`complete subject selection rules <bids-subject-selection>`
```

- [ ] **Step 2: Add the canonical reference section**

Insert `.. _bids-subject-selection:` and a `BIDS Subject Selection` section
before `MRI Import`. Define all four forms in a table, then state these rules
explicitly:

```rst
Use labels without the ``sub-`` prefix. In ``"first:N"``, ``N`` must be a
positive integer. If fewer than ``N`` subjects are available, all discovered
subjects are selected. Discovery order determines which subjects are first;
use an explicit list when exact membership must be reproducible.

``last:N``, numeric ranges, slice syntax, and wildcards are not supported.
These entity filters apply to BIDS input. For non-BIDS input, use
``raw_include_keywords`` and ``raw_exclude_keywords`` instead.
```

- [ ] **Step 3: Point MEG and MRI import descriptions to the canonical rules**

Update `MRI Import` to say that `mri_import.subject_id` follows the
`bids-subject-selection` target. Update the `meg_import.subject_id` table row to
summarize its accepted forms and link to the same target. Keep `session_id`,
`task`, and `run_id` documented as null/string/list filters.

- [ ] **Step 4: Run focused source checks**

Run:

```bash
rg -n 'first:N|first:10|last:N|bids-subject-selection|raw_include_keywords' \
  docs/source/quickstart/quick_guide.rst \
  docs/source/reference/configuration_datasets.rst
git diff --check -- \
  docs/source/quickstart/quick_guide.rst \
  docs/source/reference/configuration_datasets.rst
```

Expected: both pages contain the intended selector guidance and cross-reference;
`git diff --check` exits with no output.

- [ ] **Step 5: Build the documentation strictly**

Run:

```bash
scripts/development/build_docs.sh --strict
```

Expected: Sphinx exits `0` without warnings or broken references.

- [ ] **Step 6: Commit the implementation**

```bash
git add -f docs/superpowers/plans/2026-07-20-subject-id-selector-docs.md
git add docs/source/quickstart/quick_guide.rst \
  docs/source/reference/configuration_datasets.rst
git commit -m "docs: explain subject id selectors"
```
