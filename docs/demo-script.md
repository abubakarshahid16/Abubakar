# Client Demonstration Script - AI Submittal Review

Ten minutes, six clicks, in this order. Written for the demonstrator
(Usman), against the brief: one contractor datasheet in, a completed CRS
out, with review code, page/section, comment, and exact clause per finding.

## Before the audience arrives (5 minutes)

1. Run `scripts\start-system.bat` (or start backend, frontend, Ollama by
   hand). Open the app, log in, confirm the Dashboard loads.
2. Confirm the drum sheet's review run exists on the AI Submittal Review
   page. If not, run it from the Dashboard button - it takes ~8 seconds.
3. Have both PDFs (SAES-L-132 and the drum datasheet) closed but handy.

## The demonstration

**1. Dashboard (30 seconds).** "Everything runs on this one machine.
No document ever leaves it." Point at the four cards and the
Upload Datasheet and Run AI Review button.

**2. Run a review live (1 minute).** Click the button, pick the drum
datasheet, run. ~8 seconds, 1,580 requirements evaluated. Say the number.

**3. The findings (3 minutes).** Open the run. Talking points, in order:
- The findings that need attention are at the top; the 1,500+ requirements
  with nothing to check are folded behind an honest count, not hidden and
  not shown as failures. "The system never pads its results."
- Open one finding. Show: requirement text, submitted value, the exact
  clause and page on BOTH sides.
- Click the citation. The standard opens AT the cited page. "Every claim
  is checkable in two clicks. We have verified 6,804 of 6,805 page
  references."

**4. The engineer stays in charge (2 minutes).** Show Confirm and Reject.
"A rejected pairing is remembered forever - the machine never asks twice."
Show the recommended review code beside the engineer's final code.
"The AI recommends; the engineer decides; both are stored."

**5. The CRS (2 minutes).** Click Export CRS. Open the Excel file.
"This is your own CRS template - same columns, same layout - filled
automatically: comment, page/section, exact clause, and the recommended
review code with its reason." Point at the rows naming missing standards:
"When a governing spec is not in the library, the system says so by name
instead of guessing - this is what makes it safe."

**6. Close (1 minute).** "Three different contractor formats read and
tested. 2,250+ automated checks. Every wrong claim the system ever made
during development is recorded in an audit file - 41 entries - and each
one was caught by our own gates before reaching a reviewer."

## The two questions clients always ask

**"Can it be wrong?"** - "It can miss things, and it says so honestly -
'needs engineer review', never a guess. What it does not do is invent: in
testing, zero fabricated verdicts survived to a human. The design rule is
that unsure always goes to the engineer."

**"Does our data go to the cloud / ChatGPT?"** - "No. Everything, including
the AI model, runs on this machine. Unplug the network cable and the
demonstration continues identically." (Offer to actually do it.)

## What NOT to claim

- Not "it reviews everything": drawings and image-embedded text are not
  read yet; statement-type rules go to the engineer by design.
- Not "100% accurate": say "every claim is citable and checkable", which
  is stronger and true.
