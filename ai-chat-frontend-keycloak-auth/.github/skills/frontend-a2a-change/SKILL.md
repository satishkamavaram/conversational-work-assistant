---
name: frontend-a2a-change
description: Playbook for migrating or debugging the React A2A client flow, including agent-card discovery, message/send payloads, task parsing, and attachment rendering.
---

Use this skill when prompts mention:

- A2A client flow
- agent-card discovery
- `message/send`
- task parsing
- Keycloak-authenticated frontend requests
- returned file attachments

Reading order:

1. `src/App.js`
2. `src/hooks/useA2AClient.js`
3. `src/services/a2aClient.js`
4. `src/components/MessageInput.js`
5. `src/components/Message.js`

Checklist:

1. Confirm the frontend can load `/.well-known/agent-card.json`.
2. Confirm the frontend posts JSON-RPC to `/`.
3. Confirm text and file parts are built with the expected A2A shape.
4. Confirm the response normalizer can handle both `message` and `task` results.
5. Confirm returned file parts still render or download correctly.
