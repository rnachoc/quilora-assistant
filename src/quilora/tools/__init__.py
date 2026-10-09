"""The store's tools. One registry is shared by the agent loop and the MCP server.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

from quilora.paths import DATA_DIR
from quilora.store.profile import StoreProfile, load_profile
from quilora.tools.base import ToolRegistry, ToolSpec
from quilora.tools.catalog import CHECK_STOCK, GET_PRODUCT, GET_SIZE_RECOMMENDATION, SEARCH_PRODUCTS
from quilora.tools.handoff import HANDOFF_TO_HUMAN
from quilora.tools.orders import GET_ORDER_STATUS
from quilora.tools.policies import SEARCH_POLICIES
from quilora.tools.returns import CREATE_RETURN_REQUEST
from quilora.tools.store_info import ESTIMATE_DELIVERY, GET_ACTIVE_PROMOTIONS

ALL_TOOLS: list[ToolSpec] = [
    SEARCH_PRODUCTS,
    GET_PRODUCT,
    CHECK_STOCK,
    GET_SIZE_RECOMMENDATION,
    SEARCH_POLICIES,
    ESTIMATE_DELIVERY,
    GET_ACTIVE_PROMOTIONS,
    GET_ORDER_STATUS,
    CREATE_RETURN_REQUEST,
    HANDOFF_TO_HUMAN,
]

LANGUAGE_NAMES = {"en": "English", "es": "Spanish", "fr": "French", "it": "Italian",
                  "pt": "Portuguese", "de": "German", "nl": "Dutch", "sv": "Swedish"}


def build_registry(profile: StoreProfile | None = None, read_only: bool = False) -> ToolRegistry:
    """Create the registry for a store (default: the bundled demo shop).

    `read_only=True` keeps only tools that do not change data (used by the MCP server).
    """
    profile = profile or load_profile(str(DATA_DIR))
    specs = [s for s in ALL_TOOLS if not (read_only and s.mutates)]
    language = profile.catalog.language
    return ToolRegistry(specs, variables={
        "store_name": profile.name,
        "catalog_language": LANGUAGE_NAMES.get(language, language),
    })
