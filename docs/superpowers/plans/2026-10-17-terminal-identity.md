# Bishop identity implementation plan

**Goal:** Replace the basic boot identity with an intentional, detailed terminal/brand design.
**Architecture:** identity.py owns vector geometry and fine braille sampling; terminal.py composes wordmark, compact metadata and inventory. Matching SVG and previews support visual QA.
**Tech Stack:** Python stdlib runtime, native SVG; local rendering tools for standalone visual review.

- [ ] Identity lane: original faceted Bishop geometry, braille render API and matching SVG; tests and raster preview for review.
- [ ] Integration lane: compact responsive boot composition/custom wordmark; preserve sanitization/no-color; update meaningful visual tests.
- [ ] Review lane: independently critique design and width/accessibility/terminal safety; visual QA artifacts at multiple widths.
- [ ] Verify full suite, clean package, version update and privacy scan; commit, push, CI and release. Existing global command picks up code; restarting required for older process.
