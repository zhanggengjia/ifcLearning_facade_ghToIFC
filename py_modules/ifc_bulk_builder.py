# -*- coding: utf-8 -*-
"""
ifc_bulk_builder_fixed.py
Bulk builder (scope: UNIT/NON_UNIT, kind: Bulk)

GH leaf convention:
  Obj(Tree): leaf = [geo, raw_name]
  - raw_name = bulk_code (optionally "CODE_guid"; guid will be ignored here)

Inputs:
  Obj(Tree)
  Category(Tree)  : optional (empty -> default_category)
  Scope(Item)     : "UNIT" or "NON_UNIT" (empty -> default_scope)
  UnitId(Tree)    : required only if scope == UNIT
  SchemaVersion   : int

Outputs:
  MatData : List[List[GH_ObjectWrapper(payload)]]
  Log     : str
"""

from __future__ import annotations
from typing import Any, Dict, List, Tuple

from ifc_types import AnyInput, Payload, PathStr
from ifc_class_map import resolve_ifc_class_hint

from utils.gh_utils import to_branch_dict_any, get_branch, wrap_gh, unwrap_gh, is_datatree_like, new_datatree, add_to_datatree
from utils.payload_utils import normalize_payload_inplace
from utils.override_utils import apply_overrides_to_props


def build_bulk_matdata(
    Obj: AnyInput,
    Category: AnyInput,
    Scope: Any,
    UnitId: AnyInput,
    Overrides: Any = None,
    SchemaVersion: int = 1,
    default_category: str = "Unspecified",
    default_scope: str = "NON_UNIT",
) -> Tuple[List[List[Any]], str]:
    ObjD, ObjP = to_branch_dict_any(Obj)
    CatD, CatP = to_branch_dict_any(Category)
    UidD, UidP = to_branch_dict_any(UnitId)

    scope_raw = str(unwrap_gh(Scope) or "").strip().upper()
    scope = scope_raw if scope_raw in ("UNIT", "NON_UNIT") else str(default_scope).strip().upper()
    if scope not in ("UNIT", "NON_UNIT"):
        scope = "NON_UNIT"

    all_paths: List[PathStr] = sorted(set(ObjP) | set(CatP) | set(UidP))
    out: List[List[Any]] = []
    logs: List[str] = []

    for p in all_paths:
        objs = get_branch(ObjD, p, allow_fallback=False)

        c_branch = get_branch(CatD, p, allow_fallback=True)
        cat_value = default_category if not c_branch else str(unwrap_gh(c_branch[0]) or "").strip()
        if not cat_value:
            cat_value = default_category

        unit_id = "__NON_UNIT__"
        if scope == "UNIT":
            u_branch = get_branch(UidD, p, allow_fallback=True)
            if not u_branch:
                raise Exception(f"[{p}] bulk scope=UNIT requires UnitId (missing branch and no fallback {{0}}).")
            unit_id = str(unwrap_gh(u_branch[0]) or "").strip()
            if not unit_id:
                raise Exception(f"[{p}] bulk scope=UNIT: UnitId is empty after unwrap/strip.")

        ifc_class_hint = resolve_ifc_class_hint(cat_value)

        branch_items: List[Any] = []
        payload_count = 0
        bad_leaf = 0

        for obj_item in objs:
            pair = unwrap_gh(obj_item)
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                bad_leaf += 1
                continue

            geo = pair[0]
            raw_name = str(unwrap_gh(pair[1]) or "").strip()
            if not raw_name:
                bad_leaf += 1
                continue

            # Legacy compatible: "CODE_guid" -> CODE
            bulk_code = raw_name.rsplit("_", 1)[0].strip() if "_" in raw_name else raw_name
            if not bulk_code:
                bad_leaf += 1
                continue

            props: Dict[str, Any] = {
                "scope": scope,
                "kind": "Bulk",
                "element_code": bulk_code,
                "ifc_class_hint": ifc_class_hint,

                # bulk identity
                "bulk_code": bulk_code,

                # exporter assigns stable guid later
                "source_guid": None,

                # optional bulk metrics (fill later if you want)
                "quantity": None,
                "area_m2": None,
                "length_m": None,
                "install_location": None,

                "color_code": None,

                # redundant copy (compat)
                "unit_id": unit_id,
            }


            # User-defined Pset overrides (from GH)
            apply_overrides_to_props(props, Overrides, unit_id=unit_id)

            payload: Payload = {
                "schema": int(SchemaVersion),
                "unit_id": unit_id,
                "geo": geo,
                "name": bulk_code,
                "category": cat_value,
                "props": props,
            }

            normalize_payload_inplace(payload, default_schema=int(SchemaVersion), default_category=cat_value)

            branch_items.append(wrap_gh(payload))
            payload_count += 1

        if out_tree is not None:
            for it in branch_items:
                add_to_datatree(out_tree, p, it)
        else:
            out_list.append(branch_items)
        logs.append(
            f"{p} -> Bulk scope={scope} unit={unit_id}: payloads={payload_count}"
            + (f" | bad_leaf={bad_leaf}" if bad_leaf else "")
            + f" | Cat={cat_value}"
        )

    return (out_tree if out_tree is not None else out_list), "\n".join(logs)
