"""FastAPI app: MCP at /mcp, OAuth 2.0 flow at /oauth, health at /healthz."""

import base64
import hashlib
import os
import secrets
from contextlib import asynccontextmanager
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from mcp.server.mcpserver import MCPServer
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from . import trello

# FastAPI ships its own OTel; we use the contrib instrumentor instead, so turn it off.
NO_NATIVE_OTEL = {"tracing": False, "metrics": False, "logs": False, "operation_spans": False}

mcp = MCPServer("trello")
mcp.tool()(trello.list_boards)
mcp.tool()(trello.list_lists)
mcp.tool()(trello.list_cards)
mcp.tool()(trello.create_card)
mcp.tool()(trello.comment_card)


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def make_app(base_url: str | None = None) -> FastAPI:
    base_url = base_url or os.environ.get("TRELLO_MCP_BASE_URL", "http://localhost:8765")
    done = {"saved": False}
    pending: dict[str, str] = {}  # one login at a time

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan, openapi_url=None, telemetry=NO_NATIVE_OTEL)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz")  # probes are noise
    app.state.login_done = done

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

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

    # host != localhost disables the localhost-only Host check, which would reject real hostnames
    app.mount(
        "/mcp",
        mcp.streamable_http_app(streamable_http_path="/", stateless_http=True, host="0.0.0.0"),
    )
    return app
