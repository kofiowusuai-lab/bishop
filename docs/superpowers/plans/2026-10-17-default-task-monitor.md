# Default Bishop task monitoring

Goal: include task-monitor instructions in every wheel and provide real progress automatically through Bishop's own runtime, without relying on model tool calls or another agent's credentials.

Architecture: a private progress journal records sanitized lifecycle facts after durable runtime transitions. A background dispatcher coalesces scoped subscribers and provides elapsed-time heartbeats while model/tools block. Terminal chat subscribes by actor/session; Telegram subscribes only for the authorized originating user/chat. Completion is reported only after the response audit checkpoint succeeds. Visibility failures never replay model requests or tool calls.

Interfaces:
- `ProgressMonitor(home, heartbeat_interval=10)` owns `progress.db` and a dispatcher. `emit(run, phase, tool=None)` extracts only run_id, actor, session_id, status, phase, tool, step, created, updated, elapsed, sequence. No prompts/arguments/results/hidden reasoning. `subscribe(callback, actor=None, session_id=None)` is a context manager; `flush(timeout=5)`, `runs(limit=100)`, `events(run_id,limit=100)`, `close()` expose bounded observation. Sinks receive snapshot dictionaries. Runtime `progress=None` creates this default; `progress=False` disables it. Runtime owns/closes only its default monitor.
- `ProgressCards(home, send, edit, channel, target, authorized=None, rollover_seconds=None)` is a callable snapshot sink. Send returns a message ID; edit accepts `(message_id,text)`. Persist creation intent before network send. Ambiguous creation never retries blindly. Reuse the same card on resume; edits can retry idempotently. Persist only destination hashes, generic text and IDs; never webhook/token URLs. `render_progress(snapshot)` renders bounded generic factual cards.
- `TerminalProgress(output)` is a callable sink. TTY updates one line; redirected output emits bounded plain lines. One-shot chat sends progress to stderr to preserve stdout JSON.
- Built-in `task-monitor` instructions load through package resources; owner-installed instructions take precedence for reading without silently replacing files. Native monitoring remains independent of skill text. Default system guidance explains factual lifecycle-only progress.

Ownership:
1. Core builder: progress.py, runtime.py and core/runtime monitoring tests.
2. Transport builder: progress_transports.py and transport tests only.
3. Root integration: bundled skill/package data, config/CLI/operator, shell, Telegram, docs and release.

Verification: test blocking-provider heartbeats, approval/resume and audit failure order, sink isolation, bounded secret-free journal, actor/session isolation, create-time uncertainty/restart, edit reuse, WhatsApp rollover, Discord mention suppression, disabled mode, wheel resource presence, terminal JSON separation and real-runtime fake Telegram flow. No real channel messages or paid inference during tests.

Remote progress destinations are opt-in environment references in Bishop configuration. Discord webhooks and the task-monitor-compatible WhatsApp bridge provide outbound progress only, not inbound agent gateways. WhatsApp bridge rollover remains explicit. No Hermes/OpenClaw environment fallback.
