# Bishop command interface implementation plan

Goal: expose working operator commands for existing Bishop systems, preserving existing syntax and credential isolation.

Architecture: CLI aliases delegate to existing onboarding/auth flows. A separate operator module supplies offline, sanitized status/configuration/doctor/tools/skills reports without constructing a model provider. Configuration inspection never returns credentials, endpoint query strings or private model request content.

- [x] Write failing CLI tests for `status` without a run, `doctor`, `config`, `tools list`, `skills list/show`, `model`, `login`, and `logout` parser aliases.
- [x] Implement offline operator reports and additive CLI dispatch. Keep `status RUN`, `auth login/logout/status`, and all approval/resume behavior unchanged. `model` reuses the existing searchable selection flow. Login accepts existing auth flags.
- [x] Verify invalid skill names, malformed config, uninitialized homes and synthetic secret redaction. Doctor reports checks with explicit pass/warn/fail; a missing provider is a warning, invalid configuration fails with nonzero exit. No network probe or automatic repair.
- [x] Document every supplied Hermes command by working Bishop equivalent, partial equivalent, or planned subsystem. Explain provider profiles versus isolated runtime homes and audit sync versus skill sync.
- [x] Run focused CLI tests and full unittest suite, build wheel, inspect diff, commit and push. Confirm GitHub CI before declaring published checks successful.

Ownership: builder owns CLI/operator implementation and tests; root owns documentation, integration and publishing. No external channel sends, authentication, or credential mutation during verification.
