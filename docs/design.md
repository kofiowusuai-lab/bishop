# Bishop independent runtime v0.1

Bishop owns its conversation loop, provider calls, tool dispatch, approval lifecycle, persistent state and Telegram adapter. It does not import or delegate execution to Hermes, Eve, LangChain or another agent runtime. Agent Experience Kit is its checkpoint/QA/audit library, pinned to a released commit. One standalone Python project, MIT-licensed, Python 3.10+.

## Working scope

CLI chat and interactive mode; a tool-calling HTTP provider interface compatible with the documented chat-completions subset used by local Ollama; deterministic offline demo; persistent conversations and per-turn checkpoints; workspace file tools; explicit approvals for writes/commands; scoped persistent memory; owner-provided SKILL.md files; independent Telegram polling; optional sanitized AEK audit sync. No model credits, existing bot credentials or private Hermes data are used during development.

Default provider origin is local loopback; no model is silently selected. Model and credential references are configured explicitly. Telegram requires a new token and numeric allowed-user IDs. No live bot is activated during this build. Provider support means the documented protocol, not universal compatibility with every model/vendor.

## Runtime and recovery

A turn is a durable run bound to a session and actor. Persist a model response and its tool calls before executing them. Persist each call's argument hash and running state before invocation, then its result. Reuse persisted results after restart; never replay an ambiguous non-idempotent running call automatically. Such calls enter needs_reconciliation. Read-only calls may be repeated safely. Approval is bound to exact run/call/arguments and owner actor; a model cannot approve itself. Explicit local reconciliation supplies an inspected result before resuming.

Bound model steps, calls, input/output size and HTTP/tool timeouts. Active-session/run leases prevent concurrent owners; lease expiry permits deliberate recovery. No network request holds a SQLite transaction. Previous context includes bounded completed user/final-answer pairs, while full current tool history remains persisted. Do not truncate in the middle of a tool-call protocol sequence. Provider failures stop and preserve diagnostic categories; no blind paid retries.

Persisted final output is written as local response evidence and checkpointed through AEK. Acceptance checks prove persistence and absence of unfinished calls, not factual correctness. Explicit independent QA records can be attached afterward and synchronized. Tool outputs and remembered facts are untrusted content, not authority to change policy.

## Tools, memory and skills

Tool definitions use strict argument schemas and deterministic validation. Builtins: list_files, read_file, write_file, run_command, memory_search, memory_remember, list_skills, read_skill. Read tools are automatic; writes, memory additions and commands require exact-call approval. Commands are hidden and disabled unless the operator enables them. File paths resolve inside an explicit workspace and reject traversal, static symlink escapes and hidden credential/state paths. Commands use argv without a shell, minimal environment, bounded capture and timeout. These controls are not an operating-system sandbox; enabling commands grants powerful host access.

Memory is scoped by actor, allowing continuity across that actor's sessions. Skills are explicitly owner-installed instructions, loaded as files; no skill scripts are automatically executed. No automatic raw history import or self-modification of policy exists. Multiple allowed Telegram users are trusted operators of a shared workspace, not isolated tenants.

## Telegram

Private text messages only in v1. Allowlist the sender and require a private chat. Persist authorized updates in an inbox before advancing the getUpdates cursor. Deduplicate by update ID and claim work durably. Persist outgoing responses before attempting delivery. A timeout/crash during send is marked uncertain and not blindly resent; operators reconcile delivery explicitly. This is not an exactly-once transport.

Commands: /start, /status, /approve RUN CALL, /deny RUN CALL, /resume RUN. All run operations verify actor ownership. Ordinary text uses a chat-bound session. No Telegram-provided text becomes a shell command or approval without the explicit command parser and ownership check. Poll transport failures use bounded backoff, then stop; normal service polling may continue until interrupted. A second poller is refused by a durable service lease.

## Packaging and boundaries

Own CLI `bishop`, module `bishop_runtime`, local home defaults to ~/.bishop with a separate workspace and private state. Secrets live in environment variables, not config or traces. Bootstrap/demo are offline. Do not replace existing Hermes processes or tokens. Build and commit locally; public Bishop publication and live credentials are separate configuration actions.

## Acceptance

Tests prove real loop/tool use, conversation persistence, no duplicate execution after restart, approvals and argument-hash binding, ambiguous side-effect recovery, budgets, session concurrency, workspace escapes, bounded command capture, memory scoping, skills loading, provider HTTP protocol/errors/redirect rejection, Telegram allowlists/inbox/outbox/cursor recovery and sanitized AEK audit integration. Offline demo and clean installed-wheel use must work without credentials. Live model quality and actual Telegram delivery remain unverified until configured explicitly.
