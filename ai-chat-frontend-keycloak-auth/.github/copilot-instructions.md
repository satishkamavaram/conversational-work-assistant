# Repository overview

- This project is a React 18 frontend for a Keycloak-authenticated chat experience.
- The frontend now calls a sibling Python A2A backend instead of opening a raw WebSocket connection.
- The paired backend lives in `../ai-chat-backend-a2a`.

# Architecture and file map

- `src/App.js` owns Keycloak lifecycle wiring, auth gating, logout, and top-level chat state.
- `src/hooks/useA2AClient.js` manages agent-card discovery, A2A request flow, and client-side session tracking.
- `src/services/a2aClient.js` owns JSON-RPC request construction and response normalization.
- `src/components/MessageInput.js` builds outgoing message and file payloads.
- `src/components/Message.js` renders text responses and returned file attachments.

# Working rules

- Preserve the `login-required` Keycloak posture unless the task explicitly changes auth behavior.
- Keep the A2A JSON-RPC contract explicit and readable; do not hide message or task parsing inside UI components.
- Pass file uploads as A2A file parts with `name`, `mime_type`, and base64 `bytes`.
- Keep auth-aware network logic inside hooks or services, not scattered across components.
- When changing the frontend/backend contract, update the sibling backend project in parallel.
- Update `README.md` when setup, runtime ports, or integration behavior change.

# Validation

- Install dependencies with `npm install`.
- Start the frontend with `npm start`.
- Build production assets with `npm run build`.
- Validate the paired backend is available at `http://localhost:8082` or through `REACT_APP_A2A_SERVER_URL`.

# Coding style

- Prefer small hooks and service helpers over large components.
- Keep UI components focused on rendering and interaction.
- Preserve current attachment rendering behavior unless the task explicitly changes it.
