# Default task monitoring

Every Bishop installation includes the `task-monitor` skill and native runtime monitoring. Existing homes inherit the enabled defaults without rewriting configuration. There is no separate CLI dependency, bot token or registration needed for terminal progress.

The native runtime emits factual lifecycle stages: starting, waiting for the model, running/finishing a tool, waiting for approval, requiring reconciliation, failed/interrupted, and completed. Elapsed-time heartbeats continue while a model or tool blocks. They indicate waiting, not additional work or proof of correctness. Completion follows successful response persistence and the AEK audit checkpoint.

Terminal chat updates a compact line; redirected output uses plain lines. `bishop chat TEXT` and `bishop resume RUN` keep progress on stderr and the result JSON on stdout. Each approval/resume retains its run ID. Models do not need to invoke a skill or remember to send updates.

## Telegram

With the existing allowlisted `bishop telegram` gateway, progress automatically creates one generic card in the originating private chat and edits that card through the run. Final answers and approval details retain the gateway's normal durable delivery path. Only an authorized user receives that run's progress. Restarting or resuming uses the stored message ID.

Telegram edits use the official [editMessageText API](https://core.telegram.org/bots/api#editmessagetext). No additional Telegram token is required beyond your explicitly configured Bishop bot. Real delivery still depends on that token, allowlist, connectivity and the running gateway.

## Optional Discord progress

Set the environment variable named by `monitoring.discord_webhook_env` (default `BISHOP_DISCORD_WEBHOOK_URL`) to your incoming Discord webhook URL, then run `bishop monitor configure` and choose **Enable discord progress**. Restart Bishop or its gateway.

This is outbound progress via a webhook, not a Discord conversation gateway. One card is created with `wait=true`, then edited; mention parsing is disabled. The implementation follows Discord's official [webhook execute/edit APIs](https://docs.discord.com/developers/resources/webhook). Webhook secrets stay out of configuration and progress journals; the destination is represented by a hash in recovery commands.

## Optional WhatsApp progress

Use a task-monitor-compatible WhatsApp bridge. Set the variables named by `monitoring.whatsapp_bridge_env` and `monitoring.whatsapp_chat_env` (defaults `BISHOP_WHATSAPP_BRIDGE_URL` and `BISHOP_WHATSAPP_CHAT_ID`). Run `bishop monitor configure`, choose **Enable whatsapp progress**, and restart Bishop.

The bridge contract is:

- POST `/send` with `{chatId, message}`; return `{ok: true, messageId}`.
- POST `/edit` with `{chatId, messageId, message}`; return `{ok: true}`.

Remote bridges require HTTPS; loopback HTTP is allowed. This contract comes from the user's [task-monitor-agent workflow](https://github.com/kofiowusuai-lab/task-monitor-agent), reference `c77f46ced706f1c8a09bd60e0d682abf46b6f7f7`. Cards roll over after 840 seconds to respect the bridge's edit window. This is not WhatsApp Business Cloud API or a bundled inbound WhatsApp gateway. Bishop never reads Hermes/OpenClaw environment files or imports their tokens.

Optional Discord/WhatsApp destinations receive generic lifecycle updates for runs executed by that configured runtime. They receive no task prompts, tool arguments/results, model output or private reasoning. Explicitly configure a destination appropriate for the users sharing that Bishop home.

## Inspection and configuration

```sh
bishop skills list
bishop skills show task-monitor
bishop monitor status
bishop monitor runs
bishop monitor events RUN_ID --limit 100
bishop monitor deliveries
bishop monitor configure
```

`bishop monitoring` is an alias for `bishop monitor`. Inspection commands neither initialize a home nor contact a model/channel. Environment readiness indicates that required variable values exist, not verified remote availability. The configure menu can disable the engine or individual destinations. Apply settings by restarting the process.

Configuration defaults:

```json
{
  "monitoring": {
    "enabled": true,
    "terminal": true,
    "telegram": true,
    "discord": false,
    "whatsapp": false,
    "heartbeat_seconds": 10,
    "discord_webhook_env": "BISHOP_DISCORD_WEBHOOK_URL",
    "whatsapp_bridge_env": "BISHOP_WHATSAPP_BRIDGE_URL",
    "whatsapp_chat_env": "BISHOP_WHATSAPP_CHAT_ID"
  }
}
```

## Failure recovery and storage

Monitoring is a visibility layer. Observer failures produce sanitized warnings and never replay a model request, re-run a tool, grant approval, or prevent the final answer from using its normal delivery path. A card whose initial send timed out is uncertain: Bishop will not blindly create another one, including after restart.

Inspect `bishop monitor deliveries`. To adopt a card that you can see on the platform:

```sh
bishop monitor resolve RUN_ID --channel telegram --destination HASH --action sent --message-id MESSAGE_ID
```

`HASH` is the full destination field returned by the deliveries command. If you explicitly decide that sending a replacement is appropriate:

```sh
bishop monitor resolve RUN_ID --channel telegram --destination HASH --action retry
```

Retry clears the creation intent; a future explicit resume/event may create a replacement. A duplicate is possible if the platform accepted the original request. This command itself sends nothing. Failed edits retain the known message ID and can be attempted again on later events; missing/deleted remote cards require operator attention rather than silent replacements.

Private `progress.db` retains up to 1,000 facts per run and approximately 100,000 globally. `progress-deliveries.db` keeps message IDs and destination hashes for recovery. Read commands return bounded results. These files are local observability state, not backups or a central dashboard. Owner-installed `task-monitor/SKILL.md` can take precedence when read, but cannot disable native monitoring or alter the approval boundary.
