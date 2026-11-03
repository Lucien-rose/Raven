from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import httpx
from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from raven.adapters.github import GitHubAdapter
from raven.contracts import CandidateContext, WatchSpec
from raven.events import CandidateReadyEvent, OutboxEventDispatcher, load_pending_events
from raven.judges import JevJudge, SemanticJudge
from raven.runner import WatchRunner
from raven.runtime import WatchRuntime
from raven.scheduler import WatchScheduler
from raven.storage import SQLiteStorage


@dataclass
class AppContext:
    storage: SQLiteStorage
    runner: WatchRunner
    scheduler: WatchScheduler


@asynccontextmanager
async def app_lifespan(_: MCPServer) -> AsyncIterator[AppContext]:
    storage = SQLiteStorage(Path(os.getenv("RAVEN_DB", "~/.raven/raven.db")).expanduser())
    storage.init()

    async with httpx.AsyncClient(timeout=20) as http_client:
        judges: dict[str, SemanticJudge] = {}
        jev_api_key = os.getenv("RAVEN_JEV_API_KEY") or os.getenv("OPENROUTER_API_KEY")
        if jev_api_key:
            judges["jev"] = JevJudge(
                client=http_client,
                api_key=jev_api_key,
                base_url=os.getenv("RAVEN_JEV_BASE_URL", "https://openrouter.ai"),
                model=os.getenv("RAVEN_JEV_MODEL", "typesafe/jev-1.14"),
            )

        runner = WatchRunner(
            storage=storage,
            adapters={"github": GitHubAdapter(client=http_client)},
            runtime=WatchRuntime(judges),
        )
        scheduler = WatchScheduler(
            storage=storage,
            runner=runner,
            dispatcher=OutboxEventDispatcher(storage),
        )
        scheduler_task = asyncio.create_task(scheduler.run())

        try:
            yield AppContext(storage=storage, runner=runner, scheduler=scheduler)
        finally:
            scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await scheduler_task


mcp = MCPServer("Raven", lifespan=app_lifespan)


@mcp.tool()
def create_watch(spec: WatchSpec, ctx: Context[AppContext]) -> WatchSpec:
    """Create a persistent Watch from a host-compiled WatchSpec."""
    watch = spec.model_copy(update={"id": spec.id or str(uuid4())})
    ctx.request_context.lifespan_context.storage.save_watch(watch)
    return watch


@mcp.tool()
def get_watch(watch_id: str, ctx: Context[AppContext]) -> WatchSpec | None:
    """Return one Watch by id."""
    return ctx.request_context.lifespan_context.storage.get_watch(watch_id)


@mcp.tool()
def list_watches(
    ctx: Context[AppContext],
    status: str | None = "active",
) -> list[WatchSpec]:
    """List persistent Watches, optionally filtering by status."""
    return ctx.request_context.lifespan_context.storage.list_watches(status=status)


@mcp.tool()
def set_watch_status(
    watch_id: str,
    status: str,
    ctx: Context[AppContext],
) -> bool:
    """Set a Watch status such as active or paused."""
    return ctx.request_context.lifespan_context.storage.set_watch_status(watch_id, status)


@mcp.tool()
async def check_watch_now(
    watch_id: str,
    ctx: Context[AppContext],
) -> list[CandidateContext]:
    """Fetch a Watch's sources now and return candidates that passed Raven's current pipeline."""
    app = ctx.request_context.lifespan_context
    watch = app.storage.get_watch(watch_id)
    if watch is None:
        raise ValueError(f"Watch {watch_id!r} does not exist")
    return await app.runner.run_once(watch)


@mcp.tool()
def list_pending_events(
    ctx: Context[AppContext],
    limit: int = 50,
) -> list[CandidateReadyEvent]:
    """List undelivered Raven events for hosts that do not yet support proactive callbacks."""
    return load_pending_events(ctx.request_context.lifespan_context.storage, limit)


@mcp.tool()
def acknowledge_event(
    event_id: str,
    ctx: Context[AppContext],
) -> bool:
    """Acknowledge one pending Raven event."""
    return ctx.request_context.lifespan_context.storage.acknowledge_event(event_id)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
