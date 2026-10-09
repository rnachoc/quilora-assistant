"""The store's tools. One registry is shared by the agent loop and the MCP server.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

from quilora.tools.base import ToolRegistry, ToolSpec
from quilora.tools.catalog import CHECK_STOCK, GET_PRODUCT, GET_SIZE_RECOMMENDATION, SEARCH_PRODUCTS
from quilora.tools.handoff import HANDOFF_TO_HUMAN
from quilora.tools.orders import GET_ORDER_STATUS
from quilora.tools.policies import SEARCH_POLICIES
from quilora.tools.returns import CREATE_RETURN_REQUEST

ALL_TOOLS: list[ToolSpec] = [
    SEARCH_PRODUCTS,
    GET_PRODUCT,
    CHECK_STOCK,
    GET_SIZE_RECOMMENDATION,
    SEARCH_POLICIES,
    GET_ORDER_STATUS,
    CREATE_RETURN_REQUEST,
    HANDOFF_TO_HUMAN,
]


def build_registry(read_only: bool = False) -> ToolRegistry:
    """Create the registry with all tools, or only those that do not change data."""
    specs = [s for s in ALL_TOOLS if not (read_only and s.mutates)]
    return ToolRegistry(specs)
