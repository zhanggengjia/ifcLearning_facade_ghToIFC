# -*- coding: utf-8 -*-
"""
ifc_allGroup.py

Apply group membership to all Payload items after ifc_assembly.

GH component intent:
- Input  : MatData (Payload tree/list), Name (str tree/item)
- Output : MatData (same shape), Log

Rules:
- Name as item (single non-empty branch) -> broadcast to all MatData branches.
- Name as tree -> branch-specific mapping by GH path.
- Groups are written into payload.props["groups"].
- Existing groups are preserved; new names are appended with de-duplication.
- DataTree branch structure is preserved (Strategy S1).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple, cast

from ifc_types import Payload
from utils.gh_utils import (
    to_branch_dict_any,
    unwrap_gh,
    wrap_gh,
    is_datatree_like,
    new_datatree,
    add_to_datatree,
)
from utils.payload_utils import ensure_props, unwrap_payload


BUILD_STAMP = "ALLGROUP_BUILD__2026-02-25__v1"


def _normalize_group_names(items: List[Any]) -> List[str]:
    out: List[str] = []
    seen = set()
    for it in items:
        raw = unwrap_gh(it)
        if isinstance(raw, (list, tuple)):
            for x in raw:
                s = str(unwrap_gh(x) or "").strip()
                if s and s not in seen:
                    seen.add(s)
                    out.append(s)
            continue
        s = str(raw or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _resolve_groups_for_path(
    name_bd: Dict[str, List[Any]],
    path: str,
    common_groups: List[str],
    has_common: bool,
) -> List[str]:
    if path in name_bd:
        return _normalize_group_names(name_bd[path])
    if has_common:
        return list(common_groups)
    return []


def _merge_groups(existing: Any, incoming: List[str]) -> List[str]:
    merged: List[str] = []
    seen = set()

    if isinstance(existing, list):
        for g in existing:
            s = str(g).strip()
            if s and s not in seen:
                seen.add(s)
                merged.append(s)

    for g in incoming:
        s = str(g).strip()
        if s and s not in seen:
            seen.add(s)
            merged.append(s)

    return merged


def annotate_all_group(
    MatData: Any,
    Name: Any,
) -> Tuple[Any, str]:
    """Append group name(s) to every payload in MatData."""
    print(f"[{BUILD_STAMP}]")

    if MatData is None:
        return MatData, "allGroup: MatData is None."

    name_bd, _ = to_branch_dict_any(Name)
    non_empty_name_paths = [p for p, items in name_bd.items() if _normalize_group_names(items)]

    if not non_empty_name_paths:
        return MatData, "allGroup: empty Name -> no changes."

    # Item access / shared mode: exactly one non-empty Name branch.
    has_common = len(non_empty_name_paths) == 1
    common_groups = _normalize_group_names(name_bd[non_empty_name_paths[0]]) if has_common else []

    want_tree = is_datatree_like(MatData)
    out_tree = new_datatree() if want_tree else None
    out_list: List[Any] = []

    md_bd, md_paths = to_branch_dict_any(MatData)
    logs: List[str] = []
    touched_payloads = 0

    for path in md_paths:
        branch = md_bd.get(path, [])
        groups_for_branch = _resolve_groups_for_path(name_bd, path, common_groups, has_common)

        if not branch:
            if out_tree is None:
                out_list.append([])
            logs.append(f"{path}: empty branch")
            continue

        new_branch: List[Any] = []
        branch_touched = 0
        for item in branch:
            raw = unwrap_gh(item)
            p = unwrap_payload(raw)
            if p is None:
                new_branch.append(item)
                continue

            pp = cast(Payload, dict(p))
            props = ensure_props(pp)
            if groups_for_branch:
                props["groups"] = _merge_groups(props.get("groups"), groups_for_branch)
                branch_touched += 1
                touched_payloads += 1
            new_branch.append(wrap_gh(pp))

        if out_tree is not None:
            for it in new_branch:
                add_to_datatree(out_tree, path, it)
        else:
            out_list.append(new_branch)

        logs.append(
            f"{path}: groups={groups_for_branch if groups_for_branch else []} "
            f"payloads_touched={branch_touched}/{len(branch)}"
        )

    out_any = out_tree if out_tree is not None else out_list
    msg = (
        f"allGroup [{BUILD_STAMP}]: updated groups on {touched_payloads} payloads. "
        "Names are appended into payload.props['groups'] with de-duplication."
    )
    return out_any, msg + "\n" + "\n".join(logs)

