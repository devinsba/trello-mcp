import argparse
import json
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from . import telemetry, trello
from .app import make_app, make_login_app, mcp


def login(host: str, port: int) -> None:
    server = uvicorn.Server(
        uvicorn.Config(
            make_login_app(f"http://localhost:{port}"), host=host, port=port, log_config=None
        )
    )
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    url = f"http://localhost:{port}/oauth/login"
    print(f"Open {url} to authorize; token will be saved to {trello.token_file()}", flush=True)
    webbrowser.open(url)
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
    s.add_argument(
        "--refresh-token-file",
        type=Path,
        help="token file from `login`: serve with it, unauthenticated and private, instead of "
        "passing each caller's token through (for headless agents; keep the port private)",
    )
    lg = sub.add_parser("login", help="run the OAuth flow in your browser and save the token")
    lg.add_argument("--host", default="127.0.0.1")  # 0.0.0.0 inside a container
    lg.add_argument("--port", type=int, default=8765)
    sub.add_parser("stdio", help="run the MCP server over stdio (for command-launched clients)")
    sub.add_parser("boards", help="list boards")
    sub.add_parser("lists", help="list a board's lists").add_argument("board_id")
    sub.add_parser("cards", help="list a list's cards").add_argument("list_id")
    # Bare `trello-mcp` serves: the image's web process is bare, so `docker run image stdio` works.
    args = p.parse_args(sys.argv[1:] or ["serve"])
    telemetry.setup()
    telemetry.configure_logging(os.environ.get("LOG_LEVEL", "INFO").upper())

    match args.cmd:
        case "serve":
            if args.refresh_token_file:
                if not args.refresh_token_file.is_file():
                    sys.exit(f"{args.refresh_token_file} not found: run `trello-mcp login` first")
                os.environ["TRELLO_MCP_TOKEN_FILE"] = str(args.refresh_token_file)
            # log_config=None keeps the root JSON logging with trace ids
            uvicorn.run(
                make_app(token_file=bool(args.refresh_token_file)),
                host=args.host,
                port=args.port,
                log_config=None,
            )
        case "stdio":
            mcp.run("stdio")  # stdout is the protocol channel; logs already go to stderr
        case "login":
            login(args.host, args.port)
        case "boards":
            print(json.dumps(trello.list_boards(), indent=2))
        case "lists":
            print(json.dumps(trello.list_lists(args.board_id), indent=2))
        case "cards":
            print(json.dumps(trello.list_cards(args.list_id), indent=2))
