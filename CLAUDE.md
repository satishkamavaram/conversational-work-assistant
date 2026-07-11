# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Monorepo with three independently-run projects that together demonstrate an A2A (Agent-to-Agent protocol) chat system, plus GitHub Copilot / Claude Code customization assets applied to each:

- `ai-chat-frontend-keycloak-auth/` — React 18 chat UI, Keycloak-authenticated, talks to the backend purely over the A2A JSON-RPC protocol (no WebSocket).
- `ai-chat-backend-a2a/` — Python A2A server (`a2a-sdk`) that can run a simple built-in "guide" agent or a Strands-agent-with-MCP-tools mode.
- `mcp/` — standalone FastMCP tool server (Keycloak-OAuth-aware) that the backend's Strands agent calls over MCP for file/document/CV/appointment/ticket tools.

The three projects run as separate local processes and are wired together by URL, not by imports: frontend → backend (`http://localhost:8082`), backend's Strands mode → MCP server (`http://localhost:9000/mcp` or wherever `mcp_server.py` is run, default port 8000 in code).

## Commands

Backend (`ai-chat-backend-a2a/`):
```bash
pip install -r requirements.txt
cp .env.example .env        # sets A2A_AGENT_MODE=guide by default
python -m app.server        # serves on :8082
```
Validate: `GET /.well-known/agent-card.json`, `GET /healthz`, `POST /` with an A2A `message/send` JSON-RPC body.

Frontend (`ai-chat-frontend-keycloak-auth/`):
```bash
npm install
npm start        # :3000, proxies to :8082 in dev
npm run build
npm test
```

MCP (`mcp/`):
```bash
pip install -r requirements.txt
python mcp_server.py        # http transport, stateless, :8000
```
Only touch/validate this when a task actually depends on MCP tool behavior.

There is no top-level build; each project is developed and validated independently unless a change crosses the frontend/backend contract.

## Architecture

### A2A contract (the thing that binds all three projects)

The frontend and backend speak A2A JSON-RPC directly — `src/services/a2aClient.js` builds `message/send` requests and normalizes both `message`- and `task`-kind results; `app/executor.py` on the backend is the only place that touches A2A protocol types (`TextPart`, `FilePart`, `Artifact`, `TaskStatusUpdateEvent`, etc.). Keep protocol/transport code confined to these two files — domain logic belongs elsewhere.

Part-type convention used throughout: plain text → `TextPart`/`kind: 'text'`; files (any type — PDF, pptx, images, etc.) → `FilePart` with `FileWithBytes` (base64 `bytes` + `mime_type` + `name`) on the backend, and `{ kind: 'file', file: { name, mimeType, bytes } }` on the frontend. There is currently no JSON/"body" part type wired up — if adding one, follow the same "one Part kind per payload shape" pattern rather than overloading `TextPart` with stringified JSON.

Session continuity is client-driven: `useA2AClient.js` keeps `{ contextId, taskId }` in a ref and threads it into every subsequent `message/send` call so the backend's `InMemoryTaskStore` can resume the same task/context.

### Backend (`ai-chat-backend-a2a/app/`)

Layering, top to bottom:
- `server.py` — builds the `AgentCard`, wires `DefaultRequestHandler` + `InMemoryTaskStore`, adds CORS and `/healthz`. Nothing else should touch A2A app wiring.
- `executor.py` (`CopilotConceptExecutor`) — the sole A2A protocol boundary. Extracts uploaded `FileWithBytes` parts into plain `UploadedFile` models, calls the agent, and packs the reply back into an `Artifact` of `Part`s. Also pulls the inbound `Authorization` header off `context.call_context.state['headers']` to forward to MCP.
- `agent.py` (`CopilotConceptAgent`) — mode switch only. Reads `settings.agent_mode` (`guide` | `strands`) and delegates to one of the two services below. No protocol or business logic lives here.
- `services/concept_guide_service.py` (`ConceptGuideService`) — the default "guide" mode: answers from the static `knowledge_base.py` data and can emit a generated markdown study-guide file. Self-contained demo agent, no external calls.
- `services/strands_agent_service.py` (`StrandsAgentService`) — the "strands" mode: builds a Strands `Agent` (LiteLLM model) backed by tools discovered from the MCP server via `MCPClient`/`streamablehttp_client`, streams the agent run, and inspects tool-call/tool-result events (via `strands_result_parser.py`) to detect file-download requests (`get_cv_document`, `download_files`) and upload requests (`upload_files`), then fetches/pushes the actual bytes through separate "internal-only" MCP tools (`download_cv_document`, `fetch_files_content`, `save_uploaded_files`) that are filtered out of the tools list the LLM sees (`_INTERNAL_ONLY_TOOLS`). This keeps large base64 payloads out of the LLM context/token count — mirror this pattern for any new file-producing tool.
- `services/attachment_service.py` — pure helper for summarizing uploaded files in guide mode.
- `models.py` — frozen dataclasses (`UploadedFile`, `GeneratedFile`, `AgentReply`) shared as the internal contract between executor and services; not A2A types.
- `config.py` — single `Settings` dataclass reading env vars (`A2A_AGENT_MODE`, `A2A_HOST/PORT`, `FRONTEND_ORIGIN`, `OPENAI_API_KEY`, `STRANDS_MODEL_ID`, `MCP_SERVER_URL`). Add new config here, not scattered `os.getenv` calls.

When extending the backend for new capabilities (sessions/persistence, new agent modes, etc.), keep the same three-layer split: transport (`executor.py`) → mode dispatch (`agent.py`) → domain service (`services/`). `InMemoryTaskStore` is a placeholder — a future DB-backed task/session store should slot in at `server.py` without the executor or services needing to change.

### Frontend (`ai-chat-frontend-keycloak-auth/src/`)

- `App.js` — owns the entire Keycloak lifecycle (`login-required` mode, token refresh loop, logout) and top-level layout/gating. Do not scatter auth logic into other components.
- `auth/keycloak.js` — Keycloak client instance/config only.
- `hooks/useA2AClient.js` — connection state, agent-card fetch, message send/receive, and the `{contextId, taskId}` session ref. This is the only place that should hold chat/session state.
- `services/a2aClient.js` — pure request-building/response-normalizing functions (`buildSendMessageRequest`, `fetchAgentCard`, `sendA2AMessage`, `normalizeA2AResponse`). No React, no state — keep it that way so the A2A contract logic stays independently testable.
- `components/MessageInput.js` — turns selected files into base64 `upload_files` parts (10 MB client-side cap) and calls `onSendMessage`.
- `components/Message.js` — renders text (with an ASCII/markdown-table heuristic for `<pre>` rendering) and decodes returned file `bytes` into a Blob URL for preview/download. Note the StrictMode-aware effect ordering comment in `FileAttachment` — the Blob URL must be created inside the effect, not `useMemo`, or double-invoked effects revoke a URL still referenced by the download link.

Auth token flows from `App.js` → `useA2AClient(token)` → `a2aClient.js`, which attaches it as `Authorization: Bearer <token>` on both the agent-card fetch and `message/send` POST. The backend forwards that same header to MCP in Strands mode — if changing the auth header shape, update both this path and `executor.py`'s header extraction.

### MCP server (`mcp/mcp_server.py`)

Single-file FastMCP server exposing tools the Strands backend agent can call: CV/document tools (`get_cv_document`/`download_cv_document` split — metadata vs. bytes), folder browsing (`list_cv_files`/`download_files`/`fetch_files_content`), PPTX generation (`generate_ppt`, themed via `_THEMES`), file upload (`upload_files`/`save_uploaded_files`), plus demo Jira/appointment/weather tools. The recurring pattern across all file-producing tools: an LLM-visible tool returns metadata only (filename/size/mime), and a separate tool (often excluded from the LLM's toolset by the backend) returns the actual base64 bytes — this avoids putting large payloads through the model's context. Follow this split for any new binary-content tool. Keycloak OAuth wiring (`HybridOAuthProxy`, `CompanyAuthProvider`) is present but commented out of the active `FastMCP(...)` construction; treat it as reference/WIP, not active auth.

## Cross-project rules

- If the frontend/backend A2A contract changes, update both sides in the same task.
- If an MCP tool's name, arguments, or return shape changes and the backend depends on it, update `strands_agent_service.py` / `strands_result_parser.py` together with `mcp_server.py`.
- Keep transport/protocol logic (`executor.py`, `a2aClient.js`) separated from domain logic (`services/`, hooks/components).
- Do not hide protocol or parsing failures behind silent fallbacks.
- Update the relevant `README.md` when setup, endpoints, ports, or integration behavior changes.

## Copilot/Claude customization assets already in this repo

Each project directory has its own `.github/copilot-instructions.md` (project-scoped rules) plus example custom agents and skills under `.github/agents/` and `.github/skills/` (e.g. `a2a-backend-implementer.agent.md`, `frontend-a2a-implementer.agent.md`, `a2a-message-debugging/SKILL.md`, `frontend-a2a-change/SKILL.md`). These exist as working demonstrations of Copilot customization — read the project-local `copilot-instructions.md` before making changes there, since it encodes the same working rules as this file at a project-specific level.

## Claude Code native assets (root `.claude/`)

Demo set of native Claude Code customizations, root-scoped (not per-project like the Copilot assets above):

- `.claude/agents/python-code-reviewer.md` — subagent that reviews Python diffs in `ai-chat-backend-a2a/` and `mcp/` against this file's layering rules.
- `.claude/skills/backend-smoke-test/SKILL.md` — manual checklist for verifying the A2A backend (agent card, `/healthz`, `message/send`) after a change.
- `.claude/commands/review-python.md` (`/review-python`) and `.claude/commands/smoke-test.md` (`/smoke-test`) — slash commands that invoke the above.
- `.claude/settings.json` + `.claude/hooks/` — a `PostToolUse` hook (`check_python_syntax.sh`) that runs `python3 -m py_compile` on any `.py` file Claude edits/writes and feeds syntax errors back; plus a logging-only hook (`log_event.sh`) wired to every hook event Claude Code supports, appending each event's JSON payload to `.claude/logs/hooks.log` (gitignored) for observing the hook lifecycle. These are demo assets, not enforcement — treat findings/log output as informational.
