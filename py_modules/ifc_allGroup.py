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

Future optimization note:
- Current implementation stores group-level pset/qto overrides on each payload
  via props["group_overrides"], which can duplicate metadata in large models.
- A future update can adopt a GroupMeta pattern (similar to AssemblyMeta)
  so group-level metadata is emitted once per branch/group, reducing repeated
  annotations and improving preprocessing efficiency.
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


BUILD_STAMP = "ALLGROUP_BUILD__2026-02-26__v2"
DEFAULT_GROUP_PSET = "Pset_Group"
DEFAULT_GROUP_QTO = "Qto_Group"


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


def _kv_from_lists(k_items: List[Any], v_items: List[Any], *, where: str) -> Tuple[bool, Dict[str, Any], str]:
    if len(k_items) != len(v_items):
        return False, {}, f"[{where}] Key/Value length mismatch: {len(k_items)} vs {len(v_items)}"
    out: Dict[str, Any] = {}
    for k, v in zip(k_items, v_items):
        kk = str(unwrap_gh(k) or "").strip()
        if not kk:
            continue
        out[kk] = unwrap_gh(v)
    return True, out, ""


def _detect_common_kv(bd_key: Dict[str, List[Any]], bd_val: Dict[str, List[Any]]) -> Tuple[bool, Dict[str, Any], str]:
    k_paths = [p for p, it in bd_key.items() if it]
    v_paths = [p for p, it in bd_val.items() if it]
    if len(k_paths) == 1 and len(v_paths) == 1:
        return _kv_from_lists(bd_key[k_paths[0]], bd_val[v_paths[0]], where="COMMON")
    return False, {}, ""


def _pick_kv_for_branch(
    *,
    path: str,
    bd_key: Dict[str, List[Any]],
    bd_val: Dict[str, List[Any]],
    allow_common: bool,
    has_common: bool,
    common_kv: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any], str]:
    if path in bd_key or path in bd_val:
        return _kv_from_lists(bd_key.get(path, []), bd_val.get(path, []), where=path)
    if allow_common and has_common:
        return True, dict(common_kv), ""
    return True, {}, ""


def _merge_nested_kv(existing: Any, incoming: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if isinstance(existing, dict):
        for k, v in existing.items():
            ks = str(k).strip()
            if ks:
                out[ks] = v
    for k, v in incoming.items():
        ks = str(k).strip()
        if ks:
            out[ks] = v
    return out


def _merge_group_overrides_for_name(
    props: Dict[str, Any],
    *,
    group_name: str,
    pset_name: str,
    kv: Dict[str, Any],
    qto_name: str,
    qto_kv: Dict[str, Any],
) -> None:
    go = props.get("group_overrides")
    if not isinstance(go, dict):
        go = {}
        props["group_overrides"] = go

    one = go.get(group_name)
    if not isinstance(one, dict):
        one = {}
        go[group_name] = one

    if kv:
        pset_overrides = one.get("pset_overrides")
        if not isinstance(pset_overrides, dict):
            pset_overrides = {}
            one["pset_overrides"] = pset_overrides
        old_pset = pset_overrides.get(pset_name)
        pset_overrides[pset_name] = _merge_nested_kv(old_pset, kv)

    if qto_kv:
        qto_overrides = one.get("qto_overrides")
        if not isinstance(qto_overrides, dict):
            qto_overrides = {}
            one["qto_overrides"] = qto_overrides
        old_qto = qto_overrides.get(qto_name)
        qto_overrides[qto_name] = _merge_nested_kv(old_qto, qto_kv)


def annotate_all_group(
    MatData: Any,
    Name: Any,
    Key: Any = None,
    Value: Any = None,
    QtoName: Any = None,
    QtoKey: Any = None,
    QtoValue: Any = None,
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
    # Name mode controls Key/Value and Qto* common broadcast behavior.
    # If Name is tree-mode, KV/Qto must map by branch.
    allow_common_kv = has_common

    key_bd, _ = to_branch_dict_any(Key)
    val_bd, _ = to_branch_dict_any(Value)
    has_common_kv, common_kv, common_kv_err = _detect_common_kv(key_bd, val_bd)
    if common_kv_err:
        return MatData, f"allGroup: invalid common Key/Value: {common_kv_err}"

    qkey_bd, _ = to_branch_dict_any(QtoKey)
    qval_bd, _ = to_branch_dict_any(QtoValue)
    has_common_qto, common_qto_kv, common_qto_err = _detect_common_kv(qkey_bd, qval_bd)
    if common_qto_err:
        return MatData, f"allGroup: invalid common QtoKey/QtoValue: {common_qto_err}"

    pset_name_str = DEFAULT_GROUP_PSET
    qto_name_str = str(unwrap_gh(QtoName) or "").strip() or DEFAULT_GROUP_QTO

    want_tree = is_datatree_like(MatData)
    out_tree = new_datatree() if want_tree else None
    out_list: List[Any] = []

    md_bd, md_paths = to_branch_dict_any(MatData)
    logs: List[str] = []
    touched_payloads = 0

    for path in md_paths:
        branch = md_bd.get(path, [])
        groups_for_branch = _resolve_groups_for_path(name_bd, path, common_groups, has_common)
        ok_kv, kv, kv_err = _pick_kv_for_branch(
            path=path,
            bd_key=key_bd,
            bd_val=val_bd,
            allow_common=allow_common_kv,
            has_common=has_common_kv,
            common_kv=common_kv,
        )
        if not ok_kv:
            return MatData, f"allGroup: {kv_err}"

        ok_qto, qto_kv, qto_err = _pick_kv_for_branch(
            path=path,
            bd_key=qkey_bd,
            bd_val=qval_bd,
            allow_common=allow_common_kv,
            has_common=has_common_qto,
            common_kv=common_qto_kv,
        )
        if not ok_qto:
            return MatData, f"allGroup: {qto_err}"

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
                if kv or qto_kv:
                    for gname in groups_for_branch:
                        _merge_group_overrides_for_name(
                            props,
                            group_name=gname,
                            pset_name=pset_name_str,
                            kv=kv,
                            qto_name=qto_name_str,
                            qto_kv=qto_kv,
                        )
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
            f"payloads_touched={branch_touched}/{len(branch)} "
            f"pset_keys={list(kv.keys()) if kv else []} "
            f"qto_keys={list(qto_kv.keys()) if qto_kv else []}"
        )

    out_any = out_tree if out_tree is not None else out_list
    msg = (
        f"allGroup [{BUILD_STAMP}]: updated groups on {touched_payloads} payloads. "
        "Names are appended into payload.props['groups'] with de-duplication; "
        "group-level pset/qto overrides are stored in payload.props['group_overrides']."
    )
    return out_any, msg + "\n" + "\n".join(logs)
