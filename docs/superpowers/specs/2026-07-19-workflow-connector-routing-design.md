# Workflow Connector Routing Design

## Goal

Refine the static report's full Workflow diagram so dependency connectors are
visually subordinate to the workflow cards and the two cross-lane dependencies
follow deliberate, easy-to-read routes. The same-lane Structural MRI dependency
should connect directly to Coregistration instead of detouring below the cards.

The requested result keeps the current two-lane node layout and workflow
semantics. It changes only connector styling, marker sizing, ports, and routing.

## Approved Visual Direction

The user's annotated image defines route direction only. Its red color and large
arrowheads are not visual specifications.

The two cross-lane dependencies will use these routes:

1. **ICA to Coregistration:** leave the bottom-center port of ICA, travel
   vertically down to the vertical center of Coregistration, then travel
   horizontally right and enter the left-center port of Coregistration.
2. **Head model to Source localization:** leave the right-center port of Head
   model, travel horizontally right to the horizontal center of Source
   localization, then travel vertically up and enter the bottom-center port of
   Source localization.

This makes both dependencies read in the natural processing direction. The
Coregistration input no longer drops into the top of the card, and the Head
model dependency no longer rises from the top of its card before turning toward
Source localization.

The **Structural MRI to Coregistration** dependency will use the standard
same-lane direct route: leave the right-center port of Structural MRI, travel
horizontally, and enter the left-center port of Coregistration. The existing
special bottom detour for this edge will be removed. The user's red arrow shows
route direction only; the rendered connector keeps the current light stroke,
small arrowhead, and endpoint ports.

The direct Coregistration-to-Head-model connector remains horizontal. The
Structural-MRI-to-Head-model connector retains its existing bottom route. The
Covariance-to-Source-localization connector and the upper routed dependency into
Source localization retain their existing endpoints.

## Connector Styling

Restore the original light visual hierarchy while preserving enough contrast
for dependency tracing:

- base connector stroke: `rgba(66, 103, 213, 0.26)`;
- arrowhead fill: `rgba(66, 103, 213, 0.38)`;
- base connector width: `1.8px`;
- routed and cross-lane connectors use the same light family rather than the
  current dark variants;
- endpoint ports use a small white center and a light blue outline; and
- hover may increase contrast modestly, but must not produce a heavy dark line.

Arrowheads will use a fixed SVG user-space size of approximately 6–7 pixels.
They will not scale with connector stroke width, including during hover. Port
circles will also be reduced from the current size so they remain secondary to
the cards.

## Routing Rules

The renderer will select explicit ports for the two semantic cross-lane edges
instead of sending every cross-lane edge through alternating horizontal tracks.
The route coordinates will continue to derive from the calculated card
positions and dimensions, so the result remains correct at each supported
column count.

For the two requested edges:

- `ica` (or the active signal predecessor) to `coregistration` uses
  bottom-to-left routing;
- `headmodel` to `source` uses right-to-bottom routing.

For the same-lane anatomy edge:

- `anatomy_structural` to `coregistration` uses the generic horizontal direct
  rule because the nodes are adjacent and no intermediate model node blocks the
  path;
- the renderer removes the edge-specific exclusion and bottom-route branch that
  currently force this dependency to detour; and
- `anatomy_structural` to `headmodel` remains routed below the model cards.

Other edges continue to use the existing direct, same-lane routed, or generic
cross-lane fallback rules. This keeps anatomy-enabled and reduced-stage diagrams
functional without coupling routes to one screenshot's absolute coordinates.

## Accessibility and Semantics

The SVG remains non-interactive and retains its current accessible diagram
label, edge titles, `data-from`/`data-to` attributes, and dependency order.
No node, status, lane, or scientific workflow relationship changes.

## Verification

Focused tests will render a representative full workflow and verify:

1. the arrow marker uses a fixed user-space size;
2. the Structural-MRI-to-Coregistration path is a single horizontal segment
   from the Structural MRI right-center port to the Coregistration left-center
   port and uses the standard direct-edge class;
3. the Structural-MRI-to-Head-model dependency retains its lower routed path;
4. the ICA-to-Coregistration path starts at the ICA bottom center and ends at
   the Coregistration left center;
5. the Head-model-to-Source path starts at the Head model right center and ends
   at the Source localization bottom center;
6. direct and upper-routed Source localization dependencies remain present;
7. the original light connector and arrowhead tokens are present in the report
   stylesheet; and
8. the current dark connector tokens are no longer used.

After focused tests pass, a representative SVG or static report will be
rendered and inspected visually for arrow scale, orthogonal alignment, card
clearance, lane-label clearance, and connector overlap.

## Scope

Expected implementation files are:

- `megflow/reports/workflow_diagram.py` for marker size and route selection;
- `megflow/reports/static_html_report.py` for connector, arrowhead, hover, and
  port styling; and
- `tests/test_static_reports.py` for focused routing and style contracts.

Existing unrelated working-tree changes must remain untouched.
