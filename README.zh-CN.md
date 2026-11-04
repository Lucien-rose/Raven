# Raven

[English](README.md) | [简体中文](README.zh-CN.md)

**面向 AI Agent 的持续意图监控基础设施。**

> 告诉 AI 你在等待什么，Raven 会继续替你看着世界。

Raven 将一段长期意图编译成持续运行的 Watch。它观察受支持的 API，记录有意义的变化，先执行确定性规则，再按需调用轻量语义判断，并把值得注意的事件交回 Host AI。

## Raven 如何工作

一个 Watch 描述用户正在等待什么。Raven 让这段意图在用户离开后继续运行。

```
Host AI -> WatchSpec -> Raven
                      |
Source API -> Item -> Diff -> Hard Rules -> Optional Judge -> Event -> Host AI
```

V1 从 GitHub Issues 开始。GitHub Adapter 使用官方 REST API 与 ETag cursor。Diff 状态按 Watch 独立保存，因此多个 Watch 可以同时观察同一个 Source。

Scheduler 与 MCP Server 共用生命周期，当前状态保存在 SQLite 中。

## 产品原则

- **Intent 是监控的基本单位。**
- **确定性规则优先。**
- **语义 Judge 可选、可插拔。**
- **有意义的变化才触发重新判断。**
- **最终评分、解释与呈现交给 Host AI。**
- **Core Source Adapter 使用有文档的 API。**

## Semantic Judge

Watch 可以只使用 Hard Rules，也可以选择 Semantic Judge。

目前内置的第一份 Judge Adapter 是通过 OpenRouter Decisions 调用 Jev：

```bash
export RAVEN_JEV_API_KEY="..."
# 或 OPENROUTER_API_KEY

export RAVEN_JEV_MODEL="typesafe/jev-1.14"
```

WatchSpec 示例：

```json
{
  "judge": {
    "adapter": "jev",
    "config": {
      "min_confidence": 0.75
    }
  }
}
```

Judge 凭证保存在部署环境中。WatchSpec 只保存 Adapter 选择和当前 Watch 的判断参数。

## MCP Events

Raven 通过以下方法暴露 `candidate.ready`：

- `events/list`
- `events/subscribe`
- `events/unsubscribe`

Subscription 归属于经过认证的 principal，并绑定具体 Watch。同一个 Event 可以投递给多个 Subscription，每条投递拥有独立状态。

Raven 会在保存 Subscription 前验证 Webhook 地址。Event Delivery 使用 HTTPS 与 Standard Webhooks 签名，并对临时失败执行有限重试。

Callback 只携带精简的 Candidate 摘要，完整 Candidate 可以通过 `get_event` 读取。

不支持 MCP Events 的 Host 可以使用 `list_pending_events`。

## MCP Tools

- `create_watch`
- `get_watch`
- `list_watches`
- `set_watch_status`
- `check_watch_now`
- `get_event`
- `get_event_status`
- `list_pending_events`
- `acknowledge_event`

## 自部署

每一份 Raven 实例拥有自己的 SQLite 数据库、Source 凭证、Judge 凭证与远程身份认证配置。

本地 MCP Host 可以直接通过 stdio 运行 Raven：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
raven
```

GitHub API 凭证：

```bash
export GITHUB_TOKEN="..."
```

### 远程 MCP

远程部署使用 Streamable HTTP。部署者向 Raven 注入自己的 OAuth 2.1 Resource Server 配置。

Raven 提供统一的 Server Factory：

```python
from mcp.server.auth.settings import AuthSettings

from my_identity import token_verifier
from raven.server import create_server, run_server

server = create_server(
    auth=AuthSettings(
        issuer_url="https://identity.example.com",
        resource_server_url="https://raven.example.com/mcp",
        required_scopes=["raven"],
        validate_token_resource=False,
    ),
    token_verifier=token_verifier,
)

run_server(server)
```

TokenVerifier 可以在本地验证 JWT，也可以调用身份提供商的 Introspection Endpoint。认证后的 token subject 会成为 Raven 中 Watch、Subscription 与 Event 的 owner。

运行参数：

```bash
export RAVEN_TRANSPORT="streamable-http"
export RAVEN_HOST="127.0.0.1"
export RAVEN_PORT="8765"
export RAVEN_MCP_PATH="/mcp"
export RAVEN_ALLOWED_HOSTS="raven.example.com,raven.example.com:*"
```

Caddy 等反向代理可以负责 TLS，并把公网 MCP endpoint 转发到 localhost 上的 Raven。

## 开发

需要 Python 3.11+。

```bash
pip install -e ".[dev]"
ruff check .
pytest -q
```

## 当前状态

Raven 正处于 V1 早期开发阶段。首个正式版本发布前，Contract 仍可能继续收敛。
