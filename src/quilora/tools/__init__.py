"""The store's tools. One registry is shared by the agent loop and the MCP server."""

from __future__ import annotations

from quilora.tools.base import ToolRegistry, ToolSpec
from quilora.tools.catalog import CHECK_STOCK, GET_PRODUCT, GET_SIZE_RECOMMENDATION, SEARCH_PRODUCTS
from quilora.tools.orders import GET_ORDER_STATUS

ALL_TOOLS: list[ToolSpec] = [
    SEARCH_PRODUCTS,
    GET_PRODUCT,
    CHECK_STOCK,
    GET_SIZE_RECOMMENDATION,
    GET_ORDER_STATUS,
]


def build_registry(read_only: bool = False) -> ToolRegistry:
    specs = [s for s in ALL_TOOLS if not (read_only and s.mutates)]
    return ToolRegistry(specs)
