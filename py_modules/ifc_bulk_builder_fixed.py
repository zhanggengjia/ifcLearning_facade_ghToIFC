# -*- coding: utf-8 -*-
"""
ifc_bulk_builder.py (patched to align with your existing utils/*)

This builder:
- Does NOT change your GH-facing inputs/outputs.
- Keeps your naming convention: raw_name = "[PartNo]_[GUID]" or "[PartNo]".
- Keeps the same reserved bags in props (dims/material/finish/color_code).
- Uses your existing utils (gh_utils + payload_utils) WITHOUT modifying them.

GH Inputs:
  Obj(Tree/List/Item): leaf = [geo, raw_name]
  Category(Item)     : str (required)
  BulkContainerId    : str (required)
  SchemaVersion      : int

Outputs:
  MatData : list[Payload]
  Log     : str
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ifc_types import Payload
from utils.gh_utils import to_branch_dict_any, unwrap_gh
from utils.payload_utils import normalize_payload_inplace


def _is_pair(x: Any) -> bool:
    return isinstance(x, (list, tuple)) and len(x) >= 2


def build_bulk_matdata(
    Obj: Any,
    Category: Any,
    BulkContainerId: Any,
    SchemaVersion: int = 1,
) -> Tuple[List[Payload], str]:
    if Obj is None:
        return [], "bulk_builder: Obj is None."

    cat = str(unwrap_gh(Category) or "").strip()
    if not cat:
        raise Exception("bulk_builder: Category is required.")

    container_id = str(unwrap_gh(BulkContainerId) or "").strip()
    if not container_id:
        raise Exception("bulk_builder: BulkContainerId is required.")

    matdata: List[Payload] = []
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

            # Keep your naming convention
            if "_" in raw_name:
                part_no, source_guid = raw_name.rsplit("_", 1)
            else:
                part_no, source_guid = raw_name, None

            part_no = str(part_no).strip()
            if not part_no:
                bad_leaf += 1
                continue

            props: Dict[str, Any] = {
                "scope": "BULK",
                "kind": "Bulk",
                "element_code": part_no,
                "ifc_class_hint": "IfcBuildingElementProxy",
                "container_id": container_id,
                "part_no": part_no,
                "source_guid": str(source_guid).strip() if source_guid is not None else None,

                # keep same reserved bags as your old builder
                "dims": {"L": None, "W": None, "R": None},
                "material": {"name": None},
                "finish": {"type": None, "thickness_um": None},
                "color_code": None,
            }

            payload: Payload = {
                "schema": int(SchemaVersion),
                # Bulk doesn't have Unit concept; keep placeholder for payload contract.
                "unit_id": "__BULK__",
                "name": part_no,
                "category": cat,
                "geo": geo,
                "props": props,
            }

            normalize_payload_inplace(
                payload,
                default_schema=int(SchemaVersion),
                default_category=cat,
            )

            matdata.append(payload)
            count += 1

    log = f"bulk_builder: created {count} BULK payloads (container={container_id})."
    if bad_leaf:
        log += f" bad_leaf={bad_leaf}"
    return matdata, log
