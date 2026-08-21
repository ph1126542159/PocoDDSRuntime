# Business tracing collapsible panels - Design QA

- source visual truth: `C:\Users\ph\AppData\Local\Temp\codex-clipboard-ed888fbb-3442-489e-ba80-c3dc85f4f49a.png`
- rendered implementation (expanded): `E:\PocoDDSRuntime\webui\tracing\implementation-expanded-wide.png`
- rendered implementation (both collapsed): `E:\PocoDDSRuntime\webui\tracing\implementation-collapse-wide.png`
- combined comparisons: `E:\PocoDDSRuntime\webui\tracing\qa-comparison-expanded.png`, `E:\PocoDDSRuntime\webui\tracing\qa-comparison-collapsed.png`
- route: `http://localhost:9080/tracing/`
- source pixels: 2410 x 1087
- implementation pixels / CSS viewport: 1790 x 1080 at device scale factor 1
- density normalization: both comparison images were scaled proportionally into equal 940 px-wide slots; no density-only findings were filed
- states: left expanded/right expanded; left collapsed/right expanded; left expanded/right collapsed; both collapsed; both restored

## Full-view comparison evidence

The expanded rendering keeps the existing three-part workspace from the source: business instances, flow canvas, and node details. The new controls sit in the two panel headers without changing the surrounding navigation, simulation panel, status treatment, node cards, or safety footer. The collapsed rendering replaces both side panels with narrow labeled rails and gives their released space to the flow canvas.

At the 1790 px viewport, the canvas grows from 778.0 px to 1460.4 px when both panels are collapsed, a gain of 682.4 px. Each collapsed rail measures 46 px. At the default 1280 px viewport, the responsive layout keeps the detail panel below the canvas and converts its collapsed state into a 46 px horizontal rail.

## Focused region comparison evidence

The annotated left and right boundaries were inspected in the combined comparison. In expanded state, each header has an aligned Lucide panel-close control. In collapsed state, each boundary remains discoverable as a bordered rail with the panel label, directionally correct expand icon, hover treatment, tooltip, visible focus style, `aria-expanded`, and `aria-controls`.

## Required fidelity surfaces

- Fonts and typography: existing Inter/Noto Sans SC/Microsoft YaHei stack, weights, sizes, and hierarchy are unchanged; rail labels use the existing 13 px secondary UI scale.
- Spacing and layout rhythm: existing 14 px grid gaps and card radii are preserved; 46 px rails are compact without crowding the expand target.
- Colors and visual tokens: existing blue, border, background, success, and muted tokens are reused; no new competing palette was introduced.
- Image quality and assets: the target contains no new raster assets. Controls use the project's existing `lucide-react` icon family; no placeholder, CSS-art, or custom SVG substitute was added.
- Copy and content: existing product copy and live data are unchanged. New labels are concise and explicit: `收起/展开业务实例` and `收起/展开节点详情`.
- Responsiveness and accessibility: four wide-screen combinations and the 1280 px responsive state were exercised. Controls remain semantic buttons, keyboard focus is visible, and no overlap or clipped persistent control was observed.

## Findings

No actionable P0/P1/P2 mismatch remains for the requested collapsible-panel change.

## Comparison history

- Pass 1: expanded and both-collapsed states were captured at 1790 x 1080 and placed beside the annotated source. No P0/P1/P2 issue was found, so no visual-fix iteration was required.

## Interaction and runtime checks

- left collapse: passed
- right collapse: passed
- both collapsed: passed
- expand both and restore original layout: passed
- flow canvas width gain: 682.4 px at 1790 px viewport
- browser console warnings/errors: none
- live runtime health: checked separately after bundle deployment

## Follow-up polish

No P3 item is required for this scope.

final result: passed
