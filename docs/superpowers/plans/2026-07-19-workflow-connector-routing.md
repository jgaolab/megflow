# Workflow Connector Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the static Workflow diagram's light connector hierarchy, use fixed small arrowheads, and route ICA-to-Coregistration and Head-model-to-Source-localization through the ports shown in the approved annotation.

**Architecture:** Keep the current stage-column and two-lane layout. Add two semantic cross-lane routing cases before the generic cross-lane fallback, then adjust the embedded report CSS and SVG marker/port sizes without changing workflow dependencies.

**Tech Stack:** Python 3, inline SVG, embedded CSS, `unittest`/pytest-compatible tests.

## Global Constraints

- The annotated red arrows define route direction only; do not copy their color or size.
- ICA-to-Coregistration is bottom-center to left-center.
- Head-model-to-Source-localization is right-center to bottom-center.
- Restore the base connector to `rgba(66, 103, 213, 0.26)`, the arrowhead to `rgba(66, 103, 213, 0.38)`, and the base width to `1.8px`.
- Arrowheads use a fixed 6–7 user-space pixel size and never scale with stroke width.
- Keep all workflow nodes, dependencies, statuses, lanes, titles, and edge metadata unchanged.
- Preserve all unrelated working-tree changes. The three implementation files already contain pre-existing uncommitted work, so do not commit their full contents as an isolated change.

---

### Task 1: Lock the requested ports and marker size with a failing SVG test

**Files:**
- Modify: `tests/test_static_reports.py:456-502`
- Modify: `megflow/reports/workflow_diagram.py:827-1079`

**Interfaces:**
- Consumes: `workflow_diagram.build_workflow_nodes(manifest, source)` and `workflow_diagram._render_svg(nodes, status_fn)`.
- Produces: existing SVG strings whose two targeted edge paths use the approved ports and whose arrow marker uses `markerUnits="userSpaceOnUse"`.

- [ ] **Step 1: Write the failing routing and marker test**

Add this method to `StaticManifestScopeTests` after the existing orthogonal-routing test:

```python
def test_full_workflow_svg_uses_requested_cross_lane_ports_and_small_marker(self):
    manifest = {
        "steps_raw": "meg_all",
        "parsed": {
            "primary": "meg_all",
            "meg_stage": 3,
            "run_meg": True,
            "run_anatomy": False,
            "skip_ica": False,
        },
        "params_snapshot": {
            "effective_config": {
                "megqc": {"enabled": True},
                "covariance": {"type": "epochs"},
                "source": {"type": "epochs"},
            }
        },
    }
    nodes, _ = workflow_report.build_workflow_nodes(manifest, "manifest")

    rendered = workflow_report._render_svg(nodes, lambda _node: "done")

    self.assertIn(
        'markerWidth="7" markerHeight="7" refX="6.5" refY="3.5" '
        'orient="auto" markerUnits="userSpaceOnUse"',
        rendered,
    )
    self.assertIn(
        'data-from="ica" data-to="coregistration"><title>ICA -&gt; '
        'Coregistration</title><path d="M584.0,146.0 V270.0 H676.0"',
        rendered,
    )
    self.assertIn(
        'data-from="headmodel" data-to="source"><title>Head model -&gt; '
        'Source localization</title><path d="M978.0,270.0 H1070.0 V146.0"',
        rendered,
    )
    self.assertIn(
        'data-from="epochs" data-to="source"',
        rendered,
    )
    self.assertIn(
        'data-from="covariance" data-to="source"',
        rendered,
    )
    self.assertIn('r="2.6" class="wf-port"', rendered)
```

- [ ] **Step 2: Run the test and verify the RED state**

Run:

```bash
ssh liaopan@100.114.213.66 "cd /data/liaopan/megprep && conda run -n megprep python -m pytest tests/test_static_reports.py::StaticManifestScopeTests::test_full_workflow_svg_uses_requested_cross_lane_ports_and_small_marker -q"
```

Expected: FAIL because the current marker is `9 × 9`, uses `strokeWidth`, the two paths enter from the old ports, and ports have radius `3.2`.

- [ ] **Step 3: Implement the fixed marker and two semantic routes**

Replace the marker definition with:

```python
f'<marker id="{mid}-arrow" markerWidth="7" markerHeight="7" refX="6.5" refY="3.5" orient="auto" markerUnits="userSpaceOnUse">',
'<path d="M0,0 L7,3.5 L0,7 z" class="wf-arrowhead" />',
```

After computing `source_center_x` and `target_center_x`, add these cases before the same-lane routed cases:

```python
if (
    not same_lane
    and target_node["key"] == "coregistration"
    and source_key in {"ica", "artifacts"}
):
    start = (source_center_x, source_y + box_h)
    end = (target_x, target_y + box_h / 2.0)
    ports.update((start, end))
    append_edge(
        source,
        target_node,
        f"M{start[0]:.1f},{start[1]:.1f} V{end[1]:.1f} H{end[0]:.1f}",
        "wf-edge wf-edge-routed wf-edge-cross-lane",
    )
    continue

if (
    not same_lane
    and source_key == "headmodel"
    and target_node["key"] == "source"
):
    start = (source_x + box_w, source_y + box_h / 2.0)
    end = (target_center_x, target_y + box_h)
    ports.update((start, end))
    append_edge(
        source,
        target_node,
        f"M{start[0]:.1f},{start[1]:.1f} H{end[0]:.1f} V{end[1]:.1f}",
        "wf-edge wf-edge-routed wf-edge-cross-lane",
    )
    continue
```

Render ports with radius `2.6`:

```python
parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" class="wf-port" />')
```

- [ ] **Step 4: Run the focused routing test and verify the GREEN state**

Run the Step 2 command again.

Expected: `1 passed`.

- [ ] **Step 5: Review only the incremental routing diff**

Run:

```bash
git diff -- megflow/reports/workflow_diagram.py tests/test_static_reports.py
```

Confirm the new test, marker, two route cases, and port radius are the only additions made by this task. Do not stage the full files because they contain pre-existing user work.

---

### Task 2: Restore the light connector hierarchy with a failing CSS contract

**Files:**
- Modify: `tests/test_static_reports.py:503`
- Modify: `megflow/reports/static_html_report.py:593-736`

**Interfaces:**
- Consumes: `static_html_report.REPORT_CSS`.
- Produces: the unchanged `REPORT_CSS: str` public module constant with light Workflow connector tokens.

- [ ] **Step 1: Write the failing style test**

Add this method to `StaticManifestScopeTests`:

```python
def test_workflow_connector_css_restores_light_visual_hierarchy(self):
    css = static_report.REPORT_CSS

    self.assertIn("fill: rgba(66, 103, 213, 0.38);", css)
    self.assertIn("stroke: rgba(66, 103, 213, 0.26);", css)
    self.assertIn("stroke-width: 1.8;", css)
    self.assertNotIn("rgba(57, 80, 157, 0.82)", css)
    self.assertNotIn("rgba(57, 80, 157, 0.68)", css)
    self.assertNotIn("rgba(77, 92, 151, 0.66)", css)
    self.assertNotIn("rgba(41, 91, 137, 0.72)", css)
```

- [ ] **Step 2: Run the test and verify the RED state**

Run:

```bash
ssh liaopan@100.114.213.66 "cd /data/liaopan/megprep && conda run -n megprep python -m pytest tests/test_static_reports.py::StaticManifestScopeTests::test_workflow_connector_css_restores_light_visual_hierarchy -q"
```

Expected: FAIL because the current connector, arrowhead, routed edge, and cross-lane edge use dark tokens.

- [ ] **Step 3: Apply the light style tokens**

Use these CSS blocks:

```css
.wf-arrowhead {
  fill: rgba(66, 103, 213, 0.38);
}

.wf-edge {
  fill: none;
  stroke: rgba(66, 103, 213, 0.26);
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
  pointer-events: stroke;
}

.wf-edge-direct,
.wf-edge-routed,
.wf-edge-cross-lane {
  stroke: rgba(66, 103, 213, 0.26);
  stroke-width: 1.8;
}

.wf-edge-group:hover .wf-edge {
  stroke: rgba(66, 103, 213, 0.52);
  stroke-width: 2.2;
}

.wf-port {
  fill: #ffffff;
  stroke: rgba(66, 103, 213, 0.42);
  stroke-width: 1.4;
  pointer-events: none;
}
```

- [ ] **Step 4: Run the focused style test and verify the GREEN state**

Run the Step 2 command again.

Expected: `1 passed`.

- [ ] **Step 5: Run both new contract tests together**

Run:

```bash
ssh liaopan@100.114.213.66 "cd /data/liaopan/megprep && conda run -n megprep python -m pytest tests/test_static_reports.py -q -k 'requested_cross_lane_ports or restores_light_visual_hierarchy'"
```

Expected: `2 passed`.

---

### Task 3: Verify the full report behavior and inspect the rendered diagram

**Files:**
- Verify: `megflow/reports/workflow_diagram.py`
- Verify: `megflow/reports/static_html_report.py`
- Verify: `tests/test_static_reports.py`

**Interfaces:**
- Consumes: the updated renderer, report stylesheet, and existing static-report tests.
- Produces: test evidence and a rendered PNG used only for visual inspection.

- [ ] **Step 1: Run the complete static-report test module**

Run:

```bash
ssh liaopan@100.114.213.66 "cd /data/liaopan/megprep && conda run -n megprep python -m pytest tests/test_static_reports.py -q"
```

Expected: all tests pass with no new failures.

- [ ] **Step 2: Render the representative full Workflow SVG**

Run:

```bash
python3 -c 'import sys; from pathlib import Path; sys.path.insert(0, "megflow/reports"); import workflow_diagram as w; manifest={"steps_raw":"meg_all","parsed":{"primary":"meg_all","meg_stage":3,"run_meg":True,"run_anatomy":False,"skip_ica":False},"params_snapshot":{"effective_config":{"megqc":{"enabled":True},"covariance":{"type":"epochs"},"source":{"type":"epochs"}}}}; nodes,_=w.build_workflow_nodes(manifest,"manifest"); Path("/private/tmp/megprep-workflow-routing.svg").write_text(w._render_svg(nodes,lambda node: "missing" if node["key"] in {"coregistration","headmodel","source"} else "done"),encoding="utf-8")'
rsvg-convert /private/tmp/megprep-workflow-routing.svg -o /private/tmp/megprep-workflow-routing.png
```

Expected: both files exist and the conversion exits successfully.

- [ ] **Step 3: Inspect the PNG**

Check that:

- arrowheads are small and no longer dominate the cards;
- all connectors and ports use the restored light hierarchy;
- ICA enters Coregistration from the left after a down-and-right turn;
- Head model exits from the right and enters Source localization from below;
- Covariance-to-Source and Epochs-to-Source remain clear;
- no connector crosses card text, status pills, or lane labels.

- [ ] **Step 4: Run syntax validation and review the final incremental diff**

Run:

```bash
ssh liaopan@100.114.213.66 "cd /data/liaopan/megprep && conda run -n megprep python -m py_compile megflow/reports/workflow_diagram.py megflow/reports/static_html_report.py tests/test_static_reports.py"
git diff --check
```

Expected: both commands exit successfully with no output from `git diff --check`.

- [ ] **Step 5: Preserve the user's existing worktree ownership**

Report the modified files and verification results. Do not create an implementation commit containing the full three files unless the user explicitly authorizes committing their pre-existing changes together with this refinement.
