---
description: Run the backend-smoke-test checklist against the A2A backend
argument-hint: [base-url, default http://localhost:8082]
---

Follow the `backend-smoke-test` skill checklist against base URL `${ARGUMENTS:-http://localhost:8082}`: agent-card discovery, `/healthz`, and a `message/send` JSON-RPC call. Report pass/fail for each step, and for any failure point to the specific file (`app/server.py`, `app/executor.py`, etc.) that owns that behavior.
