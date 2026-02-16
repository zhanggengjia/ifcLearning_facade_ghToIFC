# ifc_assembly.py
# -*- coding: utf-8 -*-
"""
Assembly annotation module for the GH-to-IFC pipeline.

PURPOSE
-------
This module sits between the builder (ifc_builder) and the exporter (ifc_exporter).
It stamps *assembly nesting information* onto each Payload flowing through the
Grasshopper DataTree, so the downstream exporter can reconstruct the IFC
spatial/assembly hierarchy.

KEY CONCEPTS
------------
1. **Payload** (see ifc_types.py)
   A dict with stable core keys (schema, unit_id, geo, name, category)
   and a mutable `props` dict for evolving data.

2. **assembly_path** (props['assembly_path'])
   A list[dict] that records the nesting chain of assembly levels.
   Each dict has: {name, key, role?}.
   The list is ordered from innermost (index 0) to outermost.

3. **Stable outer wrap rule**
   When a subassembly is applied, its node is PREPENDED to the existing
   assembly_path. Duplicate keys are collapsed so repeated application
   does not create unwanted extra depth.

4. **Strategy S1 – branch preservation**
   The Grasshopper DataTree branch paths ({0;0}, {0;1}, …) represent
   unit boundaries. This module MUST output the same branch paths as
   input — it never merges or splits branches.

5. **AssemblyMeta payload**
   When Key/Value overrides are supplied, a lightweight synthetic payload
   (category = "__ASSEMBLY_META__") is appended to the branch. It carries
   `props['pset_overrides']` so the exporter can write IFC property sets
   onto the assembly node without attaching them to a real geometric element.
   Its `geo` is a tiny dummy mesh (Rhino requirement for DataTree items).

ENTRY POINT
-----------
    annotate_subassembly(MatData, Name, KeySuffix, Role, Key, Value, UnitId)
        -> (annotated_MatData, log_string)

All other functions are internal helpers prefixed with '_'.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, cast
from collections import Counter

from ifc_types import Payload
from utils.gh_utils import (
    unwrap_gh,
    wrap_gh,
    is_datatree_like,
    to_branch_dict_any,    new_datatree,
    add_to_datatree,
)
from utils.payload_utils import ensure_props

# Printed at runtime to identify which build of this module is active.
BUILD_STAMP = "ASSEMBLY_BUILD__2026-02-16__META_HARDENED__v3"

# Canonical category string for synthetic metadata payloads.
# The exporter skips geometric IFC creation for payloads with this category
# and instead writes their pset_overrides onto the parent assembly node.
ASSEMBLY_META_CATEGORY = "__ASSEMBLY_META__"

# Default IFC property-set name used when writing assembly-level KV overrides.
DEFAULT_ASSEMBLY_PSET = "Pset_Assembly"


def is_payload(x: Any) -> bool:
    """Check whether *x* looks like a valid Payload dict.

    This is a duck-type check (not isinstance(Payload)) because payloads
    arrive as plain dicts after GH wrapping/unwrapping.  The minimum
    requirements are: dict with 'geo' present, 'unit_id' as str, 'name'
    as str, and optional 'props' (dict), 'schema' (int), 'category' (str).
    """
    if not isinstance(x, dict):
        return False
    if "geo" not in x:
        return False
    if not isinstance(x.get("unit_id", None), str):
        return False
    if not isinstance(x.get("name", None), str):
        return False
    props = x.get("props", None)
    if props is not None and not isinstance(props, dict):
        return False
    sch = x.get("schema", None)
    if sch is not None and not isinstance(sch, int):
        return False
    cat = x.get("category", None)
    if cat is not None and not isinstance(cat, str):
        return False
    return True


def _build_key(name: str, key_suffix: Optional[str]) -> str:
    """Build the stable identity key for an assembly node.

    Format: "name" or "name|suffix" when a KeySuffix is supplied.
    The key is used for deduplication during the stable-outer-wrap step.
    """
    n = str(name or "").strip()
    s = str(key_suffix or "").strip() if key_suffix else ""
    if not s:
        return n
    return f"{n}|{s}"


def _same_key(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Return True if two assembly-path nodes share the same identity key."""
    return str(a.get("key", "")) == str(b.get("key", ""))


def _stable_wrap_outer(path: Any, node: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Prepend *node* to *path* while deduplicating by key (stable outer wrap).

    Algorithm:
      1. Remove any existing entries in *path* that share the same key as *node*.
      2. Prepend *node* to the front of the cleaned path.
      3. Collapse any consecutive entries with the same key (safety net).

    This guarantees idempotent wrapping: applying the same subassembly
    twice produces the same assembly_path as applying it once.
    """
    if not isinstance(path, list):
        path = []

    # Step 1: strip out prior entries with the same key as the new node
    cleaned: List[Dict[str, Any]] = []
    for lvl in path:
        if isinstance(lvl, dict) and _same_key(lvl, node):
            continue
        if isinstance(lvl, dict):
            cleaned.append(lvl)

    # Step 2: prepend the new node
    out: List[Dict[str, Any]] = [node] + cleaned

    # Step 3: collapse consecutive duplicate keys
    collapsed: List[Dict[str, Any]] = []
    for lvl in out:
        if not collapsed:
            collapsed.append(lvl)
            continue
        prev = collapsed[-1]
        if isinstance(prev, dict) and isinstance(lvl, dict) and _same_key(prev, lvl):
            continue
        collapsed.append(lvl)

    return collapsed


def _annotate_payload(payload: Payload, sub_name: str, key_suffix: Optional[str], role: Optional[str]) -> Payload:
    """Stamp a single Payload with the current subassembly node.

    Creates a shallow copy of the payload, then applies the stable-outer-wrap
    rule to props['assembly_path'].  The original payload is not mutated.
    """
    p: Dict[str, Any] = dict(payload)
    props = ensure_props(cast(Payload, p))

    path = props.get("assembly_path")
    if not isinstance(path, list):
        path = []
        props["assembly_path"] = path

    # Build the assembly node descriptor for this level
    node: Dict[str, Any] = {
        "name": sub_name,
        "key": _build_key(sub_name, key_suffix) or sub_name,
    }
    if role:
        node["role"] = role

    props["assembly_path"] = _stable_wrap_outer(path, node)
    return cast(Payload, p)


def _kv_from_lists(k_items: List[Any], v_items: List[Any], *, where: str) -> Tuple[bool, Dict[str, Any], str]:
    """Zip parallel Key and Value lists into a {k: v} dict.

    Returns (ok, kv_dict, error_msg).  Fails if the two lists differ in length.
    Empty key strings are silently skipped.
    """
    if len(k_items) != len(v_items):
        return False, {}, f"[{where}] Key/Value length mismatch: {len(k_items)} vs {len(v_items)}"
    out: Dict[str, Any] = {}
    for k, v in zip(k_items, v_items):
        kk = str(unwrap_gh(k) or "").strip()
        if not kk:
            continue
        out[kk] = unwrap_gh(v)
    return True, out, ""


def _detect_common_override(key_bd: Dict[str, List[Any]], val_bd: Dict[str, List[Any]]) -> Tuple[bool, Dict[str, Any], str]:
    """Detect a "common" (single-branch) KV override that applies to all units.

    If both Key and Value inputs have exactly one non-empty branch each,
    they are treated as a common override shared across every MatData branch.
    """
    k_paths = [p for p, it in key_bd.items() if it]
    v_paths = [p for p, it in val_bd.items() if it]
    if len(k_paths) == 1 and len(v_paths) == 1:
        ok, kv, err = _kv_from_lists(key_bd[k_paths[0]], val_bd[v_paths[0]], where="COMMON")
        if not ok:
            return False, {}, err
        return True, kv, ""
    return False, {}, ""


def _pick_kv_for_unit_branch(
    *,
    unit_path: str,
    key_bd: Dict[str, List[Any]],
    val_bd: Dict[str, List[Any]],
    has_common: bool,
    common_kv: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any], str]:
    """Resolve the KV override dict for a specific unit branch.

    Resolution order:
      1. If a branch-specific Key/Value exists for this path, use it.
      2. Else if a common override was detected, use the common KV.
      3. Otherwise no override (empty dict) — still OK, no error.
    """
    if unit_path in key_bd or unit_path in val_bd:
        k_items = key_bd.get(unit_path, [])
        v_items = val_bd.get(unit_path, [])
        ok, kv, err = _kv_from_lists(k_items, v_items, where=unit_path)
        return ok, kv, err

    if has_common:
        return True, dict(common_kv), ""

    return True, {}, ""


def _validate_unitid_against_paths(obj_paths: List[str], uid_bd: Dict[str, List[Any]]) -> Tuple[bool, str]:
    """Validate that every MatData branch has a matching UnitId entry.

    Skipped entirely when no UnitId tree is supplied (uid_bd is empty).
    When supplied, each MatData branch path must appear in uid_bd with
    a non-empty first element.  Fails fast on the first missing/empty entry.
    """
    if not uid_bd:
        return True, ""
    for p in obj_paths:
        items = uid_bd.get(p, [])
        if not items:
            return False, f"UnitId validation failed: missing branch {p}"
        s = str(unwrap_gh(items[0]) or "").strip()
        if not s:
            return False, f"UnitId validation failed: empty UnitId at branch {p}"
    return True, ""


def _tiny_dummy_mesh() -> Any:
    """Create a minimal 1-triangle Rhino Mesh as a placeholder geometry.

    AssemblyMeta payloads need a non-None geo to survive GH DataTree
    operations (some GH components drop items with None geo).
    The exporter recognises category == ASSEMBLY_META_CATEGORY and skips
    IFC geometry creation for these items.
    """
    try:
        import Rhino.Geometry as rg  # type: ignore
        m = rg.Mesh()
        m.Vertices.Add(0, 0, 0)
        m.Vertices.Add(0.001, 0, 0)
        m.Vertices.Add(0, 0.001, 0)
        m.Faces.AddFace(0, 1, 2)
        return m
    except Exception:
        return None


def _make_assembly_meta_payload(
    *,
    unit_id: str,
    scope: str,
    schema: int,
    sub_name: str,
    kv: Dict[str, Any],
) -> Payload:
    """Build a synthetic AssemblyMeta payload carrying KV overrides.

    The resulting payload:
      - category = ASSEMBLY_META_CATEGORY ("__ASSEMBLY_META__")
      - geo = tiny dummy mesh (placeholder, not exported to IFC)
      - props.kind = "AssemblyMeta"
      - props.pset_overrides = { "Pset_Assembly": {k: v, ...} }

    The exporter writes pset_overrides onto the parent IfcElementAssembly
    node rather than creating a standalone IFC element for this payload.
    """
    props: Dict[str, Any] = {
        "scope": scope,
        "kind": "AssemblyMeta",
        "unit_id": unit_id,
        "pset_overrides": {DEFAULT_ASSEMBLY_PSET: dict(kv)},
    }
    return cast(Payload, {
        "schema": int(schema),
        "unit_id": unit_id,
        "geo": _tiny_dummy_mesh(),
        "name": sub_name,
        "category": ASSEMBLY_META_CATEGORY,
        "props": props,
    })


def _count_meta_in_items(items: List[Any]) -> int:
    """Count how many AssemblyMeta payloads exist in *items* (for diagnostics)."""
    n = 0
    for it in items:
        raw = unwrap_gh(it)
        if isinstance(raw, dict) and raw.get("category") == ASSEMBLY_META_CATEGORY:
            n += 1
    return n


def _add_items_to_tree(tree: Any, path: str, items: List[Any]) -> None:
    """
    Your utils.add_to_datatree appears to accept (tree, path, single_item).
    If we pass a list, it becomes one list-item in the branch -> downstream can't see payload dicts.
    So we always add item-by-item.
    """
    for it in items:
        add_to_datatree(tree, path, it)


def _flatten_one_level(x: Any) -> List[Any]:
    """
    If a branch accidentally contains one element which is a list-of-items,
    flatten it for debug / verification.
    """
    if isinstance(x, list):
        return x
    return [x]


def annotate_subassembly(
    MatData: Any,
    Name: Any,
    KeySuffix: Any = None,
    Role: Any = None,
    Key: Any = None,
    Value: Any = None,
    UnitId: Any = None,
) -> Tuple[Any, str]:
    """Main entry point — annotate every Payload in MatData with assembly info.

    This function is called from a GHPython component.  It corresponds to
    one level of the assembly hierarchy (e.g. "Mullion", "Panel", "CW_Unit").

    Parameters
    ----------
    MatData : GH DataTree or list
        Input payloads organised by unit branches.
    Name : str
        Assembly level name (e.g. "Panel_A").
    KeySuffix : str, optional
        Appended to Name to form the identity key ("Name|Suffix").
        Useful when the same Name appears in different roles.
    Role : str, optional
        Semantic role tag stored in the assembly_path node (e.g. "frame").
    Key / Value : GH DataTree or list, optional
        Parallel lists of property keys and values for assembly-level
        IFC property-set overrides.  Can be branch-matched (per-unit)
        or single-branch (common to all units).
    UnitId : GH DataTree or list, optional
        Explicit unit-id per branch.  When supplied, every MatData branch
        must have a matching entry (fail-fast validation).

    Returns
    -------
    (annotated_output, log_string)
        annotated_output preserves the same DataTree/list shape as MatData
        (Strategy S1).  log_string is a human-readable diagnostic.

    Processing steps (per branch)
    -----------------------------
    1. Extract unit_id, scope, schema from the first payload in the branch.
    2. Annotate every payload via _annotate_payload (stable outer wrap).
    3. Resolve KV overrides for this branch (_pick_kv_for_unit_branch).
    4. If KV overrides exist, create and append an AssemblyMeta payload.
    5. Rebuild the output tree/list preserving original branch paths.
    6. Run a verification pass counting categories for diagnostics.
    """
    print(f"[{BUILD_STAMP}]")

    # ── 0. Parse scalar inputs ──────────────────────────────────────────
    sub_name = str(Name).strip() if Name is not None else ""
    if not sub_name:
        return MatData, "assembly: empty Name -> no changes."

    key_suffix = None
    if KeySuffix is not None:
        ks = str(KeySuffix).strip()
        key_suffix = ks if ks else None

    role = None
    if Role is not None:
        r = str(Role).strip()
        role = r if r else None

    # ── 1. Normalise tree-like inputs into branch dicts ─────────────────
    key_bd, _ = to_branch_dict_any(Key)
    val_bd, _ = to_branch_dict_any(Value)
    uid_bd, _ = to_branch_dict_any(UnitId)

    # ── 2. Detect common (single-branch) KV override ───────────────────
    has_common, common_kv, common_err = _detect_common_override(key_bd, val_bd)
    if common_err:
        return MatData, f"assembly: invalid common override: {common_err}"

    # ── 3. Prepare output container matching input shape (Strategy S1) ──
    want_tree = is_datatree_like(MatData)
    out_tree = new_datatree() if want_tree else None

    md_bd, md_paths = to_branch_dict_any(MatData)
    ok_uid, uid_err = _validate_unitid_against_paths(md_paths, uid_bd)
    if not ok_uid:
        return MatData, f"assembly: {uid_err}"

    logs: List[str] = []
    out_list: List[Any] = []
    per_branch_meta: Dict[str, int] = {}

    # ── 4. Process each branch ──────────────────────────────────────────
    for p in md_paths:
        branch = md_bd.get(p, [])
        if not branch:
            if out_tree is None:
                out_list.append([])
            continue

        # 4a. Infer unit_id / scope / schema from the first payload in branch
        unit_id = ""
        scope = "UNIT"
        schema = 1
        for it in branch:
            leaf = unwrap_gh(it)
            if is_payload(leaf):
                pl = cast(Payload, leaf)
                unit_id = str(pl.get("unit_id", "")).strip()
                schema = int(pl.get("schema", 1) or 1)
                pr = ensure_props(pl)
                scope = str(pr.get("scope", "UNIT") or "UNIT").strip().upper()
                scope = "NON_UNIT" if scope == "NON_UNIT" else "UNIT"
                break

        # 4b. Annotate each payload with the assembly_path node
        new_branch_items: List[Any] = []
        touched = 0
        for it in branch:
            leaf0 = unwrap_gh(it)
            if is_payload(leaf0):
                annotated = _annotate_payload(cast(Payload, leaf0), sub_name, key_suffix, role)
                new_branch_items.append(wrap_gh(annotated))
                touched += 1
            else:
                new_branch_items.append(it)

        # 4c. Resolve KV overrides for this branch
        ok_kv, kv, err = _pick_kv_for_unit_branch(
            unit_path=p,
            key_bd=key_bd,
            val_bd=val_bd,
            has_common=has_common,
            common_kv=common_kv,
        )
        if not ok_kv:
            return MatData, f"assembly: {err}"

        # 4d. If KV overrides exist, emit an AssemblyMeta payload
        added_meta = 0
        if kv:
            # Fallback unit_id from UnitId input if the branch had none
            if not unit_id:
                items = uid_bd.get(p, [])
                if items:
                    unit_id = str(unwrap_gh(items[0]) or "").strip()
                if not unit_id:
                    unit_id = "__NO_UNIT_ID__"

            meta = _make_assembly_meta_payload(
                unit_id=unit_id,
                scope=scope,
                schema=schema,
                sub_name=sub_name,
                kv=kv,
            )
            # The meta payload itself must also be annotated so it
            # participates in further assembly levels (multi-level rule).
            meta2 = _annotate_payload(meta, sub_name, key_suffix, role)

            # Append to TAIL so downstream "Cull Index 0" patterns
            # still hit a real geometry payload, not the meta.
            new_branch_items.append(wrap_gh(meta2))
            added_meta = 1

            meta_props = cast(Dict[str, Any], meta2.get("props", {}) or {})
            logs.append(
                "  [DEBUG] Created AssemblyMeta: "
                f"path={p} unit_id={meta2.get('unit_id','')!r} "
                f"pset_overrides={meta_props.get('pset_overrides', {})!r} "
                f"assembly_path_depth={len(meta_props.get('assembly_path', []) or [])}"
            )

        # 4e. Write items into the output container (same branch path)
        if out_tree is not None:
            # Items must be added one-by-one; passing a list would insert
            # a single list-object as one leaf, breaking downstream iteration.
            _add_items_to_tree(out_tree, p, new_branch_items)
        else:
            out_list.append(new_branch_items)

        meta_cnt = _count_meta_in_items(new_branch_items)
        per_branch_meta[p] = meta_cnt
        logs.append(f"{p}: annotated={touched} added_meta={'Y' if added_meta else 'N'} meta_in_branch={meta_cnt}")

    out_any = out_tree if out_tree is not None else out_list

    # ── 5. Verification pass ────────────────────────────────────────────
    # Re-read the output to count categories — helps catch insertion bugs.
    output_cats: List[str] = []
    bd2, paths2 = to_branch_dict_any(out_any)
    for pp in paths2:
        for it in bd2.get(pp, []):
            raw = unwrap_gh(it)

            # Handle legacy case: branch accidentally contains one list-item
            if isinstance(raw, list):
                for it2 in raw:
                    raw2 = unwrap_gh(it2)
                    if isinstance(raw2, dict) and isinstance(raw2.get("category", None), str):
                        output_cats.append(raw2["category"])
            else:
                if isinstance(raw, dict) and isinstance(raw.get("category", None), str):
                    output_cats.append(raw["category"])

    cat_counts = Counter(output_cats)
    logs.append(f"[DEBUG] Output verification: total={len(output_cats)} categories={dict(cat_counts)}")
    logs.append(f"[DEBUG] Per-branch meta counts: {per_branch_meta}")

    msg = (
        "assembly: applied. "
        "Rule: stable outer wrap (prepend) on props['assembly_path']. "
        "Unit branches preserved (Strategy S1). "
        "Assembly override: emits AssemblyMeta payloads (category='__ASSEMBLY_META__') with props['pset_overrides']."
    )
    return out_any, msg + "\n" + "\n".join(logs)
