# trello-mcp

Trello [MCP](https://modelcontextprotocol.io) server and CLI, with an OAuth flow to get credentials.

Tools: `list_boards`, `list_lists`, `list_cards`, `create_card`, `comment_card`.

## Setup

Create an OAuth 2.0 client for your app at <https://trello.com/apps/admin> (OAuth 2.0 tab). Add
`http://localhost:8765/oauth/callback` as a callback URL and enable the scopes you need
(`read:member:trello`, `read:board:trello`, `write:board:trello` by default; override with
`TRELLO_SCOPES`). Public clients need only the client ID; confidential clients also need
`TRELLO_CLIENT_SECRET`.

Authorize once. The directory `~/.config/trello-mcp` is mounted **read/write**, because access
tokens last an hour and each refresh rotates the single-use refresh token, which has to be saved.
Open the printed URL yourself:

```sh
export TRELLO_CLIENT_ID=...    # and TRELLO_CLIENT_SECRET=... for a confidential client
mkdir -p ~/.config/trello-mcp
docker run --rm -it -p 127.0.0.1:8765:8765 \
  -e TRELLO_CLIENT_ID -e TRELLO_CLIENT_SECRET -e TRELLO_MCP_TOKEN_FILE=/run/trello/token.json \
  -v "$HOME/.config/trello-mcp:/run/trello" \
  ghcr.io/devinsba/trello-mcp login --host 0.0.0.0
```

Or from source: `uv run trello-mcp login` (opens the browser). The tokens are saved to
`~/.config/trello-mcp/token.json` (mode 600). Refresh tokens expire after 90 days of disuse; run
`login` again then.

## Run with Docker (default)

The image is `ghcr.io/devinsba/trello-mcp`. The token directory is mounted read/write (see above);
`TRELLO_CLIENT_ID` (and the secret, if any) pass through from your shell.

**stdio** (the MCP client launches the container):

```sh
claude mcp add trello -e TRELLO_CLIENT_ID -- docker run -i --rm \
  -e TRELLO_CLIENT_ID -e TRELLO_CLIENT_SECRET -e TRELLO_MCP_TOKEN_FILE=/run/trello/token.json \
  -v "$HOME/.config/trello-mcp:/run/trello" \
  ghcr.io/devinsba/trello-mcp stdio
```

```json
{ "mcpServers": { "trello": { "command": "docker", "args": [
  "run", "-i", "--rm",
  "-e", "TRELLO_CLIENT_ID", "-e", "TRELLO_MCP_TOKEN_FILE=/run/trello/token.json",
  "-v", "/Users/you/.config/trello-mcp:/run/trello",
  "ghcr.io/devinsba/trello-mcp", "stdio"
], "env": { "TRELLO_CLIENT_ID": "..." } } } }
```

(Add `-e TRELLO_CLIENT_SECRET` to the args and env for a confidential client.)

**HTTP** (`serve`, streamable HTTP at `/mcp`, health at `/healthz`):

```sh
docker run -d --name trello-mcp -p 127.0.0.1:8080:8080 \
  -e TRELLO_CLIENT_ID -e TRELLO_CLIENT_SECRET -e TRELLO_MCP_TOKEN_FILE=/run/trello/token.json \
  -v "$HOME/.config/trello-mcp:/run/trello" \
  ghcr.io/devinsba/trello-mcp
claude mcp add --transport http trello http://localhost:8080/mcp
```

Other HTTP clients: `{ "mcpServers": { "trello": { "url": "http://localhost:8080/mcp" } } }`.

Don't run two containers against one token directory at once: a simultaneous refresh can burn the
single-use refresh token. On Linux the container user must be able to write the directory: add
`--user "$(id -u):$(id -g)"` if it can't.

## Run from source

```sh
uv sync
uv run trello-mcp stdio     # or: serve | boards | lists <board_id> | cards <list_id>
```

## Config (env)

| Var | Purpose |
| --- | --- |
| `TRELLO_CLIENT_ID` | required; OAuth 2.0 client ID |
| `TRELLO_CLIENT_SECRET` | confidential clients only |
| `TRELLO_SCOPES` | space-separated scopes (default read/write board + member read + `offline_access`) |
| `TRELLO_MCP_TOKEN_FILE` | token path (default `~/.config/trello-mcp/token.json`) |
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
