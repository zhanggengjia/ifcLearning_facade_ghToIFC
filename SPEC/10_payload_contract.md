# Purpose

Define the canonical Payload / MatData contract shared across builder / assembly / exporter.

# Payload (canonical)

Payload is a dict-like object with stable core keys + props.

## Stable core keys (MUST)

- schema: int # internal payload schema version (NOT IFC schema)
- unit_id: str # unit code / container key
- geo: Any # Rhino geometry (or None for meta payload)
- name: str # element name
- category: str # e.g. Vertical/Horizontal/... or special meta categories
- props: dict[str, Any] # everything evolving goes here

## Rule: "stable core" vs "props"

- Builders MUST keep: schema, unit_id, geo, name, category at top-level.
- Builders MUST put evolving fields into props (NOT new top-level keys).

# MatData shape

MatData may be:

- GH DataTree of wrapped Payload leaves (preferred)
- or list/iterable of Payload leaves (fallback)

## Tree invariants (MUST)

- Preserve unit branch boundaries (Strategy S1): output paths identical to input paths.
- Leaves may be wrapped/unwrapped by GH wrappers.

# Semantic fields in props (common)

- scope: "UNIT" | "NON_UNIT" | "CONTEXT"
  - "UNIT": unit-level elements (curtain wall units, etc.)
  - "NON_UNIT": general non-unit elements
  - "CONTEXT": context reference objects (beams, slabs, structural refs)
- kind: "Part" | "Bulk" | "AssemblyMeta" (etc.)
- ifc_class_hint: optional IFC entity hint
- pset_overrides: dict[pset_name -> dict[k->v]]
- assembly_path: list[dict] # preferred canonical format
- groups: list[str] # optional list of IFC group names this element belongs to

## Special payloads

### AssemblyMeta payload (canonical constant)

Assembly metadata payload MUST use the exact category string:

`"__ASSEMBLY_META__"`

This is a canonical string constant (NOT markdown formatting).

Rules:

- category MUST equal `"__ASSEMBLY_META__"`
- geo MUST be None (or tiny dummy mesh for GH compatibility)
- props.pset_overrides carries metadata intended for assembly nodes
  - Pset name is determined by scope:
    - UNIT → Pset_Unit
    - NON_UNIT → Pset_NonUnit
    - CONTEXT → Pset_Context
    - Others → Pset_Assembly (fallback)
- No geometric IFC element should be created for this payload
- Used only to inject metadata onto assembly nodes

Important:
Do NOT write this as markdown bold or without quotes.
The exact string must be used for programmatic comparison.
