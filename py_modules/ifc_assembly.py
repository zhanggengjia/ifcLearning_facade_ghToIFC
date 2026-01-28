# -*- coding: utf-8 -*-
"""
ifc_assembly.py (AUTO WRAP + Payload runtime check, NO TypeGuard)

Rule:
- If payload already has props["assembly_path"] (non-empty) -> PREPEND (wrap outer)
- Else -> APPEND (create first level)

Typing:
- MatData is Any (GH reality)
- We import ifc_types.Payload as a contract type, but runtime checking uses key/shape checks.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple, Optional, cast
from ifc_types import Payload  # TypedDict contract

try:
    from Grasshopper.Kernel.Types import GH_ObjectWrapper  # type: ignore
except Exception:
    GH_ObjectWrapper = None  # type: ignore


# ------------------------------------------------------------------------------
# GH helpers
# ------------------------------------------------------------------------------

def _unwrap(x: Any) -> Any:
    if GH_ObjectWrapper is not None and isinstance(x, GH_ObjectWrapper):  # type: ignore
        return getattr(x, "Value", x)
    return x


def _wrap(x: Any) -> Any:
    if GH_ObjectWrapper is not None and isinstance(x, dict):  # type: ignore
        return GH_ObjectWrapper(x)
    return x


def _is_datatree_like(x: Any) -> bool:
    return hasattr(x, "BranchCount") and hasattr(x, "Branch")


# ------------------------------------------------------------------------------
# Payload runtime validation (no TypeGuard)
# ------------------------------------------------------------------------------

def is_payload(x: Any) -> bool:
    """
    Runtime shape check for ifc_types.Payload.

    We can't do isinstance(x, Payload) because Payload is TypedDict (typing-only).
    """
    if not isinstance(x, dict):
        return False

    # Must have these stable core keys (per ifc_types.Payload) :contentReference[oaicite:3]{index=3}
    if not isinstance(x.get("unit_id", None), str):
        return False
    if not isinstance(x.get("name", None), str):
        return False
    if "geo" not in x:
        return False

    # props can be missing (we'll normalize), but if present must be dict
    props = x.get("props", None)
    if props is not None and not isinstance(props, dict):
        return False

    # optional sanity checks (permissive)
    sch = x.get("schema", None)
    if sch is not None and not isinstance(sch, int):
        return False

    cat = x.get("category", None)
    if cat is not None and not isinstance(cat, str):
        return False

    return True


def _normalize_payload_inplace(p: Dict[str, Any]) -> None:
    if "props" not in p or p["props"] is None or not isinstance(p["props"], dict):
        p["props"] = {}
    if "schema" not in p or p["schema"] is None or not isinstance(p["schema"], int):
        p["schema"] = 1
    if "category" not in p or p["category"] is None or not isinstance(p["category"], str):
        p["category"] = "Unspecified"


# ------------------------------------------------------------------------------
# Assembly helpers
# ------------------------------------------------------------------------------

def _ensure_props(payload: Dict[str, Any]) -> Dict[str, Any]:
    props = payload.get("props")
    if not isinstance(props, dict):
        props = {}
        payload["props"] = props
    return props


def _build_key(sub_name: str, key_suffix: Optional[str]) -> str:
    base = sub_name.strip()
    if not base:
        return ""
    if key_suffix:
        suf = str(key_suffix).strip()
        if suf:
            return f"{base}|{suf}"
    return base


def _same_key(a: dict, b: dict) -> bool:
    return str(a.get("key", "")).strip() == str(b.get("key", "")).strip()

def _stable_wrap_outer(path: list, node: dict) -> list:
    """
    Make `node` the OUTERMOST level, stably.

    Rules:
    - If node already exists anywhere in path -> remove it (dedupe)
    - Insert node at the front
    - Collapse consecutive duplicates (trim, trim)
    """
    if not isinstance(path, list):
        path = []

    # 1) remove existing occurrences of same key
    cleaned = []
    for lvl in path:
        if isinstance(lvl, dict) and _same_key(lvl, node):
            continue
        cleaned.append(lvl)

    # 2) insert as outermost
    out = [node] + cleaned

    # 3) collapse consecutive duplicates by key
    collapsed = []
    for lvl in out:
        if not collapsed:
            collapsed.append(lvl)
            continue
        prev = collapsed[-1]
        if isinstance(prev, dict) and isinstance(lvl, dict) and _same_key(prev, lvl):
            continue
        collapsed.append(lvl)

    return collapsed



def _annotate_payload(payload: Payload, sub_name: str, key_suffix: Optional[str]) -> Payload:
    p: Dict[str, Any] = dict(payload)  # defensive copy
    _normalize_payload_inplace(p)

    props = _ensure_props(p)

    path = props.get("assembly_path")
    if not isinstance(path, list):
        path = []
        props["assembly_path"] = path

    node = {
        "name": sub_name,
        "key": _build_key(sub_name, key_suffix) or sub_name,
    }

    props["assembly_path"] = _stable_wrap_outer(path, node)
    return cast(Payload, p)


# ------------------------------------------------------------------------------
# Walk MatData and annotate only valid Payload leaves
# ------------------------------------------------------------------------------

def _walk(obj: Any, sub_name: str, key_suffix: Optional[str]) -> Any:
    if obj is None:
        return None

    if _is_datatree_like(obj):
        out: List[List[Any]] = []
        for i in range(int(obj.BranchCount)):
            br = obj.Branch(i)
            out.append([_walk(it, sub_name, key_suffix) for it in br])
        return out

    if isinstance(obj, list):
        return [_walk(it, sub_name, key_suffix) for it in obj]
    if isinstance(obj, tuple):
        return tuple(_walk(it, sub_name, key_suffix) for it in obj)

    leaf = _unwrap(obj)

    if is_payload(leaf):
        pl = cast(Payload, leaf)
        annotated = _annotate_payload(pl, sub_name, key_suffix)
        return _wrap(annotated)

    return obj


# ------------------------------------------------------------------------------
# GH entry
# ------------------------------------------------------------------------------

def annotate_subassembly(MatData: Any, Name: Any, KeySuffix: Any = None) -> Tuple[Any, str]:
    sub_name = str(Name).strip() if Name is not None else ""
    if not sub_name:
        return MatData, "assembly(auto): empty Name -> no changes."

    key_suffix = None
    if KeySuffix is not None:
        ks = str(KeySuffix).strip()
        key_suffix = ks if ks else None

    new_matdata = _walk(MatData, sub_name, key_suffix)

    return new_matdata, (
        "assembly(auto): applied. "
        "Rule: if existing assembly_path -> PREPEND (wrap outer), else -> APPEND (first level). "
        "Runtime check: only annotates dicts matching ifc_types.Payload contract."
    )
