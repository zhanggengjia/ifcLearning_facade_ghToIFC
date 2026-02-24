# utils/exporter_utils.py
# -*- coding: utf-8 -*-
"""
utils/exporter_utils.py

ONLY ADDITIVE helper module for ifc_exporter.py.

Constraints / intent
--------------------
- Do NOT modify existing utils modules (gh_utils, payload_utils, path_utils, etc.).
- Keep all rules that were previously embedded in exporter in one place, so exporter stays small.
- Enforce strict contract:
    * UNIT payload MUST have top-level payload["unit_id"]
    * props["assembly_path"] supports:
        - list[dict] levels: {"name": "...", "key": "...", optional "role": "..."}
        - list[str] levels: "trimAssembly", "frameAssembly|frameRole"
        - legacy props["assembly"] dict: {"sub_name": "...", "sub_key": "..."}
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from ifc_types import Payload
from utils.gh_utils import iter_payloads, unwrap_gh
from utils.payload_utils import unwrap_payload, normalize_payload_inplace, ensure_props


# ---------------------------------------------------------------------
# Payload collection / grouping
# ---------------------------------------------------------------------

def _infer_scope_from_domain(domain: int) -> Optional[str]:
    """
    Infer scope from GH DataTree domain path.

    Domain 0 → "UNIT"
    Domain 1 → "NON_UNIT"
    Domain 2 → "CONTEXT" (context reference objects: beams, slabs, structural refs)
    """
    if domain == 0:
        return "UNIT"
    elif domain == 1:
        return "NON_UNIT"
    elif domain == 2:
        return "CONTEXT"
    else:
        return None


def collect_payloads(MatData: Any, *, log_fn: Any = None) -> Tuple[List[Payload], int]:
    """
    Collect payloads from MatData, preserving domain path information.

    Priority for scope determination:
    1. Explicit payload.props.scope (if valid)
    2. Inferred from domain path (if DataTree)
    3. Default to "UNIT" with warning

    Returns (payloads, ignored_non_payload_count).
    """
    from utils.gh_utils import is_tree_like, to_branch_dict_any

    def log(msg: str) -> None:
        if log_fn is not None:
            log_fn(msg)

    payloads: List[Payload] = []
    bad = 0

    # Check if input is a DataTree with domain paths
    if is_tree_like(MatData):
        branches, paths = to_branch_dict_any(MatData)

        for path_str in paths:
            # Parse domain from path (e.g., "{0;1}" → domain=0)
            domain = 0
            try:
                if path_str.startswith("{") and ";" in path_str:
                    domain = int(path_str[1:].split(";")[0])
            except Exception:
                domain = 0

            inferred_scope = _infer_scope_from_domain(domain)

            for item in branches.get(path_str, []):
                raw = unwrap_gh(item)
                p = unwrap_payload(raw)
                if p is None:
                    bad += 1
                    continue

                normalize_payload_inplace(
                    p,
                    default_schema=int(p.get("schema", 1) or 1),
                    default_category=str(p.get("category", "Unspecified") or "Unspecified"),
                )
                props = ensure_props(p)

                # Scope determination with priority.
                # Domain 2 (CONTEXT) is authoritative: always overrides props.scope.
                # This is necessary because nonUnit builder writes scope="NON_UNIT",
                # but Entwine into {2;...} marks these as context reference objects.
                if inferred_scope == "CONTEXT":
                    final_scope = "CONTEXT"
                    props["scope"] = final_scope
                else:
                    explicit_scope = props.get("scope")
                    if explicit_scope and str(explicit_scope).strip().upper() in ("UNIT", "NON_UNIT"):
                        # Trust explicit scope
                        final_scope = str(explicit_scope).strip().upper()
                        final_scope = "NON_UNIT" if final_scope == "NON_UNIT" else "UNIT"

                        # Warn if domain mismatch
                        if inferred_scope and inferred_scope != final_scope:
                            log(
                                f"[WARN] Domain-scope mismatch: payload in {{{domain};...}} "
                                f"but scope='{final_scope}'. Trusting explicit scope. "
                                f"name={p.get('name','')!r}\n"
                            )
                    elif inferred_scope:
                        # Use inferred scope
                        final_scope = inferred_scope
                        props["scope"] = final_scope
                    else:
                        log(
                            f"[WARN] Payload in domain {domain} missing explicit scope; "
                            f"defaulting to 'UNIT'. name={p.get('name','')!r}\n"
                        )
                        final_scope = "UNIT"
                        props["scope"] = final_scope

                payloads.append(p)
    else:
        # Fallback: list input (no domain inference)
        raw_items = list(iter_payloads(MatData))

        for it in raw_items:
            raw = unwrap_gh(it)
            p = unwrap_payload(raw)
            if p is None:
                bad += 1
                continue

            normalize_payload_inplace(
                p,
                default_schema=int(p.get("schema", 1) or 1),
                default_category=str(p.get("category", "Unspecified") or "Unspecified"),
            )
            props = ensure_props(p)

            # No domain inference for list input
            if not props.get("scope"):
                log(
                    f"[WARN] Flattened list input: payload missing scope; "
                    f"defaulting to 'UNIT'. name={p.get('name','')!r}\n"
                )
                props["scope"] = "UNIT"

            payloads.append(p)

    return payloads, bad


def get_scope(p: Payload) -> str:
    props = ensure_props(p)
    scope = props.get("scope", "UNIT")
    s = str(scope).strip().upper() if scope is not None else "UNIT"
    if s == "NON_UNIT":
        return "NON_UNIT"
    if s == "CONTEXT":
        return "CONTEXT"
    return "UNIT"


def get_container_id(p: Payload, *, log_fn: Any = None) -> str:
    """
    Get container_id based on scope.

    For UNIT: STRICT top-level payload["unit_id"] only.
    For NON_UNIT: props.container_id OR default "__NON_UNIT__".
    For CONTEXT: props.container_id OR default "__CONTEXT__".

    Returns container_id string.
    Raises ValueError if UNIT payload missing unit_id.
    """
    def log(msg: str) -> None:
        if log_fn is not None:
            log_fn(msg)

    props = ensure_props(p)
    scope = get_scope(p)

    if scope == "NON_UNIT":
        cid = props.get("container_id")
        if cid is not None and str(cid).strip():
            return str(cid).strip()
        log(
            f"[WARN] NON_UNIT payload missing container_id; using default '__NON_UNIT__'. "
            f"name={p.get('name','')!r}\n"
        )
        return "__NON_UNIT__"

    if scope == "CONTEXT":
        cid = props.get("container_id")
        if cid is not None and str(cid).strip():
            return str(cid).strip()
        return "__CONTEXT__"

    # UNIT strict contract
    uid = p.get("unit_id", None)
    if uid is None or str(uid).strip() == "":
        raise ValueError(
            f"UNIT payload missing top-level 'unit_id'. (Strict spec; no props fallback) "
            f"name={p.get('name','')!r}"
        )
    return str(uid).strip()



# ---------------------------------------------------------------------
# Scope / kind helpers
# ---------------------------------------------------------------------

def get_kind(p: Payload) -> str:
    """Return element semantic kind.

    Allowed (normalized): "Part" | "Bulk".
    Defaults to "Part" if missing/unknown.
    """
    props = ensure_props(p)
    k = props.get("kind", "Part")
    s = str(k).strip().lower() if k is not None else "part"
    return "Bulk" if s == "bulk" else "Part"


def build_psets_for_payload(
    p: Payload,
    *,
    scope: str,
    kind: str,
) -> List[Tuple[str, Dict[str, Any]]]:
    """Build core Psets for an element based on (scope, kind, props).

    This keeps exporter small: exporter only iterates the returned psets.

    Notes:
    - `scope` is container ownership: UNIT | NON_UNIT
    - `kind` is element semantics: Part | Bulk
    """
    props = ensure_props(p)
    cat = str(p.get("category", "Unspecified") or "Unspecified")
    unit_id = str(p.get("unit_id", "") or "")

    dims = props.get("dims", {}) if isinstance(props.get("dims"), dict) else {}
    material = props.get("material", {}) if isinstance(props.get("material"), dict) else {}
    finish = props.get("finish", {}) if isinstance(props.get("finish"), dict) else {}

    part_no = props.get("part_no")
    bulk_code = props.get("bulk_code")
    element_code = props.get("element_code")
    src_guid = props.get("source_guid")

    # Identity (always)
    out: List[Tuple[str, Dict[str, Any]]] = []
    out.append((
        "Pset_CWIdentity",
        {
            "Scope": scope,
            "UnitId": unit_id,
            "ElementCode": element_code,
            "PartNo": part_no,
            "Category": cat,
            "SourceGuid": src_guid,
        },
    ))

    # Kind-specific
    if kind == "Bulk":
        out.append((
            "Pset_Bulk",
            {
                "BulkCode": bulk_code or element_code or str(p.get("name", "") or ""),
                "Quantity": props.get("quantity"),
                "Area_m2": props.get("area_m2"),
                "Length_m": props.get("length_m"),
                "InstallLocation": props.get("install_location"),
            },
        ))
    else:
        out.append((
            "Pset_Part",
            {
                "PartCode": part_no or element_code,
                "PartType": cat,
                "ProfileCode": part_no or element_code,
                "Material": material.get("name") if isinstance(material, dict) else None,
                "Finish": finish.get("type") if isinstance(finish, dict) else None,
                "Length": dims.get("L") if isinstance(dims, dict) else None,
            },
        ))

        out.append((
            "Pset_CWDimensions",
            {
                "Length_mm": dims.get("L"),
                "Width_mm": dims.get("W"),
                "Radius_mm": dims.get("R"),
            },
        ))
        out.append(("Pset_CWMaterial", {"MaterialName": material.get("name")}))
        out.append((
            "Pset_CWSurfaceFinish",
            {
                "FinishType": finish.get("type"),
                "FinishThickness_um": finish.get("thickness_um"),
            },
        ))
        out.append(("Pset_CWAppearance", {"ColorCode": props.get("color_code")}))

    return out


# ---------------------------------------------------------------------------
# IfcElementQuantity helpers
# ---------------------------------------------------------------------------

# Maps type-prefix → (IfcEntity, attribute holding the value)
_QTO_PREFIX_MAP: Dict[str, Tuple[str, str]] = {
    "L": ("IfcQuantityLength", "LengthValue"),
    "A": ("IfcQuantityArea",   "AreaValue"),
    "C": ("IfcQuantityCount",  "CountValue"),
    "W": ("IfcQuantityWeight", "WeightValue"),
}


def parse_qto_for_product(
    qto_overrides: Any,
) -> List[Tuple[str, List[Tuple[str, str, str, float]]]]:
    """Parse qto_overrides into IFC-ready quantity data.

    Parameters
    ----------
    qto_overrides : dict
        Structure: {QtoName: {"L:N01": 2450.0, "C:M8": 4, ...}}

    Returns
    -------
    List of (qto_name, quantities) where quantities is a list of
    (ifc_entity_type, value_attr, qty_name, qty_value) tuples.

    Unknown prefixes and None / non-numeric values are silently skipped.

    Example
    -------
    parse_qto_for_product({"Qto_CWPart": {"L:N01": 2450.0, "C:M8": 4}})
    → [("Qto_CWPart", [
          ("IfcQuantityLength", "LengthValue", "N01",  2450.0),
          ("IfcQuantityCount",  "CountValue",  "M8",   4.0),
       ])]
    """
    result: List[Tuple[str, List[Tuple[str, str, str, float]]]] = []
    if not isinstance(qto_overrides, dict):
        return result

    for qto_name, kv in qto_overrides.items():
        if not isinstance(qto_name, str) or not qto_name.strip():
            continue
        if not isinstance(kv, dict):
            continue

        quantities: List[Tuple[str, str, str, float]] = []
        for raw_key, value in kv.items():
            if not isinstance(raw_key, str):
                continue
            prefix, _, qty_name = raw_key.partition(":")
            if not qty_name:
                continue
            entry = _QTO_PREFIX_MAP.get(prefix.upper())
            if not entry:
                continue  # unknown prefix → skip
            if value is None:
                continue
            try:
                qty_value = float(value)
            except (TypeError, ValueError):
                continue
            ifc_type, attr = entry
            quantities.append((ifc_type, attr, qty_name, qty_value))

        if quantities:
            result.append((qto_name.strip(), quantities))

    return result


def container_display_name(scope: str, cid: str) -> str:
    if scope == "NON_UNIT":
        return "NON_UNIT"
    if scope == "CONTEXT":
        return "CONTEXT"
    return f"Unit_{cid}"



def group_by_container(payloads: List[Payload], *, log_fn: Any = None) -> Dict[Tuple[str, str], List[Payload]]:
    """
    Group payloads by (scope, container_id).

    Raises ValueError if any UNIT payload is missing unit_id.
    """
    out: Dict[Tuple[str, str], List[Payload]] = {}
    for p in payloads:
        scope = get_scope(p)
        cid = get_container_id(p, log_fn=log_fn)
        out.setdefault((scope, cid), []).append(p)
    return out


# ---------------------------------------------------------------------
# Assembly path parsing
# ---------------------------------------------------------------------

def parse_assembly_path(p: Payload) -> List[Dict[str, str]]:
    """
    Normalize assembly path into list[{"name":..., "key":..., optional "role":...}].
    """
    props = ensure_props(p)
    ap = props.get("assembly_path")
    out: List[Dict[str, str]] = []

    if isinstance(ap, list):
        for lvl in ap:
            # dict form
            if isinstance(lvl, dict):
                nm = str(lvl.get("name", "")).strip()
                ky = str(lvl.get("key", "")).strip()
                if not nm and not ky:
                    continue
                if not ky:
                    ky = nm
                if not nm:
                    nm = ky
                d: Dict[str, str] = {"name": nm, "key": ky}
                rl = lvl.get("role")
                if rl is not None:
                    rr = str(rl).strip()
                    if rr:
                        d["role"] = rr
                out.append(d)
                continue

            # string form
            if isinstance(lvl, str):
                ky = lvl.strip()
                if not ky:
                    continue
                if "|" in ky:
                    nm, suf = ky.split("|", 1)
                    nm = (nm or ky).strip()
                    suf = suf.strip()
                    d = {"name": nm, "key": ky}
                    if suf:
                        d["role"] = suf
                    out.append(d)
                else:
                    out.append({"name": ky, "key": ky})
                continue

        return out

    # legacy single-level
    asm = props.get("assembly")
    if isinstance(asm, dict):
        sub_key = str(asm.get("sub_key", "")).strip()
        sub_name = str(asm.get("sub_name", "")).strip()
        if sub_key:
            if not sub_name:
                sub_name = sub_key
            return [{"name": sub_name, "key": sub_key}]

    return []


# ---------------------------------------------------------------------
# Assembly node creation (per-container cache)
# ---------------------------------------------------------------------

def ensure_assembly_chain(
    *,
    ifc_run: Any,
    model: Any,
    container_elem: Any,
    scope: str,
    container_id: str,
    assembly_path: List[Dict[str, str]],
    node_cache: Dict[Tuple[int, str], Any],
    add_pset: Any,
) -> Any:
    """
    Ensure nested IfcElementAssembly nodes exist under container_elem,
    following assembly_path. Returns deepest node.

    node_cache key = (id(parent), level_key)
    """
    parent = container_elem
    depth = 0

    for lvl in assembly_path:
        depth += 1
        nm = str(lvl.get("name", "")).strip()
        ky = str(lvl.get("key", "")).strip()
        if not nm and not ky:
            continue
        if not ky:
            ky = nm
        if not nm:
            nm = ky

        cache_key = (id(parent), ky)
        if cache_key in node_cache:
            parent = node_cache[cache_key]
            continue

        asm = ifc_run("root.create_entity", model, ifc_class="IfcElementAssembly", name=nm)
        ifc_run("aggregate.assign_object", model, products=[asm], relating_object=parent)

        # Small, low-noise psets for traceability.
        ps = {"Scope": scope, "ContainerId": container_id, "Level": int(depth), "Name": nm}
        role = lvl.get("role")
        if role:
            ps["ChildRole"] = str(role)
        if ky != nm:
            ps["Key"] = ky
        add_pset(asm, "Pset_AssemblyNode", ps)

        add_pset(asm, "Pset_Assembly", {
            "AssemblyCode": ky,
            "AssemblyType": nm,
            "InstallType": None,
            "ChildRole": str(role) if role else None,
        })

        node_cache[cache_key] = asm
        parent = asm

    return parent


# ---------------------------------------------------------------------
# Stable Source GUID assignment (JSON-backed)
#
# Goal
# - Builder may output props['source_guid'] = None.
# - Exporter assigns a stable GUID per (unit_id, part_name, bbox_center).
# - The GUIDs are persisted to guid_file.json (next to IFC output by default).
#
# Constraints
# - Keep this module additive; exporter can opt-in without changing other flows.
# - Rhino dependency is imported lazily inside functions.
# ---------------------------------------------------------------------

import os
import json
import time
import uuid
from contextlib import contextmanager


def resolve_guid_json_path(resolved_out_path: Any, *, filename: str = "guid_file.json") -> str:
    """
    Determine where to store guid_file.json based on resolved_out_path.

    Logic:
    - If resolved_out_path endswith '.ifc' (case-insensitive): store JSON in same folder.
    - Else: treat resolved_out_path as a directory path, store JSON inside it.
    - If path is empty: fallback to cwd.
    """
    p = str(resolved_out_path or "").strip().strip('"').strip("'")

    if not p:
        base_dir = os.getcwd()
        return os.path.join(base_dir, filename)

    p_lower = p.lower()

    # Case A: IFC file path
    if p_lower.endswith(".ifc"):
        base_dir = os.path.dirname(p)
        if not base_dir:
            base_dir = os.getcwd()
        return os.path.join(base_dir, filename)

    # Case B: treat as directory path
    base_dir = p

    # Make sure directory exists (safe to call; exporter will already have permission context)
    try:
        os.makedirs(base_dir, exist_ok=True)
    except Exception:
        # If cannot create, fallback to cwd to avoid crashing exporter
        base_dir = os.getcwd()

    return os.path.join(base_dir, filename)


def _point_key_xyz(x: float, y: float, z: float, *, decimals: int = 3) -> str:
    """Stable fixed-decimal key."""
    x = round(float(x), decimals)
    y = round(float(y), decimals)
    z = round(float(z), decimals)
    fmt = "{:0." + str(decimals) + "f}"
    return ",".join([fmt.format(x), fmt.format(y), fmt.format(z)])


def bbox_center_key(geo: Any, *, decimals: int = 3) -> str:
    """Compute bbox center key from Rhino geometry. Raises on invalid bbox."""
    if geo is None:
        raise ValueError("bbox_center_key: geo is None")

    # Lazy import to avoid breaking non-Rhino environments.
    import Rhino.Geometry as rg  # type: ignore

    bb = None
    try:
        if hasattr(geo, "GetBoundingBox"):
            bb = geo.GetBoundingBox(True)
    except Exception:
        bb = None

    if bb is None or (hasattr(bb, "IsValid") and not bb.IsValid):
        try:
            brep = rg.Brep.TryConvertBrep(geo)
            if brep:
                bb = brep.GetBoundingBox(True) # type: ignore
        except Exception:
            bb = None

    if bb is None or (hasattr(bb, "IsValid") and not bb.IsValid): # type: ignore
        raise ValueError(f"bbox_center_key: cannot compute bounding box. geo_type={type(geo).__name__}")

    c = bb.Center # type: ignore
    return _point_key_xyz(c.X, c.Y, c.Z, decimals=decimals)


def get_unit_id_for_guid(p: Payload) -> str:
    """
    Get unit/container key for GUID keying.

    For UNIT: uses payload['unit_id'] (STRICT)
    For NON_UNIT: uses container_id or "__NON_UNIT__"
    """
    scope = get_scope(p)

    if scope == "NON_UNIT":
        # Use container_id for NON_UNIT payloads
        props = ensure_props(p)
        cid = props.get("container_id")
        if cid is not None and str(cid).strip():
            return str(cid).strip()
        return "__NON_UNIT__"

    # UNIT strict contract
    uid = p.get("unit_id", None)
    if uid is None or str(uid).strip() == "":
        raise ValueError(
            f"GUID assignment for UNIT payload requires top-level unit_id. "
            f"name={p.get('name','')!r}"
        )
    return str(uid).strip()



def _load_json_dict(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        # Treat as empty if corrupted/partial.
        return {}


def _atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    folder = os.path.dirname(path)
    if folder and not os.path.exists(folder):
        os.makedirs(folder, exist_ok=True)

    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _acquire_lock(lock_path: str, timeout_s: float = 0.4, poll_s: float = 0.02) -> bool:
    t0 = time.time()
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return True
        except Exception:
            if (time.time() - t0) >= timeout_s:
                return False
            time.sleep(poll_s)


def _release_lock(lock_path: str) -> None:
    try:
        if os.path.exists(lock_path):
            os.remove(lock_path)
    except Exception:
        pass


@contextmanager
def locked_guid_db(json_path: str, *, timeout_s: float = 0.4) -> Any:
    """Context manager yielding a mutable dict db and persisting on exit."""
    lock_path = json_path + ".lock"
    got = _acquire_lock(lock_path, timeout_s=timeout_s)
    db = _load_json_dict(json_path)
    try:
        yield db
    finally:
        try:
            _atomic_write_json(json_path, db)
        finally:
            if got:
                _release_lock(lock_path)


def guid_db_get_or_create(
    db: Dict[str, Any],
    *,
    storey_name: str,
    unit_key: str,
    part_name: str,
    center_key: str,
) -> str:
    """
    Schema:
      db[storey_name][unit_key][part_name][center_key] = guid_str

    where:
      - storey_name e.g. "N02F"
      - unit_key    e.g. "__NON_UNIT__" or a real unit_id
    """
    s = str(storey_name or "").strip() or "__STOREY__"
    ukey = str(unit_key or "").strip() or "__UNIT__"
    pname = str(part_name or "").strip() or "Unnamed"
    ckey = str(center_key or "").strip() or "0.000,0.000,0.000"

    storey_dict = db.get(s)
    if not isinstance(storey_dict, dict):
        storey_dict = {}
        db[s] = storey_dict

    unit_dict = storey_dict.get(ukey)
    if not isinstance(unit_dict, dict):
        unit_dict = {}
        storey_dict[ukey] = unit_dict

    name_dict = unit_dict.get(pname)
    if not isinstance(name_dict, dict):
        name_dict = {}
        unit_dict[pname] = name_dict

    existing = name_dict.get(ckey)
    if isinstance(existing, str) and existing.strip():
        return existing.strip()

    g = str(uuid.uuid4())
    name_dict[ckey] = g
    return g



def ensure_source_guid_from_json_inplace(
    p: Payload,
    db: Dict[str, Any],
    *,
    storey_name: str,
    decimals: int = 3,
) -> str:
    """
    If props['source_guid'] is missing/empty, compute and assign stable guid.

    Key structure:
      storey_name -> unit_key -> part_name -> bbox_center

    Where unit_key is:
      - UNIT: payload["unit_id"]
      - NON_UNIT: props.container_id or "__NON_UNIT__"
    """
    props = ensure_props(p)

    cur = props.get("source_guid")
    if isinstance(cur, str) and cur.strip():
        return cur.strip()

    # Get unit/container key for GUID keying
    try:
        unit_key = get_unit_id_for_guid(p)
    except Exception:
        # Fallback for safety (shouldn't happen with proper validation)
        unit_key = "__NON_UNIT__"

    part_name = str(p.get("name", "") or "").strip() or "Unnamed"

    geo = p.get("geo", None)
    ckey = bbox_center_key(geo, decimals=decimals)

    guid_str = guid_db_get_or_create(
        db,
        storey_name=storey_name,
        unit_key=unit_key,
        part_name=part_name,
        center_key=ckey,
    )

    props["source_guid"] = guid_str
    return guid_str


