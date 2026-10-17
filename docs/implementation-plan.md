# Bishop implementation plan

1. Runtime lane: write failing tests for a real provider/tool loop, persistence, approvals, recovery and budgets; implement runtime/state against interfaces.md. Integrate AEK checkpoints and sanitized events. No provider transport, CLI or tools-module edits.
2. Tools lane: write failing workspace/memory/skills/command tests; implement strict registry, bounded filesystem/process handling, scoped memory and explicit skill loader. No arbitrary Python evaluation or automatic skill scripts.
3. Telegram lane: write failing fake-Bot-API/ownership/durability tests; implement standalone transport and durable inbox/outbox/service lease. No use of existing bot credentials or real external messages.
4. Integration lane: implement provider/config/CLI after failing acceptance tests. Supply offline scripted demo, manual QA/sync commands, setup/docs and optional Docker instructions. Build package with pinned AEK dependency and test a clean wheel outside the repository.
5. Cross-review spec compliance and code quality. Resolve findings, run deterministic end-to-end tests and privacy scan, commit as the human identity. Report precisely what runs offline and what still needs live model/bot configuration.

No live API spend, model downloads, bot registration, hosted deployment or public repository creation is part of this local build.
