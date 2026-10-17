# Independent web research

Bishop includes native `web_search` and `web_read` tools, enabled by default. They work in terminal conversations and the configured Telegram gateway. A bundled `web-research` skill and runtime guidance tell the model to search, read useful sources and cite the URLs actually used. Current tool definitions take precedence over older conversation claims that internet access was unavailable.

Start a fresh Bishop process after updating, then ask a concrete question:

> Research Hermes Agent from official sources. Explain its capabilities and cite what you read.

Use `/tools`, `/skills` and `/version` inside chat to inspect the running process. `/version` also compares the installed package version so future updates can be distinguished from a still-running older session. The boot screen lists the actual tools and skills.

## Tools

`web_search` accepts a nonempty `query` of up to 1,000 characters. It returns ordered titles, source URLs, bounded snippets and a retrieval timestamp. Results are discovery leads, not proof that the full source was read.

`web_read` accepts a public HTTP(S) `url`. It returns the final URL, title, extracted text, content type, retrieval timestamp and an explicit truncation flag. Substantive main content takes priority over navigation and unrelated article teasers. HTML, plain text, Markdown and JSON are supported. Scripts are not executed; authenticated browser sessions, JavaScript rendering and binary/PDF extraction are outside these tools.

Network failures, challenges, unsupported content and size limits become structured tool data so the model can try another relevant source within its existing step budget. They do not automatically abort the entire run. Source metadata is retained when content is trimmed; if even the citation metadata cannot fit, the tool reports `web_output_limit` rather than returning a source-less fragment.

## Search providers

The default is [DuckDuckGo Lite](https://duckduckgo.com/duckduckgo-help-pages/features/non-javascript), which needs no additional key. Public search can challenge, rate-limit or change its markup; keyless availability and ranking quality are not guaranteed. Bishop detects those conditions and does not bypass challenges or invent results.

For the optional [Brave Search API](https://api-dashboard.search.brave.com/app/documentation/web-search/get-started), run `bishop web configure` and explicitly choose Brave. Supply your own search key through `BISHOP_BRAVE_SEARCH_API_KEY`, or the environment reference configured in `web.api_key_env`. Model-provider keys are not reused. Brave requests use its fixed official endpoint; credentials are never forwarded through a redirect. Provider charges may apply according to your search account. There is no automatic switch to paid search.

```sh
bishop web status
bishop web configure
bishop web search Nous Research Hermes agent
bishop web read https://hermes-agent.nousresearch.com/
```

Direct web commands do not call a model or require a configured LLM key. `web status` is offline and does not initialize a home. `web configure` uses choices to select a provider or disable web research. Restart Bishop or its gateway to apply settings.

## Configuration

Existing homes inherit these defaults without rewriting their config:

```json
{
  "web": {
    "enabled": true,
    "provider": "duckduckgo",
    "api_key_env": "BISHOP_BRAVE_SEARCH_API_KEY",
    "timeout": 12,
    "max_results": 5,
    "page_chars": 12000
  }
}
```

The timeout is a total socket-transfer deadline, including slow headers and chunked bodies. Operating-system DNS resolution is synchronous and may outlast that deadline; Bishop checks it before any connection starts. Responses are bounded to 2 MB. DNS, provider availability, ranking quality and website access restrictions remain external dependencies.

## Boundaries and evidence

Only public internet addresses on standard HTTP/HTTPS ports are readable. Loopback, private, link-local, mapped and other non-public addresses are rejected, including through DNS and redirects. Connections pin a validated address while HTTPS verifies the original hostname. Userinfo credentials in URLs are rejected. Ambient proxies, cookies and model-provided authentication headers are not used.

Search queries are sent to the selected search provider; reads are sent to the requested public site. The model is instructed not to include secrets or unrelated private workspace data. Web text is untrusted data and cannot grant approvals or override system rules. GET requests do not authorize website edits, login, purchases or code execution. Existing exact-call approvals still govern Bishop's write tools.

A successful read proves that a source was retrieved, not that all its claims are true. The model should compare evidence, prefer primary sources and cite sources it actually read. Native task monitoring records the real web tool activity. Live public search and reading were verified for this release; research-loop tests use scripted model responses and do not certify any particular LLM's answer quality.
