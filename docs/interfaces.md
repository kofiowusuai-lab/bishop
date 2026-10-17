# Shared implementation interfaces

## Provider (integration lane)

`provider.complete(messages:list[dict], tools:list[dict])->dict` returns `{content:str|null, tool_calls:[{id:str,name:str,arguments:dict}]}`. Tools are chat-completions function definitions. Provider responses are validated before return. The runtime creates the provider wire assistant/tool messages itself; stringifies function arguments when replaying a model response. No model/network retry by default. `ScriptedProvider(responses)` supports deterministic tests and demos. `HTTPProvider(base_url,model,api_key=None,timeout=30,max_tokens=1024)` speaks `/chat/completions` below the configured base URL.

## Tool registry (tools lane)

`MemoryStore(path)` with `remember(scope,text)->dict`, `search(scope,query,limit=10)->list[dict]`, `close()`.

`ToolRegistry(workspace,memory,skills_dir,allow_write=True,allow_command=False,max_output_chars=16000,command_timeout=15)`.
- `definitions()->list[dict]` advertised chat-completions tools; hidden disabled tools cannot be invoked.
- `describe(name)->dict` returns `{risk:'read'|'write'|'command',idempotent:bool}`. Unknown/disabled tools raise ValueError.
- `validate(name,arguments)->dict` rejects extra fields and wrong types; returns a detached normalized copy.
- `invoke(name,arguments,scope='local')->str` validates again and returns bounded text (JSON for structured results). Risk enforcement belongs to the runtime; direct registry callers are trusted operators.

Tool argument schemas: list_files `{path?:str}`; read_file `{path:str}`; write_file `{path:str,content:str}`; run_command `{argv:list[str]}`; memory_search `{query:str}`; memory_remember `{text:str}`; list_skills `{}`; read_skill `{name:str}`. write_file and run_command are non-idempotent. memory_remember may be idempotent by scope/text. All non-read risks still require approval.

## Runtime (runtime lane)

`Runtime(home,provider,tools,max_steps=12,history_turns=8)` creates `home/runtime.db`, private response artifacts, and `home/audit.db` (AEK).
- `run(session_id,text,actor='local')->RUN`
- `resume(run_id,actor='local')->RUN`
- `approve(run_id,call_id,actor='local')->RUN` records approval, does not itself execute.
- `deny(run_id,call_id,actor='local')->RUN`
- `reconcile(run_id,call_id,result,actor='local')->RUN` records an operator-inspected result for an ambiguous call.
- `status(run_id)->RUN`, `active(session_id,actor='local')->RUN|None`, `sessions()->list[dict]`, `close()`.

RUN: `{id,session_id,actor,status,output:str|null,error:str|null,pending:[{id,name,arguments,arguments_hash,risk}],...}`. Status: completed, awaiting_approval, failed, needs_reconciliation, step_limit, running. Error strings must be sanitized categories, not credentials or provider raw bodies. Approval authorization matches exact actor plus persisted argument hash. Status reads do not perform network/tool work. Failed or budget-limited turns require explicit handling, never an infinite recovery loop.

## Telegram (Telegram lane)

`TelegramClient(token,base_url='https://api.telegram.org',timeout=35)` with `get_updates(offset,timeout=25)->list[dict]`, `send_message(chat_id,text)->dict`. Disable redirects and sanitize all errors so token-bearing URLs never appear. Private text messages only; payloads/bodies bounded. Message splitting must respect Telegram's limits without silently dropping output.

`TelegramService(home,client,runtime,allowed_users:list[int])` with `poll_once()->dict` and `serve()->None`, `close()`. State in `home/telegram.db`; durable inbox, cursor, outbox and service lease. `poll_once` obtains one bounded batch and processes queued work. `serve` uses bounded consecutive-failure retry/backoff. Owner actor format `telegram:USER_ID`, session `telegram:CHAT_ID`. Do not persist denied users' text. A second pending run in a session must queue or return a truthful active-run response, not interleave tool histories.

Incoming update IDs are idempotent. Outgoing text is persisted before send; in-flight sends after timeout/crash become uncertain. Provide `deliveries()->list[dict]` and `resolve_delivery(delivery_id,action)` where action `sent` marks operator-confirmed delivery and `retry` explicitly permits another attempt. Never claim exactly-once send. Telegram polling is optional and not started by init or demo.

## Integration lane ownership

Config, HTTP provider/transport, CLI, offline demo, docs, packaging, CI and integration tests. Runtime lane owns runtime.py/state.py/tests runtime. Tools lane owns tools.py/memory.py/skills.py/tests tools. Telegram lane owns telegram.py/channel_state.py/tests telegram. No overlapping writes and one Git integration lane.
