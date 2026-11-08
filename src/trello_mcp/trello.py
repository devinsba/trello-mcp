"""Thin Trello REST client and OAuth 2.0 (Atlassian 3LO + PKCE) credential storage."""

import json
import os
import time
from pathlib import Path

import requests

# Public identifier of the OAuth 2.0 client (not a secret).
CLIENT_ID = "nWVvErB2yFphPyjOpaBAUv56yZOGUB9f"
API = "https://trello.com/1"
AUTHORIZE_URL = "https://auth.atlassian.com/authorize"
TOKEN_URL = "https://auth.atlassian.com/oauth/token"
# Must be a subset of the client's configured scopes; offline_access yields a refresh token.
DEFAULT_SCOPES = "read:member:trello read:board:trello write:board:trello offline_access"


def token_file() -> Path:
    return Path(
        os.environ.get("TRELLO_MCP_TOKEN_FILE", "~/.config/trello-mcp/token.json")
    ).expanduser()


def scopes() -> str:
    return os.environ.get("TRELLO_SCOPES", DEFAULT_SCOPES)


def load_token() -> dict:
    try:
        return json.loads(token_file().read_text())
    except FileNotFoundError:
        raise RuntimeError("No Trello token: run `trello-mcp login`") from None


def save_token(token: dict) -> None:
    path = token_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write-then-rename so a crash can't lose the single-use refresh token. Needs the directory
    # (not just the file) to be writable.
    tmp = path.with_name(path.name + ".tmp")
    tmp.touch(mode=0o600)
    tmp.write_text(json.dumps(token))
    tmp.replace(path)


def _token_request(**body) -> dict:
    # client_secret only for confidential clients; public clients omit it.
    if secret := os.environ.get("TRELLO_CLIENT_SECRET"):
        body["client_secret"] = secret
    resp = requests.post(TOKEN_URL, json={"client_id": CLIENT_ID, **body}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _store(resp: dict, old_refresh: str | None = None) -> dict:
    token = {
        "access_token": resp["access_token"],
        "refresh_token": resp.get("refresh_token") or old_refresh,
        "expires_at": time.time() + resp["expires_in"],
    }
    save_token(token)
    return token


def exchange_code(code: str, verifier: str, redirect_uri: str) -> None:
    _store(
        _token_request(
            grant_type="authorization_code",
            code=code,
            code_verifier=verifier,
            redirect_uri=redirect_uri,
        )
    )


def access_token() -> str:
    """Refresh tokens are single-use, so refresh writes the new one back before returning.

    shortcut: no cross-process lock, two processes sharing one token file can race a refresh;
    add a file lock if that happens.
    """
    token = load_token()
    if token["expires_at"] - 60 < time.time():
        old = token["refresh_token"]
        token = _store(_token_request(grant_type="refresh_token", refresh_token=old), old)
    return token["access_token"]


def call(method: str, path: str, **params):
    resp = requests.request(
        method,
        f"{API}{path}",
        headers={"Authorization": f"Bearer {access_token()}"},
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def list_boards():
    return call("GET", "/members/me/boards", fields="name,url,closed")


def list_lists(board_id: str):
    return call("GET", f"/boards/{board_id}/lists", fields="name")


def list_cards(list_id: str):
    return call("GET", f"/lists/{list_id}/cards", fields="name,desc,url,due")


def create_card(list_id: str, name: str, desc: str = ""):
    return call("POST", "/cards", idList=list_id, name=name, desc=desc)


def comment_card(card_id: str, text: str):
    return call("POST", f"/cards/{card_id}/actions/comments", text=text)
