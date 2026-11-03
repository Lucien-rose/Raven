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

## Event delivery

Raven emits internal `candidate.ready` events into a durable outbox.

The MCP Triggers & Events work is still experimental, so Raven does not hard-code a private callback protocol into core. Hosts without proactive callbacks can use:

- `list_pending_events`
- `acknowledge_event`

A transport adapter can later deliver the same internal event through a standardized callback mechanism without changing the Watch runtime.

## MCP tools

- `create_watch` — persist a host-compiled WatchSpec.
- `get_watch` — inspect one Watch.
- `list_watches` — list active or all Watches.
- `set_watch_status` — pause or reactivate a Watch.
- `check_watch_now` — run one Watch through its source, diff, and hard-rule pipeline now.
- `list_pending_events` — read undelivered events as a compatibility fallback.
- `acknowledge_event` — acknowledge a delivered event.

A semantic judge is optional. If a Watch requests one, Raven requires a configured judge adapter rather than silently skipping semantic judgment.

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
