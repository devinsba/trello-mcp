"""FastAPI apps. `make_app` (serve): MCP at /mcp as an OAuth resource server that passes the
caller's Atlassian token through to Trello, health at /healthz. `make_login_app` (login): the
local OAuth flow that saves a token file for stdio and the CLI."""

import asyncio
import base64
import hashlib
import os
import secrets
import time
from contextlib import asynccontextmanager
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.routes import create_protected_resource_routes
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from . import trello

# FastAPI ships its own OTel; we use the contrib instrumentor instead, so turn it off.
NO_NATIVE_OTEL = {"tracing": False, "metrics": False, "logs": False, "operation_spans": False}

TOOLS = [
    trello.list_boards,
    trello.list_lists,
    trello.list_cards,
    trello.create_card,
    trello.comment_card,
]


def build_mcp(**kwargs) -> MCPServer:
    server = MCPServer("trello", **kwargs)
    for tool in TOOLS:
        server.tool()(tool)
    return server


mcp = build_mcp()  # unauthenticated: stdio uses the token file


class PassthroughVerifier:
    """Accepts a bearer iff Trello does, so an expired token gets a 401 (the client then
    refreshes) instead of a tool error. The token itself is used by trello.call.

    shortcut: validated tokens are cached 60s per process, so a revoked token lives that long.
    """

    def __init__(self) -> None:
        self.ok: dict[str, float] = {}

    async def verify_token(self, token: str) -> AccessToken | None:
        now = time.monotonic()
        self.ok = {t: exp for t, exp in self.ok.items() if exp > now}  # bounds the cache
        if token not in self.ok:
            try:
                await asyncio.to_thread(trello.call, "GET", "/members/me", token=token, fields="id")
            except Exception:
                return None
            self.ok[token] = now + 60
        return AccessToken(token=token, client_id=trello.CLIENT_ID, scopes=trello.SCOPES.split())


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def make_login_app(base_url: str) -> FastAPI:
    done = {"saved": False}
    pending: dict[str, str] = {}  # one login at a time

    app = FastAPI(openapi_url=None, telemetry=NO_NATIVE_OTEL)
    app.state.login_done = done

    @app.get("/oauth/login")
    def login():
        pending["verifier"], challenge = _pkce()
        pending["state"] = secrets.token_urlsafe(16)  # stops other sites from planting a code
        params = {
            "client_id": trello.CLIENT_ID,
            "scope": trello.SCOPES,
            "redirect_uri": f"{base_url}/oauth/callback",
            "response_type": "code",
            "prompt": "consent",
            "state": pending["state"],
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return RedirectResponse(f"{trello.AUTHORIZE_URL}?{urlencode(params)}")

    @app.get("/oauth/callback", response_class=HTMLResponse)
    def callback(code: str, state: str):
        if not pending or not secrets.compare_digest(state, pending["state"]):
            raise HTTPException(400, "bad state")
        trello.exchange_code(code, pending.pop("verifier"), f"{base_url}/oauth/callback")
        pending.clear()
        done["saved"] = True
        return "Logged in. You can close this tab."

    return app


def make_app(base_url: str | None = None, token_file: bool = False) -> FastAPI:
    """Passthrough resource server by default. `token_file=True` is the private mode for headless
    agents: no auth, every call uses the saved token (trello.token_file()), refreshed as needed."""
    base_url = (base_url or os.environ.get("TRELLO_MCP_BASE_URL", "http://localhost:8080")).rstrip(
        "/"
    )
    auth = AuthSettings(
        issuer_url="https://auth.atlassian.com",
        resource_server_url=f"{base_url}/mcp",
        required_scopes=trello.SCOPES.split(),
        validate_token_resource=False,  # Trello is the authority on the token
    )
    server = (
        build_mcp() if token_file else build_mcp(auth=auth, token_verifier=PassthroughVerifier())
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with server.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan, openapi_url=None, telemetry=NO_NATIVE_OTEL)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz")  # probes are noise

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    if not token_file:
        # RFC 9728 metadata must sit at the host root, outside the /mcp mount, to be discoverable
        app.router.routes.extend(
            create_protected_resource_routes(
                resource_url=auth.resource_server_url,
                authorization_servers=[auth.issuer_url],
                scopes_supported=auth.required_scopes,
            )
        )
    # host != localhost disables the localhost-only Host check, which would reject real hostnames
    app.mount(
        "/mcp",
        server.streamable_http_app(streamable_http_path="/", stateless_http=True, host="0.0.0.0"),
    )
    return app
