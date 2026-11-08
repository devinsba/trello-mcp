"""Thin Trello REST client and credential storage."""

import os
from pathlib import Path

import requests

API = "https://api.trello.com/1"


def token_file() -> Path:
    return Path(os.environ.get("TRELLO_MCP_TOKEN_FILE", "~/.config/trello-mcp/token")).expanduser()


def api_key() -> str:
    return os.environ["TRELLO_API_KEY"]


def load_token() -> str:
    """TRELLO_TOKEN wins; otherwise the token saved by `trello-mcp login`."""
    if token := os.environ.get("TRELLO_TOKEN"):
        return token
    try:
        return token_file().read_text().strip()
    except FileNotFoundError:
        raise RuntimeError("No Trello token: run `trello-mcp login` or set TRELLO_TOKEN") from None


def save_token(token: str) -> None:
    path = token_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600)
    path.write_text(token)


def call(method: str, path: str, **params):
    resp = requests.request(
        method,
        f"{API}{path}",
        # Header, not query params: URLs end up in exception messages and logs.
        headers={
            "Authorization": f'OAuth oauth_consumer_key="{api_key()}", oauth_token="{load_token()}"'
        },
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
