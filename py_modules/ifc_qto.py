# -*- coding: utf-8 -*-
"""
ifc_qto.py

Annotate GH wrapper objects with IFC quantity measurements.

This module sits BEFORE the builder in the pipeline.
It marks objects with quantity data (length, area, count, weight) that
will be exported as IfcElementQuantity in the IFC file.

Distinct from ifc_override.py (which handles IfcPropertySet).

WORKFLOW
--------
GH wrapper ([geo, name])
→ ifc_qto (annotate quantity data)
→ ([geo, name, override_data])  # override_data["qto_overrides"] is set
→ Builder (writes to payload.props.qto_overrides)
→ Exporter (creates IfcElementQuantity on element)

KEY FORMAT
----------
Keys use a type-prefix convention: "{prefix}:{name}"

Prefix → IFC quantity type:
  L: → IfcQuantityLength  (e.g. "L:N01", "L:N01:TotalLength")
  A: → IfcQuantityArea    (e.g. "A:PNL_1200")
  C: → IfcQuantityCount   (e.g. "C:M8")
  W: → IfcQuantityWeight  (e.g. "W:Frame")

Only the FIRST ":" is parsed as the prefix separator.
Everything after the first ":" is used as-is as the IFC quantity Name.
  "L:N01"             → IfcQuantityLength, Name="N01"
  "L:N01:TotalLength" → IfcQuantityLength, Name="N01:TotalLength"

USAGE
-----
Single measurement:
    annotated_obj, log = annotate_qto(Obj, Key="L:N01", Value=2450.0)

Multiple measurements:
    annotated_obj, log = annotate_qto(
        Obj,
        Key=["L:N01", "C:M8"],
        Value=[2450.0, 4],
    )

Custom Qto set name:
    annotated_obj, log = annotate_qto(
        Obj,
        Key=["L:N01"],
        Value=[2450.0],
        QtoName="Qto_AlumExtrusion",
    )

Per-branch (tree access):
    # Key and Value as DataTree with per-branch entries
    annotated_obj, log = annotate_qto(Obj, Key=KeyTree, Value=ValueTree)
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from utils.gh_utils import (
    to_branch_dict_any,
    unwrap_gh,
    wrap_gh,
    is_datatree_like,
    new_datatree,
    add_to_datatree,
)

BUILD_STAMP = "QTO_BUILD__2026-02-24__v1"

DEFAULT_QTO_NAME = "Qto_CWPart"


def _is_wrapper(x: Any) -> bool:
    """Check if x is a valid GH wrapper: [geo, name] or [geo, name, override]."""
    return isinstance(x, (list, tuple)) and len(x) >= 2


def _parse_kv_lists(
    k_items: List[Any],
    v_items: List[Any],
) -> Tuple[bool, Dict[str, Any], str]:
    """Zip parallel Key/Value lists into a {k: v} dict.

    Returns (ok, kv_dict, error_msg).
    Fails if lists differ in length.
    Empty key strings are silently skipped.
    """
    if len(k_items) != len(v_items):
        return False, {}, f"Key/Value length mismatch: {len(k_items)} vs {len(v_items)}"
    out: Dict[str, Any] = {}
    for k, v in zip(k_items, v_items):
        kk = str(unwrap_gh(k) or "").strip()
        if not kk:
            continue
        out[kk] = unwrap_gh(v)
    return True, out, ""


def _merge_qto(
    existing: Dict[str, Dict[str, Any]],
    qto_name: str,
    new_kv: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """Merge new_kv into existing qto_overrides under qto_name.

    Does not mutate existing; returns a new dict.
    """
    out: Dict[str, Dict[str, Any]] = {
        k: dict(v) for k, v in existing.items() if isinstance(v, dict)
    }
    if qto_name not in out:
        out[qto_name] = {}
    for k, v in new_kv.items():
        if isinstance(k, str) and k.strip():
            out[qto_name][k.strip()] = v
    return out


def annotate_qto(
    Obj: Any,
    Key: Any,
    Value: Any,
    QtoName: Any = None,
) -> Tuple[Any, str]:
    """Annotate GH wrapper objects with quantity measurements.

    Parameters
    ----------
    Obj : Tree/List/Item
        GH wrapper objects: [geo, name] or [geo, name, override_data]

    Key : str | List[str] | Tree
        Quantity keys with type prefix. Format: "{prefix}:{name}"
        - "L:N01"          → IfcQuantityLength, Name="N01"
        - "C:M8"           → IfcQuantityCount,  Name="M8"
        - "A:PNL_1200"     → IfcQuantityArea,   Name="PNL_1200"
        - "W:Frame"        → IfcQuantityWeight, Name="Frame"

    Value : number | List[number] | Tree
        Quantity values, parallel to Key.
        Must match Key count per branch.

    QtoName : str, optional
        IFC IfcElementQuantity set name (default "Qto_CWPart").

    Returns
    -------
    (annotated_output, log_string)
        annotated_output: same tree/list structure as Obj.
        log_string: diagnostic message.

    Behavior
    --------
    - Transforms [geo, name] → [geo, name, {"qto_overrides": {QtoName: {...}}}]
    - Transforms [geo, name, override] → merges qto_overrides into existing override
    - If called multiple times, merges (union of keys, last value wins per key)
    - Preserves tree structure (Strategy S1)
    - Common (item access): Key/Value in one branch → broadcast to all Obj branches
    - Per-branch (tree access): Key/Value DataTree → matched by branch path
    """
    print(f"[{BUILD_STAMP}]")

    if Obj is None:
        return Obj, "ifc_qto: Obj is None."

    qto_name = str(unwrap_gh(QtoName) or "").strip() or DEFAULT_QTO_NAME

    # ── Parse Key/Value inputs ──────────────────────────────────────────
    key_bd, _ = to_branch_dict_any(Key)
    val_bd, _ = to_branch_dict_any(Value)

    k_paths = [p for p, it in key_bd.items() if it]
    v_paths = [p for p, it in val_bd.items() if it]

    if not k_paths and not v_paths:
        return Obj, "ifc_qto: Key/Value empty. No quantities added."

    # Detect common (single-branch) KV: broadcast to all Obj branches
    has_common = False
    common_kv: Dict[str, Any] = {}

    if len(k_paths) == 1 and len(v_paths) == 1:
        ok, common_kv, err = _parse_kv_lists(
            key_bd[k_paths[0]], val_bd[v_paths[0]]
        )
        if not ok:
            return Obj, f"ifc_qto: {err}"
        has_common = True

    # ── Parse Obj input ─────────────────────────────────────────────────
    want_tree = is_datatree_like(Obj)
    out_tree = new_datatree() if want_tree else None
    out_list: List[Any] = []

    obj_bd, obj_paths = to_branch_dict_any(Obj)

    annotated_count = 0
    branch_count = 0
    logs: List[str] = []

    for path in obj_paths:
        branch = obj_bd.get(path, [])
        if not branch:
            continue

        branch_count += 1

        # Resolve KV for this branch
        if path in key_bd or path in val_bd:
            # Per-branch KV (tree access)
            ok, branch_kv, err = _parse_kv_lists(
                key_bd.get(path, []), val_bd.get(path, [])
            )
            if not ok:
                logs.append(f"{path}: KV error: {err} — passed through unchanged")
                if out_tree is not None:
                    for item in branch:
                        add_to_datatree(out_tree, path, item)
                else:
                    out_list.extend(branch)
                continue
        elif has_common:
            branch_kv = dict(common_kv)
        else:
            branch_kv = {}

        if not branch_kv:
            # No KV for this branch → pass through unchanged
            if out_tree is not None:
                for item in branch:
                    add_to_datatree(out_tree, path, item)
            else:
                out_list.extend(branch)
            logs.append(f"{path}: no qto data (passed through)")
            continue

        # Annotate each item in the branch with the same KV
        new_items: List[Any] = []
        for item in branch:
            wrapper = unwrap_gh(item)

            if not _is_wrapper(wrapper):
                # Not a valid wrapper → pass through unchanged
                new_items.append(item)
                continue

            geo = wrapper[0]
            name = wrapper[1]

            # Get or create override_data (3rd slot)
            if len(wrapper) >= 3 and isinstance(wrapper[2], dict):
                override = dict(wrapper[2])
            else:
                override = {}

            # Merge into qto_overrides
            existing_qto = override.get("qto_overrides", {})
            if not isinstance(existing_qto, dict):
                existing_qto = {}
            merged_qto = _merge_qto(existing_qto, qto_name, branch_kv)
            override["qto_overrides"] = merged_qto

            new_wrapper = [geo, name, override]
            new_items.append(wrap_gh(new_wrapper))
            annotated_count += 1

        # Add to output
        if out_tree is not None:
            for item in new_items:
                add_to_datatree(out_tree, path, item)
        else:
            out_list.extend(new_items)

        logs.append(
            f"{path}: added qto keys={list(branch_kv.keys())} "
            f"to {len(new_items)} items (QtoName={qto_name!r})"
        )

    out_any = out_tree if out_tree is not None else out_list

    msg = (
        f"ifc_qto [{BUILD_STAMP}]: annotated {annotated_count} items "
        f"across {branch_count} branches. QtoName={qto_name!r}. "
        f"qto_overrides written to payload.props.qto_overrides by builder."
    )
    return out_any, msg + "\n" + "\n".join(logs)
