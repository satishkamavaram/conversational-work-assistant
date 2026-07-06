# Project

Monorepo for AI agent concepts with three active areas:

- `ai-chat-backend-a2a/` - Python A2A backend
- `ai-chat-frontend-keycloak-auth/` - React frontend with Keycloak auth
- `mcp/` - FastMCP server and related tooling

This repository is used to explore agent workflows, A2A integration, MCP tooling, and GitHub issue-to-PR automation.

# Structure

- `ai-chat-backend-a2a/` owns A2A server behavior, executor wiring, agent modes, and backend-specific Copilot assets
- `ai-chat-frontend-keycloak-auth/` owns UI behavior, A2A client parsing, and frontend-specific Copilot assets
- `mcp/` owns MCP server code and MCP-specific runtime dependencies
- Root-level files should describe monorepo workflow and cross-project coordination, not duplicate project-local implementation details

# Cross-Project Rules

- If the frontend/backend contract changes, update both sides in the same task
- If MCP tool behavior changes and backend code depends on it, update both together
- Keep transport and protocol logic separated from domain behavior
- Reuse existing project structure before adding new abstractions

# Issue Workflow

When working from a GitHub issue:

1. Extract explicit acceptance criteria from the issue
2. Identify which project areas are affected
3. Use a branch name in the form `copilot/issue-<number>-<short-slug>`
4. Implement the smallest complete change
5. Validate the affected surfaces only
6. Review for correctness, coding standards, reusability, maintainability, and readability
7. Prepare a PR summary tied back to the issue

If GitHub operations are available in the current surface, create the branch and PR directly. Otherwise, still produce the exact branch name, PR title, PR body, and merge recommendation.

# Coding Standards

- Prefer clean, modular, readable code
- Favor small explicit modules over monolithic files
- Keep naming clear enough to show whether code is UI logic, A2A transport logic, backend domain logic, or MCP integration logic
- Do not hide protocol or parsing failures behind silent fallbacks
- Update documentation when setup, behavior, or workflow changes

# Validation

Backend:

- `cd ai-chat-backend-a2a && python -m app.server`
- verify `GET /.well-known/agent-card.json`
- verify `GET /healthz`
- verify `POST /` with A2A `message/send`

Frontend:

- `cd ai-chat-frontend-keycloak-auth && npm run build`

MCP:

- validate only when a task touches `mcp/`

# Pull Requests

PRs should clearly answer:

- what issue is being solved
- which project areas changed
- what contract or behavior was preserved or intentionally changed
- what validation was performed
- whether the change is ready to merge
