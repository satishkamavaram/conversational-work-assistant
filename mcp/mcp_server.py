"""
#latest dependencies
#fastmcp==3.1.0
#mcp==1.26.0
"""
import httpx
from fastmcp import FastMCP
import os
import base64
import logging
import datetime
import mimetypes
from fastmcp.server.dependencies import get_http_headers, get_access_token
from starlette.responses import JSONResponse, FileResponse
from urllib.parse import quote
from fastmcp.server.auth import OAuthProxy, RemoteAuthProvider
from fastmcp.server.auth.providers.jwt import JWTVerifier
from starlette.routing import Route
from pydantic import AnyHttpUrl

logging.basicConfig(level=logging.DEBUG)

# setup keycloak server : create realm satishrealm and create private client with client id and secret for mcp server

# In Keycloak
# creates 'Visual Studio Code' as client and client_is as random uuid in keycloak and in jwt token aud field value will be None
""" sample decoded jwt token 
{
  "exp": 1757013717,
  "iat": 1757013417,
  "jti": "onrtna:929cf910-370e-9949-8f9b-46ec3913e753",
  "iss": "http://localhost:8080/realms/satishrealm",
  "sub": "8ede11cf-58a5-4bc2-91e2-aebd381f52cc",
  "typ": "Bearer",
  "azp": "ed6bfa06-4b96-4a37-aa29-40cc4f1965f0",
  "sid": "48eb9b22-db6a-4c27-8417-eac0af6092f4",
  "acr": "1",
  "allowed-origins": [
    "http://127.0.0.1:33418",
    "http://127.0.0.1",
    "http://localhost:33418",
    "https://vscode.dev",
    "http://localhost",
    "https://insiders.vscode.dev"
  ],
  "scope": "openid profile email",
  "email_verified": false,
  "name": "s f",
  "preferred_username": "satish2",
  "given_name": "s",
  "family_name": "f",
  "email": "satish2@test.com"
}
"""

"""
configure in mcp.json vscode client

"weather-mcp-server-oauth": {
			"url": "http://127.0.0.1:8000/mcp",
			"type": "http"
		}
"""
token_verifier = JWTVerifier(
    jwks_uri="http://localhost:8080/realms/satishrealm/protocol/openid-connect/certs",
    issuer="http://localhost:8080/realms/satishrealm",
)


"""The core fix was introducing HybridOAuthProxy and using it instead of plain OAuthProxy.
  In FastMCP v3, OAuthProxy mainly expects proxy-issued token flow (great for IDE), so UI’s direct Keycloak bearer token could get 401 invalid_token; HybridOAuthProxy.load_access_token() now tries normal 
  OAuthProxy validation first, then falls back to direct JWTVerifier.verify_token(token) for UI bearer tokens.
  That preserved IDE OAuth behavior while allowing your UI app’s raw bearer token path to authenticate on the same MCP server."""


class HybridOAuthProxy(OAuthProxy):
    async def load_access_token(self, token: str):
        validated = await super().load_access_token(token)
        # For IDE clients - this validated value will have jwt token.. for UI client - it will be None
        logging.info(f"is validated???????????????????????????? {validated}")
        if validated is not None:
            return validated
        # Allow direct upstream bearer tokens (UI flow) in addition to proxy-issued tokens.
        logging.info(
            f"ui flow validated....######################### {validated}")
        return await self._token_validator.verify_token(token)


# Create the auth proxy to enable FastMCP servers to authenticate with OAuth providers that don’t support Dynamic Client Registration (DCR). In this case keycloak.
# create a private client with client id and secret in keycloak for mcp server which helps to create dynamic client registration. In this case, Visual Studio Code public client is created in keycloak.
# use discovery endpoint to get authorization and token endpoints - http://127.0.0.1:8080/realms/satishrealm/.well-known/openid-configuration
auth = HybridOAuthProxy(
    # Provider's OAuth endpoints (from their documentation)
    upstream_authorization_endpoint="http://localhost:8080/realms/satishrealm/protocol/openid-connect/auth",
    upstream_token_endpoint="http://localhost:8080/realms/satishrealm/protocol/openid-connect/token",
    upstream_client_id="testmcpclient",
    upstream_client_secret="ZpyYMtFUelgEuMeijXl3D1hZGrQNzCub",
    # upstream_client_id="testclient",
    # upstream_client_secret="NjoJI3AYor285gPwj0F6fP0LtY4GZy1f",
    token_verifier=token_verifier,
    base_url="http://127.0.0.1:8000",
)


class CompanyAuthProvider(RemoteAuthProvider):
    def __init__(self):
        # handles token validation using IDP provider public keys
        logging.debug(
            "[CompanyAuthProvider] Initializing with JWT validation...")
        token_verifier = JWTVerifier(
            # to fetch public keys for token validation
            jwks_uri="http://localhost:8080/realms/satishrealm/protocol/openid-connect/certs",
            issuer="http://localhost:8080/realms/satishrealm",
            audience="account",  # MUST match the "aud" claim in the JWT token from Keycloak
        )
        logging.debug(
            f"[CompanyAuthProvider] JWTVerifier configured with issuer='http://localhost:8080/realms/satishrealm', audience='account'")

        super().__init__(
            token_verifier=token_verifier,
            authorization_servers=[
                AnyHttpUrl(
                    "http://localhost:8080/realms/satishrealm"
                )  # telling mcp clients list of IDPs to trust
            ],
            resource_server_url="http://127.0.0.1:8000/mcp",  # Your server base URL
        )
        logging.debug(
            "[CompanyAuthProvider] RemoteAuthProvider initialized successfully")

    # this is to just add custom routes , nothing related to token verification
    def get_routes(self) -> list[Route]:
        """Add custom endpoints to the standard protected resource routes."""

        # Get the standard OAuth protected resource routes
        routes = super().get_routes()

        # Add authorization server metadata forwarding for client convenience
        async def authorization_server_metadata(request):
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "http://localhost:8080/realms/satishrealm/.well-known/openid-configuration"
                )
                response.raise_for_status()
                return JSONResponse(response.json())

        # /.well-known/oauth-protected-resource
        # /mcp/.well-known/oauth-authorization-server
        routes.append(
            Route(
                "/mcp/.well-known/oauth-protected-resource",
                authorization_server_metadata,
            )
        )

        return routes


# Single server for both IDE + UI clients:
# - IDE clients use OAuth flow via OAuthProxy endpoints.
# - UI clients pass bearer JWTs that are verified by the same token_verifier.
mcp = FastMCP("Weather MCP Server")  # , auth=auth)

# this is just custom endpoint not used during authentication


@mcp.custom_route("/mcp/.well-known/oauth-protected-resource", methods=["GET"])
async def custom_well_known_endpoint(request):
    return JSONResponse(
        {
            "resource": "http://127.0.0.1:8000/mcp",
            "authorization_servers": [
                "http://localhost:8080/realms/satishrealm"
            ],
            "scopes_supported": ["openid", "email", "profile"],
            "bearer_methods_supported": ["header"],
        }
    )


async def _keycloak_openid_metadata() -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "http://localhost:8080/realms/satishrealm/.well-known/openid-configuration"
        )
        response.raise_for_status()
        return response.json()


# FastMCP v3 + IDE compatibility aliases for auth discovery paths.
@mcp.custom_route("/.well-known/oauth-authorization-server/mcp", methods=["GET"])
async def oauth_authorization_server_mcp_alias(request):
    return JSONResponse(await _keycloak_openid_metadata())


@mcp.custom_route("/.well-known/openid-configuration/mcp", methods=["GET"])
async def openid_configuration_mcp_alias(request):
    return JSONResponse(await _keycloak_openid_metadata())


@mcp.custom_route("/mcp/.well-known/openid-configuration", methods=["GET"])
async def mcp_openid_configuration_alias(request):
    return JSONResponse(await _keycloak_openid_metadata())

CURRENT_YEAR = datetime.datetime.now().year

# mcp = FastMCP("jira MCP Server")
logging.basicConfig(level=logging.INFO)
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


# ---------------------------------------------------------------------------
# CV / resume document tools
# ---------------------------------------------------------------------------
# The model calls get_cv_document() (lightweight metadata only) when the user
# asks for the CV. The jira agent then calls download_cv_document() directly
# over MCP to fetch the actual PDF bytes and stream them to the UI as an A2A
# file artifact. Keeping the bytes out of get_cv_document() means the base64
# PDF never enters the LLM context (no token blow-up).
CV_DOCUMENT_PATH = os.getenv(
    "CV_DOCUMENT_PATH",
    "/Users/satish/work/job_search_Germany/lead_cv/Satish_CV.pdf",
)
CV_DOCUMENT_NAME = "Satish_CV.pdf"
CV_DOCUMENT_MIME = "application/pdf"


@mcp.tool()
def get_cv_document() -> dict:
    """Offer Satish's CV / resume PDF document to the user.

    Call this tool (with no arguments) whenever the user asks for the CV,
    resume, profile, or "the pdf document". It returns only lightweight
    metadata (filename, mime type, size). The actual document is delivered
    automatically to the chat UI as a downloadable, previewable attachment, so
    you do NOT need the file content yourself - just tell the user their CV is
    ready below.

    Returns:
        dict: filename, mime_type and size_bytes of the CV document.
    """
    headers = get_http_headers(include={"authorization"})
    jwt_token = _get_request_jwt_token()
    logging.info(f"get_cv_document headers received: {headers}")
    logging.info(f"get_cv_document jwt token received: {jwt_token}")

    if not os.path.exists(CV_DOCUMENT_PATH):
        return {"error": f"CV document not found at {CV_DOCUMENT_PATH}"}

    return {
        "filename": CV_DOCUMENT_NAME,
        "mime_type": CV_DOCUMENT_MIME,
        "size_bytes": os.path.getsize(CV_DOCUMENT_PATH),
    }


@mcp.tool()
def download_cv_document() -> dict:
    """Return Satish's CV / resume PDF document as base64-encoded bytes.

    This is used by the agent to stream the file to the UI. It returns the full
    document content, so it is meant for programmatic delivery rather than for
    showing to the user.

    Returns:
        dict: filename, mime_type, size_bytes and content_base64 (the PDF bytes
        encoded as a base64 string).
    """
    headers = get_http_headers(include={"authorization"})
    jwt_token = _get_request_jwt_token()
    logging.info(f"download_cv_document headers received: {headers}")
    logging.info(f"download_cv_document jwt token received: {jwt_token}")

    if not os.path.exists(CV_DOCUMENT_PATH):
        return {"error": f"CV document not found at {CV_DOCUMENT_PATH}"}

    with open(CV_DOCUMENT_PATH, "rb") as f:
        content_base64 = base64.b64encode(f.read()).decode("utf-8")

    return {
        "filename": CV_DOCUMENT_NAME,
        "mime_type": CV_DOCUMENT_MIME,
        "size_bytes": os.path.getsize(CV_DOCUMENT_PATH),
        "content_base64": content_base64,
    }


import datetime as _dt
from pptx import Presentation as _Presentation
from pptx.util import Inches as _Inches, Pt as _Pt
from pptx.dml.color import RGBColor as _RGBColor
from pptx.enum.text import PP_ALIGN as _PP_ALIGN

# ---------------------------------------------------------------------------
# PPT generation tool
# ---------------------------------------------------------------------------
# generate_ppt()  -> LLM-visible: LLM authors all slide content AND chooses
#                    the theme / layout per slide. Saves .pptx to LEAD_CV_DIR,
#                    returns only metadata. Bytes delivered via fetch_files_content
#                    (same pattern as download_files / fetch_files_content).
# ---------------------------------------------------------------------------

_THEMES = {
    # name       bg                 accent1            accent2            text
    "dark":     (0x0F1729, 0x38BDF8, 0x34D399, 0xCBD5E1),
    "light":    (0xF8FAFC, 0x1D4ED8, 0x0891B2, 0x1E293B),
    "blue":     (0x1E3A5F, 0x60A5FA, 0x93C5FD, 0xE0F2FE),
    "green":    (0x064E3B, 0x34D399, 0xA7F3D0, 0xD1FAE5),
    "purple":   (0x2E1065, 0xA78BFA, 0xC4B5FD, 0xEDE9FE),
    "red":      (0x450A0A, 0xF87171, 0xFCA5A5, 0xFEE2E2),
    "corporate":(0x1F2937, 0x3B82F6, 0x10B981, 0xF3F4F6),
    "minimal":  (0xFFFFFF, 0x111827, 0x6B7280, 0x374151),
    "orange":   (0x431407, 0xFB923C, 0xFED7AA, 0xFFF7ED),
    "pink":     (0x500724, 0xF472B6, 0xFBCFE8, 0xFDF2F8),
}

def _hex(h: int) -> _RGBColor:
    r = (h >> 16) & 0xFF
    g = (h >> 8)  & 0xFF
    b =  h        & 0xFF
    return _RGBColor(r, g, b)


def _build_pptx(topic: str, slides: list, theme: str = "dark",
                font_family: str = "Calibri") -> bytes:
    """Render slides and return raw .pptx bytes."""
    th = _THEMES.get(theme.lower(), _THEMES["dark"])
    BG, AC1, AC2, TXT = (_hex(c) for c in th)
    WHITE = _RGBColor(0xFF, 0xFF, 0xFF)
    is_light = th[0] > 0x888888           # light bg → use dark text

    # cycle palette for multi-column headings
    PALETTE = [_hex(c) for c in (
        0x38BDF8, 0x34D399, 0xFBBF24, 0xA78BFA,
        0xF472B6, 0xFB923C, 0x60A5FA, 0x4ADE80,
    )]

    prs = _Presentation()
    prs.slide_width  = _Inches(13.33)
    prs.slide_height = _Inches(7.5)
    blank = prs.slide_layouts[6]

    def _bg(slide):
        fill = slide.background.fill
        fill.solid()
        fill.fore_color.rgb = BG

    def _box(slide, l, t, w, h, color, alpha=None):
        s = slide.shapes.add_shape(
            1, _Inches(l), _Inches(t), _Inches(w), _Inches(h))
        s.line.fill.background()
        s.fill.solid()
        s.fill.fore_color.rgb = color
        return s

    def _txt(slide, text, l, t, w, h, size=16, bold=False,
             color=None, align=_PP_ALIGN.LEFT, italic=False):
        if color is None:
            color = TXT if is_light else WHITE
        tb = slide.shapes.add_textbox(
            _Inches(l), _Inches(t), _Inches(w), _Inches(h))
        tb.word_wrap = True
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.alignment = align
        run = p.add_run()
        run.text = text
        run.font.name  = font_family
        run.font.size  = _Pt(size)
        run.font.bold  = bold
        run.font.italic = italic
        run.font.color.rgb = color

    def _bullet_frame(slide, bullets, l, t, w, h, size=14,
                      color=None, marker="▸"):
        if color is None:
            color = TXT if is_light else _hex(th[3])
        tb = slide.shapes.add_textbox(
            _Inches(l), _Inches(t), _Inches(w), _Inches(h))
        tb.word_wrap = True
        tf = tb.text_frame
        tf.word_wrap = True
        first = True
        for b in (bullets or []):
            p = tf.paragraphs[0] if first else tf.add_paragraph()
            first = False
            p.space_before = _Pt(5)
            run = p.add_run()
            run.text = f"{marker}  {b}"
            run.font.name = font_family
            run.font.size = _Pt(size)
            run.font.color.rgb = color

    # ── Cover / title slide ──────────────────────────────────────────────────
    ts = prs.slides.add_slide(blank)
    _bg(ts)
    _box(ts, 0, 0,     13.33, 0.08, AC1)
    _box(ts, 0, 7.42,  13.33, 0.08, AC2)
    _box(ts, 0, 0.08,  0.07,  7.34, AC2)
    _txt(ts, topic,    0.4, 1.3, 12.3, 1.2,
         size=44, bold=True, color=AC1)
    _box(ts, 0.4, 2.7, 4.5, 0.04, AC2)
    date_str = _dt.date.today().strftime("%B %d, %Y")
    _txt(ts, f"AI-Generated Presentation  ·  {date_str}",
         0.4, 2.85, 10, 0.5, size=15,
         color=_hex(th[3]), italic=True)
    _txt(ts, f"{len(slides)} slide{'s' if len(slides) != 1 else ''}",
         0.4, 3.45, 3, 0.4, size=13, color=AC2)
    _txt(ts, "1", 12.9, 7.1, 0.35, 0.3, size=10,
         color=_hex(th[3]), align=_PP_ALIGN.RIGHT)

    # ── Content slides ───────────────────────────────────────────────────────
    for idx, sd in enumerate(slides):
        sl = prs.slides.add_slide(blank)
        _bg(sl)
        col = PALETTE[idx % len(PALETTE)]
        _box(sl, 0, 0,    13.33, 0.08, col)
        _box(sl, 0, 7.42, 13.33, 0.08, AC2)
        _box(sl, 0, 0.08, 0.07,  7.34, col)

        title    = sd.get("title", f"Slide {idx+1}")
        subtitle = sd.get("subtitle", "")
        bullets  = sd.get("bullets") or []
        columns  = sd.get("columns") or []   # [{heading, points:[]}]
        layout   = sd.get("layout", "auto")  # "bullets","columns","two_column","quote"
        quote    = sd.get("quote", "")       # big centred text
        bg_color_override = sd.get("bg_color")  # hex int e.g. 0x1a2b3c

        if bg_color_override:
            _box(sl, 0, 0, 13.33, 7.5, _hex(int(bg_color_override, 16)
                 if isinstance(bg_color_override, str) else bg_color_override))

        # Title bar
        _txt(sl, title, 0.3, 0.18, 12.7, 0.72, size=28, bold=True, color=col)
        _box(sl, 0.3, 0.97, 12.7, 0.03, col)

        body_top = 1.1 + (0.45 if subtitle else 0.0)
        if subtitle:
            _txt(sl, subtitle, 0.3, 1.03, 12.5, 0.4, size=14,
                 color=_hex(th[3]), italic=True)

        # — layout: quote / big text
        if layout == "quote" or quote:
            q = quote or (bullets[0] if bullets else "")
            _txt(sl, f'"{q}"', 0.8, 2.0, 11.5, 3.5, size=28, bold=True,
                 color=col, align=_PP_ALIGN.CENTER, italic=True)
            if len(bullets) > 1:
                _txt(sl, "— " + bullets[1], 0.8, 5.2, 11.5, 0.5,
                     size=16, color=_hex(th[3]), align=_PP_ALIGN.CENTER)

        # — layout: columns / multi-card
        elif columns or layout in ("columns", "two_column"):
            cols = columns or []
            n = len(cols)
            if n == 0 and layout == "two_column" and len(bullets) >= 2:
                mid = len(bullets) // 2
                cols = [{"heading": "", "points": bullets[:mid]},
                        {"heading": "", "points": bullets[mid:]}]
                n = 2
            if n:
                cw = (12.5 - 0.15*(n-1)) / n
                for ci, c in enumerate(cols):
                    cx = 0.3 + ci*(cw+0.15)
                    card_col = PALETTE[ci % len(PALETTE)]
                    _box(sl, cx, body_top, cw, 7.5-body_top-0.2,
                         _hex(th[0]+0x111111 if th[0] < 0xEEEEEE else th[0]-0x111111))
                    _box(sl, cx, body_top, cw, 0.07, card_col)
                    if c.get("heading"):
                        _txt(sl, c["heading"], cx+0.1, body_top+0.12,
                             cw-0.2, 0.42, size=13, bold=True, color=card_col)
                    _bullet_frame(sl, c.get("points") or [],
                                  cx+0.1, body_top+0.6, cw-0.2,
                                  7.5-body_top-0.9, size=11.5)

        # — layout: bullets (default)
        elif bullets:
            bsize = 17 if len(bullets) <= 5 else 14
            _bullet_frame(sl, bullets, 0.5, body_top, 12.0,
                          7.5-body_top-0.3, size=bsize)

        # slide number
        _txt(sl, str(idx+2), 12.9, 7.1, 0.35, 0.3, size=10,
             color=_hex(th[3]), align=_PP_ALIGN.RIGHT)

    import io
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


@mcp.tool()
def generate_ppt(topic: str, slides: list,
                 theme: str = "dark", font: str = "Calibri") -> dict:
    """Generate a styled PowerPoint presentation from slide content YOU compose.

    Call this when the user asks to create, generate, or build a presentation,
    slideshow, or PPT on any topic.

    YOU must:
    1. Compose all slide content (titles, bullets, columns) based on the topic.
    2. Choose an appropriate theme and layout for each slide.
    3. Call this tool — the .pptx is saved and returned as a download link
       automatically. Just confirm in one sentence it is ready.

    ── theme choices (pass as the `theme` arg) ──────────────────────────────
      "dark"      navy-black + sky-blue   (tech / AI talks)
      "light"     white + navy blue       (business / corporate)
      "blue"      dark-blue + light-blue  (professional)
      "green"     dark-green + teal       (sustainability / finance)
      "purple"    deep-purple + lavender  (creative / design)
      "red"       dark-red + coral        (bold / impactful)
      "corporate" charcoal + blue-green   (enterprise)
      "minimal"   white + near-black      (clean / academic)
      "orange"    dark-orange + amber     (energy / startup)
      "pink"      deep-rose + pink        (lifestyle / health)

    ── slide dict fields ────────────────────────────────────────────────────
      title    (str)        required — slide heading
      subtitle (str)        optional sub-heading
      layout   (str)        "bullets" | "columns" | "two_column" | "quote"
                            default "bullets" when `bullets` is provided,
                            default "columns" when `columns` is provided
      bullets  (list[str])  bullet points for "bullets" / "two_column" layouts
      columns  (list[dict]) for "columns" layout:
                              [{heading: str, points: [str]}]
      quote    (str)        large centred quote text for "quote" layout

    ── font choices ─────────────────────────────────────────────────────────
      "Calibri" (default), "Arial", "Helvetica", "Georgia", "Trebuchet MS"

    Args:
        topic:  Presentation title shown on the cover slide.
        slides: List of slide dicts (aim for 3-8 slides).
        theme:  Visual theme name (default "dark").
        font:   Font family (default "Calibri").

    Returns:
        dict: filename, size_bytes — metadata only; bytes delivered automatically.
    """
    headers = get_http_headers(include={"authorization"})
    logging.info(f"generate_ppt: topic={topic!r} slides={len(slides)} "
                 f"theme={theme!r} font={font!r}")

    os.makedirs(LEAD_CV_DIR, exist_ok=True)
    slug = "".join(c if c.isalnum() else "_" for c in topic)[:40]
    timestamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{slug}_{timestamp}.pptx"
    dest = os.path.join(LEAD_CV_DIR, filename)

    try:
        raw = _build_pptx(topic, slides, theme=theme, font_family=font)
        with open(dest, "wb") as f:
            f.write(raw)
        logging.info(f"generate_ppt saved {dest} ({len(raw)} bytes)")
        return {"filename": filename, "size_bytes": len(raw),
                "path": dest, "status": "created"}
    except Exception as e:
        logging.error(f"generate_ppt error: {e}")
        return {"error": str(e), "filename": None}


# ---------------------------------------------------------------------------
# Document folder browsing / download tools
# ---------------------------------------------------------------------------
# list_cv_files()        -> the model lists what is available (metadata only)
# download_files(names)  -> the model "triggers" a download (metadata only)
# fetch_files_content()  -> the jira agent fetches the real bytes (programmatic)
# Splitting the bytes into fetch_files_content keeps the large base64 content
# out of the LLM context.
LEAD_CV_DIR = os.getenv(
    "LEAD_CV_DIR",
    "/Users/satish/work/job_search_Germany/lead_cv",
)
# guard so we never push a huge file through the websocket / blob path
MAX_DOWNLOAD_BYTES = int(os.getenv("MAX_DOWNLOAD_BYTES", str(25 * 1024 * 1024)))


def _safe_file_path(filename: str) -> str | None:
    """Resolve a filename to a file that lives directly inside LEAD_CV_DIR.

    Strips any directory component (basename only) to prevent path traversal.
    Returns the absolute path or None if it is not a valid file in the folder.
    """
    if not filename:
        return None
    name = os.path.basename(filename.strip())
    full_path = os.path.join(LEAD_CV_DIR, name)
    if os.path.isfile(full_path) and os.path.dirname(os.path.abspath(full_path)) == os.path.abspath(LEAD_CV_DIR):
        return full_path
    return None


@mcp.tool()
def list_cv_files() -> dict:
    """List the documents available in Satish's document folder.

    Call this when the user asks to "show me the list of files", "what
    documents are available", etc. Returns only metadata (filename, size, type)
    so the user can then ask to download one or more of them by name.

    Returns:
        dict: directory path and a list of files (filename, size_bytes, mime_type).
    """
    headers = get_http_headers(include={"authorization"})
    logging.info(f"list_cv_files headers received: {headers}")

    if not os.path.isdir(LEAD_CV_DIR):
        return {"error": f"Folder not found: {LEAD_CV_DIR}"}

    files = []
    for name in sorted(os.listdir(LEAD_CV_DIR)):
        full_path = os.path.join(LEAD_CV_DIR, name)
        # skip hidden files (e.g. .DS_Store) and sub-directories
        if name.startswith(".") or not os.path.isfile(full_path):
            continue
        files.append({
            "filename": name,
            "size_bytes": os.path.getsize(full_path),
            "mime_type": mimetypes.guess_type(name)[0] or "application/octet-stream",
        })
    return {"directory": LEAD_CV_DIR, "count": len(files), "files": files}


@mcp.tool()
def download_files(filenames: list) -> dict:
    """Offer one or more documents from the folder for download.

    Call this when the user asks to download specific file(s) by name (you can
    pass several filenames at once). The files are delivered automatically to
    the chat UI as downloadable, previewable attachments, so you only need to
    confirm which files are on their way. Returns metadata only.

    Args:
        filenames: list of file names to download (as shown by list_cv_files).

    Returns:
        dict: per-file metadata (filename, mime_type, size_bytes, available).
    """
    headers = get_http_headers(include={"authorization"})
    logging.info(f"download_files headers received: {headers}; filenames={filenames}")

    results = []
    for filename in (filenames or []):
        full_path = _safe_file_path(filename)
        if not full_path:
            results.append({"filename": filename, "available": False,
                            "error": "file not found in folder"})
            continue
        results.append({
            "filename": os.path.basename(full_path),
            "mime_type": mimetypes.guess_type(full_path)[0] or "application/octet-stream",
            "size_bytes": os.path.getsize(full_path),
            "available": True,
        })
    return {"files": results}


@mcp.tool()
def fetch_files_content(filenames: list) -> dict:
    """Return the actual bytes (base64) for one or more files in the folder.

    Used by the agent to stream the requested files to the UI. Files larger
    than the configured limit are skipped with an error entry.

    Args:
        filenames: list of file names to fetch.

    Returns:
        dict: list of per-file results with content_base64 (or an error).
    """
    headers = get_http_headers(include={"authorization"})
    logging.info(f"fetch_files_content headers received: {headers}; filenames={filenames}")

    results = []
    for filename in (filenames or []):
        full_path = _safe_file_path(filename)
        if not full_path:
            results.append({"filename": filename, "error": "file not found in folder"})
            continue
        size_bytes = os.path.getsize(full_path)
        if size_bytes > MAX_DOWNLOAD_BYTES:
            results.append({
                "filename": os.path.basename(full_path),
                "error": f"file too large to deliver ({size_bytes} bytes, limit {MAX_DOWNLOAD_BYTES})",
            })
            continue
        with open(full_path, "rb") as f:
            content_base64 = base64.b64encode(f.read()).decode("utf-8")
        results.append({
            "filename": os.path.basename(full_path),
            "mime_type": mimetypes.guess_type(full_path)[0] or "application/octet-stream",
            "size_bytes": size_bytes,
            "content_base64": content_base64,
        })
    return {"files": results}


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


# ---------------------------------------------------------------------------
# File upload tools
# ---------------------------------------------------------------------------
# upload_files()        -> LLM-visible signal tool (metadata only, like download_files)
# save_uploaded_files() -> app-only byte handler (hidden from LLM, like fetch_files_content)
# The actual bytes never enter the LLM; the app intercepts the upload_files
# tool call and invokes save_uploaded_files directly, exactly mirroring the
# download pattern.
UPLOAD_TEMP_DIR = os.getenv(
    "UPLOAD_TEMP_DIR",
    "/Users/satish/work/job_search_Germany/lead_cv/temp",
)


@mcp.tool()
def upload_files(filenames: list) -> dict:
    """Signal that the user wants to upload files to the server temp directory.

    Call this when the user asks to upload, save, or store files to the server.
    Returns only lightweight metadata (filenames, destination). The actual file
    bytes are delivered automatically by the application after this tool
    responds - you do NOT need the file content yourself. Just confirm in one
    short sentence which files are being uploaded.

    Args:
        filenames: list of filenames the user wants to upload.

    Returns:
        dict: filenames and upload destination path.
    """
    headers = get_http_headers(include={"authorization"})
    logging.info(f"upload_files called: filenames={filenames}")
    return {
        "filenames": filenames,
        "status": "upload_requested",
        "destination": UPLOAD_TEMP_DIR,
    }


@mcp.tool()
def save_uploaded_files(files: list) -> dict:
    """Save user-uploaded files to the temp directory.

    Used by the application to store the actual file bytes. Each item in files
    must have: filename (str), content_base64 (str), mime_type (str, optional).
    Files are written to UPLOAD_TEMP_DIR. Returns metadata for each saved file.

    Args:
        files: list of {filename, content_base64, mime_type}

    Returns:
        dict: {saved: [{filename, size_bytes, path}], errors: [{filename, error}]}
    """
    headers = get_http_headers(include={"authorization"})
    logging.info(f"save_uploaded_files called: count={len(files or [])}")
    os.makedirs(UPLOAD_TEMP_DIR, exist_ok=True)
    saved = []
    errors = []
    for item in (files or []):
        filename = os.path.basename((item.get("filename") or "").strip())
        if not filename:
            errors.append({"filename": item.get("filename"), "error": "invalid filename"})
            continue
        try:
            content_bytes = base64.b64decode(item.get("content_base64", ""))
        except Exception as e:
            errors.append({"filename": filename, "error": f"base64 decode error: {e}"})
            continue
        dest = os.path.join(UPLOAD_TEMP_DIR, filename)
        try:
            with open(dest, "wb") as f:
                f.write(content_bytes)
            saved.append({"filename": filename, "size_bytes": len(content_bytes), "path": dest})
            logging.info(f"Saved uploaded file: {dest} ({len(content_bytes)} bytes)")
        except Exception as e:
            errors.append({"filename": filename, "error": f"write error: {e}"})
    return {"saved": saved, "errors": errors}


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
