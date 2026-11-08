# trello-mcp

Trello [MCP](https://modelcontextprotocol.io) server and CLI, with an OAuth flow to get credentials.

Tools: `list_boards`, `list_lists`, `list_cards`, `create_card`, `comment_card`.

## Setup

Create a Power-Up at <https://trello.com/power-ups/admin> to get an API key, and add
`http://localhost:8765` (the login callback) to its allowed origins. Then authorize once on the
host (it opens a browser, so it can't run in the container):

```sh
export TRELLO_API_KEY=...
uv run trello-mcp login     # saves the token to ~/.config/trello-mcp/token (mode 600)
```

## Run with Docker (default)

The image is `ghcr.io/devinsba/trello-mcp`. The saved token is mounted into the container
read-only and `TRELLO_API_KEY` is passed through from your shell.

**stdio** (the MCP client launches the container):

```sh
claude mcp add trello -e TRELLO_API_KEY -- docker run -i --rm \
  -e TRELLO_API_KEY -e TRELLO_MCP_TOKEN_FILE=/run/trello-token \
  -v "$HOME/.config/trello-mcp/token:/run/trello-token:ro" \
  ghcr.io/devinsba/trello-mcp stdio
```

```json
{ "mcpServers": { "trello": { "command": "docker", "args": [
  "run", "-i", "--rm",
  "-e", "TRELLO_API_KEY", "-e", "TRELLO_MCP_TOKEN_FILE=/run/trello-token",
  "-v", "/Users/you/.config/trello-mcp/token:/run/trello-token:ro",
  "ghcr.io/devinsba/trello-mcp", "stdio"
], "env": { "TRELLO_API_KEY": "..." } } } }
```

**HTTP** (`serve`, streamable HTTP at `/mcp`, health at `/healthz`):

```sh
docker run -d --name trello-mcp -p 127.0.0.1:8080:8080 \
  -e TRELLO_API_KEY -e TRELLO_MCP_TOKEN_FILE=/run/trello-token \
  -v "$HOME/.config/trello-mcp/token:/run/trello-token:ro" \
  ghcr.io/devinsba/trello-mcp
claude mcp add --transport http trello http://localhost:8080/mcp
```

Other HTTP clients: `{ "mcpServers": { "trello": { "url": "http://localhost:8080/mcp" } } }`.

The mount is read-only, so `/oauth/login` on a containerized `serve` can't save a token; log in
on the host. On Linux the container user must be able to read the token file (owned by you, mode
600): add `--user "$(id -u):$(id -g)"` if it can't.

## Run from source

```sh
uv sync
uv run trello-mcp stdio     # or: serve | boards | lists <board_id> | cards <list_id>
```

## Config (env)

| Var | Purpose |
| --- | --- |
| `TRELLO_API_KEY` | required |
| `TRELLO_TOKEN` | token; overrides the saved one |
| `TRELLO_MCP_TOKEN_FILE` | token path (default `~/.config/trello-mcp/token`) |
| `LOG_LEVEL` | default `INFO`; logs are JSON on stderr with trace ids |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | enables OTLP/HTTP traces and metrics export (other `OTEL_*` apply) |
| `TRELLO_MCP_BASE_URL` | public URL for the `serve` OAuth callback (default `http://localhost:8765`) |

`serve` also exposes `/oauth/login`. The `serve` endpoint has no auth of its own: keep it private.

## Releases

Pushing a `vX.Y.Z` tag runs CI, builds a multi-arch image to `ghcr.io/devinsba/trello-mcp`, and
drafts a GitHub Release with the wheel and sdist attached (install with
`uv tool install <wheel URL>`; GitHub Packages has no Python registry) and notes written by the `release-notes` agentic workflow (edit the `.md`, not the
generated `.lock.yml`).

## Development

```sh
uv run ruff check && uv run ruff format --check && uv run pytest
```
