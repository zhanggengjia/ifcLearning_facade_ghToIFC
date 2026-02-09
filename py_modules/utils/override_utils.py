# utils/override_utils.py
# Py3.9-safe helpers for "override" GH component and builders.

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from utils.gh_utils import unwrap_gh


DEFAULT_OVERRIDE_PSET = "Pset_Override"


def normalize_pset_overrides(
    override_obj: Any,
    *,
    default_pset: str = DEFAULT_OVERRIDE_PSET,
) -> Dict[str, Dict[str, Any]]:
    """Normalize the 3rd slot override object into a canonical structure.

    Canonical structure:
        { "PsetName": { "Key": value, ... }, ... }

    Accepted inputs:
    - None / empty -> {}
    - {"Pset_X": {"K": V}} -> returned as-is (shallow-copied)
    - {"K": V} -> treated as properties under default_pset
    - ("K", V) or ["K", V] -> treated as single property under default_pset
    - "K=V" (string) -> parsed and stored under default_pset
    """
    o = unwrap_gh(override_obj)
    if o is None:
        return {}

    # tuple/list pair
    if isinstance(o, (list, tuple)) and len(o) == 2 and isinstance(o[0], (str, bytes)):
        k = str(o[0]).strip()
        v = unwrap_gh(o[1])
        if not k:
            return {}
        return {default_pset: {k: v}}

    # string "k=v"
    if isinstance(o, str):
        s = o.strip()
        if not s:
            return {}
        if "=" in s:
            k, v = s.split("=", 1)
            k = k.strip()
            v = v.strip()
            if not k:
                return {}
            return {default_pset: {k: v}}
        # treat as key with empty value
        return {default_pset: {s: ""}}

    # dict
    if isinstance(o, dict):
        # Case 1: already {pset: {k:v}}
        if all(isinstance(v, dict) for v in o.values()) and any(
            isinstance(k, str) and k.lower().startswith("pset") for k in o.keys()
        ):
            out: Dict[str, Dict[str, Any]] = {}
            for pset_name, kv in o.items():
                if not isinstance(pset_name, str) or not pset_name.strip():
                    continue
                if not isinstance(kv, dict):
                    continue
                out[pset_name.strip()] = dict(kv)
            return out

        # Case 2: plain {k:v} -> default pset
        return {default_pset: dict(o)}

    return {}


def merge_pset_overrides(
    base: Optional[Dict[str, Dict[str, Any]]],
    extra: Any,
    *,
    default_pset: str = DEFAULT_OVERRIDE_PSET,
) -> Dict[str, Dict[str, Any]]:
    """Merge `extra` override object into `base` and return the merged dict."""
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(base, dict):
        for pset_name, kv in base.items():
            if isinstance(pset_name, str) and isinstance(kv, dict):
                out[pset_name] = dict(kv)

    extra_norm = normalize_pset_overrides(extra, default_pset=default_pset)
    for pset_name, kv in extra_norm.items():
        if pset_name not in out:
            out[pset_name] = {}
        for k, v in kv.items():
            if isinstance(k, str) and k.strip():
                out[pset_name][k.strip()] = v
    return out


def apply_overrides_to_props(
    props: Dict[str, Any],
    override_obj: Any,
    *,
    default_pset: str = DEFAULT_OVERRIDE_PSET,
) -> None:
    """In-place: ensure props['pset_overrides'] exists and merge override_obj."""
    if not isinstance(props, dict):
        return
    existing = props.get("pset_overrides")
    merged = merge_pset_overrides(existing if isinstance(existing, dict) else None, override_obj, default_pset=default_pset)
    if merged:
        props["pset_overrides"] = merged
