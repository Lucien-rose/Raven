import base64
from types import SimpleNamespace

import pytest

from raven.mcp_events import MCPEvents, advertise_events, subscription_identity


def test_events_extension_exposes_standard_methods() -> None:
    assert [binding.method for binding in MCPEvents().methods()] == [
        "events/list",
        "events/subscribe",
        "events/unsubscribe",
    ]


@pytest.mark.asyncio
async def test_capability_shim_advertises_events() -> None:
    ctx = SimpleNamespace(method="initialize")

    async def call_next(_):
        return {"capabilities": {"tools": {}}}

    result = await advertise_events(ctx, call_next)

    assert result["capabilities"] == {"tools": {}, "events": {}}


def test_subscription_identity_is_canonical() -> None:
    first = subscription_identity(
        owner="alice",
        callback_url="https://example.com/events",
        event_name="candidate.ready",
        arguments={"watch_id": "watch-1", "extra": "x"},
    )
    second = subscription_identity(
        owner="alice",
        callback_url="https://example.com/events",
        event_name="candidate.ready",
        arguments={"extra": "x", "watch_id": "watch-1"},
    )

    assert first == second
    assert first.startswith("sub_")


def test_valid_webhook_secret_shape() -> None:
    from raven.mcp_events import _validate_secret

    secret = "whsec_" + base64.b64encode(b"x" * 32).decode()
    _validate_secret(secret)
