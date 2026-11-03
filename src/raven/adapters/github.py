from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import httpx

from raven.adapters.base import FetchBatch
from raven.contracts import Item, SourceBinding

_API_ROOT = "https://api.github.com"


class GitHubAdapter:
    def __init__(self, token: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        self._token = token or os.getenv("GITHUB_TOKEN")
        self._client = client

    async def fetch(self, source: SourceBinding, cursor: str | None = None) -> FetchBatch:
        if source.type != "github":
            raise ValueError(f"GitHubAdapter cannot fetch source type {source.type!r}")

        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if cursor:
            headers["If-None-Match"] = cursor

        client = self._client or httpx.AsyncClient(timeout=20)
        owns_client = self._client is None
        try:
            response = await client.get(
                f"{_API_ROOT}/repos/{source.target}/issues",
                params={"state": "all", "sort": "updated", "direction": "desc", "per_page": 100},
                headers=headers,
            )
            if response.status_code == 304:
                return FetchBatch(cursor=cursor)

            response.raise_for_status()
            items = [
                self._normalize_issue(source.target, payload)
                for payload in response.json()
                if "pull_request" not in payload
            ]
            return FetchBatch(items=items, cursor=response.headers.get("etag"))
        finally:
            if owns_client:
                await client.aclose()

    @staticmethod
    def _normalize_issue(repository: str, payload: dict[str, Any]) -> Item:
        labels = [
            label["name"] if isinstance(label, dict) else str(label)
            for label in payload.get("labels", [])
        ]
        assignees = [
            assignee.get("login")
            for assignee in payload.get("assignees", [])
            if isinstance(assignee, dict) and assignee.get("login")
        ]

        return Item(
            source_type="github",
            source_id=repository,
            external_id=f"issue:{payload['number']}",
            url=payload["html_url"],
            title=payload["title"],
            content=payload.get("body") or "",
            author=(payload.get("user") or {}).get("login"),
            created_at=_parse_datetime(payload.get("created_at")),
            updated_at=_parse_datetime(payload.get("updated_at")),
            metadata={
                "number": payload["number"],
                "state": payload.get("state"),
                "state_reason": payload.get("state_reason"),
                "labels": labels,
                "assignees": assignees,
                "assignee_count": len(assignees),
                "comments": payload.get("comments", 0),
                "locked": payload.get("locked", False),
                "milestone": (payload.get("milestone") or {}).get("title"),
            },
        )


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
