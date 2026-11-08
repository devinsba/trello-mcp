import json
import time
from urllib.parse import parse_qs, urlparse

import requests
from fastapi.testclient import TestClient

from trello_mcp import trello
from trello_mcp.app import make_app


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
    monkeypatch.setenv("TRELLO_CLIENT_ID", "cid")
    monkeypatch.setenv("TRELLO_MCP_TOKEN_FILE", str(tmp_path / "token.json"))
    calls = []
    monkeypatch.setattr(requests, "post", fake_post(calls))
    with TestClient(make_app("http://x")) as c:
        assert c.get("/healthz").json() == {"status": "ok"}
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
    assert calls[1] == {"client_id": "cid", "grant_type": "refresh_token", "refresh_token": "r1"}
    assert json.loads((tmp_path / "token.json").read_text())["refresh_token"] == "r2"


def test_mcp_lists_tools():
    with TestClient(make_app("http://x")) as c:
        r = c.post(
            "/mcp/",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"accept": "application/json, text/event-stream"},
        )
    assert r.status_code == 200 and "list_boards" in r.text


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
