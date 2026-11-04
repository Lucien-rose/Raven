# Raven

**Intent-driven monitoring infrastructure for AI agents.**

> Tell your AI what you are waiting for. Raven keeps watch.

Raven turns a long-lived intent into a persistent Watch. It observes supported sources, filters deterministic mismatches cheaply, optionally asks a pluggable semantic judge about ambiguous candidates, and hands high-value changes back to the host AI.

## Product principles

- **Intent is the unit of monitoring.**
- **Deterministic first.** Hard rules run before semantic judgment.
- **Judgment is optional and pluggable.** Raven does not require a specific model.
- **State matters.** Raven reacts to meaningful change, not just new objects.
- **Host AI is the interface.** Raven is MCP-native; the host handles conversation, final scoring, and presentation.
- **Respect the source.** Core adapters use documented APIs and feeds.

## V1

The first vertical slice is GitHub Issues:

```
Host AI -> WatchSpec -> Raven
                      |
GitHub API -> Item -> Diff -> Hard Rules -> Optional Judge -> Candidate -> Event -> Host AI
```

The current GitHub adapter uses the documented REST API and persists ETag cursors. Diff state is tracked per Watch, so multiple intents can safely observe the same source without consuming each other's changes.

Raven starts its scheduler inside the MCP server lifespan and shuts it down with the server. There are no hidden worker threads or import-time background tasks.

## Semantic judges

Judgment is a registry, not a hard dependency. A Watch can omit `judge` entirely and send every hard-rule candidate to the Host AI.

The first bundled adapter is `jev`, using OpenRouter's Decisions API. Configure the server with:

```bash
export RAVEN_JEV_API_KEY="..."
# or OPENROUTER_API_KEY

export RAVEN_JEV_MODEL="typesafe/jev-1.14"
```

Then a Watch can opt in with:

```json
{
  "judge": {
    "adapter": "jev",
    "config": {
      "min_confidence": 0.75
    }
  }
}
```

Secrets stay in the server environment rather than WatchSpec. The model and confidence threshold can vary per Watch.

## Event delivery

Raven writes every `candidate.ready` event to a durable outbox before delivery.

The internal event contains the full Candidate, but proactive delivery sends only a compact trigger:

```json
{
  "event_id": "...",
  "type": "candidate.ready",
  "watch_id": "...",
  "created_at": "..."
}
```

The callback does not carry source content. After a trigger wakes the host, the host reads the full event with `get_event` and acknowledges it after consumption.

The first transport is a generic webhook:

```bash
export RAVEN_EVENT_WEBHOOK_URL="https://host.example/raven/events"
export RAVEN_EVENT_WEBHOOK_TOKEN="optional-bearer-token"
```

Successful delivery and host acknowledgement are separate states. Failed callback attempts use a small capped exponential retry and remain visible through `get_event_status`.

The MCP Triggers & Events work is still experimental, so the transport layer stays replaceable. When a standardized MCP callback mechanism is ready, it can implement the same `EventTransport` contract without changing Watch, Scheduler, or Event storage.

Hosts without proactive callbacks can continue to use `list_pending_events`.

## MCP tools

- `create_watch` — persist a host-compiled WatchSpec.
- `get_watch` — inspect one Watch.
- `list_watches` — list active or all Watches.
- `set_watch_status` — pause or reactivate a Watch.
- `check_watch_now` — run one Watch through its source, diff, and judgment pipeline now.
- `get_event` — fetch a full event after a compact delivery trigger.
- `get_event_status` — inspect delivery, retry, and acknowledgement state.
- `list_pending_events` — read unacknowledged events as a compatibility fallback.
- `acknowledge_event` — acknowledge an event after the host consumes it.

## Remote MCP

The same server can run locally over stdio or remotely over Streamable HTTP.

```bash
export RAVEN_TRANSPORT="streamable-http"
export RAVEN_HOST="127.0.0.1"
export RAVEN_PORT="8765"
export RAVEN_MCP_PATH="/mcp"
raven
```

When a reverse proxy forwards a public hostname, explicitly allow that Host header:

```bash
export RAVEN_ALLOWED_HOSTS="raven.example.com,raven.example.com:*"
```

Browser origins can be allowlisted separately with `RAVEN_ALLOWED_ORIGINS`.

Keep Raven bound to localhost behind Caddy/nginx and terminate TLS at the proxy. The MCP endpoint still needs authentication before public exposure; Raven does not invent a private auth scheme in core.

## Development

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
raven
```

For authenticated GitHub API access, set `GITHUB_TOKEN` in the server environment.

The MCP server uses the official Python SDK.

## Status

Early V1 construction. Contracts and behavior may change before the first tagged release.
