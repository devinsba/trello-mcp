import argparse
import json
import threading
import time
import webbrowser

import uvicorn

from . import trello
from .app import make_app


def login(port: int) -> None:
    server = uvicorn.Server(
        uvicorn.Config(make_app(f"http://localhost:{port}"), port=port, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    print(f"Opening browser to authorize; token will be saved to {trello.token_file()}")
    webbrowser.open(f"http://localhost:{port}/oauth/login")
    while not server.config.app.state.login_done["saved"]:
        time.sleep(0.2)
    server.should_exit = True
    print("Logged in.")


def main() -> None:
    p = argparse.ArgumentParser(prog="trello-mcp")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the MCP server (/mcp) with OAuth routes (/oauth)")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8080)
    sub.add_parser(
        "login", help="run the OAuth flow in your browser and save the token"
    ).add_argument("--port", type=int, default=8765)
    sub.add_parser("boards", help="list boards")
    sub.add_parser("lists", help="list a board's lists").add_argument("board_id")
    sub.add_parser("cards", help="list a list's cards").add_argument("list_id")
    args = p.parse_args()

    match args.cmd:
        case "serve":
            uvicorn.run(make_app(), host=args.host, port=args.port)
        case "login":
            login(args.port)
        case "boards":
            print(json.dumps(trello.list_boards(), indent=2))
        case "lists":
            print(json.dumps(trello.list_lists(args.board_id), indent=2))
        case "cards":
            print(json.dumps(trello.list_cards(args.list_id), indent=2))
