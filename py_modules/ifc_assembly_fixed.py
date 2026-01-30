# ifc_assembly.py
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

from typing import Any, Dict, List, Optional, Tuple, cast

from ifc_types import Payload
from utils.gh_utils import unwrap_gh, wrap_gh, is_datatree_like


def is_payload(x: Any) -> bool:
    """
    Runtime shape check for ifc_types.Payload (TypedDict cannot be isinstance).
    """
    if not isinstance(x, dict):
        return False

    if not isinstance(x.get("unit_id", None), str):
        return False
    if not isinstance(x.get("name", None), str):
        return False
    if "geo" not in x:
        return False

    props = x.get("props", None)
    if props is not None and not isinstance(props, dict):
        return False

    sch = x.get("schema", None)
    if sch is not None and not isinstance(sch, int):
        return False

    cat = x.get("category", None)
    if cat is not None and not isinstance(cat, str):
        return False

    return True


def _ensure_props(p: Dict[str, Any]) -> Dict[str, Any]:
    props = p.get("props")
    if not isinstance(props, dict):
        props = {}
        p["props"] = props
    return props


def _build_key(name: str, key_suffix: Optional[str]) -> str:
    n = str(name or "").strip()
    s = str(key_suffix or "").strip() if key_suffix else ""
    if not s:
        return n
    return f"{n}|{s}"


def _same_key(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return str(a.get("key", "")) == str(b.get("key", ""))


def _stable_wrap_outer(path: list, node: dict) -> list:
    """
    Make `node` the OUTERMOST level, stably.
    - If node already exists anywhere in path -> remove it (dedupe)
    - Insert node at the front
    - Collapse consecutive duplicates (trim, trim)
    """
    if not isinstance(path, list):
        path = []

    cleaned = []
    for lvl in path:
        if isinstance(lvl, dict) and _same_key(lvl, node):
            continue
        cleaned.append(lvl)

    out = [node] + cleaned

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


def _annotate_payload(payload: Payload, sub_name: str, key_suffix: Optional[str], role: Optional[str]) -> Payload:
    p: Dict[str, Any] = dict(payload)  # defensive copy
    _ensure_props(p)

    props = cast(Dict[str, Any], p["props"])
    path = props.get("assembly_path")
    if not isinstance(path, list):
        path = []
        props["assembly_path"] = path

    node: Dict[str, Any] = {
        "name": sub_name,
        "key": _build_key(sub_name, key_suffix) or sub_name,
    }
    if role:
        node["role"] = role

    props["assembly_path"] = _stable_wrap_outer(path, node)
    return cast(Payload, p)


def walk(obj: Any, sub_name: str, key_suffix: Optional[str], role: Optional[str]) -> Any:
    """
    Walk MatData and annotate only valid Payload leaves.
    Preserves container shapes:
      - DataTree-like => List[List[...]]
      - list => list
      - tuple => tuple
      - scalar => scalar
    """
    if obj is None:
        return None

    if is_datatree_like(obj):
        out: List[List[Any]] = []
        try:
            bc = int(getattr(obj, "BranchCount"))
        except Exception:
            bc = 0

        for i in range(bc):
            br = obj.Branch(i)
            out.append([walk(it, sub_name, key_suffix, role) for it in br])
        return out

    if isinstance(obj, list):
        return [walk(it, sub_name, key_suffix, role) for it in obj]
    if isinstance(obj, tuple):
        return tuple(walk(it, sub_name, key_suffix, role) for it in obj)

    leaf = unwrap_gh(obj)

    if is_payload(leaf):
        pl = cast(Payload, leaf)
        annotated = _annotate_payload(pl, sub_name, key_suffix, role)
        return wrap_gh(annotated)

    return obj


def annotate_subassembly(MatData: Any, Name: Any, KeySuffix: Any = None, Role: Any = None) -> Tuple[Any, str]:
    sub_name = str(Name).strip() if Name is not None else ""
    if not sub_name:
        return MatData, "assembly(auto): empty Name -> no changes."

    key_suffix = None
    if KeySuffix is not None:
        ks = str(KeySuffix).strip()
        key_suffix = ks if ks else None

    role = None
    if Role is not None:
        r = str(Role).strip()
        role = r if r else None

    new_matdata = walk(MatData, sub_name, key_suffix, role)
    return new_matdata, (
        "assembly(auto): applied. "
        "Rule: wrap outer (prepend) stably. Optional role is stored per assembly node. "
        "Runtime check: only annotates dicts matching ifc_types.Payload contract."
    )
