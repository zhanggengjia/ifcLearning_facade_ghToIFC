# Purpose

Grasshopper → IFC experimental project for façade / curtain wall workflows, exporting unit-based IFC without Revit.

# Current pipeline (observed)

GH → (builder) → MatData (Payload leaves) → (optional assembly) → exporter → IFC file.

# Scope

- IFC schema: IFC4
- Geometry policy: mesh-based export (simplified)
- Primary focus:
  - unit-level grouping
  - flexible GH geometry input
  - assembly hierarchy support

# Non-goals (for now)

- Perfect IFC authoring for all entity classes
- Full Revit interoperability
- High-fidelity BRep pipelines

# Key constraints

- Preserve GH DataTree branch boundaries for Unit (Strategy S1)
- Keep Payload "stable core keys" and push evolving fields into props
