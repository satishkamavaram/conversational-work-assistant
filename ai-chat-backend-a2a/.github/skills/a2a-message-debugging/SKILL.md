---
name: a2a-message-debugging
description: Debugging checklist for A2A agent-card discovery, JSON-RPC message/send payloads, task parsing, and file-part handling in this backend.
---

Use this skill when prompts mention:

- agent-card discovery
- JSON-RPC request shape
- `message/send`
- task parsing
- returned file parts
- frontend/backend A2A mismatch

Reading order:

1. `app/server.py`
2. `app/executor.py`
3. `app/models.py`
4. `app/services/concept_guide_service.py`

Checklist:

1. Confirm the agent card URL and reported `url` field match the running server.
2. Confirm the frontend posts JSON-RPC to `/` with method `message/send`.
3. Confirm text and file parts are being parsed correctly.
4. Confirm the executor emits a completed task with an artifact that the frontend can render.
