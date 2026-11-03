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

Raven is intentionally small at this stage. No dashboard, browser automation, vector database, or bundled general-purpose LLM.

## Development

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
raven
```

The MCP server uses the official Python SDK.

## Status

Early V1 construction. Contracts and behavior may change before the first tagged release.
