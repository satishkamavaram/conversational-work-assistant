# AI Chat Backend A2A

This project is a clean, modular Python A2A backend designed to sit alongside the React frontend in `../ai-chat-frontend-keycloak-auth`.

## What it does

- Exposes an A2A JSON-RPC endpoint at `/`
- Serves an agent card at `/.well-known/agent-card.json`
- Accepts text plus uploaded file parts
- Returns text responses and file attachments from MCP-backed workflows
- Uses a Strands agent with LiteLLM/OpenAI and MCP tools

## Project structure

```text
app/
  agent.py
  config.py
  executor.py
  models.py
  server.py
  services/
    strands_agent_service.py
    strands_result_parser.py
```

## Run locally

1. Create and activate a virtual environment.
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Copy the example environment file and adjust values as needed:

   ```bash
   cp .env.example .env
   ```

   Configure `OPENAI_API_KEY`, `STRANDS_MODEL_ID`, and `MCP_SERVER_URL`.

   The default MCP endpoint is `http://127.0.0.1:8000/mcp`, which matches the FastMCP server output you shared.

4. Start the server:

   ```bash
   python -m app.server
   ```

The backend listens on `http://localhost:8082` by default.

## Logging

`app/executor.py` (the sole A2A protocol boundary) logs the raw A2A wire payloads at `INFO` level:

- `a2a.request.payload` — the inbound `message/send` request message.
- `a2a.stream.payload` — every event pushed onto the A2A event queue (the created `Task`, status updates, and the artifact update).
- `a2a.response.payload` — the response `Artifact` built for the request.

Each payload is the model's `model_dump(mode='json', exclude_none=True)` output (the same shape sent/received on the wire), with any `bytes`/`content_base64`/`bytes_base64` field redacted to `{"redacted": true, "length": N}` so large file payloads never bloat the logs.

`A2A_LOG_LEVEL` (default `INFO`) controls the root logger level via `logging.basicConfig` in `app/server.py`; set it to `DEBUG` to enable any future, more verbose trace-level logging without changing default behavior today.

**Privacy note:** at `INFO` level, raw user message text and tool call/result content are now written to the logs. Treat backend logs as containing sensitive user content and handle/retain them accordingly.

## Backend endpoints

- agent card: `http://localhost:8082/.well-known/agent-card.json`
- JSON-RPC root: `http://localhost:8082/`
- health check: `http://localhost:8082/healthz`

The frontend should discover the backend through the agent card and then call the JSON-RPC root for A2A requests.

## Frontend integration

The frontend uses the A2A agent card and JSON-RPC endpoint from this server instead of the old WebSocket connection.
