# ifcLearning_facade_ghToIFC

A **Grasshopper → IFC** project for **façade / curtain wall workflows**.

Exports structured IFC4 files from Grasshopper using GHPython + ifcopenshell,
without relying on Revit. Supports unit-based assembly hierarchy, multi-scope
grouping, bulk items, and per-element property sets.

> **IFC output reference:** See [IFC_PROPERTY_SPEC.md](IFC_PROPERTY_SPEC.md)
> for the pset schema and IFC object types used in exported files.
> Intended for IFC viewers, QC reviewers, and coordination teams.

---

## Folder Structure

```
.
├─ README.md
├─ IFC_PROPERTY_SPEC.md        # IFC pset / object type specification (viewer reference)
├─ openshell_test_dbml_v3.gh   # Main Grasshopper file
│
├─ py_modules/                 # Python modules (loaded by GHPython components)
│  ├─ ifc_types.py             # Payload type definitions and core contracts
│  ├─ ifc_unit_builder.py      # Build UNIT-scope MatData from GH geometry
│  ├─ ifc_nonUnit_builder.py   # Build NON_UNIT-scope MatData
│  ├─ ifc_bulk_builder.py      # Build Bulk-kind MatData (fasteners, accessories)
│  ├─ ifc_assembly.py          # Annotate assembly hierarchy (assembly_path)
│  ├─ ifc_override.py          # Inject per-element property overrides
│  ├─ ifc_exporter.py          # Export IFC4 from MatData (mesh-based)
│  ├─ ifc_class_map.py         # Category → IFC class mapping table
│  ├─ ifc_color_csv.py         # Color code CSV utilities
│  ├─ PAYLOAD_SCHEMA.md        # Payload data contract (developer reference)
│  └─ utils/                   # Internal utilities
│     ├─ gh_utils.py           # GH DataTree / unwrap helpers
│     ├─ payload_utils.py      # Payload normalization
│     ├─ override_utils.py     # Override merging
│     ├─ assembly_path_utils.py
│     ├─ exporter_utils.py
│     └─ path_utils.py
│
├─ SPEC/                       # Architecture specifications (developer reference)
│  ├─ SPEC_INDEX.md            # Read this first — index and loading policy
│  ├─ 00_project_overview.md
│  ├─ 10_payload_contract.md   # Payload / MatData contract
│  ├─ 15_gh_workflow.md        # GH component wiring rules
│  ├─ 20_assembly_rules.md     # Assembly hierarchy rules
│  ├─ 30_exporter_pipeline.md  # IFC export pipeline
│  └─ 40_dbml_semantics.md     # Semantic model (DBML)
│
├─ ifc_test_file/              # IFC export outputs (not versioned)
├─ rhino_file/                 # Rhino source models (not versioned)
└─ reference_file/             # Reference documents
```

---

## Large Files

Large `.3dm` and `.ifc` files are **not stored in this repository**.

[Google Drive — Rhino models and exported IFC files](https://drive.google.com/drive/folders/1wDdWIqzuKG9pSJIgunSWJQMx7P8IkPxj)

---

## Workflow Overview

### Scopes

All exported elements belong to one of three scopes:

| Scope | Meaning |
|---|---|
| **UNIT** | Hoistable / shippable fabrication unit. Each unit is one `IfcElementAssembly` container. |
| **NON_UNIT** | Elements not bound to a unit (site-installed, misc.). Grouped by container code. |
| **CONTEXT** | Structural reference geometry (beams, slabs, embedded parts). Reference-only; not fabrication. |

### GH Pipeline

```
Builder(s) → [ifc_assembly] → [ifc_override] → Entwine → Exporter
```

- **Builders** (`ifc_unit_builder`, `ifc_nonUnit_builder`, `ifc_bulk_builder`):
  Convert GH geometry into `MatData` payloads with scope and kind tags.
- **ifc_assembly** (optional): Annotates multi-level assembly hierarchy via `props.assembly_path`.
  Apply sub-assembly components first, then the container-level assembly last.
- **ifc_override** (optional): Injects per-element property key/value overrides.
- **Entwine**: Routes payloads into domain branches `{0;...}` UNIT / `{1;...}` NON_UNIT / `{2;...}` CONTEXT.
- **ifc_exporter**: Writes the IFC4 file. Container names derive from `assembly_path[0]`.

### Element kinds

| Kind | Pset | Usage |
|---|---|---|
| **Part** | `Pset_Part` | Fabricated elements (mullions, panels, brackets, …) |
| **Bulk** | `Pset_Bulk` | Counted/measured items (fasteners, sealant, …) |

---

## Notes

- IFC output is mesh-based (ifcopenshell BREP via Rhino mesh)
- GUID stability is managed via `guid_file.json` — commit this file to preserve IFC GUIDs across exports
- This is a working project repository; `SPEC/` and `py_modules/PAYLOAD_SCHEMA.md` are the developer references
- For the IFC property schema visible in viewers, see [IFC_PROPERTY_SPEC.md](IFC_PROPERTY_SPEC.md)
