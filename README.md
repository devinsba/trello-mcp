# trello-mcp

Trello [MCP](https://modelcontextprotocol.io) server and CLI, with an OAuth flow to get credentials.

Tools: `list_boards`, `list_lists`, `list_cards`, `create_card`, `comment_card`.

## Setup

Create an OAuth 2.0 client for your app at <https://trello.com/apps/admin> (OAuth 2.0 tab). Add
`http://localhost:8765/oauth/callback` (for `login`) and `http://localhost:8765/callback` (for
Claude Code signing in to `serve`) as callback URLs and enable the scopes
`read:member:trello`, `read:board:trello` and `write:board:trello`. The client ID is built in, so
the client must be a public one (no secret).

Authorize once for `stdio`, the CLI and `serve --refresh-token-file` (passthrough `serve` does not
need this). The directory `~/.config/trello-mcp` is mounted **read/write**, because access tokens
last an hour and each refresh rotates the single-use refresh token, which has to be saved. Open
the printed URL yourself:

```sh
mkdir -p ~/.config/trello-mcp
docker run --rm -it -p 127.0.0.1:8765:8765 \
  -e TRELLO_MCP_TOKEN_FILE=/run/trello/token.json \
  -v "$HOME/.config/trello-mcp:/run/trello" \
  ghcr.io/devinsba/trello-mcp login --host 0.0.0.0
```

Or from source: `uv run trello-mcp login` (opens the browser). The tokens are saved to
`~/.config/trello-mcp/token.json` (mode 600). Refresh tokens expire after 90 days of disuse; run
`login` again then.

## Run modes and connecting Claude

| Mode | Who signs in | Token lives in | Use for |
| --- | --- | --- | --- |
| [stdio](#stdio-claude-launches-it) | you, once, with `login` | token file on your machine | Claude Code on your laptop |
| [serve](#serve-passthrough-http) | Claude, in the browser, per client | the client (nothing on the server) | a shared or cluster deployment with interactive clients |
| [serve --refresh-token-file](#serve---refresh-token-file-headless-agents) | you, once, with `login` | token file on the server | headless agents in a cluster |

The image is `ghcr.io/devinsba/trello-mcp`. Examples use `claude mcp add`; add `--scope user` or
`--scope project` to share the entry across projects or commit it to `.mcp.json`.

### stdio (Claude launches it)

Run `login` first (see Setup). Claude starts the server as a subprocess and talks over stdin/stdout.
The token directory is mounted read/write, since refreshes rewrite the file.

```sh
# Docker
claude mcp add trello -- docker run -i --rm \
  -e TRELLO_MCP_TOKEN_FILE=/run/trello/token.json \
  -v "$HOME/.config/trello-mcp:/run/trello" \
  ghcr.io/devinsba/trello-mcp stdio

# From source
claude mcp add trello -- uv run --directory /path/to/trello-mcp trello-mcp stdio
```

The same as JSON (`.mcp.json` or `~/.claude.json`):

```json
{ "mcpServers": { "trello": { "command": "docker", "args": [
  "run", "-i", "--rm",
  "-e", "TRELLO_MCP_TOKEN_FILE=/run/trello/token.json",
  "-v", "/Users/you/.config/trello-mcp:/run/trello",
  "ghcr.io/devinsba/trello-mcp", "stdio"
] } } }
```

### serve (passthrough HTTP)

Streamable HTTP at `/mcp`, health at `/healthz`. It keeps no token: it is an OAuth resource server
(RFC 9728 metadata at `/.well-known/oauth-protected-resource/mcp`) that points clients at
Atlassian's authorization server, and passes each caller's bearer token straight to Trello. A token
Trello rejects gets a 401, so the client re-authorizes or refreshes. Any number of replicas can
run, with no volume. Set `TRELLO_MCP_BASE_URL` to the public URL clients use; it must match
exactly, because it is the OAuth resource identifier.

```sh
# Run it (local; in a cluster, use your public https URL)
docker run -d --name trello-mcp -p 127.0.0.1:8080:8080 \
  -e TRELLO_MCP_BASE_URL=http://localhost:8080 ghcr.io/devinsba/trello-mcp
# or from source: TRELLO_MCP_BASE_URL=http://localhost:8080 uv run trello-mcp serve

# Connect Claude Code
claude mcp add --transport http --client-id nWVvErB2yFphPyjOpaBAUv56yZOGUB9f \
  --callback-port 8765 trello http://localhost:8080/mcp
```

Then run `/mcp` in Claude Code, pick `trello` and choose Authenticate; the browser opens to
Atlassian. Claude refreshes the token itself afterwards. Atlassian has no dynamic client
registration, so the client must be given the client ID and a fixed callback port, which must be
registered as `http://localhost:8765/callback` (see Setup).

As JSON:

```json
{ "mcpServers": { "trello": {
  "type": "http",
  "url": "https://trello-mcp.example.com/mcp",
  "oauth": { "clientId": "nWVvErB2yFphPyjOpaBAUv56yZOGUB9f", "callbackPort": 8765 }
} } }
```

### serve --refresh-token-file (headless agents)

For agents with nobody to sign in. Run `serve --refresh-token-file /data/token.json` with a token
file from `login`. The server then holds the token and refreshes it (rewriting the file; the
directory must be writable). Run exactly one replica per file. Seed the file once (`kubectl cp`)
and never overwrite it on restart, since the rotated refresh token would be lost.

```sh
docker run -d --name trello-mcp -p 127.0.0.1:8080:8080 \
  -e TRELLO_MCP_TOKEN_FILE=/run/trello/token.json \
  -v "$HOME/.config/trello-mcp:/run/trello" \
  ghcr.io/devinsba/trello-mcp serve --refresh-token-file /run/trello/token.json

# Connect: no sign-in, no --client-id
claude mcp add --transport http trello http://localhost:8080/mcp
```

As JSON: `{ "mcpServers": { "trello": { "type": "http", "url": "http://localhost:8080/mcp" } } }`.
For an agent in the cluster, run the server as a sidecar and point the agent at
`http://localhost:8080/mcp`.

> **Warning: this mode has no authentication.** Anyone who can reach the port can read and write
> your Trello boards as you. Keep it reachable only by the agent:
>
> - Prefer a **sidecar** in the agent's pod and connect to `http://localhost:8080/mcp`, or bind
>   with `--host 127.0.0.1`. Nothing outside the pod can then reach it.
> - If it runs as its own Deployment, a **NetworkPolicy** that allows ingress only from the agent
>   pods is mandatory. Without one, every pod in the cluster can use your token. Kubernetes allows
>   all traffic by default, and a NetworkPolicy has no effect unless the cluster's CNI enforces it.
> - Never create an Ingress, IngressRoute or LoadBalancer Service for it. The public, authenticated
>   deployment is the passthrough `serve` above (no flag), not this one.
> - Mount the token volume only into this container. Treat the token file like a password, since
>   it holds a refresh token that lasts 90 days.

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
| `TRELLO_MCP_TOKEN_FILE` | token path for `login`, `stdio` and the CLI (not used by `serve`) |
| `LOG_LEVEL` | default `INFO`; logs are JSON on stderr with trace ids |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | enables OTLP/HTTP traces and metrics export (other `OTEL_*` apply) |
| `TRELLO_MCP_BASE_URL` | public URL of `serve` (default `http://localhost:8080`) |


## Releases

Pushing a `vX.Y.Z` tag runs CI, builds a multi-arch image to `ghcr.io/devinsba/trello-mcp`, and
drafts a GitHub Release with the wheel and sdist attached (install with
`uv tool install <wheel URL>`; GitHub Packages has no Python registry) and notes written by the `release-notes` agentic workflow (edit the `.md`, not the
generated `.lock.yml`).

## Development

```sh
uv run ruff check && uv run ruff format --check && uv run pytest
```
