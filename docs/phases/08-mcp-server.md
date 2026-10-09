# Phase 8: MCP server

## Concept: agent vs MCP

- **The agent** is a *program that decides*: it holds the conversation, calls the model,
  chooses which tool to run, enforces turn-based confirmation and answers the customer.
  It lives in `agent/loop.py`.
- **MCP** is a *protocol for publishing capabilities*: a server lists tools (name,
  description, JSON Schema) and resources (documents), and any MCP client can call them. The
  client brings its own model and its own loop; the server only executes.

An analogy from my own stack: MCP is to tools what an OpenAPI-described REST API is to
services. It does not decide anything; it makes capabilities discoverable and callable in a
standard way. The agent is the application that consumes such capabilities.

In this project both sit on the same `ToolRegistry`, so a rule like "order lookups need
the matching email" holds whether the call comes from our agent or from Claude Desktop.

## What was built

- `src/quilora/mcp_server.py`: an `MCPServer` (official SDK 2.3.0) that registers the six
  read-only tools with schemas generated from the same Pydantic models, plus the policies
  as resources `quilora://policies/{ret,shp,exc,pay,care,size,sup,faq}`.
- Tests that connect a real MCP client in-process: tool list, schemas, a successful call,
  a refused order lookup (`isError: true` with our error payload), resources.

## Try it with Claude Desktop

Add to `claude_desktop_config.json` (adjust paths):

```json
{
  "mcpServers": {
    "quilora-store": {
      "command": "/path/to/quilora-assistant/.venv/bin/python",
      "args": ["-m", "quilora.mcp_server"],
      "cwd": "/path/to/quilora-assistant",
      "env": {"DATABASE_URL": "postgresql://quilora:quilora_dev@localhost:5432/quilora",
              "STORE_TODAY": "2026-10-01"}
    }
  }
}
```

Claude Code: `claude mcp add quilora-store -- /path/to/.venv/bin/python -m quilora.mcp_server`
(check the current syntax with `claude mcp add --help`).

Check the configuration file location and format in the official MCP and Claude Desktop
documentation; they change between versions.

## Why only read-only tools

See [ADR 0014](../decisions/0014-mcp-read-only.md): our return confirmation relies on
customer turns that an MCP server cannot observe.
