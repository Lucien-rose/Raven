from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from mcp.server import MCPServer

from raven.adapters.github import GitHubAdapter
from raven.contracts import CandidateContext, WatchSpec
from raven.runner import WatchRunner
from raven.runtime import WatchRuntime
from raven.storage import SQLiteStorage

mcp = MCPServer("Raven")

_storage = SQLiteStorage(Path(os.getenv("RAVEN_DB", "~/.raven/raven.db")).expanduser())
_storage.init()

_runner = WatchRunner(
    storage=_storage,
    adapters={"github": GitHubAdapter()},
    runtime=WatchRuntime(),
)


@mcp.tool()
def create_watch(spec: WatchSpec) -> WatchSpec:
    """Create a persistent Watch from a host-compiled WatchSpec."""
    watch = spec.model_copy(update={"id": spec.id or str(uuid4())})
    _storage.save_watch(watch)
    return watch


@mcp.tool()
def get_watch(watch_id: str) -> WatchSpec | None:
    """Return one Watch by id."""
    return _storage.get_watch(watch_id)


@mcp.tool()
def list_watches(status: str | None = "active") -> list[WatchSpec]:
    """List persistent Watches, optionally filtering by status."""
    return _storage.list_watches(status=status)


@mcp.tool()
def set_watch_status(watch_id: str, status: str) -> bool:
    """Set a Watch status such as active or paused."""
    return _storage.set_watch_status(watch_id, status)


@mcp.tool()
async def check_watch_now(watch_id: str) -> list[CandidateContext]:
    """Fetch a Watch's sources now and return candidates that passed Raven's current pipeline."""
    watch = _storage.get_watch(watch_id)
    if watch is None:
        raise ValueError(f"Watch {watch_id!r} does not exist")
    return await _runner.run_once(watch)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
