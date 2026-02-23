# -*- coding: utf-8 -*-
"""
ifc_group.py

Annotate GH wrapper objects with IFC group membership.

This module sits BEFORE the builder in the pipeline.
It marks objects to be included in logical IFC groups (IfcGroup).

Groups vs Assemblies:
- IfcElementAssembly: Physical/geometric composition (e.g., frame + panels = unit)
- IfcGroup: Logical grouping (e.g., Zone A, Installation Phase 1, Floor 3)

An element can belong to multiple groups simultaneously.

WORKFLOW
--------
GH wrapper ([geo, name])
→ ifc_group (mark group membership)
→ ([geo, name, override_data])  # override_data includes {"groups": [...]}
→ Builder (writes to payload.props.groups)
→ Exporter (creates IfcGroup and assigns elements)

USAGE
-----
Single group:
    annotated_obj, log = annotate_group(Obj, GroupNames="Zone_A")

Multiple groups (tree input):
    annotated_obj, log = annotate_group(Obj, GroupNames=["Zone_A", "Phase_1"])

Per-branch groups (tree access):
    # GroupNames as DataTree with per-branch group names
    annotated_obj, log = annotate_group(Obj, GroupNames=GroupNamesTree)
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

BUILD_STAMP = "GROUP_BUILD__2026-02-23__v1"


def _is_wrapper(x: Any) -> bool:
    """Check if x is a valid GH wrapper: [geo, name] or [geo, name, override]."""
    return isinstance(x, (list, tuple)) and len(x) >= 2


def _normalize_groups(groups_input: Any) -> List[str]:
    """
    Normalize groups input to a list of group name strings.

    Accepts:
    - Single string: "Zone_A"
    - List of strings: ["Zone_A", "Phase_1"]
    - GH-wrapped values

    Returns:
    - List of non-empty group name strings
    """
    unwrapped = unwrap_gh(groups_input)

    if isinstance(unwrapped, str):
        g = unwrapped.strip()
        return [g] if g else []

    if isinstance(unwrapped, (list, tuple)):
        result = []
        for item in unwrapped:
            s = str(unwrap_gh(item) or "").strip()
            if s:
                result.append(s)
        return result

    # Fallback: try to convert to string
    s = str(unwrapped or "").strip()
    return [s] if s else []


def _merge_groups(existing: List[str], new: List[str]) -> List[str]:
    """
    Merge group lists, preserving order and avoiding duplicates.

    If an element already has groups from a previous ifc_group call,
    merge them with new groups (union).
    """
    seen = set()
    merged = []

    for g in existing + new:
        if g not in seen:
            seen.add(g)
            merged.append(g)

    return merged


def annotate_group(
    Obj: Any,
    GroupNames: Any,
) -> Tuple[Any, str]:
    """
    Annotate GH wrapper objects with group membership.

    Parameters
    ----------
    Obj : Tree/List/Item
        GH wrapper objects: [geo, name] or [geo, name, override_data]

    GroupNames : str | List[str] | Tree
        Group name(s) to assign to objects
        - Single string: all objects get same group
        - List: all objects get all groups in list
        - Tree (tree access): per-branch groups

    Returns
    -------
    (annotated_output, log_string)
        annotated_output: same structure as Obj, with groups added to override_data
        log_string: diagnostic message

    Behavior
    --------
    - Transforms [geo, name] → [geo, name, {"groups": [...]}]
    - Transforms [geo, name, override] → [geo, name, {**override, "groups": [...]}]
    - If groups already exist, merges with new groups (union)
    - Preserves tree structure (Strategy S1)
    - Can be called multiple times to add multiple groups

    Examples
    --------
    Single group for all objects:
        >>> annotate_group(Obj, "Zone_A")

    Multiple groups for all objects:
        >>> annotate_group(Obj, ["Zone_A", "Phase_1"])

    Per-branch groups (tree access):
        >>> # GroupNames is a DataTree with different groups per branch
        >>> annotate_group(Obj, GroupNamesTree)
    """
    print(f"[{BUILD_STAMP}]")

    if Obj is None:
        return Obj, "ifc_group: Obj is None."

    # Parse GroupNames input
    # Support both item access (single/list) and tree access (per-branch)
    group_bd, _ = to_branch_dict_any(GroupNames)

    # Detect common groups (item access): all branches have same groups
    has_common_groups = False
    common_groups: List[str] = []

    group_paths = [p for p, items in group_bd.items() if items]
    if len(group_paths) == 1:
        # Single branch in GroupNames → treat as common (broadcast to all)
        common_groups = _normalize_groups(group_bd[group_paths[0]])
        has_common_groups = True
    elif len(group_paths) == 0:
        # No groups provided
        return Obj, "ifc_group: GroupNames is empty. No groups added."

    # Parse Obj input
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

        # Resolve groups for this branch
        if path in group_bd:
            # Branch-specific groups (tree access)
            branch_groups = _normalize_groups(group_bd[path])
        elif has_common_groups:
            # Common groups (item access / broadcast)
            branch_groups = common_groups
        else:
            # No groups for this branch
            branch_groups = []

        if not branch_groups:
            # No groups to add for this branch → pass through unchanged
            if out_tree is not None:
                for item in branch:
                    add_to_datatree(out_tree, path, item)
            else:
                out_list.extend(branch)
            logs.append(f"{path}: no groups (passed through)")
            continue

        # Annotate each item in branch
        new_items: List[Any] = []
        for item in branch:
            wrapper = unwrap_gh(item)

            if not _is_wrapper(wrapper):
                # Not a valid wrapper → pass through unchanged
                new_items.append(item)
                continue

            geo = wrapper[0]
            name = wrapper[1]

            # Get existing override_data (if any)
            if len(wrapper) >= 3 and isinstance(wrapper[2], dict):
                override = dict(wrapper[2])  # Copy existing override
            else:
                override = {}

            # Merge groups
            existing_groups = override.get("groups", [])
            if not isinstance(existing_groups, list):
                existing_groups = []

            merged_groups = _merge_groups(existing_groups, branch_groups)
            override["groups"] = merged_groups

            # Build new wrapper
            new_wrapper = [geo, name, override]
            new_items.append(wrap_gh(new_wrapper))
            annotated_count += 1

        # Add to output
        if out_tree is not None:
            for item in new_items:
                add_to_datatree(out_tree, path, item)
        else:
            out_list.extend(new_items)

        logs.append(f"{path}: added groups {branch_groups} to {len(new_items)} items")

    out_any = out_tree if out_tree is not None else out_list

    msg = (
        f"ifc_group: annotated {annotated_count} items across {branch_count} branches. "
        f"Groups will be written to payload.props.groups by builder."
    )

    return out_any, msg + "\n" + "\n".join(logs)
