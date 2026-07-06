# AI Agent Concepts

This repository contains a paired frontend and backend example for applying GitHub Copilot customization concepts in a real project.

## Projects

- `ai-chat-frontend-keycloak-auth` - React 18 frontend authenticated with Keycloak and integrated with an A2A backend
- `ai-chat-backend-a2a` - Python A2A backend built with `a2a-sdk`
- `mcp` - custom FastMCP server module with OAuth-aware tooling

## What this repo demonstrates

- migrating a frontend from a raw WebSocket chat flow to an A2A client flow
- structuring a small Python A2A backend with clear transport and domain separation
- applying Copilot custom instructions, custom agents, and skills to both repositories
- keeping a custom MCP server in the same repo for tool-backed agent experiments
- returning text plus file attachments through the A2A protocol

## Run locally

### Backend

```bash
cd ai-chat-backend-a2a
pip install -r requirements.txt
python -m app.server
```

### Frontend

```bash
cd ai-chat-frontend-keycloak-auth
npm install
npm start
```

The frontend expects the backend at `http://localhost:8082` by default.
