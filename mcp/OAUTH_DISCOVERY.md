# OAuth discovery & token validation (`new_mcp_server.py`)

How this MCP server authenticates two different kinds of callers against a
single Keycloak realm, with **no Dynamic Client Registration** on Keycloak
and **no token storage** on this server.

## Architecture in one paragraph

The server is a pure OAuth **resource server**: it never talks to Keycloak's
token endpoint and never holds a token on behalf of a client. For callers
that already hold a Keycloak-issued JWT (application agents), it just
verifies the JWT's signature/issuer against Keycloak's JWKS on every
request — stateless, one HTTP call, done. For callers that don't have a
token yet and need to go through an OAuth flow (coding agents), the server
publishes discovery metadata that points them at *itself* first, so it can
intercept Dynamic Client Registration and hand back one pre-existing,
shared Keycloak client instead of letting Keycloak mint a new client per
agent. The actual login and code/token exchange still happen directly
between the coding agent and Keycloak — this server is never in that path.

```
Coding agent (no token yet)          Application agent (already has a JWT)
        |                                          |
        v                                          v
  discovery + mocked DCR              Authorization: Bearer <jwt> straight
  against THIS server            to /mcp, no discovery calls at all
        |                                          |
        v                                          v
  browser login + code/token         this server verifies signature +
  exchange directly with Keycloak    issuer against Keycloak's JWKS
        |                                          |
        v                                          v
  Authorization: Bearer <jwt> to /mcp  -----> same verification path
```

Either way, the JWT itself lives only on the client. The server never
persists a token.

## Flow 1 — coding agent (VS Code / Copilot, Cursor, Claude Code, ...)

### Step 1 — unauthenticated call, server points at its own metadata

```
POST /mcp
(no Authorization header)
```

```
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer resource_metadata="http://127.0.0.1:8000/.well-known/oauth-protected-resource/mcp"
```

### Step 2 — client fetches Protected Resource Metadata (RFC 9728)

```
GET /.well-known/oauth-protected-resource/mcp
```

```json
{
  "resource": "http://127.0.0.1:8000/mcp",
  "authorization_servers": ["http://127.0.0.1:8000/"],
  "scopes_supported": [],
  "bearer_methods_supported": ["header"]
}
```

Note `authorization_servers` points at **this server**, not at Keycloak's
realm URL. That single detail is what routes the rest of discovery through
the facade instead of straight to Keycloak.

### Step 3 — client fetches Authorization Server metadata from us

```
GET /.well-known/oauth-authorization-server
```

The server fetches Keycloak's real `.well-known/openid-configuration` and
returns it almost unmodified — only two fields are rewritten:

```json
{
  "issuer": "http://127.0.0.1:8000",
  "authorization_endpoint": "http://localhost:8080/realms/satishrealm/protocol/openid-connect/auth",
  "token_endpoint": "http://localhost:8080/realms/satishrealm/protocol/openid-connect/token",
  "jwks_uri": "http://localhost:8080/realms/satishrealm/protocol/openid-connect/certs",
  "registration_endpoint": "http://127.0.0.1:8000/register",
  "grant_types_supported": ["authorization_code", "refresh_token", "..."],
  "code_challenge_methods_supported": ["S256"]
}
```

- `issuer` is rewritten to this server's own URL, so the metadata is
  self-consistent with where it was fetched from.
- `registration_endpoint` is rewritten to this server's mock endpoint
  (Step 4) instead of Keycloak's real DCR endpoint.
- `authorization_endpoint` / `token_endpoint` / `jwks_uri` are **left
  pointing at real Keycloak** — the browser login and the code/PKCE token
  exchange in Steps 5–6 happen directly between the coding agent and
  Keycloak. This server is never in that request path.

### Step 4 — client attempts Dynamic Client Registration (intercepted)

```
POST /register
Content-Type: application/json

{
  "client_name": "Visual Studio Code",
  "redirect_uris": ["http://127.0.0.1:33418/callback"],
  "grant_types": ["authorization_code", "refresh_token"]
}
```

The server never calls Keycloak here. It always returns the **same**
pre-existing Keycloak client, regardless of who's asking:

```json
{
  "client_id": "testmcpclient",
  "client_id_issued_at": 1784387076,
  "client_name": "Visual Studio Code",
  "redirect_uris": ["http://127.0.0.1:33418/callback"],
  "grant_types": ["authorization_code", "refresh_token"],
  "response_types": ["code"],
  "scope": "openid profile email",
  "token_endpoint_auth_method": "client_secret_post",
  "client_secret": "***",
  "client_secret_expires_at": 0
}
```

Ten different coding agents "registering" ten times produces the exact
same `client_id` every time. Keycloak's client list never grows. This is
the piece that replaces DCR without disabling the agent's normal OAuth
flow.

### Step 5 — browser login (direct to Keycloak, not through this server)

The coding agent opens a browser to the **real** `authorization_endpoint`
from Step 3, with PKCE:

```
GET http://localhost:8080/realms/satishrealm/protocol/openid-connect/auth
    ?client_id=testmcpclient
    &redirect_uri=http://127.0.0.1:33418/callback
    &response_type=code
    &code_challenge=<...>
    &code_challenge_method=S256
    &scope=openid profile email
```

User authenticates against Keycloak's real login page. Keycloak redirects
back to the agent's loopback `redirect_uri` with `?code=...`.

### Step 6 — token exchange (direct to Keycloak, not through this server)

```
POST http://localhost:8080/realms/satishrealm/protocol/openid-connect/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
&code=<code from step 5>
&redirect_uri=http://127.0.0.1:33418/callback
&client_id=testmcpclient
&code_verifier=<PKCE verifier>
```

```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzUxMiIs...",
  "token_type": "Bearer",
  "expires_in": 216000
}
```

The JWT is now held only by the coding agent. This server has not seen any
part of this exchange.

### Step 7 — normal MCP calls

```
POST /mcp
Authorization: Bearer eyJhbGciOiJSUzI1NiIs...
```

```
HTTP/1.1 200 OK
{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18", "...": "..."}}
```

## Client-specific behavior: Claude Code CLI vs. GitHub Copilot CLI

Both clients complete the same discovery → facade AS metadata → mocked-DCR
→ direct-Keycloak-login flow described above, and both end up talking to
the real Keycloak endpoints for the browser login and token exchange —
there is no OAuth *standards* incompatibility between them. But raw server
logs from an actual Claude Code CLI connection show it drives that flow
noticeably more chattily than Copilot CLI, plus one genuine protocol-level
difference:

```
POST /mcp                                            -> 401
GET /.well-known/oauth-protected-resource/mcp        -> 200
GET /.well-known/oauth-authorization-server          -> 200   (facade; fetches Keycloak's real metadata server-side)
POST /register                                       -> 201   (mocked DCR, static client_id returned)

--- new connection, after the browser login + token exchange with Keycloak ---
GET /.well-known/oauth-protected-resource/mcp        -> 200
GET /.well-known/oauth-authorization-server          -> 200
GET /.well-known/oauth-authorization-server          -> 200   (repeated)
GET /.well-known/oauth-protected-resource/mcp        -> 200   (repeated)
GET /.well-known/oauth-authorization-server          -> 200   (repeated again)
GET /.well-known/oauth-protected-resource/mcp        -> 200   (repeated again)
POST /mcp  (initialize)                              -> 200   protocolVersion "2025-11-25"
POST /mcp  (notifications/initialized)                -> 202
GET  /mcp                                            -> 405   Method Not Allowed
POST /mcp  (tools/list)                              -> 200   (separate stateless request)
POST /mcp  (prompts/list)                            -> 200   (separate stateless request)
POST /mcp  (resources/list)                           -> 200   (separate stateless request)
```

Observed differences worth knowing if you're debugging this specific
client:

- **Repeated metadata re-fetching.** Claude Code re-fetches both
  `/.well-known/oauth-protected-resource/mcp` and
  `/.well-known/oauth-authorization-server` several times per connection
  attempt — including *after* it already has a token, on what looks like
  every reconnect/health-check cycle. Harmless (our facade handler is
  cheap and cached — see `_as_metadata_cache`), just noisier in the logs
  than Copilot's flow.
- **A `GET /mcp` probe that 405s.** Claude Code issues a bare `GET /mcp`
  at some point, which this server (stateless `streamable-http` only)
  correctly rejects with `405 Method Not Allowed`. This looks like a
  capability probe (checking for an SSE-style GET stream) rather than a
  real failure — the flow continues normally afterward.
- **Newer MCP protocol version.** Claude Code's `initialize` negotiates
  `protocolVersion: "2025-11-25"`, versus `"2025-06-18"` seen from direct
  bearer-token calls elsewhere in this doc. This is the MCP JSON-RPC
  protocol version, unrelated to the OAuth discovery mechanism — just
  something to expect if you diff request/response payloads across
  clients.
- **`tools/list` / `prompts/list` / `resources/list` as three separate
  requests**, each its own stateless HTTP connection, rather than one
  batched exchange. Expected given `stateless_http=True` on this server;
  just noting it so it doesn't look like three retries of the same call.

**What this was *not* the cause of:** an earlier connection failure that
looked like a Claude-Code-specific OAuth incompatibility ("Unable to
connect. Is the computer able to access the url?") turned out to be
unrelated to any of the above — it was a stale, unrelated MCP server entry
in `.claude.json` (a leftover `mcp-demo` config pointing at a dead
`localhost` port from earlier experimentation) that shadowed the real,
correctly-configured entry in Claude Code's `/mcp` status panel. If
Claude Code's `/mcp` panel shows a server failing to connect, check
`claude mcp list` / `.claude.json` for a duplicate or stale entry with a
similar name before assuming the OAuth flow itself is broken.

## Flow 2 — application agent that already holds a JWT (e.g. AWS Strands)

No discovery calls at all. The agent already has a Keycloak-issued JWT
(client-credentials grant, a service account, or reuse of a token minted
for some other client in the same realm) and just sends it:

```
POST /mcp
Authorization: Bearer eyJhbGciOiJSUzI1NiIs...
Content-Type: application/json

{"jsonrpc":"2.0","id":0,"method":"initialize","params":{...}}
```

```
HTTP/1.1 200 OK
{"jsonrpc":"2.0","id":0,"result":{"protocolVersion":"2025-06-18","serverInfo":{"name":"Weather MCP Server", ...}}}
```

Every subsequent tool call carries the same bearer token; the server
re-verifies it (still stateless — no session, no cache of "who this is")
on each request.

## Token validation — what actually gets checked

`KeycloakStaticClientAuthProvider` configures a `JWTVerifier` with exactly
two checks:

1. **Signature** — verified against Keycloak's real JWKS
   (`{realm}/protocol/openid-connect/certs`).
2. **Issuer** — the token's `iss` claim must equal the realm URL
   (`{realm}`, e.g. `http://localhost:8080/realms/satishrealm`).

Deliberately **not** checked:

- `aud` (audience) — not enforced, because different Keycloak clients in
  the same realm don't necessarily carry the same audience mapper. The
  coding agent's shared client and an application agent's own separate
  client (different `client_id`/`azp`) can both present valid tokens.
- `client_id` / `azp` — same reasoning. The server trusts *any* client
  Keycloak has already authenticated in this realm, not one specific
  client. The DCR-mocking in Flow 1 exists purely to avoid client sprawl in
  Keycloak's client list, not to restrict who can call this server.

So the real trust boundary is: **"was this JWT minted by our Keycloak
realm, with a valid signature, and not expired?"** — nothing more.

## The one pitfall we hit: `iss` must be identical for every caller

Keycloak stamps the `iss` claim from whatever hostname the caller used to
reach it, *unless* the realm has a fixed Frontend URL configured. In this
project's local setup, the browser frontend (Dockerized, using
`host.docker.internal:8080`) and this MCP server / coding agents (using
`localhost:8080`) were reaching the *same* Keycloak realm through two
different hostnames — so tokens minted via the frontend had
`iss: http://host.docker.internal:8080/realms/satishrealm` while this
server expected `iss: http://localhost:8080/realms/satishrealm`. Same
realm, same signing key, different issuer string — the strict `iss`
equality check in `JWTVerifier` rejected it.

Fix applied: pointed the frontend's Keycloak client config at the same
`localhost` hostname the rest of the system uses, so every caller gets
tokens with the identical `iss`.

**Is this safe for production as-is?** Yes, and it's the *right* fix, not
a workaround — production should have exactly one canonical way every
caller reaches Keycloak, not several hostname aliases for the same
instance. Concretely:

- Set Keycloak's realm **Frontend URL** (Realm Settings → General →
  Frontend URL) to one stable, public hostname (e.g.
  `https://auth.yourcompany.com`). Once set, Keycloak stamps that exact
  value into `iss` for every token, regardless of which internal
  network path (load balancer, container network, VPN, etc.) a given
  caller used to physically reach it.
- Point `KEYCLOAK_REALM_URL` in this server, and every OAuth client
  config (coding agents, application agents, frontends), at that same
  canonical hostname.
- With a fixed Frontend URL, the "different hostname aliases produce
  different `iss`" class of bug can't recur — there's only one issuer
  string, ever, for the realm.

If you ever do need to support genuinely different issuers (e.g. two
separate Keycloak realms, or a migration period between old/new hostnames),
`JWTVerifier(issuer=...)` accepts a list of acceptable issuer strings
instead of one — but that's a deliberate multi-issuer policy, not a
substitute for fixing the Frontend URL.
