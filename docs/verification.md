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
