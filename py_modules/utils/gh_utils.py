# utils/gh_utils.py
# Py3.9-safe utilities for Grasshopper/Rhino Python environments.
# Goals:
# - Accept GH DataTree / list / scalar inputs uniformly.
# - Provide safe unwrap/wrap helpers (GH_ObjectWrapper friendly).
# - Provide flatten iteration for "payload-like" containers without importing heavy IFC logic.

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union, cast

from ifc_types import AnyInput, BranchDict, GHDataTreeLike, PathStr

PathStr = str
BranchDict = Dict[PathStr, List[Any]]

# --- Soft GH imports (never hard-fail outside GH) ---
try:
    from Grasshopper.Kernel.Types import GH_ObjectWrapper  # type: ignore
except Exception:  # pragma: no cover
    GH_ObjectWrapper = None  # type: ignore


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

def is_datatree_like(obj: Any) -> bool:
    """Alias of is_tree_like for legacy call sites."""
    return is_tree_like(obj)

def unwrap_gh(x: Any) -> Any:
    """Unwrap GH_ObjectWrapper if available; otherwise return as-is."""
    if GH_ObjectWrapper is not None and isinstance(x, GH_ObjectWrapper):
        x = getattr(x, "Value", x)
    return x


def wrap_gh(x: Any) -> Any:
    """Wrap a Python object into GH_ObjectWrapper if available."""
    if GH_ObjectWrapper is not None:
        try:
            return GH_ObjectWrapper(x)
        except Exception:
            return x
    return x


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
    if is_datatree_like(x):
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
    *,
    allow_fallback: bool = False,
    fallback_path: PathStr = "{0}",
) -> List[Any]:
    """
    Get branch items by path.

    Parameters
    ----------
    branch_dict : Mapping[PathStr, List[Any]]
        GH-like branch dictionary, e.g. {"{0}": [...], "{1}": [...]}

    path : PathStr
        Target branch path.

    allow_fallback : bool
        - False (default): STRICT mode
            * Only return data if `path` exists.
            * Missing path => []  (recommended for Geo / Obj / existence data)
        - True: BROADCAST mode
            * If `path` missing, try `fallback_path`.
            * Used for label-like data (Category / UnitId / Role).

    fallback_path : PathStr
        Branch path used when broadcasting is enabled.
        Default is "{0}", matching common GH patterns.

    Returns
    -------
    List[Any]
        A COPY of the branch list (safe against in-place mutation).
    """
    if path in branch_dict:
        return list(branch_dict[path])

    if allow_fallback and fallback_path in branch_dict:
        return list(branch_dict[fallback_path])

    return []


def iter_payloads(obj: Any) -> List[Any]:
    """
    Flatten any GH/tree/list/scalar structure into a list of leaf items.

    Notes:
    - This returns *leaf objects* (possibly wrapped) without validating payload shape.
    - Exporter/assembly will call unwrap_gh + payload validation separately.
    """
    out: List[Any] = []

    def _walk(o: Any) -> None:
        o = unwrap_gh(o)
        if is_tree_like(o):
            bd, paths = to_branch_dict_any(o)
            for p in paths:
                for item in bd.get(p, []):
                    _walk(item)
            return
        if isinstance(o, list):
            for item in o:
                _walk(item)
            return
        out.append(o)

    _walk(obj)
    return out


def tname(x: Any) -> str:
    try:
        return x.GetType().FullName  # type: ignore[attr-defined]
    except Exception:
        try:
            return str(type(x))
        except Exception:
            return "<unknown-type>"


