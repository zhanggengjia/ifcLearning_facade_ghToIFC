# -*- coding: utf-8 -*-
"""
ifc_builder.py

Build a Grasshopper-friendly "MatData" payload from flexible inputs
(GH DataTree / list / scalar), and normalize it into a predictable structure.

Output shape:
- MatData = List[List[wrapped_payload]]
  - outer list  : branches (sorted by path string)
  - inner list  : items in that branch
  - leaf item   : payload dict (wrapped into GH_ObjectWrapper if available)

This file is designed to pair with an exporter:
- Builder: converts GH inputs -> normalized payloads
- Exporter: consumes payloads -> IFC entities
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Tuple, cast

from ifc_class_map import resolve_ifc_class_hint, DEFAULT_IFC_CLASS

from utils.gh_utils import to_branch_dict_any, get_branch, wrap_gh, unwrap_gh
from utils.payload_utils import normalize_payload_inplace

from ifc_types import AnyInput, BranchDict, GHDataTreeLike, PathStr, Payload

# -----------------------------------------------------------------------------
# MatData builder
# -----------------------------------------------------------------------------
def build_matdata(
    Obj: AnyInput,
    Category: AnyInput,
    UnitId: AnyInput,
    schema_version: int = 1,
    default_category: str = "Unspecified",
) -> Tuple[List[List[Any]], str]:
    """
    Obj(Tree) builder (解法A):
      leaf = GH_ObjectWrapper([geo, raw_name])
    where raw_name = "[PartNo]_[GUID]" or "[PartNo]"

    Output MatData keeps the same shape as before:
      List[branch] where each branch is List[GH_ObjectWrapper(payload_dict)]
    """

    ObjD, ObjP = to_branch_dict_any(Obj)
    CatD, CatP = to_branch_dict_any(Category)
    UidD, UidP = to_branch_dict_any(UnitId)
    all_paths: List[PathStr] = sorted(set(ObjP) | set(UidP) | set(CatP))

    out: List[List[Any]] = []
    logs: List[str] = []

    for p in all_paths:
        objs = get_branch(ObjD, p, allow_fallback=False)
        us = get_branch(UidD, p, allow_fallback=True)
        if not us:
            raise Exception(f"[{p}] UnitId is required (missing branch and no fallback {{0}}).")
        unit_id = str(us[0])

        cs = get_branch(CatD, p, allow_fallback=True)
        cat_value = default_category if not cs else str(cs[0])
        # Optional: derive a loose IFC class hint (aligns with DBML ifcClassHint)
        cat_lower = (cat_value or "").strip().lower()
        ifc_class_hint = resolve_ifc_class_hint(cat_value)

        branch_items: List[Any] = []
        payload_count = 0

        for k, obj_item in enumerate(objs):
            pair = unwrap_gh(obj_item)

            # Expect [geo, raw_name]
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                raise Exception(f"[{p}] Obj leaf[{k}] must be [geo, raw_name]. Got: {type(pair)}")

            geo = pair[0]
            raw_name = str(pair[1])

            # Keep your naming convention
            if "_" in raw_name:
                part_no, source_guid = raw_name.rsplit("_", 1)
            else:
                part_no, source_guid = raw_name, None

            props: Dict[str, Any] = {
                "kind": "Part",
                "element_code": part_no,
                "ifc_class_hint": ifc_class_hint,

                "part_no": part_no,
                "source_guid": source_guid,

                # keep same reserved bags as your old builder
                "dims": {"L": None, "W": None, "R": None},
                "material": {"name": None},
                "finish": {"type": None, "thickness_um": None},
                "color_code": None,
            }

            payload: Payload = {
                "schema": int(schema_version),
                "unit_id": unit_id,
                "geo": geo,            # <-- guaranteed single geometry now
                "name": part_no,
                "category": cat_value,
                "props": props,
            }

            branch_items.append(wrap_gh(payload))
            payload_count += 1

        out.append(branch_items)
        logs.append(f"{p} -> Unit {unit_id}: payloads={payload_count} | Cat={cat_value}")

    return out, "\n".join(logs)


