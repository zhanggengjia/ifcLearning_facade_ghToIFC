# ifc_assembly.py
# -*- coding: utf-8 -*-
"""
ifc_assembly.py

Goals (your finalized direction)
-------------------------------
1) Preserve Unit branch boundaries (Strategy S1):
   - If input MatData is a GH DataTree, output MUST also be a GH DataTree
   - Paths are preserved verbatim (e.g. {0}, {1}, {2} stay as-is)
2) Assembly nesting is driven by payload.props['assembly_path'].
   - This component PREPENDS a new outer assembly node to every payload leaf
   - It is stable (dedupe same key) to avoid accidental extra depth
3) Assembly override (parallel to element override):
   - Optional Key/Value inputs inject KV onto the *assembly node* via a synthetic
     "AssemblyMeta payload" (no geometry).
   - The meta payload participates in further assemblies, so multi-level assembly works.

AssemblyMeta payload contract
-----------------------------
category == "__ASSEMBLY_META__"
geo == None
props['pset_overrides'] = { "Pset_Assembly": {K: V, ...}, ... }
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, cast

from ifc_types import Payload
from utils.gh_utils import (
    unwrap_gh,
    wrap_gh,
    is_datatree_like,
    to_branch_dict_any,
    new_datatree,
    add_to_datatree,
)
from utils.payload_utils import ensure_props


ASSEMBLY_META_CATEGORY = "__ASSEMBLY_META__"
DEFAULT_ASSEMBLY_PSET = "Pset_Assembly"


def is_payload(x: Any) -> bool:
    """Runtime shape check for ifc_types.Payload (TypedDict cannot be isinstance)."""
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


def _build_key(name: str, key_suffix: Optional[str]) -> str:
    n = str(name or "").strip()
    s = str(key_suffix or "").strip() if key_suffix else ""
    if not s:
        return n
    return f"{n}|{s}"


def _same_key(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return str(a.get("key", "")) == str(b.get("key", ""))


def _stable_wrap_outer(path: list, node: dict) -> list:
    """Make `node` the OUTERMOST level, stably."""
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
    props = ensure_props(cast(Payload, p))

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


# ---------------------------------------------------------------------
# Assembly override (Key/Value mapping, tree-driven)
# ---------------------------------------------------------------------

def _kv_from_lists(k_items: List[Any], v_items: List[Any], *, where: str) -> Tuple[bool, Dict[str, Any], str]:
    if len(k_items) != len(v_items):
        return False, {}, f"[{where}] Key/Value length mismatch: {len(k_items)} vs {len(v_items)}"
    out: Dict[str, Any] = {}
    for i, (k, v) in enumerate(zip(k_items, v_items)):
        kk = str(unwrap_gh(k) or "").strip()
        if not kk:
            continue
        out[kk] = unwrap_gh(v)
    return True, out, ""


def _detect_common_override(key_bd: Dict[str, List[Any]], val_bd: Dict[str, List[Any]]) -> Tuple[bool, Dict[str, Any], str]:
    # common override means each has exactly one non-empty branch (usually "{0}")
    k_paths = [p for p, it in key_bd.items() if it]
    v_paths = [p for p, it in val_bd.items() if it]
    if len(k_paths) == 1 and len(v_paths) == 1:
        ok, kv, err = _kv_from_lists(key_bd[k_paths[0]], val_bd[v_paths[0]], where="COMMON")
        if not ok:
            return False, {}, err
        return True, kv, ""
    return False, {}, ""


def _pick_kv_for_unit_branch(
    *,
    unit_path: str,
    key_bd: Dict[str, List[Any]],
    val_bd: Dict[str, List[Any]],
    has_common: bool,
    common_kv: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any], str]:
    # per-branch shared override: use exact unit_path
    if unit_path in key_bd or unit_path in val_bd:
        k_items = key_bd.get(unit_path, [])
        v_items = val_bd.get(unit_path, [])
        ok, kv, err = _kv_from_lists(k_items, v_items, where=unit_path)
        return ok, kv, err

    # fallback: common
    if has_common:
        return True, dict(common_kv), ""

    # no override for this unit branch
    return True, {}, ""


def _validate_unitid_against_paths(obj_paths: List[str], uid_bd: Dict[str, List[Any]]) -> Tuple[bool, str]:
    if not uid_bd:
        return True, ""
    # strict: if user supplied UnitId tree, each obj_path must exist and have 1 non-empty item
    for p in obj_paths:
        items = uid_bd.get(p, [])
        if not items:
            return False, f"UnitId validation failed: missing branch {p}"
        s = str(unwrap_gh(items[0]) or "").strip()
        if not s:
            return False, f"UnitId validation failed: empty UnitId at branch {p}"
    return True, ""


def _make_assembly_meta_payload(
    *,
    unit_id: str,
    scope: str,
    schema: int,
    sub_name: str,
    category: str,
    kv: Dict[str, Any],
) -> Payload:
    props: Dict[str, Any] = {
        "scope": scope,
        "kind": "AssemblyMeta",
        "unit_id": unit_id,
    }
    if kv:
        props["pset_overrides"] = {DEFAULT_ASSEMBLY_PSET: dict(kv)}

    # geo=None on purpose (exporter will not create elements for this category)
    return cast(Payload, {
        "schema": int(schema),
        "unit_id": unit_id,
        "geo": None,
        "name": sub_name,
        "category": category,
        "props": props,
    })


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def annotate_subassembly(
    MatData: Any,
    Name: Any,
    KeySuffix: Any = None,
    Role: Any = None,
    Key: Any = None,
    Value: Any = None,
    UnitId: Any = None,
) -> Tuple[Any, str]:
    sub_name = str(Name).strip() if Name is not None else ""
    if not sub_name:
        return MatData, "assembly: empty Name -> no changes."

    key_suffix = None
    if KeySuffix is not None:
        ks = str(KeySuffix).strip()
        key_suffix = ks if ks else None

    role = None
    if Role is not None:
        r = str(Role).strip()
        role = r if r else None

    # Normalize overrides (tree-driven)
    key_bd, _ = to_branch_dict_any(Key)
    val_bd, _ = to_branch_dict_any(Value)
    uid_bd, _ = to_branch_dict_any(UnitId)

    has_common, common_kv, common_err = _detect_common_override(key_bd, val_bd)
    if common_err:
        return MatData, f"assembly: invalid common override: {common_err}"

    # Walk MatData: preserve GH DataTree if present
    want_tree = is_datatree_like(MatData)
    out_tree = new_datatree() if want_tree else None

    md_bd, md_paths = to_branch_dict_any(MatData)
    ok_uid, uid_err = _validate_unitid_against_paths(md_paths, uid_bd)
    if not ok_uid:
        return MatData, f"assembly: {uid_err}"

    logs: List[str] = []
    out_list: List[Any] = []  # for non-tree mode

    for p in md_paths:
        branch = md_bd.get(p, [])
        if not branch:
            # keep empty branches as empty (tree mode)
            continue

        # Determine unit_id + scope from first valid payload in this branch (Strategy S1)
        unit_id = ""
        scope = "UNIT"
        schema = 1
        for it in branch:
            leaf = unwrap_gh(it)
            if is_payload(leaf):
                pl = cast(Payload, leaf)
                unit_id = str(pl.get("unit_id", "")).strip()
                schema = int(pl.get("schema", 1) or 1)
                pr = ensure_props(pl)
                scope = str(pr.get("scope", "UNIT") or "UNIT").strip().upper()
                scope = "NON_UNIT" if scope == "NON_UNIT" else "UNIT"
                break

        # Annotate every leaf payload in this branch (including any existing AssemblyMeta payloads)
        new_branch_items: List[Any] = []
        touched = 0
        for it in branch:
            leaf0 = unwrap_gh(it)
            if is_payload(leaf0):
                annotated = _annotate_payload(cast(Payload, leaf0), sub_name, key_suffix, role)
                new_branch_items.append(wrap_gh(annotated))
                touched += 1
            else:
                new_branch_items.append(it)

        # Create one AssemblyMeta payload per unit branch (if Key/Value provides anything)
        ok_kv, kv, err = _pick_kv_for_unit_branch(
            unit_path=p,
            key_bd=key_bd,
            val_bd=val_bd,
            has_common=has_common,
            common_kv=common_kv,
        )
        if not ok_kv:
            return MatData, f"assembly: {err}"

        # Only add meta if user actually provided override data (either per-branch or common, and kv non-empty)
        if kv and unit_id:
            meta = _make_assembly_meta_payload(
                unit_id=unit_id,
                scope=scope,
                schema=schema,
                sub_name=sub_name,
                category=ASSEMBLY_META_CATEGORY,
                kv=kv,
            )
            # meta must also receive the same wrapping rule so it nests correctly in later assemblies
            meta2 = _annotate_payload(meta, sub_name, key_suffix, role)
            new_branch_items.append(wrap_gh(meta2))

        # Emit
        if out_tree is not None:
            for it in new_branch_items:
                add_to_datatree(out_tree, p, it)
        else:
            out_list.append(new_branch_items)

        logs.append(f"{p}: annotated={touched} added_meta={'Y' if (kv and unit_id) else 'N'}")

    out_any = out_tree if out_tree is not None else out_list
    msg = (
        "assembly: applied. "
        "Rule: stable outer wrap (prepend) on props['assembly_path']. "
        "Unit branches preserved (Strategy S1). "
        "Assembly override: emits AssemblyMeta payloads (category='__ASSEMBLY_META__') with props['pset_overrides']."
    )
    return out_any, msg + "\n" + "\n".join(logs)
