# Bishop terminal and provider setup implementation plan

**Goal:** Make Bishop launch as an interactive branded agent with saved model/provider profiles and a documented OAuth route.
**Architecture:** Terminal rendering is separate from chat control. Profiles and credentials resolve to existing provider.complete interface. Native Anthropic adapter translates tool history; OAuth research determines independently registered authentication support.
**Tech Stack:** Python stdlib, existing Bishop/AEK, unittest fake transports.

- [ ] Terminal lane: tests first; original dot chess Bishop, responsive banner/panel, ANSI sanitization, no-color and non-TTY behavior.
- [ ] Providers lane: tests first; named profiles, atomic config/secret persistence, native Claude adapter and preset endpoints checked against primary docs. Preserve legacy configuration.
- [ ] Authentication lane: official documentation and local non-secret capability inspection; implement independently registered supported OAuth if feasible; fake transport tests. Never authorize real account.
- [ ] Integration: default interactive launch, setup menu/private keys, explicit provider selection, slash commands and inline exact approval. Existing JSON CLI remains stable.
- [ ] Verify: focused tests, full tests, actual PTY demo, package install, privacy scan and independent review; local human-authored commit. No publication/spend.
