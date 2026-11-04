import pytest
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings

from raven import server


class TestVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        return AccessToken(
            token=token,
            client_id="test-client",
            scopes=["raven"],
            subject="alice",
        )


def test_mcp_server_constructs() -> None:
    assert server.mcp is not None


def test_create_server_accepts_deployment_auth() -> None:
    auth = AuthSettings(
        issuer_url="https://identity.example.com",
        resource_server_url="https://raven.example.com/mcp",
        required_scopes=["raven"],
        validate_token_resource=False,
    )

    configured = server.create_server(
        auth=auth,
        token_verifier=TestVerifier(),
    )

    assert configured.settings.auth == auth


def test_main_runs_stdio_by_default(monkeypatch) -> None:
    calls = []
    monkeypatch.delenv("RAVEN_TRANSPORT", raising=False)
    monkeypatch.setattr(server.mcp, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    server.main()

    assert calls == [((), {})]


def test_remote_transport_requires_auth(monkeypatch) -> None:
    monkeypatch.setenv("RAVEN_TRANSPORT", "streamable-http")

    with pytest.raises(ValueError, match="authenticated server"):
        server.run_server(server.create_server())


def test_run_server_configures_streamable_http(monkeypatch) -> None:
    calls = []
    auth = AuthSettings(
        issuer_url="https://identity.example.com",
        resource_server_url="https://raven.example.com/mcp",
        required_scopes=["raven"],
        validate_token_resource=False,
    )
    configured = server.create_server(
        auth=auth,
        token_verifier=TestVerifier(),
    )

    monkeypatch.setenv("RAVEN_TRANSPORT", "streamable-http")
    monkeypatch.setenv("RAVEN_PORT", "9001")
    monkeypatch.setenv("RAVEN_ALLOWED_HOSTS", "raven.example.com,raven.example.com:*")
    monkeypatch.setattr(
        configured,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    server.run_server(configured)

    args, kwargs = calls[0]
    assert args == ()
    assert kwargs["transport"] == "streamable-http"
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 9001
    assert kwargs["streamable_http_path"] == "/mcp"
    assert kwargs["transport_security"].allowed_hosts == [
        "raven.example.com",
        "raven.example.com:*",
    ]
