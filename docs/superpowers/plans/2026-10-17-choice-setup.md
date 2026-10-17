# Choice-driven setup implementation plan

**Goal:** Remove required manual model/profile entry and offer searchable menu choices throughout setup.
**Architecture:** Standalone menu rendering, bounded provider catalog adapter, staged onboarding transaction. Keep all credential destination binding and runtime approvals.
**Tech Stack:** Python stdlib, unittest fake HTTP/PTY, existing adapters.

- [ ] Menu lane: extract choose into menu.py; scrolling/search/current selection/no overflow and backward-compatible API; test first.
- [ ] Catalog lane: catalog.py live bounded GET adapters and provider presets/plan metadata; official docs; fake tests, no real keys/inference.
- [ ] Integration lane: setup staged key management, automatic profile names, model choice/failure choices; model switching; ProfileStore clear credential method; tests first.
- [ ] Cross-review, full test/package checks, PTY verification, version patch; commit and push; CI green; publish patch artifacts.
