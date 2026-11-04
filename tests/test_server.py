from raven import server


def test_mcp_server_constructs() -> None:
    assert server.mcp is not None


def test_main_runs_stdio_by_default(monkeypatch) -> None:
    calls = []
    monkeypatch.delenv("RAVEN_TRANSPORT", raising=False)
    monkeypatch.setattr(server.mcp, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    server.main()

    assert calls == [((), {})]


def test_main_configures_streamable_http(monkeypatch) -> None:
    calls = []
    monkeypatch.setenv("RAVEN_TRANSPORT", "streamable-http")
    monkeypatch.setenv("RAVEN_PORT", "9001")
    monkeypatch.setenv("RAVEN_ALLOWED_HOSTS", "raven.example.com,raven.example.com:*")
    monkeypatch.setattr(server.mcp, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    server.main()

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
