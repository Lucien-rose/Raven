from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import mcp.types as types
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.extension import Extension, MethodBinding
from mcp.shared.exceptions import MCPError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from raven.identity import request_principal

EVENTS_EXTENSION_ID = "io.modelcontextprotocol/events"
CALLBACK_ENDPOINT_ERROR = -32015
DEFAULT_SUBSCRIPTION_TTL = timedelta(days=30)
MAX_SUBSCRIPTION_TTL = timedelta(days=30)


class EventDefinition(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    description: str
    delivery: list[Literal["webhook"]]
    input_schema: dict[str, Any] = Field(alias="inputSchema")
    payload_schema: dict[str, Any] = Field(alias="payloadSchema")


class EventsListParams(types.PaginatedRequestParams):
    pass


class EventsListResult(types.Result):
    events: list[EventDefinition]
    next_cursor: str | None = None


class WebhookDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["webhook"]
    url: str
    secret: str


class WebhookDestination(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["webhook"]
    url: str


class EventsSubscribeParams(types.RequestParams):
    name: str
    arguments: dict[str, Any]
    delivery: WebhookDelivery
    cursor: str | None = None
    ttl_ms: int | None = Field(default=None, alias="ttlMs", ge=1)


class EventsSubscribeResult(types.Result):
    id: str
    refresh_before: datetime | None = None
    cursor: str | None = None
    truncated: bool = False


class EventsUnsubscribeParams(types.RequestParams):
    name: str
    arguments: dict[str, Any]
    delivery: WebhookDestination


class CandidateReadyArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    watch_id: str = Field(min_length=1)


async def advertise_events(
    ctx: ServerRequestContext[Any, Any],
    call_next: CallNext,
) -> HandlerResult:
    result = await call_next(ctx)
    if ctx.method not in {"initialize", "server/discover"} or not isinstance(result, dict):
        return result

    capabilities = result.get("capabilities")
    if not isinstance(capabilities, dict):
        return result

    return {
        **result,
        "capabilities": {
            **capabilities,
            "events": {},
        },
    }


async def list_events(
    ctx: ServerRequestContext[Any, Any],
    params: EventsListParams,
) -> EventsListResult:
    request_principal(ctx)
    return EventsListResult(events=[_candidate_ready_definition()])


async def subscribe_event(
    ctx: ServerRequestContext[Any, Any],
    params: EventsSubscribeParams,
) -> EventsSubscribeResult:
    if params.name != "candidate.ready":
        raise MCPError(code=types.INVALID_PARAMS, message="Unknown event")

    try:
        arguments = CandidateReadyArguments.model_validate(params.arguments)
        _validate_secret(params.delivery.secret)
    except (ValidationError, ValueError) as exc:
        raise MCPError(code=types.INVALID_PARAMS, message="Invalid event subscription") from exc

    owner = request_principal(ctx)
    app = ctx.lifespan_context
    if app.storage.get_watch(arguments.watch_id, owner=owner) is None:
        raise MCPError(code=types.INVALID_PARAMS, message="Unknown watch")

    subscription_id = subscription_identity(
        owner=owner,
        callback_url=params.delivery.url,
        event_name=params.name,
        arguments=arguments.model_dump(mode="json"),
    )

    try:
        await app.callback_sender.verify(
            params.delivery.url,
            params.delivery.secret,
            subscription_id,
        )
    except Exception as exc:
        raise MCPError(
            code=CALLBACK_ENDPOINT_ERROR,
            message="Callback endpoint verification failed",
            data={"reason": "challenge_failed"},
        ) from exc

    refresh_before = _refresh_before(params.ttl_ms)
    canonical_arguments = _canonical_json(arguments.model_dump(mode="json"))
    app.storage.upsert_event_subscription(
        subscription_id=subscription_id,
        owner=owner,
        event_name=params.name,
        routing_key=arguments.watch_id,
        arguments_json=canonical_arguments,
        callback_url=params.delivery.url,
        secret=params.delivery.secret,
        refresh_before=refresh_before.isoformat(),
    )
    return EventsSubscribeResult(
        id=subscription_id,
        refresh_before=refresh_before,
        cursor=None,
        truncated=False,
    )


async def unsubscribe_event(
    ctx: ServerRequestContext[Any, Any],
    params: EventsUnsubscribeParams,
) -> types.EmptyResult:
    if params.name != "candidate.ready":
        return types.EmptyResult()

    try:
        arguments = CandidateReadyArguments.model_validate(params.arguments)
    except ValidationError:
        return types.EmptyResult()

    owner = request_principal(ctx)
    subscription_id = subscription_identity(
        owner=owner,
        callback_url=params.delivery.url,
        event_name=params.name,
        arguments=arguments.model_dump(mode="json"),
    )
    ctx.lifespan_context.storage.remove_event_subscription(subscription_id, owner)
    return types.EmptyResult()


class OpenAIEvents(Extension):
    identifier = EVENTS_EXTENSION_ID

    def methods(self) -> Sequence[MethodBinding]:
        return [
            MethodBinding("events/list", EventsListParams, list_events),
            MethodBinding("events/subscribe", EventsSubscribeParams, subscribe_event),
            MethodBinding("events/unsubscribe", EventsUnsubscribeParams, unsubscribe_event),
        ]


def subscription_identity(
    owner: str,
    callback_url: str,
    event_name: str,
    arguments: dict[str, Any],
) -> str:
    raw = "\0".join(
        [
            owner,
            callback_url,
            event_name,
            _canonical_json(arguments),
        ]
    )
    return "sub_" + hashlib.sha256(raw.encode()).hexdigest()[:32]


def _candidate_ready_definition() -> EventDefinition:
    return EventDefinition(
        name="candidate.ready",
        description="A Raven Watch found a new or meaningfully changed candidate worth reviewing.",
        delivery=["webhook"],
        inputSchema={
            "type": "object",
            "properties": {
                "watch_id": {
                    "type": "string",
                    "description": "The Raven Watch to receive candidate events from.",
                }
            },
            "required": ["watch_id"],
            "additionalProperties": False,
        },
        payloadSchema={
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
                "watch_id": {"type": "string"},
                "title": {"type": "string"},
                "url": {"type": "string"},
                "source_type": {"type": "string"},
                "source_id": {"type": "string"},
                "semantic_decision": {
                    "type": "string",
                    "enum": ["pass", "uncertain"],
                },
            },
            "required": [
                "event_id",
                "watch_id",
                "title",
                "url",
                "source_type",
                "source_id",
            ],
            "additionalProperties": False,
        },
    )


def _validate_secret(secret: str) -> None:
    if not secret.startswith("whsec_"):
        raise ValueError("Webhook secret must use whsec_ format")
    encoded = secret.removeprefix("whsec_")
    padded = encoded + "=" * (-len(encoded) % 4)
    try:
        decoded = base64.b64decode(padded, validate=True)
    except ValueError as exc:
        raise ValueError("Webhook secret is not valid base64") from exc
    if not 24 <= len(decoded) <= 64:
        raise ValueError("Webhook secret must decode to 24-64 bytes")


def _refresh_before(ttl_ms: int | None) -> datetime:
    requested = timedelta(milliseconds=ttl_ms) if ttl_ms is not None else DEFAULT_SUBSCRIPTION_TTL
    return datetime.now(UTC) + min(requested, MAX_SUBSCRIPTION_TTL)


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
