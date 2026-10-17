# Bishop command reference and Hermes comparison

Bishop is an independent runtime. A similar command name does not imply Hermes feature parity. Commands below run in your terminal, outside the conversation. Use `bishop --home PATH COMMAND` for a separate state directory.

## Working operator commands

| Command | Behavior |
| --- | --- |
| `bishop`, `bishop chat` | Interactive conversation; `chat TEXT` sends one turn. |
| `bishop model` | Open the active provider model catalog directly; choose a model through searchable menus. |
| `bishop setup` | Add a provider/key using the setup wizard and live model catalog. |
| `bishop providers list/add/select/use/remove` | Manage saved provider configurations; these share the current runtime home. |
| `bishop login`, `bishop auth login` | Bishop-owned ChatGPT OAuth and account model selection. API keys use setup. |
| `bishop logout`, `bishop auth logout` | Clear Bishop-owned ChatGPT authentication. Saved API keys are separate. |
| `bishop auth status` | Inspect ChatGPT authentication without printing tokens. |
| `bishop config`, `bishop config show` | Inspect sanitized configuration; does not change settings. |
| `bishop status` | Inspect local runtime configuration and component readiness. |
| `bishop status RUN` | Inspect a persisted run and its pending approvals. |
| `bishop doctor` | Offline configuration/readiness checks; does not call a model or repair settings. |
| `bishop tools`, `bishop tools list` | List enabled built-in tools and their risk classifications. |
| `bishop skills`, `bishop skills list` | List owner-installed skill instructions. |
| `bishop skills show NAME` | Read bounded skill instructions; never execute skill scripts. |
| `bishop monitor` / `bishop monitoring` | Inspect default task monitoring, history, destinations and delivery recovery. |
| `bishop monitor configure` | Enable/disable native monitoring or individual destinations through choices. |
| `bishop sessions` | List persisted sessions. |
| `bishop approve RUN CALL`, `bishop deny RUN CALL` | Record an operator decision for an exact tool call. |
| `bishop resume RUN` | Continue a run; this is not a system-wide emergency resume. |
| `bishop reconcile RUN CALL --result-file PATH` | Record an inspected result for an ambiguous tool outcome. |
| `bishop telegram` | Run the allowlisted Telegram polling gateway. |
| `bishop telegram --once` | Run one polling cycle. |
| `bishop telegram --deliveries` | Inspect durable Telegram message deliveries. |
| `bishop telegram --resolve ID --action sent\|retry` | Explicitly resolve uncertain delivery; retry may send another message. |
| `bishop audit` | Inspect pending sanitized AEK audit events. |
| `bishop review RUN --report PATH` | Attach independent QA evidence to audit history. |
| `bishop sync` | Send one bounded audit batch to the configured hub. |
| `bishop init`, `bishop demo`, `bishop preview` | Initialize a home, run an offline diagnostic, or display startup branding. |
| `bishop --help`, `bishop COMMAND --help` | Show available syntax. |

Read-only operator reports do not authenticate or make model requests. Doctor readiness is an offline check, not proof that a remote provider or gateway is reachable.

## Remaining Hermes command families

The following are a capability map, not executable Bishop commands.

| Hermes commands | Bishop equivalent or remaining work |
| --- | --- |
| `moa`, `fallback` | Planned: orchestration and explicit fallback policy. Current runtime uses one selected provider. |
| `auth add/list/remove/reset` | Partial: `providers` manages independently configured keys; credential pooling/rotation is not implemented. |
| `config set/edit` | Partial: sanitized inspection exists; validated configuration editing needs a separate interface. |
| `profile` | Partial: use `--home` for isolated state. Provider profiles select credentials/models within one home. |
| `gateway` | Partial: `telegram` provides one foreground polling service. Service installation and multi-platform lifecycle are planned. |
| `proxy` | Planned: OpenAI-compatible inference proxy. |
| `whatsapp`, `whatsapp-cloud`, `slack`, `send` | Planned: messaging adapters and explicit outbound delivery. Discord also needs an adapter. |
| `pairing`, `peer` | Partial: Telegram has a configured numeric user allowlist. Pairing codes and bot-to-bot transport are planned. |
| `portal` | Planned: provider-specific tool gateway integration. |
| `pause`, system-wide `resume` | Planned: durable emergency-stop policy. Existing `resume RUN` only resumes that run. |
| `cron`, `webhook`, `kanban` | Planned: scheduling, authenticated webhook subscriptions and collaboration board. |
| `project` | Partial: each home has one workspace. Named multi-folder projects are planned. |
| `hooks`, `worktree`, `browser`, `lsp` | Planned: managed shell hooks, worktree maintenance, browser profiles and language servers. |
| `secrets`, `egress` | Partial: private saved keys and environment references exist. External vaults and credential injection firewall are planned. |
| `skills search/install/configure` | Partial: local list/read is implemented. Registry discovery and trusted installation are planned. |
| `bundles`, `plugins`, `curator` | Planned: packaging, plugin validation and skill maintenance. |
| skill `sync` | Planned. Bishop's current `sync` sends audit events, not skills. |
| platform-specific `tools` configuration | Partial: tools inspection exists; configuration flags control write/command exposure globally per home. |
| `mcp`, `computer-use` | Planned: MCP client/server and computer-control backends. |
| external `memory`, `journey` | Partial: actor-scoped local memory tools exist. External providers and a learning timeline are planned. |
| `pets`, `skin` | Partial: Bishop has its own boot identity. Mascot browsing and theme management are planned. |
| advanced `sessions` operations | Partial: list exists; browse/rename/export/prune/delete need explicit interfaces. |
| `insights`, `monitoring`, `logs` | Partial: native task monitoring, lifecycle history and delivery recovery are implemented through `monitor`. Usage analytics and general diagnostic logs remain to build. |
| `verify`, `security`, `approvals` proposals | Partial: runtime verifies persistence/audit checkpoints. Project smoke tests, vulnerability scanning and approval proposals are planned. |
| `dump`, `debug`, `prompt-size` | Planned: sanitized support bundles and prompt accounting. |
| `backup`, `import`, `checkpoints` | Planned: portable backup/restore and filesystem checkpoint management. Current run persistence is not a backup system. |
| `import-agent`, `claw`, `migrate` | Planned: explicit migration tools. Bishop does not silently import another agent's credentials. |
| `console` | Partial: interactive chat exposes slash commands. A separate safe administration console is planned. |
| `dashboard`, `serve`, `desktop/gui`, `acp` | Planned in Bishop. AEK's separate audit dashboard does not supply these Bishop runtime interfaces. |
| `completion` | Planned: shell completion generation. |
| `update`, `uninstall` | Use the installation tool: `uv tool upgrade bishop-runtime` / `uv tool uninstall bishop-runtime` for uv tool installs. Checkout installs use their own update process. |

Future command families should ship with real implementations, persistence rules, authorization, failure recovery and end-to-end checks before appearing as working commands.

## Implementation order for the remaining systems

1. Default runtime task monitoring is implemented: durable lifecycle events, terminal progress, edited Telegram cards and explicitly configured Discord/WhatsApp progress transports. Outbound progress does not imply a full inbound chat gateway.
2. Messaging gateway lifecycle: common channel interface, routing, pairing/revocation and durable delivery recovery, then Discord and WhatsApp inbound adapters.
3. Operations: emergency pause, scheduled jobs, authenticated webhooks and named projects, with explicit crash-recovery and authorization policies.
4. Extensions: trusted skill installation, MCP, plugin boundaries and computer tools.
5. Hosted interfaces: headless API, dashboard and desktop clients over the same runtime authorization boundary.

Each step should preserve Bishop's independent agent loop and exact-call approvals. Feature names enter CLI help when their implementations are usable.
