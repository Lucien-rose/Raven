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

## MCP Events

Raven exposes `candidate.ready` through the MCP Events methods used by ChatGPT:

- `events/list`
- `events/subscribe`
- `events/unsubscribe`

Subscriptions are scoped to the authenticated principal and a specific Watch. One Raven event can fan out to multiple subscriptions without sharing delivery state.

Raven verifies each webhook destination before saving the subscription, requires HTTPS, rejects private/local callback addresses, and signs callback requests with Standard Webhooks. Delivery failures use bounded exponential retry; permanent `410` and `413` responses are not retried.

The callback payload is intentionally compact:

```json
{
  "eventId": "...",
  "name": "candidate.ready",
  "timestamp": "...",
  "data": {
    "event_id": "...",
    "watch_id": "...",
    "title": "...",
    "url": "...",
    "source_type": "github",
    "source_id": "owner/repo"
  },
  "cursor": null
}
```

The full Candidate remains in Raven and can be read with `get_event`. Successful webhook delivery and host acknowledgement are separate states.

The current Python MCP SDK has public support for custom extension methods but does not yet model the top-level `events` capability directly. Raven keeps that compatibility shim isolated in `mcp_events.py`; Watch, Scheduler, Outbox, and delivery storage do not depend on it.

Hosts without MCP Events can still use `list_pending_events`.

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

Keep Raven bound to localhost behind Caddy/nginx and terminate TLS at the proxy.

Remote user-specific Watches and Events require an authenticated MCP endpoint. Raven scopes Watches, subscriptions, and event reads to the verified request principal; unauthenticated HTTP requests are rejected. Authentication is intentionally not implemented as a home-grown identity service in core.

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
