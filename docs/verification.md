# Local verification — 2026-10-17

Bishop 0.1.0 was validated on macOS with Python 3.12.13.

- 61 tests passed with ResourceWarning promoted to errors.
- Built the source distribution and wheel.
- Installed the wheel into a separate fresh virtual environment, resolving AEK from its public pinned Git commit rather than the local checkout.
- Ran the same 61 tests against that installed wheel from outside the Bishop source directory.
- Installed `bishop demo` completed real read/write approval, restart persistence and pending AEK audit checks without credentials.
- Gitleaks directory scan found no leaks; Git whitespace check passed.
- Independent cross-review covered runtime recovery, tools and Telegram; identified symlink, bounded directory scan, queued revocation and multipart uncertainty issues were fixed with regressions.

Live model calls, real Telegram delivery and a live dashboard ingestion pass were not performed. CI matrix configuration is included; hosted CI has not run because this standalone project has not been published.

## Bishop 0.2 terminal/provider update

The update adds branded boot and interactive chat, exact inline approvals, named provider/key profiles, native Anthropic Messages and Bishop-owned ChatGPT OAuth/public Responses support. Verification includes actual PTY arrow navigation, private profile endpoint binding, simulated browser callbacks, signed JWT identity validation, account model catalog parsing and continuation state across an actual approval/restart.

104 tests pass locally. Wheel installation, boot preview and offline demo are validated in a separate environment. Live ChatGPT authorization, provider inference and real Telegram remain unverified. No existing Hermes/Codex credentials were imported.

## Bishop 0.2.1 choice-driven setup

142 tests pass locally, including a matrix for every supported provider/preset and all custom transport kinds. Real PTY tests cover search, scrolling, rapid arrows, cancellation and zero-size terminal fallback. Live public OpenRouter/OpenCode catalogs were read without keys or inference. API keys remain staged until the model choice is confirmed, and stale preset routing cannot redirect a saved key. Unsupported generation/batch/native protocols are excluded from the picker.

The update adds API-key Responses support and Bishop-specific OpenCode conversation headers. Real authenticated model inference remains outside this verification.

## Bishop 0.2.2 visual identity

148 tests pass locally. Identity, sanitization, width bounds, monochrome, truecolor and indexed-color fallback are covered. Actual terminal output was rendered and visually reviewed at 80, 100 and 200 columns, and preview startup was checked through a PTY. The SVG logo and terminal mark were reviewed together. Preview PNG metadata identifies Bishop/Kedolabs; the displayed profile is an example.

## Bishop 0.3.0 operator commands

161 tests pass locally with ResourceWarning promoted to errors, including 13 new operator-command regressions. Model selection and ChatGPT login/logout aliases delegate to existing flows. Offline status, doctor, configuration, tools and skills inspection are checked without constructing providers, making network requests or mutating initialized/uninitialized homes. Doctor and live providers share pure transport validation. Tests cover malformed URL types, invalid active profiles, secret-bearing endpoint redaction, skill symlink rejection and Markdown preservation.

Independent review identified incomplete profile validation and malformed URL handling; both are fixed with regressions. Gitleaks found no leaks and Git whitespace checks pass. Live authentication and provider inference were not performed for this command release. The command reference explicitly identifies unimplemented Hermes subsystems.

## Bishop 0.3.1 direct model selection

164 tests pass locally. `bishop model` and interactive `/model` open the active provider's catalog directly; `bishop providers select` keeps saved-provider switching available. New regressions verify no extra provider/action menus, cancellation without changes, saved-key retention and the correct home for ChatGPT's account catalog. Independent review found no remaining actionable regressions. One initial full-suite run hit the existing command-tool test's 0.2-second interpreter-start timeout; the isolated tool suite and complete rerun both passed. No live model inference or authentication was performed.

## Bishop 0.3.2 missing-key preflight

168 tests pass locally. An OpenCode Go profile without a configured credential now fails before live adapter construction, with private setup guidance. Doctor warns about the missing key. Regression coverage spans known paid presets, saved keys, keyless local/free/custom routes and sanitized doctor output. Independent review confirmed exact route matching does not widen credential routing. Secret scan passes. The reported user's active Go profile was inspected through credential-presence metadata only; no keys were imported and no paid inference request was made. Successful real inference still requires the user to enter their key.

## Bishop 0.4.0 bundled task monitoring

209 tests pass locally and against the final wheel in a fresh virtual environment outside the source checkout, with ResourceWarning promoted to errors. The installed wheel contains `builtin_skills/task-monitor/SKILL.md`; skill inspection works without creating a home. An actual PTY verified live model-wait, elapsed heartbeat and completion output.

Tests cover real runtime lifecycle/audit ordering, approval/resume card reuse, blocked-provider live notification, scoped Telegram delivery, secret exclusion, uncertain creation/restart/adoption, coalesced edits, Discord mention suppression, WhatsApp bridge payload/rollover, readonly monitor commands, config opt-out, owner skill precedence and stdout JSON/stderr progress separation. Telegram edit retries accept the bounded already-current response. A corrupt optional journal warns without preventing the task.

Independent review found and verified fixes for premature completion on audit resume, unbounded observer unsubscribe, journal retention and an admin delivery-recovery race. Package builds, secret scan and whitespace checks pass. Discord and WhatsApp are outbound progress adapters requiring explicit configuration; full inbound gateways are not included. Real remote messages and paid inference were not sent during this verification. Final answers retain the existing durable channel delivery path.
