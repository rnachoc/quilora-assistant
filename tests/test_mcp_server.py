"""Phase 8: the MCP server exposes the same tools, schemas and rules, in-process.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

import asyncio
import json

from mcp import Client

from quilora.mcp_server import create_server


def _run(coro):
    return asyncio.run(coro)


def test_lists_only_read_only_tools_with_full_schemas(database, settings):
    server = create_server(settings, database)

    async def go():
        async with Client(server) as client:
            return (await client.list_tools()).tools

    tools = {t.name: t for t in _run(go())}
    assert set(tools) == {"search_products", "get_product", "check_stock",
                          "get_size_recommendation", "search_policies", "get_order_status"}
    schema = tools["search_products"].input_schema
    assert schema["properties"]["max_price_eur"]["description"] == "Maximum price in EUR."
    assert tools["get_order_status"].annotations.read_only_hint is True


def test_call_tool_and_security_rules_hold_over_mcp(database, settings):
    server = create_server(settings, database)

    async def go():
        async with Client(server) as client:
            ok = await client.call_tool("check_stock", {"product_id": "QL-TRS-001",
                                                        "color": "black", "size": "M"})
            denied = await client.call_tool("get_order_status",
                                            {"order_id": 1043, "email": "x@example.com"})
            return ok, denied

    ok, denied = _run(go())
    assert not ok.is_error
    assert json.loads(ok.content[0].text)["variants"][0]["availability"] == "in_stock"
    assert denied.is_error
    assert "ORDER_NOT_FOUND_OR_EMAIL_MISMATCH" in denied.content[0].text


def test_policies_are_published_as_resources(database, settings):
    server = create_server(settings, database)

    async def go():
        async with Client(server) as client:
            listed = (await client.list_resources()).resources
            read = await client.read_resource("quilora://policies/ret")
            return listed, read

    listed, read = _run(go())
    assert any(str(r.uri) == "quilora://policies/ret" for r in listed)
    assert "Return window" in read.contents[0].text
