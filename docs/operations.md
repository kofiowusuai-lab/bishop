# Operations and recovery

## Local state

Use `bishop --home PATH ...` for a separate installation. Default `~/.bishop` contains:

- `config.json`: model endpoint, credential environment names, tool flags and Telegram allowlist.
- `runtime.db`: conversations, tool calls/results, approvals, run status and leases.
- `profiles.json`: named endpoints, models, protocol and selected profile; no key values.
- `credentials.json`: private API keys bound to exact endpoint/protocol.
- `auth/chatgpt.json`: Bishop-owned OAuth registration and rotating tokens.
- `memory.db`: explicit actor-scoped memories.
- `audit.db`: AEK checkpoints, reviews and sanitized sync outbox.
- `telegram.db`: authorized inbox, cursor, delivery journal and poller lease.
- `responses/`: final response evidence.
- `workspace/`: shared operator work files.
- `skills/NAME/SKILL.md`: owner-installed skill instructions.

Runtime home and databases are created with private permissions. Content is not encrypted at rest. Keep the home outside Git. Stop Bishop before a consistent backup of the entire home; SQLite WAL/SHM files may exist while running. Do not copy only the main DB files from a live process.

## Run states

`completed` stores a final answer. `awaiting_approval` needs exact-call approval or denial followed by explicit resume. `needs_reconciliation` means an interrupted non-idempotent call might already have happened. `failed` and `step_limit` are terminal; inspect them, then create a new task deliberately. Provider requests are never retried automatically after an interrupted response.

When an action's outcome is unknown, inspect the filesystem or external service first. Supply an accurate result to Bishop; this records your observation without rerunning the action:

```sh
bishop reconcile RUN CALL --result-file inspected-result.txt
bishop resume RUN
```

For a Telegram-owned run, a trusted local host operator can specify its actor:

```sh
bishop --actor telegram:USER_ID reconcile RUN CALL --result-file inspected-result.txt
bishop --actor telegram:USER_ID resume RUN
```

Local CLI access is privileged filesystem access. It is not a separate authentication boundary. Telegram users cannot change their actor.

Read/idempotent tool calls may be replayed after an interrupted operation. Non-idempotent writes/commands are never replayed automatically. Lease protection prevents concurrent local run owners for a bounded period (600 seconds, renewed before each operation). Built-in model/tool timeouts are shorter. Custom injected providers/tools must honor bounded timeouts shorter than the lease. A dead worker's leased run may require waiting for expiry before explicit recovery; status reads do not execute work.

## Telegram recovery

An interrupted inbox item is not blindly submitted as another agent task. Bishop reports the active run if present; otherwise it tells the operator to inspect status and explicitly resubmit if appropriate. `/status RUN` can retrieve an owned completed run after interrupted delivery.

Stop the Telegram poller before using the local `telegram --deliveries` or `--resolve` commands; administrative access currently takes the same single-poller lease. Only uncertain deliveries can be resolved as `sent` or `retry`. The retry choice explicitly permits a possible duplicate. Later chunks wait behind unresolved predecessors. Revoked users' queued work is discarded after restart; historical inbox records are retained locally.

The Telegram lease conservatively treats a live recorded PID as an active poller, including during long model calls. Rare operating-system PID reuse can block a restart. Verify that the old Bishop poller is gone, back up state, and remove only the stale `lease` row from `telegram.db`'s `meta` table before restarting. Never clear a live poller's lease. This is a single-machine guard, not distributed orchestration.

Polling stops after three consecutive transport failures with bounded backoff. Restart explicitly after inspecting the failure; normal successful long polling continues until stopped. No automatic boot daemon is installed.

## Current boundaries

This alpha has no automatic self-training, scheduler, subagents, voice, browser tool, container sandbox, multi-tenant RBAC or semantic success evaluator. Skills/memory are untrusted context. It does not import private Hermes history or modify an existing Hermes installation.

Live model tool quality and real Telegram delivery need operator-configured credentials and a separate live acceptance pass. Offline demonstration and fake transport tests cannot establish those results.
