# -*- coding: utf-8 -*-
"""
ifc_override.py

Grasshopper "Override" component.

Attach override key/value info to Obj wrappers:
    [geo, name, overrides]

Where `overrides` canonical structure is:
    { "Pset_Override": {key: value, ...}, ... }

Design rules (final):
- Mapping mode is determined by Key/Value tree structure, NOT by UnitId.
- UnitId (if provided) is validation-only:
    * top-level branches must match Obj top-level branches
    * each UnitId branch must have 1 non-empty item
- Priority per Obj branch:
    1) Per-object: branches like {obj_path;idx} provide MULTIPLE key/value pairs for that object
       - optional same-branch shared fallback {obj_path} if some {obj_path;idx} missing
    2) Per-branch shared: branch {obj_path} provides MULTIPLE key/value pairs shared by all objects in that branch
    3) Common override: Key and Value each have exactly ONE non-empty branch; apply to all Obj branches/items
- No cross-branch fallback except Common override.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple, Optional

try:
    import Grasshopper as gh  # type: ignore
    from Grasshopper import DataTree  # type: ignore
    from Grasshopper.Kernel.Data import GH_Path  # type: ignore
    from Grasshopper.Kernel import GH_RuntimeMessageLevel as RML  # type: ignore
except Exception:  # pragma: no cover
    gh = None
    DataTree = None
    GH_Path = None
    RML = None

from utils.gh_utils import to_branch_dict_any, unwrap_gh, wrap_gh
from utils.override_utils import DEFAULT_OVERRIDE_PSET, merge_pset_overrides


def _add_msg(level: Any, text: str) -> None:
    try:
        ghenv.Component.AddRuntimeMessage(level, text)  # type: ignore[name-defined]
    except Exception:
        pass


def _parse_path_tokens(path_str: str) -> List[int]:
    s = (path_str or "").strip()
    if s.startswith("{") and s.endswith("}"):
        s = s[1:-1]
    if not s:
        return [0]
    parts = [p.strip() for p in s.split(";") if p.strip()]
    out: List[int] = []
    for p in parts:
        try:
            out.append(int(p))
        except Exception:
            out.append(0)
    return out


def _append_path_index(path_str: str, idx: int) -> str:
    toks = _parse_path_tokens(path_str)
    toks.append(int(idx))
    return "{" + ";".join(str(i) for i in toks) + "}"


def _tree_has_any_data(bd: Dict[str, List[Any]]) -> bool:
    for v in bd.values():
        if v:
            for it in v:
                if str(unwrap_gh(it) or "").strip():
                    return True
    return False


def _tree_nonempty_paths(bd: Dict[str, List[Any]]) -> List[str]:
    out: List[str] = []
    for p, items in bd.items():
        if not items:
            continue
        ok = False
        for it in items:
            if str(unwrap_gh(it) or "").strip():
                ok = True
                break
        if ok:
            out.append(p)
    return sorted(out)


def _top_level_paths(paths: List[str]) -> List[str]:
    tops = set()
    for p in paths:
        toks = _parse_path_tokens(p)
        if toks:
            tops.add("{" + str(toks[0]) + "}")
    return sorted(tops)


def _validate_unitid_against_obj(obj_paths: List[str], uid_bd: Dict[str, List[Any]]) -> bool:
    """
    Validation-only (UnitId never affects mapping).

    If UnitId is provided (any data), enforce:

    - For every Obj top-level branch {i} that exists in Obj, UnitId must provide
      exactly one non-empty unit id for that same top-level {i}.
    - Extra UnitId branches are allowed (common case: some units have no objects
      for this override pass). We warn, but do NOT fail.

    Accepted UnitId layouts:
    - {i} -> [unitId]
    - deeper paths under the same top-level (e.g. {i;0}) are tolerated as long as
      they resolve to a single consistent non-empty unitId.
    """
    if not _tree_has_any_data(uid_bd):
        return True

    obj_top = _top_level_paths(obj_paths)
    uid_top = _top_level_paths(list(uid_bd.keys()))

    # Warn (but allow) if UnitId has extra tops that Obj doesn't have.
    extra = [p for p in uid_top if p not in obj_top]
    if extra:
        _add_msg(
            RML.Warning if RML else None,
            f"UnitId has extra top-level branches not present in Obj (allowed): {extra}",
        )

    # For each Obj top-level branch, we must be able to resolve exactly one unit id.
    for top in obj_top:
        # Collect all candidate unitId strings under this top-level.
        cands: List[str] = []

        # Direct {i}
        direct = uid_bd.get(top, [])
        for it in direct:
            s = str(unwrap_gh(it) or "").strip()
            if s:
                cands.append(s)

        # Deeper paths {i;...}
        top_tok = _parse_path_tokens(top)[0]
        for p, items in uid_bd.items():
            toks = _parse_path_tokens(p)
            if not toks or toks[0] != top_tok:
                continue
            for it in items:
                s = str(unwrap_gh(it) or "").strip()
                if s:
                    cands.append(s)

        # Deduplicate while preserving order
        seen = set()
        uniq: List[str] = []
        for s in cands:
            if s not in seen:
                seen.add(s)
                uniq.append(s)

        if len(uniq) != 1:
            _add_msg(
                RML.Warning if RML else None,
                f"UnitId branch {top} must resolve to exactly 1 non-empty item. "
                f"Resolved={uniq} (count={len(uniq)}). Output suppressed.",
            )
            return False

    return True

    obj_top = _top_level_paths(obj_paths)
    uid_top = _top_level_paths(list(uid_bd.keys()))

    if obj_top != uid_top:
        _add_msg(
            RML.Warning if RML else None,
            "UnitId top-level branches do not match Obj.\n"
            f"Obj tops: {obj_top}\nUnitId tops: {uid_top}\n"
            "Fix tree data. Output suppressed.",
        )
        return False

    for p in obj_top:
        items = uid_bd.get(p, [])
        if len(items) != 1 or not str(unwrap_gh(items[0]) or "").strip():
            _add_msg(RML.Warning if RML else None, f"UnitId branch {p} must have exactly 1 non-empty item. Output suppressed.")
            return False

    return True


def _kv_from_lists(k_items: List[Any], v_items: List[Any], *, where: str) -> Tuple[bool, Dict[str, Any], str]:
    if len(k_items) != len(v_items):
        return False, {}, f"Key/Value count mismatch at {where}: key={len(k_items)} value={len(v_items)}"
    kv: Dict[str, Any] = {}
    for kk, vv in zip(k_items, v_items):
        k = str(unwrap_gh(kk) or "").strip()
        v = unwrap_gh(vv)
        if k:
            kv[k] = v
    if not kv:
        return False, {}, f"Empty Key/Value at {where} (all keys blank)."
    return True, kv, ""


def _detect_common_override(key_bd: Dict[str, List[Any]], val_bd: Dict[str, List[Any]]) -> Tuple[bool, Dict[str, Any], str]:
    """
    Common override if Key and Value each have exactly ONE non-empty branch, and paths are identical.
    """
    k_paths = _tree_nonempty_paths(key_bd)
    v_paths = _tree_nonempty_paths(val_bd)
    if len(k_paths) == 1 and len(v_paths) == 1 and k_paths[0] == v_paths[0]:
        p = k_paths[0]
        ok, kv, err = _kv_from_lists(key_bd.get(p, []), val_bd.get(p, []), where=f"COMMON {p}")
        if not ok:
            return False, {}, err
        return True, kv, ""
    return False, {}, ""


def _pick_kv_for_obj_branch(
    *,
    obj_bd: Dict[str, List[Any]],
    key_bd: Dict[str, List[Any]],
    val_bd: Dict[str, List[Any]],
    obj_path: str,
) -> Tuple[bool, List[Dict[str, Any]], str]:
    """
    For a given Obj branch, return per-item kv dict list aligned to the number of objects in that branch.

    Priority inside the branch:
    1) Per-object sub-branches {obj_path;idx} if any exist
       - Each sub-branch contains MULTIPLE key/value pairs for that object.
       - If some sub-branch missing, allow SAME-branch shared fallback {obj_path}.
    2) Shared branch {obj_path}: MULTIPLE key/value pairs broadcast to all items in that branch.
    3) Missing: return error (caller may decide to apply common override).
    """
    branch = obj_bd.get(obj_path, [])
    n = len(branch)
    if n <= 0:
        return True, [], ""

    # detect any per-object sub-branch
    sub_any = False
    for i in range(n):
        sp = _append_path_index(obj_path, i)
        if sp in key_bd or sp in val_bd:
            sub_any = True
            break

    shared_k = key_bd.get(obj_path, [])
    shared_v = val_bd.get(obj_path, [])

    # per-object mode
    if sub_any:
        shared_ok = False
        shared_kv: Dict[str, Any] = {}
        if shared_k or shared_v:
            ok, kv, err = _kv_from_lists(shared_k, shared_v, where=obj_path)
            if not ok:
                return False, [], err
            shared_ok = True
            shared_kv = kv

        out: List[Dict[str, Any]] = []
        for i in range(n):
            sp = _append_path_index(obj_path, i)
            k_items = key_bd.get(sp, [])
            v_items = val_bd.get(sp, [])
            if not k_items and not v_items:
                if shared_ok:
                    out.append(dict(shared_kv))
                    continue
                return False, [], f"Missing Key/Value branch {sp} (and no shared {obj_path})."
            ok, kv, err = _kv_from_lists(k_items, v_items, where=sp)
            if not ok:
                return False, [], err
            out.append(kv)
        return True, out, ""

    # shared branch mode
    if shared_k or shared_v:
        ok, kv, err = _kv_from_lists(shared_k, shared_v, where=obj_path)
        if not ok:
            return False, [], err
        return True, [dict(kv) for _ in range(n)], ""

    return False, [], f"Missing Key/Value for branch {obj_path}."


def override_obj_tree(Obj: Any, Key: Any, Value: Any, UnitId: Any) -> Tuple[Any, str]:
    obj_bd, obj_paths = to_branch_dict_any(Obj)
    key_bd, _ = to_branch_dict_any(Key)
    val_bd, _ = to_branch_dict_any(Value)
    uid_bd, _ = to_branch_dict_any(UnitId)

    if DataTree is None or GH_Path is None:
        return Obj, "override: GH DataTree unavailable; passthrough."

    out_tree = DataTree[object]()
    logs: List[str] = []

    if not obj_paths:
        _add_msg(RML.Error if RML else None, "Obj is empty.")
        return DataTree[object](), "override: empty obj"

    # UnitId validation only
    if not _validate_unitid_against_obj(obj_paths, uid_bd):
        return DataTree[object](), "override: unitId validation failed"

    # detect common override
    has_common, common_kv, common_err = _detect_common_override(key_bd, val_bd)
    if common_err:
        _add_msg(RML.Error if RML else None, common_err)
        return DataTree[object](), "override: common override invalid"
    if has_common:
        logs.append("override: common override detected (single Key/Value branch).")

    # Per Obj branch mapping
    for p in obj_paths:
        toks = _parse_path_tokens(p)
        ghp = GH_Path(*toks)  # type: ignore
        branch = obj_bd.get(p, [])
        if not branch:
            continue

        ok, per_item_kv, err = _pick_kv_for_obj_branch(obj_bd=obj_bd, key_bd=key_bd, val_bd=val_bd, obj_path=p)

        # if missing mapping for this branch, apply common override (if present)
        if not ok:
            if has_common:
                per_item_kv = [dict(common_kv) for _ in range(len(branch))]
                ok = True
                logs.append(f"override: branch {p} used common override.")
            else:
                _add_msg(RML.Error if RML else None, err)
                return DataTree[object](), "override: mapping error"

        for idx, item in enumerate(branch):
            pair = unwrap_gh(item)
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                _add_msg(RML.Warning if RML else None, f"Obj leaf at {p}[{idx}] is not [geo, name]. Skipped.")
                continue

            geo = pair[0]
            name = unwrap_gh(pair[1])
            existing = pair[2] if len(pair) >= 3 else None

            kv = per_item_kv[idx] if idx < len(per_item_kv) else {}
            wrapped = {DEFAULT_OVERRIDE_PSET: kv} if kv else {}
            merged = merge_pset_overrides(existing, wrapped)

            out_tree.Add(wrap_gh([geo, name, merged]), ghp)

    logs.append("override: done")
    return out_tree, "\n".join(logs)

