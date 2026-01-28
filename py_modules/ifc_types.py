# -*- coding: utf-8 -*-
"""
ifc_types.py

Shared type contracts for:
- ifc_builder.py  (build MatData payload)
- ifc_exporter.py (consume MatData payload)

Rule:
- Keep "stable core" keys at top-level (unit_id/name/geo/category/schema).
- Put everything evolving into `props`.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Protocol, Sequence, TypedDict, Union

# In Grasshopper, a DataTree branch has a "Path" like {0;1;2}. We store it as str.
PathStr = str

# Branch dictionary shape: { "{0;1}": [item, item, ...], ... }
BranchDict = Dict[PathStr, List[Any]]


class GHDataTreeLike(Protocol):
    """Minimal duck-typed protocol for a Grasshopper DataTree-like object."""
    BranchCount: int

    def Path(self, i: int) -> Any: ...
    def Branch(self, path: Any) -> Iterable[Any]: ...


# AnyInput = what GH wires might provide (tree / list / scalar)
AnyInput = Union[GHDataTreeLike, Sequence[Any], Any]


class Payload(TypedDict):
    """
    Payload contract shared with exporter.

    Stable core keys:
      - schema     : int (internal payload schema version, NOT IFC schema)
      - unit_id    : str
      - geo        : Any (Rhino geometry)
      - name       : str
      - category   : str
      - props      : Dict[str, Any] (everything else goes here)
    """
    schema: int
    unit_id: str
    geo: Any
    name: str
    category: str
    props: Dict[str, Any]
