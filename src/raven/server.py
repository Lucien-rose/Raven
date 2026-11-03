from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from mcp.server import MCPServer

from raven.contracts import WatchSpec
from raven.storage import SQLiteStorage

mcp = MCPServer("Raven")

_storage = SQLiteStorage(
    Path(os.getenv("RAVEN_DB", "~/.raven/raven.db")).expanduser()
)
_storage.init()


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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
