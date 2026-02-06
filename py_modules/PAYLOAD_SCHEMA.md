# IFC Payload Schema (Curtain Wall Pipeline)

This document defines the canonical payload structure used between
Grasshopper builders and the IFC exporter.

Two orthogonal axes:

- scope → container ownership
- kind → element semantic type

They must NOT be mixed.

---

# 1. Payload Root Structure

Each payload is a dict:

{
"schema": int,
"unit_id": str,
"geo": Rhino geometry,
"name": str,
"category": str,
"props": dict
}

---

# 2. Scope (container ownership)

props.scope determines where the element belongs.

Allowed values:

- "UNIT"
- "NON_UNIT"

Meaning:

UNIT
→ belongs to a façade unit container

NON_UNIT
→ belongs to loose/non-unit container
(trim, loose ceiling, loose metal etc)

⚠ scope MUST NOT describe element type (bulk/part)

---

# 3. Kind (element semantic type)

props.kind determines element semantic meaning.

Allowed values:

- "Part"
- "Bulk"

Meaning:

Part
→ physical member
→ extrusion, bracket, panel etc

Bulk
→ aggregated material or loose component
→ ceiling board, trim length, sheet, etc

---

# 4. Common Props (ALL elements)

Required or commonly present:

props.scope : "UNIT" | "NON_UNIT"
props.kind : "Part" | "Bulk"
props.source_guid : stable guid (assigned in exporter)
props.element_code : unified identity code (part_no or bulk_code)
props.color_code : optional viewer color

---

# 5. Part Props Schema

Used when:
props.kind == "Part"

Recommended structure:

props.part_no : str
props.dims : { L, W, R }
props.material : { name }
props.finish : { type, thickness_um }
props.ifc_class_hint : optional IFC class hint
props.source_guid : assigned by exporter

Example:

"props": {
"scope": "UNIT",
"kind": "Part",
"part_no": "N01",
"dims": { "L": 1200 },
"material": { "name": "Aluminum" },
"finish": { "type": "Anodized" },
"color_code": "AL01",
"source_guid": null
}

---

# 6. Bulk Props Schema

Used when:
props.kind == "Bulk"

Recommended structure:

props.bulk_code : str
props.quantity : optional
props.area_m2 : optional
props.length_m : optional
props.install_location : optional
props.source_guid : assigned by exporter
props.color_code : optional

Example:

"props": {
"scope": "NON_UNIT",
"kind": "Bulk",
"bulk_code": "AL01_CEILING",
"area_m2": 54.2,
"source_guid": null
}

---

# 7. Identity Rules

Stable GUID is determined by:

storey_name +
unit_id or "**NON_UNIT**" +
element_code +
bbox_center

Exporter assigns GUID and writes to:
guid_file.json

Builders must NOT generate GUID.

---

# 8. IFC Mapping Rules

Exporter determines Psets from:

(scope, kind, props)

Not from builder.

Mapping:

Kind=Part → Pset_Part
Kind=Bulk → Pset_Bulk

Scope=UNIT → Unit container
Scope=NON_UNIT → NonUnit container

---

# 9. Design Philosophy

Payload = neutral data layer
Exporter = IFC policy layer

Never mix IFC logic inside builder.
