# 0014. MCP server exposes read-only tools and policies, from the same registry

- **Status:** Proposed
- **Date:** 2026-10-09
- **Author:** Ignacio Rodríguez Caro

## Context

MCP (Model Context Protocol) lets any compatible client (Claude Desktop, Claude Code, other
agents) discover and call tools and read resources. We want the store's capabilities
available there without duplicating logic. The official Python SDK at version 2.3.0 calls
its high-level server class `MCPServer` (it was `FastMCP` in 1.x).

## Options

1. **Expose every tool, including `create_return_request` and `handoff_to_human`**: maximum
   reuse; but our confirmation guarantee depends on *customer turns* in our own
   conversation, which an MCP server does not see. Any MCP client could create returns or
   tickets with only the host's generic approval prompt as protection.
2. **Expose read-only tools only**: safe on any surface; writes stay in the controlled
   customer channel.
3. **Separate MCP implementation**: freedom to shape it differently, at the cost of two
   code paths that drift.

## Decision

Option 2, built on the shared `ToolRegistry`: the MCP signature is generated from each
tool's Pydantic model, so schemas, validation, security rules and error payloads are
identical. Tools carry `read_only_hint`. Policies are also published as MCP resources
(`quilora://policies/{doc}`).

## Consequences

- A support agent can use Claude Desktop with this server to look up products, policies and
  orders (still requiring order number + email).
- Over stdio there is one client per process, so the order-lookup lockout is per client.
  Serving over HTTP to many clients would need per-session state and authentication (OAuth
  support exists in the SDK); documented as a next step.
- Exposing writes over MCP would require an MCP-native confirmation (e.g. elicitation)
  and authentication; a new ADR would be needed.
