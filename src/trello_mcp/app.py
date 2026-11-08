"""FastAPI app: MCP at /mcp, OAuth (token) flow at /oauth, health at /healthz."""

import os
import secrets
from contextlib import asynccontextmanager
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from mcp.server.mcpserver import MCPServer
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import BaseModel

from . import trello

# FastAPI ships its own OTel; we use the contrib instrumentor instead, so turn it off.
NO_NATIVE_OTEL = {"tracing": False, "metrics": False, "logs": False, "operation_spans": False}

mcp = MCPServer("trello")
mcp.tool()(trello.list_boards)
mcp.tool()(trello.list_lists)
mcp.tool()(trello.list_cards)
mcp.tool()(trello.create_card)
mcp.tool()(trello.comment_card)

# Trello's authorize flow returns the token in the URL fragment, which the server never sees,
# so the callback page reads it in JS and POSTs it back.
CALLBACK_PAGE = """<!doctype html><title>Trello login</title><p id=m>Finishing login…</p>
<script>
const token = new URLSearchParams(location.hash.slice(1)).get("token");
fetch("/oauth/token", {method: "POST", headers: {"content-type": "application/json"},
  body: JSON.stringify({token, state: new URLSearchParams(location.search).get("state")})})
  .then(r => m.textContent = r.ok && token ? "Logged in. Close this tab." : "Login failed.");
</script>"""


class TokenBody(BaseModel):
    token: str | None
    state: str


def make_app(base_url: str | None = None) -> FastAPI:
    base_url = base_url or os.environ.get("TRELLO_MCP_BASE_URL", "http://localhost:8765")
    state = secrets.token_urlsafe(16)  # stops other sites from planting a token
    done = {"saved": False}

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
        params = {
            "key": trello.api_key(),
            "name": "trello-mcp",
            "scope": "read,write",
            "expiration": "never",
            "response_type": "token",
            "callback_method": "fragment",
            "return_url": f"{base_url}/oauth/callback?state={state}",
        }
        return RedirectResponse(f"https://trello.com/1/authorize?{urlencode(params)}")

    @app.get("/oauth/callback", response_class=HTMLResponse)
    def callback():
        return CALLBACK_PAGE

    @app.post("/oauth/token")
    def token(body: TokenBody):
        if not body.token or not secrets.compare_digest(body.state, state):
            raise HTTPException(400, "bad token or state")
        trello.save_token(body.token)
        done["saved"] = True
        return {"ok": True}

    # host != localhost disables the localhost-only Host check, which would reject real hostnames
    app.mount(
        "/mcp",
        mcp.streamable_http_app(streamable_http_path="/", stateless_http=True, host="0.0.0.0"),
    )
    return app
