# trello-mcp

Trello [MCP](https://modelcontextprotocol.io) server and CLI, with an OAuth flow to get credentials.

Tools: `list_boards`, `list_lists`, `list_cards`, `create_card`, `comment_card`.

## Setup

Create a Power-Up at <https://trello.com/power-ups/admin> to get an API key, and add the base URL
you'll use (default `http://localhost:8765`) to its allowed origins.

```sh
uv sync
export TRELLO_API_KEY=...
uv run trello-mcp login     # opens the browser, saves the token to ~/.config/trello-mcp/token
uv run trello-mcp boards    # CLI: boards | lists <board_id> | cards <list_id>
uv run trello-mcp serve     # MCP over streamable HTTP at :8080/mcp, health at /healthz
```

## Config (env)

| Var | Purpose |
| --- | --- |
| `TRELLO_API_KEY` | required |
| `TRELLO_TOKEN` | token; overrides the saved one |
| `TRELLO_MCP_TOKEN_FILE` | token path (default `~/.config/trello-mcp/token`) |
| `TRELLO_MCP_BASE_URL` | public URL for the `serve` OAuth callback (default `http://localhost:8765`) |

`serve` also exposes `/oauth/login`, so a deployed server can be authorized by visiting it.
The `serve` endpoint has no auth of its own: keep it private.

## Development

```sh
uv run ruff check && uv run ruff format --check && uv run pytest
```
