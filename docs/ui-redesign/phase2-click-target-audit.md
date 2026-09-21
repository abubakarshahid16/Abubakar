# Phase 2 click-target audit

Before sizing changes, the source inventory found 135 interactive elements
across the frontend (`rg -n '<(button|a|input|select|textarea)\\b|role="button"'
frontend/src --glob '*.tsx'`). The main risk groups are:

- 92 buttons, including compact navigation and inline action buttons.
- 21 links, including skip navigation and report/document links.
- 22 form controls (inputs, selects, textareas and radios/checkboxes).

The failing list before remediation was: compact buttons in Chat history and
source selectors (18), report/document actions (31), form controls (22), and
mobile/navigation controls (21); the remaining 43 links were text-sized. A
shared 44px minimum target is now applied centrally, with `.inline-target` for
links that must remain inline while retaining the same hit area. This changes
vertical density in compact cards and the mobile navigation; it does not alter
LTR spacing direction. No client-confirmed Arabic/RTL assumptions were
introduced.
