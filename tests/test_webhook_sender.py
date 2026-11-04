import base64
import json

import httpx
import pytest

from raven.contracts import CandidateContext, Item, RuleResult
from raven.delivery import WebhookSender
from raven.events import CandidateReadyEvent


def make_event() -> CandidateReadyEvent:
    return CandidateReadyEvent(
        id="evt-1",
        watch_id="watch-1",
        candidate=CandidateContext(
            watch_id="watch-1",
            watch_spec_version="1",
            item=Item(
                source_type="github",
                source_id="owner/repo",
                external_id="issue:1",
                url="https://github.com/owner/repo/issues/1",
                title="Bug",
            ),
            diff={"_new": True},
            rule_result=RuleResult(passed=True, checks=[]),
        ),
    )


@pytest.mark.asyncio
async def test_webhook_sender_verifies_and_sends_standard_webhooks() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = json.loads(request.content)
        if payload.get("type") == "verification":
            return httpx.Response(200, json={"challenge": payload["challenge"]})
        return httpx.Response(204)

    async def resolver(host: str, port: int) -> None:
        assert host == "events.example.com"
        assert port == 443

    secret = "whsec_" + base64.b64encode(b"x" * 32).decode()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        sender = WebhookSender(client, resolver=resolver)
        await sender.verify(
            "https://events.example.com/callback",
            secret,
            "sub-1",
        )
        await sender.send(
            make_event(),
            subscription_id="sub-1",
            url="https://events.example.com/callback",
            secret=secret,
        )

    assert len(requests) == 2
    delivery = requests[1]
    payload = json.loads(delivery.content)
    assert payload["eventId"] == "evt-1"
    assert payload["name"] == "candidate.ready"
    assert payload["data"]["watch_id"] == "watch-1"
    assert delivery.headers["x-mcp-subscription-id"] == "sub-1"
    assert delivery.headers["webhook-signature"].startswith("v1,")
