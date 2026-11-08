import json
import time
from urllib.parse import parse_qs, urlparse

import requests
from fastapi.testclient import TestClient

from trello_mcp import trello
from trello_mcp.app import make_app, make_login_app


def fake_post(calls):
    def post(url, json, timeout):
        calls.append(json)
        n = len(calls)
        return type(
            "R",
            (),
            {
                "raise_for_status": lambda self: None,
                "json": lambda self: {
                    "access_token": f"a{n}",
                    "refresh_token": f"r{n}",
                    "expires_in": 3600,
                },
            },
        )()

    return post


def test_oauth_flow_and_refresh(monkeypatch, tmp_path):
    monkeypatch.setenv("TRELLO_MCP_TOKEN_FILE", str(tmp_path / "token.json"))
    calls = []
    monkeypatch.setattr(requests, "post", fake_post(calls))
    with TestClient(make_login_app("http://x")) as c:
        loc = c.get("/oauth/login", follow_redirects=False).headers["location"]
        q = parse_qs(urlparse(loc).query)
        assert loc.startswith("https://auth.atlassian.com/authorize?")
        assert q["code_challenge_method"] == ["S256"] and q["redirect_uri"] == [
            "http://x/oauth/callback"
        ]
        assert c.get("/oauth/callback?code=c&state=bad").status_code == 400
        assert c.get(f"/oauth/callback?code=c&state={q['state'][0]}").status_code == 200
    assert calls[0]["grant_type"] == "authorization_code" and calls[0]["code_verifier"]
    assert trello.access_token() == "a1"  # fresh: no refresh

    saved = json.loads((tmp_path / "token.json").read_text())
    saved["expires_at"] = time.time() - 1
    (tmp_path / "token.json").write_text(json.dumps(saved))
    assert trello.access_token() == "a2"  # expired: refreshed, single-use token rotated
    assert calls[1] == {
        "client_id": trello.CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": "r1",
    }
    assert json.loads((tmp_path / "token.json").read_text())["refresh_token"] == "r2"


def fake_trello(monkeypatch, valid="good"):
    """Stands in for trello.com: records the bearer of each call, 401s any other token."""
    seen = []

    def request(method, url, headers, params, timeout):
        bearer = headers["Authorization"].removeprefix("Bearer ")
        seen.append((url, bearer))

        def raise_for_status():
            if bearer != valid:
                raise requests.HTTPError("401")

        return type(
            "R",
            (),
            {
                "raise_for_status": staticmethod(raise_for_status),
                "json": staticmethod(lambda: [{"name": "b"}]),
            },
        )()

    monkeypatch.setattr(requests, "request", request)
    return seen


MCP = {"accept": "application/json, text/event-stream"}


def rpc(c, token, method, params=None):
    return c.post(
        "/mcp/",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
        headers={**MCP, "authorization": f"Bearer {token}"},
    )


def test_serve_requires_trello_valid_bearer(monkeypatch):
    fake_trello(monkeypatch)
    with TestClient(make_app("http://x")) as c:
        assert c.get("/healthz").json() == {"status": "ok"}
        meta = c.get("/.well-known/oauth-protected-resource/mcp").json()
        assert meta["authorization_servers"] == ["https://auth.atlassian.com/"] or meta[
            "authorization_servers"
        ] == ["https://auth.atlassian.com"]
        assert meta["resource"] == "http://x/mcp"
        anon = c.post(
            "/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=MCP
        )
        assert anon.status_code == 401 and "resource_metadata" in anon.headers["www-authenticate"]
        assert rpc(c, "stale", "tools/list").status_code == 401
        r = rpc(c, "good", "tools/list")
        assert r.status_code == 200 and "list_boards" in r.text


def test_serve_passes_caller_token_to_trello(monkeypatch, tmp_path):
    monkeypatch.setenv("TRELLO_MCP_TOKEN_FILE", str(tmp_path / "none.json"))  # must not be read
    seen = fake_trello(monkeypatch)
    with TestClient(make_app("http://x")) as c:
        r = rpc(c, "good", "tools/call", {"name": "list_boards", "arguments": {}})
    assert r.status_code == 200 and "isError" not in r.text.replace('"isError":false', "")
    assert seen[-1] == ("https://trello.com/1/members/me/boards", "good")


def test_serve_with_token_file_is_private_and_uses_it(monkeypatch, tmp_path):
    f = tmp_path / "token.json"
    f.write_text(json.dumps({"access_token": "good", "refresh_token": "r", "expires_at": 2e9}))
    monkeypatch.setenv("TRELLO_MCP_TOKEN_FILE", str(f))
    seen = fake_trello(monkeypatch)
    with TestClient(make_app("http://x", token_file=True)) as c:
        assert c.get("/.well-known/oauth-protected-resource/mcp").status_code == 404
        r = c.post(
            "/mcp/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "list_boards", "arguments": {}},
            },
            headers=MCP,  # no authorization header
        )
    assert r.status_code == 200 and seen == [("https://trello.com/1/members/me/boards", "good")]


def test_stdio_lists_tools():
    import json
    import subprocess
    import sys

    p = subprocess.Popen(
        [sys.executable, "-c", "from trello_mcp import main; main()", "stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )

    def rpc(msg):
        p.stdin.write(json.dumps({"jsonrpc": "2.0", **msg}) + "\n")
        p.stdin.flush()
        return p.stdout.readline() if "id" in msg else None

    try:
        rpc(
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "0"},
                },
            }
        )
        rpc({"method": "notifications/initialized"})
        assert "list_boards" in rpc({"id": 2, "method": "tools/list"})
    finally:
        p.kill()
