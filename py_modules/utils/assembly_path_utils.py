# py_modules/utils/assembly_path_utils.py
# -*- coding: utf-8 -*-
"""
utils/assembly_path_utils.py

Assembly path key building + stable wrapping policy.
"""

from __future__ import annotations

from typing import Optional

from ifc_types import Payload
from utils.payload_utils import ensure_props


def build_key(sub_name: str, suffix: str = "") -> str:
    suffix2 = f"|{suffix}" if suffix else ""
    return f"{sub_name}{suffix2}"


def same_key(k1: str, k2: str) -> bool:
    return k1 == k2


def stable_wrap_outer(
    p: Payload,
    sub_name: str,
    *,
    suffix: str = "",
    role: Optional[str] = None,
) -> Payload:
    """
    If payload already has assembly_path, we PREPEND the new key.
    To avoid "double wrap" when called repeatedly with the same (sub_name,suffix),
    we only prepend if the current head differs.

    Also supports stamping 'role' (string) into props if provided.
    """
    props = ensure_props(p)
    if role:
        props["role"] = role

    key = build_key(sub_name, suffix)
    ap = props.get("assembly_path")
    if not ap:
        props["assembly_path"] = [key]
        return p

    if isinstance(ap, list) and ap:
        head = ap[0]
        if not same_key(str(head), key):
            props["assembly_path"] = [key] + list(ap)
    else:
        props["assembly_path"] = [key]
    return p
