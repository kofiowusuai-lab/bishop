# Provider model discovery

Setup performs bounded catalog GET requests, with no inference and no guessed model IDs. Catalog failures are recoverable through Retry or Back. There is no static model fallback.

- Ollama and LM Studio enumerate installed models through their compatible `/models` endpoint.
- OpenRouter uses its [model catalog](https://openrouter.ai/docs/api-reference/models/get-models), filtering advertised tool support and text-only output. Vision-capable input remains eligible. Image/audio generators and [batch-only variants](https://github.com/OpenRouterTeam/docs/blob/main/faq.mdx) are excluded.
- OpenAI API uses its model catalog and conservatively excludes non-chat families. Current GPT and o-series families use the Responses adapter; older GPT families retain chat completions. See the official [Responses migration guide](https://developers.openai.com/api/docs/guides/migrate-to-responses).
- Anthropic uses its [native catalog](https://docs.anthropic.com/en/api/models-list), API headers and bounded pagination.
- Custom compatible endpoints use `/models`; they must expose a catalog for menu setup.
- OpenCode uses the current [Zen catalog](https://opencode.ai/inference/v1/models) or Go catalog at `/inference/go/v1/models`. Because catalog rows currently omit transport metadata, Bishop joins IDs with the live official [endpoint table](https://opencode.ai/v2/docs/console/models/) or [Go endpoint table](https://opencode.ai/v2/docs/console/go/). Only supported transports are selectable: chat completions, Anthropic Messages and Responses. Native Google and SystemOne routes require additional adapters and are excluded. Unknown routes are excluded rather than guessed.

OpenCode Free selects only explicit free IDs or rows with zero input and output prices. Availability and pricing can change; the current catalog does not guarantee future free usage. Go requests identify Bishop and carry a stable conversation session header as described in the official Go documentation.

Requests refuse redirects, bound response sizes, paginate at most 20 pages, and show sanitized errors. Credentials are never attached to OpenCode's public catalog or routing-document requests. Model display labels reject terminal control characters.
