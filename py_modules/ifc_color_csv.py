# -*- coding: utf-8 -*-
"""
Viewer color mapping loader (CSV version).

Expected CSV format (UTF-8):
--------------------------------
Name,R,G,B
AL01,39,105,227
N64,158,98,109

- Name: lookup key (matches IFC element.Name)
- R,G,B: 0~255

Returns:
  mapping: Dict[str, (r,g,b)]  where r,g,b are floats 0~1
"""

from __future__ import annotations

import os
import csv
from typing import Any, Dict, Tuple

RGBF = Tuple[float, float, float]


def _clamp255(x: Any) -> int:
    try:
        v = int(float(x))
    except Exception:
        return 0
    return 0 if v < 0 else (255 if v > 255 else v)


def _rgb255_to_float(r: Any, g: Any, b: Any) -> RGBF:
    return (
        _clamp255(r) / 255.0,
        _clamp255(g) / 255.0,
        _clamp255(b) / 255.0,
    )


def load_color_map_csv_with_diag(csv_path: str):
    """
    Returns: (mapping: Dict[str, RGBF], diag_message: str)
    """
    if not csv_path:
        return {}, "Color CSV path is empty."

    if not os.path.exists(csv_path):
        return {}, f"Color CSV not found: {csv_path}"

    out: Dict[str, RGBF] = {}
    row_count = 0

    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row_count += 1
                name = (row.get("Name") or "").strip()
                if not name:
                    continue

                r = row.get("R")
                g = row.get("G")
                b = row.get("B")

                out[name] = _rgb255_to_float(r, g, b)

        return out, f"Loaded {len(out)} colors from {csv_path} (rows scanned: {row_count})."

    except Exception as e:
        return {}, f"Failed reading CSV: {csv_path} err={repr(e)}"


def resolve_view_color(key: Any, mapping: Dict[str, RGBF], default_rgb: RGBF) -> RGBF:
    k = str(key or "").strip()
    if not k:
        return default_rgb
    return mapping.get(k, default_rgb)
