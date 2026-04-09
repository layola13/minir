# MCP Integration — Claude Code

## Setup

Run the MCP server:

```bash
python mcp_server.py
```

Or add to Claude Code:

```bash
claude mcp add mimir -- python /path/to/mimir/mcp_server.py
```

## Available Tools

- **mimir_status** — palace stats (wings, rooms, drawer counts)
- **mimir_search** — semantic search across all memories
- **mimir_list_wings** — list all projects in the palace

## Usage in Claude Code

Once configured, Claude Code can search your memories directly during conversations.
