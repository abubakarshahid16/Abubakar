# Contrast root-cause report (Phase 0)

Generated 2026-09-17 from the approved 1600x900 axe run. The detailed
machine-readable evidence is in `contrast-root-cause.json`; it contains one
row for every serious/critical axe node. The run found **448 color-contrast
nodes in 31 computed foreground/background/font groups** (249 light, 199
dark), matching the 448 color-contrast nodes recorded in
`axe-baseline.json`. It also reproduced the two Dashboard list violations.

## How it was measured

`frontend/tests/e2e/contrast-root-cause.spec.ts` opened all eight views in
both themes, waited five seconds for settled data, ran axe, and recorded the
computed color, nearest opaque background, font size/weight, class names, and
axe target for every serious/critical node. No production style or token was
changed in this pass.

## Baseline distribution

| View | Light contrast nodes | Dark contrast nodes | List nodes |
| --- | ---: | ---: | ---: |
| Dashboard | 16 | 14 | 1 each |
| Documents | 20 | 13 | 0 |
| Chat | 19 | 16 | 0 |
| Analysis | 22 | 14 | 0 |
| Reports | 13 | 12 | 0 |
| Deliverables | 41 | 21 | 0 |
| Ingestion | 59 | 33 | 0 |
| Administration | 59 | 76 | 0 |
| **Total** | **249** | **199** | **1 each** |

## Every failing computed pair, grouped by pair and font

The first two rows are the dominant defect: `slateish-500` is used for 11px
metadata across every view. The next rows are the same light/dark ramp problem
for `slateish-400` labels. Alpha backgrounds are listed separately because the
effective background is an overlay, not a solid token.

| Nodes | Foreground | Background | Size/weight | Source/class family |
| ---: | --- | --- | --- | --- |
| 104 | #626c74 (`slateish-500`) | #1a1f23 (`ink-850`) | 11/400 | `text-[11px] text-slateish-500` metadata, dark |
| 104 | #7a8592 (`slateish-500`) | #eef0f2 (`ink-850`) | 11/400 | same metadata, light |
| 59 | #7d878f (`slateish-400`) | #1c2125 (`ink-800`) | 12/400 | `text-xs text-slateish-400`, Administration dark |
| 38 | #667382 (`slateish-400`) | #eef0f2 (`ink-850`) | 11/400 | compact labels, light |
| 34 | #667382 (`slateish-400`) | #eef0f2 (`ink-850`) | 12/400 | section labels, light |
| 17 | #626c74 (`slateish-500`) | #1a1f23 (`ink-850`) | 12/400 | secondary metadata, dark |
| 17 | #7a8592 (`slateish-500`) | #eef0f2 (`ink-850`) | 12/400 | secondary metadata, light |
| 9 | #667382 (`slateish-400`) | #f4f5f6 (`ink-900`) | 14/400 | descriptive copy, light |
| 8 | #626c74 (`slateish-500`) | signal alpha overlay | 11/400 | metadata on dark tinted cards |
| 8 | #667382 (`slateish-400`) | #eef0f2 (`ink-850`) | 12/700 | table/header labels, light |
| 8 | #667382 (`slateish-400`) | #f4f5f6 (`ink-900`) | 12/500 | filter/status controls, light |
| 8 | #7a8592 (`slateish-500`) | signal alpha overlay | 11/400 | metadata on light tinted cards |
| 4 | #8c5530 (`warn-500`) | warn alpha overlay | 12/400 | warning badge, light |
| 4 | #667382 (`slateish-400`) | #f4f5f6 (`ink-900`) | 12/400 | muted controls, light |
| 3 | #7d878f (`slateish-400`) | #1c2125 (`ink-800`) | 12/700 | compact labels, dark |
| 3 | #626c74 (`slateish-500`) | #16191c (`ink-900`) | 12/400 | ingestion metadata, dark |
| 3 | #7a8592 (`slateish-500`) | #f4f5f6 (`ink-900`) | 12/400 | ingestion metadata, light |
| 2 | #667382 (`slateish-400`) | #eef0f2 (`ink-850`) | 12/600 | uppercase labels, light |
| 2 | #4b5563 | #ffffff | 11/400 | monospace low-opacity text |
| 2 | #667382 (`slateish-400`) | #eef0f2 (`ink-850`) | 11/600 | uppercase labels, light |
| 1 | #626c74 (`slateish-500`) | #16191c (`ink-900`) | 11/400 | monospace metadata, dark |
| 1 | warn alpha | #ffffff | 13/400 | warning badge text, dark |
| 1 | #7d878f (`slateish-400`) | signal alpha overlay | 12/400 | muted copy, dark |
| 1 | #7a8592 (`slateish-500`) | #ffffff | 12/400 | metadata on white card |
| 1 | #7a8592 (`slateish-500`) | #f4f5f6 (`ink-900`) | 11/400 | monospace metadata, light |
| 1 | #667382 (`slateish-400`) | #eef0f2 (`ink-850`) | 10/400 | opacity-reduced label, light |
| 1 | #667382 (`slateish-400`) | white alpha overlay | 14/400 | descriptive copy, light |
| 1 | #667382 (`slateish-400`) | signal alpha overlay | 12/400 | muted copy, light |
| 1 | warn alpha | #1c2125 (`ink-800`) | 13/400 | warning badge text, dark |
| 1 | #7d878f (`slateish-400`) | #1a1f23 (`ink-850`) | 10/400 | opacity-reduced label, dark |
| 1 | #626c74 (`slateish-500`) | #1c2125 (`ink-800`) | 12/400 | muted metadata, dark |

## Root cause

The failures are not isolated component mistakes. The theme ramps assign the
same low-emphasis tokens to body text on both raised cards and pale light-theme
surfaces. In particular, `slateish-500` at 11px (208 nodes) and
`slateish-400` at 11–12px (131+ nodes) are below the normal-text contrast
threshold. Opacity utilities and warning alpha badges add smaller variants of
the same problem. The 9–11px sizes amplify the issue, but increasing size alone
would not make the color pair pass; the token values and the small-text usage
must be corrected together. The Dashboard list issue is independent DOM
structure and is not a color-token problem.

## Deliberate stop

Per the approved instruction, this is the root-cause report only. No token,
font-size, component, Dashboard-list, CI, or Phase 1 routing change has been
made. The next step is to review/approve this diagnosis, then fix the token and
size groups together and rerun axe in both themes until serious/critical
violations reach zero.
