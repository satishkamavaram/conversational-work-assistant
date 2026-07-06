# AI Chat Backend A2A

This project is a clean, modular Python A2A backend designed to sit alongside the React frontend in `../ai-chat-frontend-keycloak-auth`.

## What it does

- Exposes an A2A JSON-RPC endpoint at `/`
- Serves an agent card at `/.well-known/agent-card.json`
- Accepts text plus uploaded file parts
- Returns text responses and can optionally return a downloadable study guide file
- Supports a simple built-in guide agent or a Strands + MCP-backed agent mode
- Demonstrates how to apply Copilot custom instructions, custom agents, and skills in a backend project

## Project structure

```text
app/
  agent.py
  config.py
  executor.py
  knowledge_base.py
  models.py
  server.py
  services/
    attachment_service.py
    concept_guide_service.py
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

   By default, `A2A_AGENT_MODE=guide`, which runs the built-in repository guide agent.

   If you want the backend to use a Strands-based agent with MCP tools instead, set:

   ```bash
   A2A_AGENT_MODE=strands
   ```

   Then provide `OPENAI_API_KEY`, `STRANDS_MODEL_ID`, and `MCP_SERVER_URL`.

4. Start the server:

   ```bash
   python -m app.server
   ```

The backend listens on `http://localhost:8082` by default.

## Frontend integration

The frontend uses the A2A agent card and JSON-RPC endpoint from this server instead of the old WebSocket connection.
