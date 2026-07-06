# Repository overview

- This repository is a Python A2A backend that pairs with the React frontend in `../ai-chat-frontend-keycloak-auth`.
- The server exposes an agent card and a JSON-RPC endpoint using `a2a-sdk`.
- The current backend is intentionally modular: config, models, services, executor, and server setup are separated.

# Working rules

- Keep A2A protocol handling in `app/executor.py` and keep domain logic in `app/services/`.
- Prefer small, explicit Python modules over monolithic files.
- Preserve a clear split between transport concerns, response-building logic, and reusable domain models.
- When changing the response contract, update the frontend integration in the sibling frontend project.
- Do not hide protocol or parsing failures behind silent fallbacks.
- Update `README.md` when startup steps, endpoints, or integration behavior change.

# Validation

- Install dependencies with `pip install -r requirements.txt`.
- Run the backend with `python -m app.server`.
- Validate the A2A surface with `GET /.well-known/agent-card.json`, `GET /healthz`, and a `POST /` JSON-RPC `message/send` request.

# Coding style

- Prefer dataclasses for simple internal models.
- Keep service methods short and readable.
- Use clear names that reveal whether code is A2A transport logic or domain logic.
