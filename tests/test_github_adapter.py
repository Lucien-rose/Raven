import httpx
import pytest

from raven.adapters.github import GitHubAdapter
from raven.contracts import SourceBinding


@pytest.mark.asyncio
async def test_github_adapter_normalizes_issues_and_uses_etag() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.headers.get("if-none-match") == '"issues-v1"':
            return httpx.Response(304)

        return httpx.Response(
            200,
            headers={"etag": '"issues-v1"'},
            json=[
                {
                    "number": 12,
                    "html_url": "https://github.com/owner/repo/issues/12",
                    "title": "Broken state",
                    "body": "State is lost after restart.",
                    "user": {"login": "alice"},
                    "created_at": "2026-11-04T00:00:00Z",
                    "updated_at": "2026-11-04T01:00:00Z",
                    "state": "open",
                    "state_reason": None,
                    "labels": [{"name": "bug"}],
                    "assignees": [],
                    "comments": 3,
                    "locked": False,
                    "milestone": None,
                },
                {
                    "number": 13,
                    "html_url": "https://github.com/owner/repo/pull/13",
                    "title": "Fix",
                    "body": "",
                    "user": {"login": "bob"},
                    "created_at": "2026-11-04T00:00:00Z",
                    "updated_at": "2026-11-04T01:00:00Z",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "comments": 0,
                    "locked": False,
                    "milestone": None,
                    "pull_request": {"url": "https://api.github.com/repos/owner/repo/pulls/13"},
                },
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = GitHubAdapter(token="token", client=client)
        source = SourceBinding(type="github", target="owner/repo")

        first = await adapter.fetch(source)
        second = await adapter.fetch(source, first.cursor)

    assert first.cursor == '"issues-v1"'
    assert len(first.items) == 1
    assert first.items[0].external_id == "issue:12"
    assert first.items[0].metadata["labels"] == ["bug"]
    assert first.items[0].metadata["assignee_count"] == 0
    assert second.items == []
    assert second.cursor == '"issues-v1"'
    assert requests[0].headers["authorization"] == "Bearer token"
    assert requests[1].headers["if-none-match"] == '"issues-v1"'
