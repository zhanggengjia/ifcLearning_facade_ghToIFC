# ifc_class_map.py
# Category -> IFC class mapping (domain policy)
# Edit this file when you add new categories.

from typing import Dict

DEFAULT_IFC_CLASS: str = "IfcBuildingElementProxy"

CATEGORY_TO_IFC: Dict[str, str] = {
    # façade members
    "vertical": "IfcMember",
    "horizontal": "IfcBeam",  # 想統一語義可改成 IfcMember

    # common future extensions (you can keep/remove as you like)
    "panel": "IfcPlate",
    "glass": "IfcPlate",
    "mullion": "IfcMember",
    "transom": "IfcMember",

    "bracket": "IfcDiscreteAccessory",
    "accessory": "IfcDiscreteAccessory",

    "fastener": "IfcMechanicalFastener",
    "bolt": "IfcMechanicalFastener",
    "screw": "IfcMechanicalFastener",
    "fitting": "IfcDiscreteAccessory",

    # structural/context elements (CONTEXT scope)
    "beam": "IfcBeam",
    "column": "IfcColumn",
    "slab": "IfcSlab",
    "wall": "IfcWall",
    "footing": "IfcFooting",
    "pile": "IfcPile",

}

def resolve_ifc_class_hint(category_value: str) -> str:
    """
    Normalize category string and map to IFC class name.
    Returns DEFAULT_IFC_CLASS when unknown.
    """
    cat = (category_value or "").strip().lower()
    return CATEGORY_TO_IFC.get(cat, DEFAULT_IFC_CLASS)
