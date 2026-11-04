from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import logging
import secrets
import socket
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from standardwebhooks.webhooks import Webhook

from raven.events import CandidateReadyEvent
from raven.storage import SQLiteStorage

logger = logging.getLogger(__name__)

PublicResolver = Callable[[str, int], Awaitable[None]]


class CallbackError(Exception):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class WebhookSender:
    def __init__(
        self,
        client: httpx.AsyncClient,
        resolver: PublicResolver | None = None,
    ) -> None:
        self._client = client
        self._resolver = resolver or ensure_public_callback
        self._verified: dict[str, datetime] = {}

    async def verify(
        self,
        url: str,
        secret: str,
        subscription_id: str,
    ) -> None:
        cache_key = sha256(f"{url}\0{secret}".encode()).hexdigest()
        now = datetime.now(UTC)
        if self._verified.get(cache_key, datetime.min.replace(tzinfo=UTC)) > now:
            return

        await self._validate(url)
        challenge = secrets.token_urlsafe(24)
        body = _json_body({"type": "verification", "challenge": challenge})
        message_id = f"msg_verification_{uuid4()}"
        headers = _signed_headers(
            secret=secret,
            message_id=message_id,
            body=body,
            subscription_id=subscription_id,
            signed_at=now,
        )

        try:
            response = await self._client.post(
                url,
                content=body.encode(),
                headers=headers,
                follow_redirects=False,
                timeout=10,
            )
        except httpx.HTTPError as exc:
            raise CallbackError("callback verification failed") from exc

        if not 200 <= response.status_code < 300:
            raise CallbackError("callback verification rejected")

        try:
            echoed = response.json()["challenge"]
        except (ValueError, KeyError, TypeError) as exc:
            raise CallbackError("callback verification returned an invalid challenge") from exc

        if not hmac.compare_digest(str(echoed), challenge):
            raise CallbackError("callback verification challenge mismatch")

        self._verified[cache_key] = now + timedelta(minutes=10)

    async def send(
        self,
        event: CandidateReadyEvent,
        subscription_id: str,
        url: str,
        secret: str,
    ) -> None:
        await self._validate(url)
        body = _json_body(_delivery_payload(event))
        signed_at = datetime.now(UTC)
        headers = _signed_headers(
            secret=secret,
            message_id=event.id,
            body=body,
            subscription_id=subscription_id,
            signed_at=signed_at,
        )

        try:
            response = await self._client.post(
                url,
                content=body.encode(),
                headers=headers,
                follow_redirects=False,
                timeout=10,
            )
        except httpx.HTTPError as exc:
            raise CallbackError("callback request failed") from exc

        if 200 <= response.status_code < 300:
            return
        if response.status_code in {410, 413}:
            raise CallbackError(
                f"callback returned {response.status_code}",
                retryable=False,
            )
        raise CallbackError(f"callback returned {response.status_code}")

    async def _validate(self, url: str) -> None:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise CallbackError("callback URL must use HTTPS", retryable=False)
        if parsed.username is not None or parsed.password is not None:
            raise CallbackError("callback URL must not contain credentials", retryable=False)
        await self._resolver(parsed.hostname, parsed.port or 443)


class EventDeliveryWorker:
    def __init__(
        self,
        storage: SQLiteStorage,
        sender: WebhookSender,
        poll_seconds: float = 1.0,
        max_attempts: int = 8,
    ) -> None:
        self._storage = storage
        self._sender = sender
        self._poll_seconds = poll_seconds
        self._max_attempts = max_attempts

    async def tick(self, now: datetime | None = None) -> None:
        current = now or datetime.now(UTC)
        for delivery in self._storage.list_deliveries_due(current.isoformat()):
            event = CandidateReadyEvent.model_validate_json(delivery["event_json"])
            attempt = delivery["attempts"] + 1
            try:
                await self._sender.send(
                    event,
                    subscription_id=delivery["subscription_id"],
                    url=delivery["callback_url"],
                    secret=delivery["secret"],
                )
            except CallbackError as exc:
                next_attempt = None
                if exc.retryable and attempt < self._max_attempts:
                    next_attempt = current + timedelta(seconds=_retry_delay(attempt))
                self._storage.mark_delivery_failed(
                    event.id,
                    delivery["subscription_id"],
                    error=str(exc),
                    next_attempt_at=next_attempt.isoformat() if next_attempt else None,
                )
                logger.warning(
                    "Event delivery failed for %s/%s: %s",
                    event.id,
                    delivery["subscription_id"],
                    exc,
                )
                continue

            self._storage.mark_delivery_succeeded(
                event.id,
                delivery["subscription_id"],
                delivered_at=current.isoformat(),
            )

    async def run(self) -> None:
        while True:
            await self.tick()
            await asyncio.sleep(self._poll_seconds)


async def ensure_public_callback(host: str, port: int) -> None:
    loop = asyncio.get_running_loop()
    addresses = await loop.getaddrinfo(
        host,
        port,
        type=socket.SOCK_STREAM,
    )
    resolved = {entry[4][0] for entry in addresses}
    if not resolved or any(not ipaddress.ip_address(address).is_global for address in resolved):
        raise CallbackError("callback URL must resolve only to public addresses", retryable=False)


def _delivery_payload(event: CandidateReadyEvent) -> dict[str, object]:
    item = event.candidate.item
    verdict = event.candidate.semantic_verdict
    data: dict[str, object] = {
        "event_id": event.id,
        "watch_id": event.watch_id,
        "title": item.title,
        "url": item.url,
        "source_type": item.source_type,
        "source_id": item.source_id,
    }
    if verdict is not None:
        data["semantic_decision"] = verdict.decision

    return {
        "eventId": event.id,
        "name": event.type,
        "timestamp": event.created_at.isoformat(),
        "data": data,
        "cursor": None,
    }


def _signed_headers(
    secret: str,
    message_id: str,
    body: str,
    subscription_id: str,
    signed_at: datetime,
) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "webhook-id": message_id,
        "webhook-timestamp": str(int(signed_at.timestamp())),
        "webhook-signature": Webhook(secret).sign(message_id, signed_at, body),
        "X-MCP-Subscription-Id": subscription_id,
    }


def _json_body(value: dict[str, object]) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _retry_delay(attempt: int) -> int:
    return min(5 * (2 ** max(attempt - 1, 0)), 300)
