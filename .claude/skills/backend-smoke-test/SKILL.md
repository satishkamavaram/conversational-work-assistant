---
name: backend-smoke-test
description: Manual smoke-test checklist for the A2A backend (ai-chat-backend-a2a) after changing server.py, executor.py, agent.py, services/, or an MCP tool it depends on. Use when asked to "smoke test the backend", "sanity check A2A", or before/after a change to the backend's protocol boundary.
---

# Backend smoke test

Quick manual checks to confirm the A2A backend is still wired correctly after a change. Run these instead of guessing from a code read alone.

## 1. Start the server (if not already running)

```bash
cd ai-chat-backend-a2a
pip install -r requirements.txt   # first run only
cp -n .env.example .env            # first run only, defaults to A2A_AGENT_MODE=guide
python -m app.server                # serves on :8082
```

## 2. Agent card discovery

```bash
curl -s http://localhost:8082/.well-known/agent-card.json | jq .
```

Confirm: valid JSON, `url` field matches the running host/port, `skills`/`capabilities` reflect the current `agent.py` mode.

## 3. Health check

```bash
curl -s http://localhost:8082/healthz
```

Confirm: 200 response.

## 4. Send a message over JSON-RPC (the real contract)

```bash
curl -s http://localhost:8082/ \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "message/send",
    "params": {
      "message": {
        "role": "user",
        "parts": [{ "kind": "text", "text": "hello" }],
        "messageId": "smoke-test-1"
      }
    }
  }' | jq .
```

Confirm:
- Response is a valid JSON-RPC result (no `error` field).
- The result is a `message` or `task` object the frontend's `normalizeA2AResponse` (in `ai-chat-frontend-keycloak-auth/src/services/a2aClient.js`) can parse — i.e. it contains text/file `Part`s in the shape documented in root `CLAUDE.md`.
- If a file was expected back (e.g. a generated study guide in guide mode), confirm the part is `kind: 'file'` with `bytes` + `mimeType` + `name`, not raw text.

## 5. If in `strands` mode

Also confirm the MCP server is reachable at `MCP_SERVER_URL` (default `http://localhost:9000/mcp` or wherever `mcp/mcp_server.py` was started) — a strands-mode failure with no obvious backend bug is often just the MCP server not running.

## When something fails

Cross-check against `app/executor.py` (the only file that should be shaping the A2A response) before assuming the bug is in a service — see the layering rules in root `CLAUDE.md`.
