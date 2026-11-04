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
from mcp.server.transport_security import TransportSecuritySettings

from raven.adapters.github import GitHubAdapter
from raven.contracts import CandidateContext, WatchSpec
from raven.delivery import EventDeliveryWorker, WebhookSender
from raven.events import (
    CandidateReadyEvent,
    EventStatus,
    OutboxEventDispatcher,
    load_event,
    load_event_status,
    load_pending_events,
)
from raven.identity import request_principal
from raven.judges import JevJudge, SemanticJudge
from raven.mcp_events import OpenAIEvents, advertise_events
from raven.runner import WatchRunner
from raven.runtime import WatchRuntime
from raven.scheduler import WatchScheduler
from raven.storage import SQLiteStorage


@dataclass
class AppContext:
    storage: SQLiteStorage
    runner: WatchRunner
    scheduler: WatchScheduler
    callback_sender: WebhookSender


@asynccontextmanager
async def app_lifespan(_: MCPServer) -> AsyncIterator[AppContext]:
    storage = SQLiteStorage(Path(os.getenv("RAVEN_DB", "~/.raven/raven.db")).expanduser())
    storage.init()

    async with (
        httpx.AsyncClient(timeout=20) as http_client,
        httpx.AsyncClient(
            timeout=10,
            follow_redirects=False,
            trust_env=False,
        ) as callback_client,
    ):
        judges: dict[str, SemanticJudge] = {}
        jev_api_key = os.getenv("RAVEN_JEV_API_KEY") or os.getenv("OPENROUTER_API_KEY")
        if jev_api_key:
            judges["jev"] = JevJudge(
                client=http_client,
                api_key=jev_api_key,
                base_url=os.getenv("RAVEN_JEV_BASE_URL", "https://openrouter.ai"),
                model=os.getenv("RAVEN_JEV_MODEL", "typesafe/jev-1.14"),
            )

        callback_sender = WebhookSender(callback_client)
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
        delivery = EventDeliveryWorker(storage, callback_sender)
        tasks = [
            asyncio.create_task(scheduler.run()),
            asyncio.create_task(delivery.run()),
        ]

        try:
            yield AppContext(
                storage=storage,
                runner=runner,
                scheduler=scheduler,
                callback_sender=callback_sender,
            )
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task


mcp = MCPServer(
    "Raven",
    lifespan=app_lifespan,
    extensions=[OpenAIEvents()],
    middleware=[advertise_events],
)


@mcp.tool()
def create_watch(spec: WatchSpec, ctx: Context[AppContext]) -> WatchSpec:
    """Create a persistent Watch from a host-compiled WatchSpec."""
    owner = request_principal(ctx.request_context)
    watch = spec.model_copy(update={"id": spec.id or str(uuid4())})
    ctx.request_context.lifespan_context.storage.save_watch(watch, owner=owner)
    return watch


@mcp.tool()
def get_watch(watch_id: str, ctx: Context[AppContext]) -> WatchSpec | None:
    """Return one Watch by id."""
    owner = request_principal(ctx.request_context)
    return ctx.request_context.lifespan_context.storage.get_watch(watch_id, owner=owner)


@mcp.tool()
def list_watches(
    ctx: Context[AppContext],
    status: str | None = "active",
) -> list[WatchSpec]:
    """List persistent Watches, optionally filtering by status."""
    owner = request_principal(ctx.request_context)
    return ctx.request_context.lifespan_context.storage.list_watches(
        status=status,
        owner=owner,
    )


@mcp.tool()
def set_watch_status(
    watch_id: str,
    status: str,
    ctx: Context[AppContext],
) -> bool:
    """Set a Watch status such as active or paused."""
    owner = request_principal(ctx.request_context)
    return ctx.request_context.lifespan_context.storage.set_watch_status(
        watch_id,
        status,
        owner=owner,
    )


@mcp.tool()
async def check_watch_now(
    watch_id: str,
    ctx: Context[AppContext],
) -> list[CandidateContext]:
    """Fetch a Watch's sources now and return candidates that passed Raven's current pipeline."""
    app = ctx.request_context.lifespan_context
    owner = request_principal(ctx.request_context)
    watch = app.storage.get_watch(watch_id, owner=owner)
    if watch is None:
        raise ValueError(f"Watch {watch_id!r} does not exist")
    return await app.runner.run_once(watch)


@mcp.tool()
def get_event(
    event_id: str,
    ctx: Context[AppContext],
) -> CandidateReadyEvent | None:
    """Return the full Raven event after an event webhook wakes the host."""
    owner = request_principal(ctx.request_context)
    return load_event(
        ctx.request_context.lifespan_context.storage,
        event_id,
        owner=owner,
    )


@mcp.tool()
def get_event_status(
    event_id: str,
    ctx: Context[AppContext],
) -> EventStatus | None:
    """Return delivery and acknowledgement state for one Raven event."""
    owner = request_principal(ctx.request_context)
    return load_event_status(
        ctx.request_context.lifespan_context.storage,
        event_id,
        owner=owner,
    )


@mcp.tool()
def list_pending_events(
    ctx: Context[AppContext],
    limit: int = 50,
) -> list[CandidateReadyEvent]:
    """List unacknowledged Raven events for hosts without proactive callbacks."""
    owner = request_principal(ctx.request_context)
    return load_pending_events(
        ctx.request_context.lifespan_context.storage,
        owner=owner,
        limit=limit,
    )


@mcp.tool()
def acknowledge_event(
    event_id: str,
    ctx: Context[AppContext],
) -> bool:
    """Acknowledge a Raven event after the host has consumed it."""
    owner = request_principal(ctx.request_context)
    return ctx.request_context.lifespan_context.storage.acknowledge_event(
        event_id,
        owner=owner,
    )


def main() -> None:
    transport = os.getenv("RAVEN_TRANSPORT", "stdio")
    if transport == "stdio":
        mcp.run()
        return
    if transport != "streamable-http":
        raise ValueError(f"Unsupported RAVEN_TRANSPORT: {transport!r}")

    allowed_hosts = _csv_env("RAVEN_ALLOWED_HOSTS")
    allowed_origins = _csv_env("RAVEN_ALLOWED_ORIGINS")
    security = None
    if allowed_hosts:
        security = TransportSecuritySettings(
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        )

    mcp.run(
        transport="streamable-http",
        host=os.getenv("RAVEN_HOST", "127.0.0.1"),
        port=int(os.getenv("RAVEN_PORT", "8765")),
        streamable_http_path=os.getenv("RAVEN_MCP_PATH", "/mcp"),
        transport_security=security,
    )


def _csv_env(name: str) -> list[str]:
    return [value.strip() for value in os.getenv(name, "").split(",") if value.strip()]


if __name__ == "__main__":
    main()
