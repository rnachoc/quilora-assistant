"""Expose the store's read-only tools (and policies as resources) over MCP.

    python -m quilora.mcp_server                      # stdio, for Claude Desktop / Claude Code
    python -m quilora.mcp_server --http --port 8001   # Streamable HTTP

Agent vs MCP, in one sentence each:
  * The AGENT (agent/loop.py) is a program that decides: it runs the model, chooses tools,
    and talks to the customer.
  * MCP is a standard PROTOCOL for publishing tools and data so any MCP client (Claude
    Desktop, Claude Code, another company's agent) can discover and call them.

Both use the same ToolRegistry, so validation, security rules and error shapes are
identical whichever way a tool is called. Only read-only tools are exposed here (ADR 0014).

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

import argparse
import inspect
from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError as MCPToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from quilora.config import Settings, load_settings
from quilora.db import Database
from quilora.search.chunking import load_policies
from quilora.tools import build_registry
from quilora.tools.base import SessionState, ToolContext, ToolRegistry, ToolSpec

# Writes need a confirmation flow tied to a customer conversation; handoffs create tickets.
# Neither belongs on a general-purpose integration surface.
EXCLUDED_TOOLS = {"create_return_request", "handoff_to_human"}


def _signature_for(spec: ToolSpec, registry: ToolRegistry) -> inspect.Signature:
    """Build a function signature from the tool's Pydantic model, so MCP generates the same
    schema (types, constraints and descriptions) that the agent's tool definition has."""
    params = []
    for name, field in spec.input_model.model_fields.items():
        annotation: Any = Annotated[field.annotation, *field.metadata,
                                    Field(description=registry.render(field.description or ""))]
        default = inspect.Parameter.empty if field.is_required() else field.default
        params.append(inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY,
                                        default=default, annotation=annotation))
    return inspect.Signature(params, return_annotation=str)


def _wrap(spec: ToolSpec, registry: ToolRegistry, context_factory) -> Any:
    """Adapt a ToolSpec into a function MCPServer can register, delegating to the shared registry.
    """
    def handler(**kwargs: Any) -> str:
        args = {k: v for k, v in kwargs.items() if v is not None}
        outcome = registry.execute(spec.name, args, context_factory())
        if outcome.is_error:
            # Reported to the client as a tool error (isError: true) with our JSON payload.
            raise MCPToolError(outcome.content())
        return outcome.content()

    handler.__name__ = spec.name
    handler.__doc__ = registry.render(spec.description)
    handler.__signature__ = _signature_for(spec, registry)  # type: ignore[attr-defined]
    handler.__annotations__ = {p.name: p.annotation for p in
                               handler.__signature__.parameters.values()}  # type: ignore[attr-defined]
    handler.__annotations__["return"] = str
    return handler


def create_server(settings: Settings, db: Database) -> MCPServer:
    """Build the MCP server with the read-only tools and the policies as resources."""
    store = settings.store
    server = MCPServer(
        name=f"{store.id}-store",
        instructions=f"Read-only access to {store.name}: catalog, stock, size "
                     "recommendations, delivery estimates, promotions, policies and order "
                     "status (order number + email).",
    )
    registry = build_registry(store)
    # One state per server process: with stdio there is one client per process, so the
    # order-lookup lockout applies per connected client. (HTTP would need per-session state.)
    state = SessionState()

    def context() -> ToolContext:
        return ToolContext(db=db, settings=settings, state=state, session_id="mcp",
                           turn_index=0)

    for spec in registry.specs:
        if spec.mutates or spec.name in EXCLUDED_TOOLS:
            continue
        server.add_tool(
            _wrap(spec, registry, context),
            name=spec.name,
            description=registry.render(spec.description),
            annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
        )

    for chunk_doc, chunks in _policies_by_doc(Path(settings.store_dir)).items():
        _register_policy_resource(server, chunk_doc, chunks)
    return server


def _policies_by_doc(store_dir: Path) -> dict[str, list]:
    """Group policy sections by document, one MCP resource per document."""
    grouped: dict[str, list] = {}
    for chunk in load_policies(store_dir / "policies"):
        grouped.setdefault(chunk.doc_id.lower(), []).append(chunk)
    return grouped


def _register_policy_resource(server: MCPServer, doc: str, chunks: list) -> None:
    """Publish one policy document as quilora://policies/{doc}."""
    title = chunks[0].doc_title
    body = f"# {title}\n\n" + "\n\n".join(
        f"## {c.section_no}. {c.section_title}\n{c.content}" for c in chunks)

    def read() -> str:
        return body

    read.__name__ = f"policy_{doc}"
    server.resource(f"quilora://policies/{doc}", name=title, mime_type="text/markdown",
                    description=f"{title} (full text)")(read)


def main() -> None:
    """Run the MCP server over stdio (default) or Streamable HTTP."""
    parser = argparse.ArgumentParser(description="Store MCP server (read-only tools and policies)")
    parser.add_argument("--http", action="store_true", help="serve Streamable HTTP")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    settings = load_settings()
    server = create_server(settings, Database(settings.database_url))
    if args.http:
        server.run("streamable-http", host=args.host, port=args.port)
    else:
        server.run()


if __name__ == "__main__":
    main()
