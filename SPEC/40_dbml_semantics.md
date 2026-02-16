# Purpose

Provide semantic truth model (DBML) for multi-level assemblies and roles.

# Conceptual model

- Spatial: Project > Building > Storey
- Element hierarchy:
  Unit (hoistable) > Sub-Assemblies > Parts/Bulk
- Composition relation: ElementRel(relType="AGGREGATES")

# Element.kind (control logic classification)

- Unit | Assembly | Part | Bulk

# childRole rules (MUST)

childRole is parent-relative and must distinguish:

- Unit -> Sub-assembly roles:
  - SUB_FRAME | SUB_TRIM_PANEL | SUB_BULK_PACK
- Assembly -> Component roles:
  - FRAME_MEMBER | TRIM_MEMBER | TRIM_FIXING | BULK_ITEM
- Fallback: GENERIC

# Pset intent

- Pset_Unit for Unit
- Pset_Part for Part
- Pset_Bulk for Bulk
- Pset_Assembly recommended for Assembly (to avoid polluting Unit/Part/Bulk psets)

# Mapping expectation (future alignment)

- payload.props.kind should map cleanly to Element.kind
- payload.props.assembly_path should map cleanly to ElementRel aggregates chain
