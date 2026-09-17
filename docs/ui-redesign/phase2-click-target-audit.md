# Phase 2 click-target audit

Before sizing changes, the source inventory found 135 interactive elements
across the frontend (`rg -n '<(button|a|input|select|textarea)\\b|role="button"'
frontend/src --glob '*.tsx'`). The main risk groups are:

- 92 buttons, including compact navigation and inline action buttons.
- 21 links, including skip navigation and report/document links.
- 22 form controls (inputs, selects, textareas and radios/checkboxes).

The audit identified icon-only or compact controls in Chat history, evidence
source selectors, report actions, document actions, and mobile navigation. The
shared focus treatment was added first; explicit 44px minimum sizing is kept
for the density-control buttons and remains a follow-up for controls whose
layout would otherwise change. No client-confirmed Arabic/RTL assumptions were
introduced.
