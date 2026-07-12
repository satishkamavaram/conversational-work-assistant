# AI Agent Concepts

This repository contains a small A2A chat stack with three local processes:

- an MCP server for tools
- a Python A2A backend powered by Strands
- a React frontend authenticated with Keycloak

## Projects

- `ai-chat-frontend-keycloak-auth` - React 18 frontend authenticated with Keycloak and integrated with an A2A backend
- `ai-chat-backend-a2a` - Python A2A backend built with `a2a-sdk`, Strands, LiteLLM/OpenAI, and MCP
- `mcp` - custom FastMCP server module with OAuth-aware tooling

## What this repo demonstrates

- migrating a frontend from a raw WebSocket chat flow to an A2A client flow
- structuring a small Python A2A backend with clear transport and domain separation
- applying Copilot custom instructions, custom agents, and skills to both repositories
- keeping a custom MCP server in the same repo for tool-backed agent experiments
- returning text plus file attachments through the A2A protocol

## Local architecture

When running locally, the processes connect like this:

```text
Frontend (http://localhost:3000)
  -> A2A backend (http://localhost:8082)
      -> MCP server (http://127.0.0.1:8000/mcp)
```

## Local endpoints

| Service | Endpoint | Purpose |
| --- | --- | --- |
| Frontend | `http://localhost:3000` | React chat UI |
| A2A backend | `http://localhost:8082` | A2A JSON-RPC server root |
| A2A JSON-RPC | `http://localhost:8082/` | `message/send` and `message/stream` requests |
| A2A agent card | `http://localhost:8082/.well-known/agent-card.json` | Agent discovery metadata |
| A2A health | `http://localhost:8082/healthz` | Backend health check |
| MCP server | `http://127.0.0.1:8000/mcp` | MCP HTTP endpoint used by the backend |

## Prerequisites

- Python 3.10+
- Node.js 18+ and npm
- an OpenAI API key for the backend Strands model
- Keycloak running for the frontend login flow

## Start all servers

Start the services in this order.

### 1. Start the MCP server

```bash
cd mcp
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python mcp_server.py
```

Expected endpoint:

- MCP HTTP endpoint: `http://127.0.0.1:8000/mcp`

### 2. Start the A2A backend

```bash
cd ai-chat-backend-a2a
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.server
```

Backend environment defaults:

- A2A server: `http://localhost:8082`
- agent card: `http://localhost:8082/.well-known/agent-card.json`
- JSON-RPC endpoint: `http://localhost:8082/`
- health check: `http://localhost:8082/healthz`
- MCP server URL: `http://127.0.0.1:8000/mcp`
- default Strands model: `openai/gpt-5-mini`

Before starting the backend, make sure `.env` is correct for your environment, especially:

- `OPENAI_API_KEY`
- `STRANDS_MODEL_ID`
- `MCP_SERVER_URL`

Useful backend checks:

```bash
curl http://127.0.0.1:8082/healthz
curl http://127.0.0.1:8082/.well-known/agent-card.json
```

### 3. Start the frontend

```bash
cd ai-chat-frontend-keycloak-auth
npm install
npm start
```

Expected frontend URL:

- Frontend: `http://localhost:3000`

The frontend talks to the backend at `http://localhost:8082` by default. If needed, override it with:

```bash
REACT_APP_A2A_SERVER_URL=http://your-host:your-port
```

## Keycloak note

The frontend uses Keycloak with `login-required` behavior. If Keycloak is not running or not configured for this frontend, the UI will not finish login even if the MCP server and A2A backend are up.

## Quick startup summary

Open three terminals:

### Terminal 1 - MCP

```bash
cd mcp
source venv/bin/activate
python mcp_server.py
```

### Terminal 2 - A2A backend

```bash
cd ai-chat-backend-a2a
source venv/bin/activate
python -m app.server
```

### Terminal 3 - Frontend

```bash
cd ai-chat-frontend-keycloak-auth
npm start
```
