# utils/exporter_utils.py
# -*- coding: utf-8 -*-
"""
utils/exporter_utils.py

ONLY ADDITIVE helper module for ifc_exporter.py.

Constraints / intent
--------------------
- Do NOT modify existing utils modules (gh_utils, payload_utils, path_utils, etc.).
- Keep all rules that were previously embedded in exporter in one place, so exporter stays small.
- Provide robust compatibility:
    * payload["unit_id"] or payload["props"]["unit_id"]
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

def collect_payloads(MatData: Any) -> Tuple[List[Payload], int]:
    """
    Flatten MatData and return only valid payload dicts (normalized).
    Returns (payloads, ignored_non_payload_count).
    """
    raw_items = list(iter_payloads(MatData))
    payloads: List[Payload] = []
    bad = 0

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
        ensure_props(p)
        payloads.append(p)

    return payloads, bad


def get_scope(p: Payload) -> str:
    props = ensure_props(p)
    scope = props.get("scope", "UNIT")
    s = str(scope).strip().upper() if scope is not None else "UNIT"
    return "NON_UNIT" if s == "NON_UNIT" else "UNIT"


def get_container_id(p: Payload) -> str:
    """
    For UNIT: prefer payload["unit_id"], fallback props["unit_id"].
    For NON_UNIT: use props["container_id"] (default "DEFAULT").
    """
    props = ensure_props(p)
    scope = get_scope(p)

    # --- Scheme A: single NON_UNIT container ---
    if scope == "NON_UNIT":
        return "__NON_UNIT__"

    # --- UNIT behavior unchanged ---
    uid = p.get("unit_id", None)
    if uid is None or str(uid).strip() == "":
        uid = props.get("unit_id", None)

    if uid is None or str(uid).strip() == "":
        raise ValueError("UNIT payload missing 'unit_id' (top-level or props['unit_id']).")

    return str(uid).strip()


def container_display_name(scope: str, cid: str) -> str:
    if scope == "NON_UNIT":
        return "NON_UNIT"
    return f"Unit_{cid}"



def group_by_container(payloads: List[Payload]) -> Dict[Tuple[str, str], List[Payload]]:
    out: Dict[Tuple[str, str], List[Payload]] = {}
    for p in payloads:
        scope = get_scope(p)
        cid = get_container_id(p)
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
