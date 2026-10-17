---
name: task-monitor
description: Default factual task progress for Bishop in terminal and configured messaging destinations.
---

# Task Monitor

Bishop's native runtime starts monitoring automatically. You do not need to invoke a shell script or send progress messages yourself. Every installation includes these instructions and the native progress journal.

Report only observed lifecycle facts: a model request is in progress, a named tool is running, operator approval is required, reconciliation is required, or the run has completed or failed. Elapsed-time heartbeats indicate waiting, not additional work or proof of success. Completion is shown only after the durable response and audit checkpoint succeed; it does not certify factual correctness.

One run keeps one progress identity across approval and resume. Terminal updates appear automatically. Telegram updates the originating authorized chat. Discord webhooks and a compatible WhatsApp bridge are optional outbound progress destinations, configured by the operator. Never select another user's chat, copy credentials from another agent, or read Hermes/OpenClaw environment files.

Do not expose task prompts, tool arguments, tool output, secrets, private reasoning or unverified claims in progress. Transport failures must never trigger a model retry or replay a tool. An uncertain initial message send requires explicit operator recovery, not a blind duplicate send. Progress visibility is separate from the final task result.

Operators can inspect `bishop monitor status`, `bishop monitor runs`, and `bishop monitor events RUN_ID`. `bishop monitor configure` provides destination choices. Skills are instructions, not authorization to bypass exact-call tool approvals.

Adapted for Bishop from the task-monitor workflow maintained at https://github.com/kofiowusuai-lab/task-monitor-agent (reference c77f46ced706f1c8a09bd60e0d682abf46b6f7f7). Bishop uses its own runtime events, configuration and credentials; the standalone upstream CLI is not required.
