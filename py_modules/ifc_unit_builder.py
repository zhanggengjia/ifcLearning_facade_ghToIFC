# -*- coding: utf-8 -*-
"""
ifc_builder.py  (patched to align with your existing utils/*)

This builder is intentionally conservative:
- Does NOT change your GH-facing inputs/outputs.
- Keeps your naming convention: raw_name = "[PartNo]_[GUID]" or "[PartNo]".
- Keeps the same reserved bags in props (dims/material/finish/color_code).
- Uses your existing utils (gh_utils + payload_utils) WITHOUT modifying them.

GH Inputs (typical):
  Obj(Tree)      : leaf = GH_ObjectWrapper([geo, raw_name])
  Category(Tree) : item/branch = str (or empty -> default_category)
  UnitId(Tree)   : item/branch = str (required)

Outputs:
  MatData : List[List[GH_ObjectWrapper(payload_dict)]]
  Log     : str
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ifc_class_map import resolve_ifc_class_hint

from ifc_types import AnyInput, Payload, PathStr

from utils.gh_utils import to_branch_dict_any, get_branch, wrap_gh, unwrap_gh, is_datatree_like, new_datatree, add_to_datatree
from utils.payload_utils import normalize_payload_inplace
from utils.override_utils import apply_overrides_to_props


def build_matdata(
    Obj: AnyInput,
    Category: AnyInput,
    UnitId: AnyInput,
    schema_version: int = 1,
    default_category: str = "Unspecified",
) -> Tuple[Any, str]:
    """
    Build MatData payloads for UNIT scope.
    This function keeps your original MatData shape (branches preserved).
    """
    ObjD, ObjP = to_branch_dict_any(Obj)
    CatD, CatP = to_branch_dict_any(Category)
    UidD, UidP = to_branch_dict_any(UnitId)

    all_paths: List[PathStr] = list(ObjP)
    # Keep Obj branches as the semantic truth (Strategy S1)
    want_tree = is_datatree_like(Obj)
    out_tree = new_datatree() if want_tree else None
    out_list: List[List[Any]] = []
    logs: List[str] = []

    for p in all_paths:
        objs = get_branch(ObjD, p, allow_fallback=False)
        u_branch = get_branch(UidD, p, allow_fallback=True)
        if not u_branch:
            raise Exception(f"[{p}] UnitId is required (missing branch and no fallback {{0}}).")

        unit_id = str(unwrap_gh(u_branch[0]) or "").strip()
        if not unit_id:
            raise Exception(f"[{p}] UnitId is empty after unwrap/strip.")

        c_branch = get_branch(CatD, p, allow_fallback=True)
        cat_value = default_category if not c_branch else str(unwrap_gh(c_branch[0]) or "").strip()
        if not cat_value:
            cat_value = default_category

        # Optional: derive loose IFC class hint (aligns with DBML ifcClassHint)
        ifc_class_hint = resolve_ifc_class_hint(cat_value)

        branch_items: List[Any] = []
        payload_count = 0
        bad_leaf = 0

        for k, obj_item in enumerate(objs):
            pair = unwrap_gh(obj_item)

            # Expect [geo, raw_name]
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                bad_leaf += 1
                continue

            geo = pair[0]
            raw_name = str(unwrap_gh(pair[1]) or "")

            # Keep legacy naming convention for PartNo extraction.
            # GUID assignment is handled in exporter (JSON-backed), so we DO NOT bind it here.
            if "_" in raw_name:
                part_no, _legacy_guid = raw_name.rsplit("_", 1)
            else:
                part_no, _legacy_guid = raw_name, None

            part_no = str(part_no).strip()
            if not part_no:
                bad_leaf += 1
                continue

            props: Dict[str, Any] = {
                "kind": "Part",
                "element_code": part_no,
                "ifc_class_hint": ifc_class_hint,

                "part_no": part_no,
                # exporter will assign stable GUID
                "source_guid": None,

                # keep same reserved bags as your old builder
                "dims": {"L": None, "W": None, "R": None},
                "material": {"name": None},
                "finish": {"type": None, "thickness_um": None},
                "color_code": None,

                # keep a redundant copy for compatibility with other parts of your pipeline
                "unit_id": unit_id,
                "scope": "UNIT",
            }

            # Optional GH override payload: 3rd slot from override component
            if len(pair) >= 3:
                apply_overrides_to_props(props, pair[2])

            payload: Payload = {
                "schema": int(schema_version),
                "unit_id": unit_id,
                "geo": geo,            # single geometry
                "name": part_no,
                "category": cat_value,
                "props": props,
            }

            normalize_payload_inplace(
                payload,
                default_schema=int(schema_version),
                default_category=cat_value,
            )

            branch_items.append(wrap_gh(payload))
            payload_count += 1

        if out_tree is not None:
            for it in branch_items:
                add_to_datatree(out_tree, p, it)
        else:
            out_list.append(branch_items)
        logs.append(
            f"{p} -> Unit {unit_id}: payloads={payload_count}"
            + (f" | bad_leaf={bad_leaf}" if bad_leaf else "")
            + f" | Cat={cat_value}"
        )

    return (out_tree if out_tree is not None else out_list), "\n".join(logs)
