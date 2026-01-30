# utils/path_utils.py
# Path normalization utilities.

from __future__ import annotations

import os
from typing import Optional, Any


def normalize_outpath(out_path: Any, storey_name: str) -> str:
    p = str(out_path).strip().strip('"')
    if p == "":
        p = "."
    ext = os.path.splitext(p)[1]

    if os.path.isdir(p) or ext == "":
        out_dir = p
        if not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)
        return os.path.join(out_dir, f"{storey_name}_multi_units.ifc")

    out_dir = os.path.dirname(p)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    root, ext2 = os.path.splitext(p)
    return (root + ".ifc") if ext2.lower() != ".ifc" else p
