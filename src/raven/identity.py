from __future__ import annotations

from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.context import ServerRequestContext
from mcp.shared.exceptions import MCPError

AUTHENTICATION_REQUIRED = -32001


def request_principal(ctx: ServerRequestContext[Any, Any]) -> str:
    token = get_access_token()
    if token is not None:
        return token.subject or token.client_id

    if ctx.request is None:
        return "local"

    raise MCPError(code=AUTHENTICATION_REQUIRED, message="Authentication required")
