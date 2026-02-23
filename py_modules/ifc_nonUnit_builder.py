# -*- coding: utf-8 -*-
"""
ifc_nonUnit_builder.py

This builder creates NON_UNIT or CONTEXT payloads for non-unit elements.

Key features:
- Supports two scope modes: NON_UNIT (default) and CONTEXT
- Keeps naming convention: raw_name = "[PartNo]_[GUID]" or "[PartNo]"
- Keeps the same reserved bags in props (dims/material/finish/color_code)
- Uses existing utils (gh_utils + payload_utils) without modification

GH Inputs:
  Obj(Tree/List/Item): leaf = [geo, raw_name]
                       or [geo, raw_name, override_payload]
  Category(Item)     : str (required)
  SchemaVersion      : int (default: 1)
  Scope              : str (default: "NON_UNIT")
                       - "NON_UNIT": for general non-unit elements
                       - "CONTEXT": for context reference objects (beams, slabs, structural refs)

Outputs:
  MatData : Tree/List[Payload] (matches input structure)
  Log     : str

Usage:
  NonUnit_Builder: Use default Scope="NON_UNIT"
  Context_Builder: Set Scope="CONTEXT"
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ifc_types import Payload
from utils.gh_utils import to_branch_dict_any, unwrap_gh, wrap_gh, is_datatree_like, new_datatree, add_to_datatree
from utils.payload_utils import normalize_payload_inplace
from utils.override_utils import apply_overrides_to_props
from ifc_class_map import resolve_ifc_class_hint


def _is_pair(x: Any) -> bool:
    return isinstance(x, (list, tuple)) and len(x) >= 2


def build_nonUnit_matdata(
    Obj: Any,
    Category: Any,
    # NonUnitContainerId: Any,
    SchemaVersion: int = 1,
    Scope: str = "NON_UNIT",
) -> Tuple[Any, str]:
    if Obj is None:
        return [], "nonUnit_builder: Obj is None."

    cat = str(unwrap_gh(Category) or "").strip()
    if not cat:
        raise Exception("nonUnit_builder: Category is required.")

    # Normalize scope: support "NON_UNIT" (default) or "CONTEXT"
    scope = str(unwrap_gh(Scope) or "NON_UNIT").strip().upper()
    if scope not in ("NON_UNIT", "CONTEXT"):
        scope = "NON_UNIT"  # Fallback to NON_UNIT if invalid

    # container_id = str(unwrap_gh(NonUnitContainerId) or "").strip()
    # if not container_id:
    #     raise Exception("nonUnit_builder: NonUnitContainerId is required.")

    want_tree = is_datatree_like(Obj)
    out_tree = new_datatree() if want_tree else None
    out_list: List[Payload] = []
    count = 0
    bad_leaf = 0

    # Unify handling: Tree / list / scalar
    bd, paths = to_branch_dict_any(Obj)
    for p in paths:
        branch = bd.get(p, [])
        for item in branch:
            pair = unwrap_gh(item)
            if not _is_pair(pair):
                bad_leaf += 1
                continue

            geo = pair[0]
            raw_name = str(unwrap_gh(pair[1]) or "").strip()
            if not raw_name:
                bad_leaf += 1
                continue

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

            ifc_class_hint = resolve_ifc_class_hint(cat)
            props: Dict[str, Any] = {
                "scope": scope,
                "kind": "Part",
                "element_code": part_no,
                "ifc_class_hint": ifc_class_hint,
                # "container_id": container_id,
                "part_no": part_no,
                # exporter will assign stable GUID
                "source_guid": None,

                # keep same reserved bags as your old builder
                "dims": {"L": None, "W": None, "R": None},
                "material": {"name": None},
                "finish": {"type": None, "thickness_um": None},
                "color_code": None,
            }

            payload: Payload = {
                "schema": int(SchemaVersion),
                # Non_Unit doesn't have Unit concept; keep placeholder for payload contract.
                "unit_id": "__NON_UNIT__",
                "name": part_no,
                "category": cat,
                "geo": geo,
                "props": props,
            }

            # Optional GH override payload: 3rd slot from override component
            if isinstance(pair, (list, tuple)) and len(pair) >= 3:
                apply_overrides_to_props(props, pair[2])

            normalize_payload_inplace(
                payload,
                default_schema=int(SchemaVersion),
                default_category=cat,
            )

            if out_tree is not None:
                add_to_datatree(out_tree, p, wrap_gh(payload))
            else:
                out_list.append(payload)
            count += 1

    # log = f"nonUnit_builder: created {count} {scope} payloads (container={container_id})."
    log = f"nonUnit_builder: created {count} {scope} payloads."
    if bad_leaf:
        log += f" bad_leaf={bad_leaf}"
    return (out_tree if out_tree is not None else out_list), log
