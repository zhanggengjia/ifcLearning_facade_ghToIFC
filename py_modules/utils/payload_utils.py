# py_modules/utils/payload_utils.py
# -*- coding: utf-8 -*-
"""
utils/payload_utils.py

Runtime payload validation + normalization.

We use a shape-check instead of isinstance checks because Payload is a TypedDict.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, cast

from ifc_types import Payload


def is_payload(x: Any) -> bool:
    if not isinstance(x, dict):
        return False
    # required keys
    if "name" not in x or "category" not in x:
        return False
    # props should be a dict if present
    if "props" in x and x["props"] is not None and not isinstance(x["props"], dict):
        return False
    return True


def ensure_props(p: Payload) -> Dict[str, Any]:
    props = p.get("props")
    if props is None or not isinstance(props, dict):
        props = {}
        p["props"] = props
    return cast(Dict[str, Any], props)


def normalize_payload_inplace(
    p: Payload,
    *,
    default_schema: int = 1,
    default_category: str = "",
) -> Payload:
    # schema
    if "schema" not in p or p.get("schema") is None:
        p["schema"] = default_schema
    # category
    if "category" not in p or p.get("category") is None:
        p["category"] = default_category
    # props
    ensure_props(p)
    return p


def unwrap_payload(x: Any) -> Optional[Payload]:
    """
    Accept a raw object; if it's a payload dict return it (as Payload), else None.
    No GH unwrap here (call gh_utils.unwrap_gh first).
    """
    if is_payload(x):
        return cast(Payload, x)
    return None
