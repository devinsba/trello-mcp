from fastapi.testclient import TestClient

from trello_mcp import trello
from trello_mcp.app import make_app


def test_oauth_flow(monkeypatch, tmp_path):
    monkeypatch.setenv("TRELLO_API_KEY", "k")
    monkeypatch.setenv("TRELLO_MCP_TOKEN_FILE", str(tmp_path / "token"))
    monkeypatch.delenv("TRELLO_TOKEN", raising=False)
    with TestClient(make_app("http://x")) as c:
        assert c.get("/healthz").json() == {"status": "ok"}
        r = c.get("/oauth/login", follow_redirects=False)
        assert r.headers["location"].startswith("https://trello.com/1/authorize?key=k&")
        state = r.headers["location"].split("state%3D")[-1].split("&")[0]
        assert c.post("/oauth/token", json={"token": "t", "state": "bad"}).status_code == 400
        assert c.post("/oauth/token", json={"token": "t", "state": state}).status_code == 200
    assert trello.load_token() == "t"
