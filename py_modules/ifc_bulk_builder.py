# -*- coding: utf-8 -*-
"""
ifc_bulk_builder.py
Bulk builder (kind: Bulk)

Scope is determined by the Scope input:
  - "UNIT"     -> requires UnitId, output mirrors Obj tree shape
  - "NON_UNIT" -> UnitId not needed, output as flat list

Overrides are NOT handled here. Use ifc_override.py upstream to inject
override data into the 3rd slot of the GH wrapper [geo, name, override_data].

GH leaf convention:
  Obj: leaf = [geo, raw_name] or [geo, raw_name, override_data]
  - raw_name = bulk_code (optionally "CODE_guid"; guid portion is stripped)

Inputs:
  Obj(Tree/List)  : GH wrapper objects
  Category(Tree)  : optional (empty -> default_category)
  Scope(Item)     : "UNIT" or "NON_UNIT"
  UnitId(Tree)    : required when Scope == "UNIT"
  SchemaVersion   : int

Outputs:
  MatData : DataTree or List (mirrors Obj shape when UNIT)
  Log     : str
"""

from __future__ import annotations
from typing import Any, Dict, List, Tuple

from ifc_types import AnyInput, Payload, PathStr
from ifc_class_map import resolve_ifc_class_hint

from utils.gh_utils import (
    to_branch_dict_any, get_branch, wrap_gh, unwrap_gh,
    is_datatree_like, new_datatree, add_to_datatree,
)
from utils.payload_utils import normalize_payload_inplace
from utils.override_utils import apply_overrides_to_props


def build_bulk_matdata(
    Obj: AnyInput,
    Category: AnyInput,
    Scope: Any = None,
    UnitId: AnyInput = None,
    SchemaVersion: int = 1,
    default_category: str = "Unspecified",
) -> Tuple[Any, str]:
    """
    Build MatData payloads for Bulk items.

    Scope is determined by the Scope input:
      - "UNIT"     -> UnitId is required, output as DataTree
      - "NON_UNIT" -> UnitId not needed, output as list
    """
    ObjD, ObjP = to_branch_dict_any(Obj)
    CatD, _ = to_branch_dict_any(Category)

    # Scope from explicit input
    scope_raw = str(unwrap_gh(Scope) or "").strip().upper()
    scope = scope_raw if scope_raw in ("UNIT", "NON_UNIT") else "NON_UNIT"
    is_unit = (scope == "UNIT")

    # UnitId parsing (only needed for UNIT scope)
    UidD: Dict[str, List[Any]] = {}
    if is_unit:
        if UnitId is None:
            raise Exception("bulk_builder: Scope=UNIT but UnitId is not provided.")
        UidD, _ = to_branch_dict_any(UnitId)

    # Output mirrors Obj shape (DataTree in -> DataTree out)
    want_tree = is_datatree_like(Obj)
    out_tree = new_datatree() if want_tree else None
    out_list: List[List[Any]] = []
    logs: List[str] = []

    all_paths: List[PathStr] = list(ObjP)

    for p in all_paths:
        objs = get_branch(ObjD, p, allow_fallback=False)

        c_branch = get_branch(CatD, p, allow_fallback=True)
        cat_value = default_category if not c_branch else str(unwrap_gh(c_branch[0]) or "").strip()
        if not cat_value:
            cat_value = default_category

        # Resolve unit_id
        unit_id = "__NON_UNIT__"
        if is_unit:
            u_branch = get_branch(UidD, p, allow_fallback=True)
            if not u_branch:
                raise Exception(f"[{p}] bulk scope=UNIT requires UnitId (missing branch and no fallback).")
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

                # optional bulk metrics (fill via override if needed)
                "quantity": None,
                "area_m2": None,
                "length_m": None,
                "install_location": None,

                "color_code": None,

                # redundant copy (compat)
                "unit_id": unit_id,
            }

            # Override from 3rd slot (injected by ifc_override.py upstream)
            if len(pair) >= 3:
                apply_overrides_to_props(props, pair[2])

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
