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

# ---------------------------------------------------------------------
# Shared type contracts (Scheme A: keep this file in the same folder)
# ---------------------------------------------------------------------
from ifc_types import AnyInput, BranchDict, GHDataTreeLike, PathStr, Payload

# -----------------------------------------------------------------------------
# Optional GH wrapper (safe import)
# -----------------------------------------------------------------------------
# Grasshopper wires sometimes behave better when dict payloads are wrapped.
# We attempt to import GH_ObjectWrapper. If running outside GH (tests/CI),
# the import fails, and we simply skip wrapping.
try:
    from Grasshopper.Kernel.Types import GH_ObjectWrapper  # type: ignore
except Exception:
    GH_ObjectWrapper = None  # type: ignore


def _wrap_payload(payload: Payload) -> Any:
    """
    Wrap payload for Grasshopper wire transport.

    Why wrap?
    - Some GH contexts don't like plain Python dicts on the wire.
    - GH_ObjectWrapper forces GH to treat it as a single "goo" item.

    Behavior:
    - In GH runtime: GH_ObjectWrapper exists -> wrap dict
    - Outside GH: return dict directly (useful for tests/scripts)
    """
    if GH_ObjectWrapper is None:
        return payload
    return GH_ObjectWrapper(payload)


# -----------------------------------------------------------------------------
# Core utilities
# -----------------------------------------------------------------------------
def is_tree_like(x: Any) -> bool:
    """
    Return True if `x` looks like a Grasshopper DataTree (duck-typed).

    We intentionally avoid checking exact .NET types and only verify required API.
    """
    return (
        x is not None
        and hasattr(x, "BranchCount")
        and hasattr(x, "Path")
        and hasattr(x, "Branch")
    )


def to_branch_dict_any(x: AnyInput) -> Tuple[BranchDict, List[PathStr]]:
    """
    Normalize an input into a (branch_dict, paths) pair.

    Supported inputs:
    1) GH DataTree-like
       - each tree path becomes a dict key (string)
       - each branch becomes a Python list
       - returns all discovered paths (sorted)

    2) list/tuple (Sequence)
       - treated as a single branch "{0}"
       - returns one path ["{0}"]

    3) scalar
       - treated as a single branch "{0}" containing that one item
       - returns one path ["{0}"]
    """
    branches: BranchDict = {}
    paths: List[PathStr] = []

    # Case 1: Grasshopper DataTree
    if is_tree_like(x):
        tree = cast(GHDataTreeLike, x)
        for i in range(int(tree.BranchCount)):
            path_obj = tree.Path(i)
            p = str(path_obj)  # normalize to stable string key, e.g. "{0;1}"
            branches[p] = list(tree.Branch(path_obj))
            paths.append(p)
        paths.sort()
        return branches, paths

    # Case 2: Python sequence -> one branch
    if isinstance(x, (list, tuple)):
        branches["{0}"] = list(x)
        return branches, ["{0}"]

    # Case 3: scalar -> one branch with one item
    branches["{0}"] = [x]
    return branches, ["{0}"]


def get_branch(
    branch_dict: Mapping[PathStr, List[Any]],
    path: PathStr,
    fallback_path: PathStr = "{0}",
) -> List[Any]:
    """
    Get branch items by path; broadcast fallback "{0}" if needed.

    Typical GH use-case this supports:
    - Geo is a DataTree with many branches, but Category/UnitId is a single item.
      In that case Category/UnitId should "broadcast" to every Geo branch.

    Returns:
    - a COPY of the branch list (safe against accidental in-place mutation)
    - empty list if neither path exists
    """
    if path in branch_dict:
        return list(branch_dict[path])
    if fallback_path in branch_dict:
        return list(branch_dict[fallback_path])
    return []


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

    try:
        from Grasshopper.Kernel.Types import GH_ObjectWrapper  # type: ignore
    except Exception:
        GH_ObjectWrapper = None  # type: ignore

    def _unwrap(x: Any) -> Any:
        if GH_ObjectWrapper is not None and isinstance(x, GH_ObjectWrapper):  # type: ignore
            return getattr(x, "Value", x)
        return x

    out: List[List[Any]] = []
    logs: List[str] = []

    for p in all_paths:
        objs = list(ObjD.get(p, []))   # 沒有就 []
        us = get_branch(UidD, p)
        if not us:
            raise Exception(f"[{p}] UnitId is required (missing branch and no fallback {{0}}).")
        unit_id = str(us[0])

        cs = get_branch(CatD, p)
        cat_value = default_category if not cs else str(cs[0])

        branch_items: List[Any] = []
        payload_count = 0

        for k, obj_item in enumerate(objs):
            pair = _unwrap(obj_item)

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

            branch_items.append(_wrap_payload(payload))
            payload_count += 1

        out.append(branch_items)
        logs.append(f"{p} -> Unit {unit_id}: payloads={payload_count} | Cat={cat_value}")

    return out, "\n".join(logs)


