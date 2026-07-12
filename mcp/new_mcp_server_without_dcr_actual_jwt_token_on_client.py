"""
#latest dependencies
#fastmcp==3.4.4
#mcp==1.28.1
"""
import time
import httpx
from fastmcp import FastMCP
import os
import logging
import datetime
from fastmcp.server.dependencies import get_http_headers, get_access_token
from starlette.responses import JSONResponse
from fastmcp.server.auth import RemoteAuthProvider
from fastmcp.server.auth.providers.jwt import JWTVerifier
from pydantic import AnyHttpUrl

logging.basicConfig(level=logging.DEBUG)

# =============================================================================
# OAuth architecture (no DCR, no server-side token storage)
# =============================================================================
#
# Goal: coding agents (VS Code/Copilot, Cursor, Claude Code, ...) and
# application agents (e.g. an AWS Strands agent holding a Keycloak-issued
# JWT) both work against this server, WITHOUT Keycloak ever creating a new
# OAuth client and WITHOUT this server ever storing a token.
#
# Two independent things happen here:
#
# 1. Token verification (stateless, applies to every request):
#    `KeycloakStaticClientAuthProvider` is a `RemoteAuthProvider` — it only
#    verifies a bearer JWT's signature/issuer/audience against Keycloak's
#    real JWKS. It never proxies a token exchange and never persists
#    anything. This is what makes an application agent's raw
#    `Authorization: Bearer <jwt>` (obtained however it likes, e.g. client
#    credentials grant) work with zero special-casing: verify_token()
#    doesn't care how the token was obtained.
#
# 2. Discovery facade (only exercised by coding agents that don't already
#    have a token and start the MCP Authorization flow):
#    - Protected Resource Metadata (RFC 9728) advertises THIS server as the
#      "authorization server" (not Keycloak's realm URL). That is what
#      makes the client fetch AS metadata from us instead of from Keycloak
#      directly.
#    - We mirror Keycloak's real AS metadata, but rewrite `issuer` (to keep
#      the metadata self-consistent with the URL it was fetched from) and
#      `registration_endpoint` (to point at our own mock endpoint below).
#      `authorization_endpoint` / `token_endpoint` / `jwks_uri` are left
#      pointing at the REAL Keycloak endpoints, so the actual browser
#      login + PKCE code/token exchange happens directly between the
#      coding agent and Keycloak. This server is never in that path and
#      never sees the resulting JWT until the agent calls an MCP tool with
#      it.
#    - The mock registration endpoint never calls Keycloak. It answers every
#      Dynamic Client Registration request with the SAME pre-existing
#      Keycloak client id (and secret, if configured) — so no matter how
#      many coding agents/instances "register", Keycloak's realm never
#      gains a new client.
#
# Result: the JWT lives only on the client (coding agent / application
# agent). This server stores nothing and stays horizontally scalable.

KEYCLOAK_REALM_URL = os.getenv(
    "KEYCLOAK_REALM_URL", "http://localhost:8080/realms/satishrealm")
# Public URL of THIS server, as reachable by the MCP client.
MCP_SERVER_BASE_URL = os.getenv("MCP_SERVER_BASE_URL", "http://127.0.0.1:8000")
# The one pre-existing Keycloak client shared by every coding agent.
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "testmcpclient")
# Optional: only set this if the shared client is confidential. Leave unset
# for a public client (PKCE, token_endpoint_auth_method "none"), which is
# the normal choice for coding-agent loopback redirects.
KEYCLOAK_CLIENT_SECRET = os.getenv(
    "KEYCLOAK_CLIENT_SECRET", "ZpyYMtFUelgEuMeijXl3D1hZGrQNzCub")

REGISTRATION_PATH = "/register"


class KeycloakStaticClientAuthProvider(RemoteAuthProvider):
    """Stateless Keycloak resource-server provider that advertises itself
    (not Keycloak) as the authorization server, so discovery/DCR can be
    intercepted by the facade routes registered below.

    Deliberately does not enforce an `audience` claim: tokens may come from
    the shared coding-agent client OR from any other client an application
    agent (e.g. AWS Strands) already holds in this same Keycloak realm, and
    those clients don't necessarily share one `aud` value. Signature +
    issuer (i.e. "minted by this realm") is the trust boundary here, not a
    specific client/audience.
    """

    def __init__(self, *, realm_url: str, mcp_base_url: str):
        self.realm_url = realm_url.rstrip("/")
        self.mcp_base_url = mcp_base_url.rstrip("/")

        token_verifier = JWTVerifier(
            jwks_uri=f"{self.realm_url}/protocol/openid-connect/certs",
            issuer=self.realm_url,
        )

        super().__init__(
            token_verifier=token_verifier,
            # Advertise OURSELVES as the authorization server so MCP clients
            # discover AS metadata (and attempt DCR) from us, not Keycloak.
            authorization_servers=[AnyHttpUrl(self.mcp_base_url)],
            base_url=AnyHttpUrl(self.mcp_base_url),
        )


auth_provider = KeycloakStaticClientAuthProvider(
    realm_url=KEYCLOAK_REALM_URL,
    mcp_base_url=MCP_SERVER_BASE_URL,
)

mcp = FastMCP("Weather MCP Server", auth=auth_provider)


# ---------------------------------------------------------------------------
# Facade: authorization-server metadata (mirrors Keycloak, minus DCR)
# ---------------------------------------------------------------------------

_as_metadata_cache: dict = {"data": None, "fetched_at": 0.0}
_AS_METADATA_CACHE_TTL_SECONDS = 300


async def _fetch_keycloak_metadata() -> dict:
    now = time.monotonic()
    if _as_metadata_cache["data"] is not None and (now - _as_metadata_cache["fetched_at"]) < _AS_METADATA_CACHE_TTL_SECONDS:
        return _as_metadata_cache["data"]

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            f"{KEYCLOAK_REALM_URL}/.well-known/openid-configuration"
        )
        response.raise_for_status()
        data = response.json()

    _as_metadata_cache["data"] = data
    _as_metadata_cache["fetched_at"] = now
    return data


async def _facade_authorization_server_metadata(request):
    try:
        metadata = dict(await _fetch_keycloak_metadata())
    except httpx.HTTPError:
        logging.exception(
            "Failed to fetch Keycloak authorization server metadata")
        return JSONResponse({"error": "server_error"}, status_code=502)

    # Keep authorization_endpoint / token_endpoint / jwks_uri pointing at the
    # REAL Keycloak so the coding agent talks to Keycloak directly for login
    # and the code/PKCE token exchange (this server is never in that path).
    metadata["issuer"] = MCP_SERVER_BASE_URL
    metadata["registration_endpoint"] = f"{MCP_SERVER_BASE_URL}{REGISTRATION_PATH}"
    return JSONResponse(metadata, headers={"Access-Control-Allow-Origin": "*"})


# Different MCP clients probe different well-known path conventions
# (RFC 8414 root, OIDC discovery, and both path-before/path-after variants
# of the resource-scoped form). Serve the same facade at all of them.
_AS_METADATA_PATHS = [
    "/.well-known/oauth-authorization-server",
    "/.well-known/oauth-authorization-server/mcp",
    "/mcp/.well-known/oauth-authorization-server",
    "/.well-known/openid-configuration",
    "/.well-known/openid-configuration/mcp",
    "/mcp/.well-known/openid-configuration",
]
for _path in _AS_METADATA_PATHS:
    mcp.custom_route(_path, methods=["GET"])(
        _facade_authorization_server_metadata)


# ---------------------------------------------------------------------------
# Facade: protected resource metadata alias (path-first convention)
# ---------------------------------------------------------------------------
# RemoteAuthProvider already registers the spec-correct
# /.well-known/oauth-protected-resource/mcp route. This alias covers clients
# that instead probe /mcp/.well-known/oauth-protected-resource.

@mcp.custom_route("/mcp/.well-known/oauth-protected-resource", methods=["GET"])
async def protected_resource_metadata_alias(request):
    return JSONResponse(
        {
            "resource": f"{MCP_SERVER_BASE_URL}/mcp",
            "authorization_servers": [MCP_SERVER_BASE_URL],
            "scopes_supported": ["openid", "profile", "email"],
            "bearer_methods_supported": ["header"],
        },
        headers={"Access-Control-Allow-Origin": "*"},
    )


# ---------------------------------------------------------------------------
# Mock Dynamic Client Registration — never calls Keycloak
# ---------------------------------------------------------------------------
# Every registration request gets back the SAME pre-existing Keycloak
# client. Nothing is ever created in the Keycloak realm here, no matter how
# many different coding agents (or repeated launches of the same one) hit
# this endpoint.

@mcp.custom_route(REGISTRATION_PATH, methods=["POST"])
async def mock_dynamic_client_registration(request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    redirect_uris = payload.get("redirect_uris")
    if not isinstance(redirect_uris, list):
        redirect_uris = []

    response_body = {
        "client_id": KEYCLOAK_CLIENT_ID,
        "client_id_issued_at": int(time.time()),
        "client_name": payload.get("client_name", "mcp-coding-agent"),
        "redirect_uris": redirect_uris,
        "grant_types": payload.get("grant_types") or ["authorization_code", "refresh_token"],
        "response_types": payload.get("response_types") or ["code"],
        "scope": payload.get("scope", "openid profile email"),
        "token_endpoint_auth_method": "client_secret_post" if KEYCLOAK_CLIENT_SECRET else "none",
    }
    if KEYCLOAK_CLIENT_SECRET:
        response_body["client_secret"] = KEYCLOAK_CLIENT_SECRET
        response_body["client_secret_expires_at"] = 0  # never expires

    logging.info(
        "DCR request intercepted; handing back static Keycloak client %r "
        "instead of registering a new one",
        KEYCLOAK_CLIENT_ID,
    )
    return JSONResponse(
        response_body, status_code=201, headers={"Access-Control-Allow-Origin": "*"}
    )


CURRENT_YEAR = datetime.datetime.now().year

api_key = os.getenv("API_KEY")
config_path = os.getenv("CONFIG_PATH")

logging.info(f"Server received API_KEY: {api_key}")
logging.info(f"Server received config path: {config_path}")


def _get_request_jwt_token() -> str | None:
    access = get_access_token()
    if access and getattr(access, "token", None):
        return access.token
    headers = get_http_headers(include={"authorization"})
    auth_header = headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1]
    return None


@mcp.tool()
def get_tickets_assigned_to_user(emailId: str) -> list:
    """Get tickets assigned to a user from jira using emailId

    Args:
        emailId: email of the user to get tickets assigned to user. valid emailId format examples like test@test.com , sati.k@cisco.com


    Returns:
        A list of tickets assigned to the user in JSON format (with sensitive data redacted) for a given emailId
    """
    headers = get_http_headers(include={"authorization"})
    jwt_token = _get_request_jwt_token()
    logging.info(f"get tickets assigned to user headers received: {headers}")
    logging.info(
        f"get tickets assigned to user jwt token received: {jwt_token}")
    real_tickets = [
        {
            "ticket_id": "PROJ-2024-001",
            "summary": "Fix authentication vulnerability in user login system",
            "description": "Critical security issue affecting user accounts",
            "assignee": emailId,
            "priority": "HIGH",
            "status": "IN_PROGRESS"
        },
        {
            "ticket_id": "PROJ-2024-002",
            "summary": "Update customer database schema for GDPR compliance",
            "description": "Database contains PII that needs protection",
            "assignee": emailId,
            "priority": "MEDIUM",
            "status": "OPEN"
        },
    ]

    return real_tickets


@mcp.tool()
def get_email_id_from_user_id(user_id: str) -> str:
    """Get email ID from user ID.

    Args:
        user_id: User ID to get email for

    Returns:
        Email ID of the user
    """
    headers = get_http_headers(include={"authorization"})
    jwt_token = _get_request_jwt_token()
    logging.info(f"get emailid for userid headers received: {headers}")
    logging.info(f"get emailid for userid jwt token received: {jwt_token}")
    user_email_map = {
        "user123": "user123@test.com",
        "user456": "user456@test.com"
    }
    return user_email_map.get(user_id, "satish.k@test.com")


@mcp.tool()
async def get_weather_alerts(state: str) -> str:
    """Get weather alerts for a German state.

    Args:
        state: Two-letter German state code (e.g. BW, BY)
    """
    headers = get_http_headers(include={"authorization"})
    jwt_token = _get_request_jwt_token()
    logging.info(f"get weather info headers received: {headers}")
    logging.info(f"get weather info jwt token received: {jwt_token}")
    data = {
        "features": [
            {
                "id": "1",
                "type": "Alert",
                "properties": {
                    "headline": "Severe Thunderstorm Warning",
                    "description": "A severe thunderstorm is approaching your area. Take cover immediately.",
                    "severity": "Severe",
                    "effective": "2024-10-01T14:00:00Z",
                    "expires": "2024-10-01T15:00:00Z"
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [-120.0, 37.0]
                }
            }
        ]
    }
    alerts = [format_alert(feature) for feature in data["features"]]
    return "\n---\n".join(alerts)


def format_alert(feature: dict) -> str:
    """Format an alert feature into a readable string."""
    props = feature["properties"]
    return f"""
Headline: {props.get('headline', 'Unknown')}
Description: {props.get('description', 'Unknown')}
Severity: {props.get('severity', 'Unknown')}
"""


@mcp.tool(description=f"Create an appointment with attendees, subject, date, and time. Always provide the date in YYYY-MM-DD format, including the year. If the user omits the year, use {CURRENT_YEAR}.")
def create_appointment(to_emails: list, from_email: str, subject: str, date: str, time: str) -> dict:
    """
    Create an appointment and return confirmation details.

    Args:
        to_emails (list): List of attendee email addresses
        from_email (str): Organizer's email address
        subject (str): Appointment subject
        date (str): Date of the appointment. Format: YYYY-MM-DD (e.g., 2025-09-01). Always include the year. If the user omits the year, use {CURRENT_YEAR}.
        time (str): Time of the appointment. Format: HH:MM (24-hour, e.g., 14:30)
    Returns:
        dict: Confirmation details

    Note:
        - date must always be in ISO format: YYYY-MM-DD (e.g., 2025-09-01). The year is required. If the user omits the year, use {CURRENT_YEAR}.
        - time must be in 24-hour format: HH:MM (e.g., 14:30)
    """
    headers = get_http_headers(include={"authorization"})
    jwt_token = _get_request_jwt_token()
    logging.info(f"create_appointment headers received: {headers}")
    logging.info(f"create_appointment jwt token received: {jwt_token}")
    appointment = {
        "to": to_emails,
        "from": from_email,
        "subject": subject,
        "date": date,
        "time": time,
        "status": "created",
        "appointment_id": f"APT-{date.replace('-', '')}-{time.replace(':', '')}"
    }
    logging.info(f"Appointment created: {appointment}")
    return appointment


if __name__ == "__main__":
    # Run with streamable-http transport for HTTP-based communication in containers
    # Note: FastMCP doesn't support transport_options parameter
    # Session timeout is handled by the underlying transport layer
    """mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=8000
    )"""
    mcp.run(
        transport="http",
        stateless_http=True,
        # host="0.0.0.0",
        port=8000
    )
    # mcp.run(transport='stdio')
