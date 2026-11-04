# Raven

[English](README.md) | [简体中文](README.zh-CN.md)

**Intent-driven monitoring infrastructure for AI agents.**

> Tell your AI what you are waiting for. Raven keeps watch.

Raven turns a long-lived intent into a persistent Watch. It observes supported APIs, tracks meaningful change, applies deterministic filters first, optionally delegates narrow semantic judgment, and sends relevant events back to the host AI.

## What Raven does

A Watch describes what the user is waiting for. Raven keeps that intent active over time.

```
Host AI -> WatchSpec -> Raven
                      |
Source API -> Item -> Diff -> Hard Rules -> Optional Judge -> Event -> Host AI
```

V1 starts with GitHub Issues. The GitHub adapter uses the documented REST API and ETag cursors. Diff state is stored per Watch, so multiple Watches can observe the same source independently.

Raven runs the scheduler inside the MCP server lifecycle and persists current state in SQLite.

## Product principles

- **Intent is the unit of monitoring.**
- **Deterministic rules run first.**
- **Semantic judgment is optional and pluggable.**
- **Meaningful change triggers reevaluation.**
- **The host AI handles final scoring, explanation, and presentation.**
- **Core source adapters use documented APIs.**

## Semantic judges

A Watch can run with hard rules alone or opt into a semantic judge.

The first bundled judge adapter is Jev through OpenRouter Decisions:

```bash
export RAVEN_JEV_API_KEY="..."
# or OPENROUTER_API_KEY

export RAVEN_JEV_MODEL="typesafe/jev-1.14"
```

Example Watch fragment:

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

Judge credentials stay in the deployment environment. WatchSpec stores only the adapter choice and per-Watch settings.

## MCP Events

Raven exposes `candidate.ready` through:

- `events/list`
- `events/subscribe`
- `events/unsubscribe`

Subscriptions belong to an authenticated principal and a specific Watch. A single event can fan out to multiple subscriptions with independent delivery state.

Webhook destinations are verified before subscription. Delivery uses HTTPS and Standard Webhooks signatures, with bounded retry for transient failures.

The callback payload carries a compact candidate summary. The full Candidate remains available through `get_event`.

Hosts without MCP Events can read `list_pending_events`.

## MCP tools

- `create_watch`
- `get_watch`
- `list_watches`
- `set_watch_status`
- `check_watch_now`
- `get_event`
- `get_event_status`
- `list_pending_events`
- `acknowledge_event`

## Self-hosting

Each Raven deployment owns its SQLite database, source credentials, judge credentials, and remote identity configuration.

Local MCP clients can run Raven over stdio:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
raven
```

For GitHub API access:

```bash
export GITHUB_TOKEN="..."
```

### Remote MCP

Remote deployments use Streamable HTTP and an OAuth 2.1 resource-server configuration supplied by the deployer.

Raven exposes a server factory:

```python
from mcp.server.auth.settings import AuthSettings

from my_identity import token_verifier
from raven.server import create_server, run_server

server = create_server(
    auth=AuthSettings(
        issuer_url="https://identity.example.com",
        resource_server_url="https://raven.example.com/mcp",
        required_scopes=["raven"],
        validate_token_resource=False,
    ),
    token_verifier=token_verifier,
)

run_server(server)
```

The verifier may validate JWTs locally or use the identity provider's introspection endpoint. The authenticated token's subject becomes the Raven owner for Watches, subscriptions, and events.

Runtime settings:

```bash
export RAVEN_TRANSPORT="streamable-http"
export RAVEN_HOST="127.0.0.1"
export RAVEN_PORT="8765"
export RAVEN_MCP_PATH="/mcp"
export RAVEN_ALLOWED_HOSTS="raven.example.com,raven.example.com:*"
```

A reverse proxy such as Caddy can terminate TLS and forward the public MCP endpoint to Raven on localhost.

## Development

Requires Python 3.11+.

```bash
pip install -e ".[dev]"
ruff check .
pytest -q
```

## Status

Raven is in early V1 development. Contracts may evolve before the first tagged release.
