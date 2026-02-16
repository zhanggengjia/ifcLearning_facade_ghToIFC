# GH Workflow Specification

(Grasshopper → Payload → IFC)

This document defines how Grasshopper components are used to construct valid payloads for the GH→IFC system.

This is a USER WORKFLOW SPEC (not internal code spec).

All GH components must follow these rules so that downstream assembly and exporter logic remains stable.

---

# 1. Overall pipeline

Typical workflow:

UnitBlock extraction
→ produce GH wrapper obj
→ Builder
→ (optional Override)
→ Assembly (repeatable)
→ Exporter

```
[Geometry]
↓
[Builder]
↓
[Override] (optional)
↓
[Assembly] (can repeat multiple times)
↓
[Exporter]
```

Multi-level assembly is achieved by chaining multiple Assembly components.

---

# 2. GH wrapper object format (CRITICAL)

Initial extracted object format:

```
[Geometry, PartName]
```

Where:

- Geometry = Rhino geometry (Brep/Mesh/etc)
- PartName = extrusion/profile name (string)

After override:

```
[Geometry, PartName, OverrideData]
```

OverrideData may contain key-value metadata for payload.props.

This wrapper is later converted into Payload inside builders.

---

# 3. DataTree invariants (MUST FOLLOW)

All components must preserve GH tree structure.

## Domain Path Convention (STRICT)

MatData MUST be a Grasshopper DataTree with domain-based paths to separate different scope types:

- **Domain 0**: `{0;...}` - UNIT branches
  - Each branch represents one unit
  - Branch structure preserved from input (Strategy S1)
  - Example: `{0;0}`, `{0;1}`, `{0;2}`, etc.

- **Domain 1**: `{1;...}` - NON_UNIT branches
  - Shared/common elements not belonging to specific units
  - Example: `{1;0}`, `{1;1}`, etc.

- **Domain 2**: `{2;...}` - BULK branches (future)
  - Bulk/mass elements
  - Not yet implemented in current workflow

## Scope Determination Priority

When routing payloads, use this priority order:

1. **First**: Check `payload.props.scope` if present and valid
2. **Second**: Infer from domain path if scope is missing
   - Domain 0 → scope = "UNIT"
   - Domain 1 → scope = "NON_UNIT"
   - Domain 2 → scope = "NON_UNIT" (BULK is a special case)
3. **Fallback**: Default to "UNIT" with warning if cannot determine

## General Rules

- **NO FLATTENING**: Do NOT flatten the DataTree before passing to exporter
  - Tree structure must be preserved
  - Domain separation is critical for correct grouping
- Never merge unit branches
- Output tree paths must match input tree paths
- Unit branch identity must remain stable

Exporter depends on stable tree paths and domain separation for container grouping.

---

# 4. Component Specifications

---

## 4.1 Override Component

File: `ifc_override.py`

### Purpose

Inject additional metadata into objects before building payload.

Used to add:

- custom properties
- override psets
- extra identity data

### Input

Obj [any][tree access]
→ GH wrapper `[Geometry, Name]`

Key [str][tree access]
Value [str][tree access]
→ key-value metadata

UnitId [str][tree access]

### Output

MatData
Log

### Behavior

Transforms wrapper into:

```
[Geometry, Name, override_data]
```

Override data will later populate payload.props.

Tree structure must remain unchanged.

---

## 4.2 Unit_Builder

File: `ifc_unit_builder.py`

### Purpose

Convert GH wrapper objects into UNIT payloads.

### Input

Obj [any][tree access]
Category [str][item access]
UnitId [str][tree access]

### Output

MatData
Log

### Behavior

Creates payload with:

```
schema
unit_id
geo
name
category
props
```

scope must be:

```
UNIT
```

UnitId must exist at top-level payload["unit_id"].

---

## 4.3 NonUnit*Builder *(reserved / WIP)\_

File: `ifc_nonUnit_builder.py`

### Purpose

Create NON_UNIT payloads for:

- trims
- loose parts
- accessories

### Input

Obj [any][tree access]
Category [str][item access]
Scope [str][item access]
UnitId [str][tree access]

### Output

MatData
Log

### Notes

Not fully active yet.
Reserved for future NON_UNIT workflows.

---

## 4.4 Bulk_Builder

File: `ifc_bulk_builder.py`

### Purpose

Create bulk material payloads.

Used for:

- screws
- sealants
- accessories
- non-geometric items

### Input

Obj [any][tree access]
Category [str][item access]

### Output

MatData
Log

### Behavior

Creates payload:

```
scope = NON_UNIT
kind = Bulk
geo may be None
```

---

## 4.5 Assembly Component (CRITICAL)

File: `ifc_assembly.py`

### Purpose

Create hierarchical IFC assembly structure.

Supports multi-level nesting via chaining.

### Input

MatData [any][tree access]
Name [str][item access]
KeySuffix [str][item access]
Role [str][item access]
Key [str][tree access]
Value [str][tree access]
UnitId [str][tree access]

### Output

MatData
Log

### Core behavior

Each Assembly call:

- prepends one level into payload.props["assembly_path"]
- does NOT change tree paths
- preserves branch identity

### Multi-level assembly

Multiple assembly components can be chained:

```
Builder
→ Assembly(Frame)
→ Assembly(UnitizedFrame)
→ Assembly(System)
```

Result:

```
assembly_path = [
 {name:"System"},
 {name:"UnitizedFrame"},
 {name:"Frame"}
]
```

Unlimited nesting depth allowed.

---

## 4.6 Assembly override injection

If Key/Value provided:

Assembly component generates an AssemblyMeta payload:

category = `"__ASSEMBLY_META__"`
geo = None

props.pset_overrides carries KV data.

This payload follows same branch path.

Exporter applies metadata to deepest assembly node.

---

## 4.7 Exporter Component

File: `ifc_exporter.py`

### Input

MatData [any][tree access]
UnitIdTree [str][tree access]
BayNoTree [str][tree access]
StoreyName [str][item access]
StoreyElev [float][item access]
OutPath [str][item access]
Run [bool][item access]

### Output

OK
Log

### Behavior

Exporter performs:

1. Container grouping by (scope, unit_id)
2. Assembly chain creation
3. IFC element creation
4. Pset writing
5. GUID stabilization
6. IFC file export

Run must be True to execute export.

### Input Requirements (STRICT)

Exporter input MUST be a DataTree with domain paths:

- **Domain 0** `{0;...}`: UNIT payloads
  - MUST have top-level `payload["unit_id"]`
  - Represents primary unit elements
  - `props.scope` SHOULD be `"UNIT"` (may be inferred from domain)
  - Used to construct main unit containers

- **Domain 1** `{1;...}`: NON_UNIT payloads
  - `props.scope` MUST be `"NON_UNIT"`
  - Used for trims, accessories, shared components
  - SHOULD provide `container_id`
  - If missing, exporter assigns default `"__NON_UNIT__"`
  - MUST NOT be grouped into UNIT containers

- **Domain 2** `{2;...}`: BULK payloads
  - `props.kind` SHOULD be `"Bulk"`
  - `props.scope` MUST be either `"UNIT"` or `"NON_UNIT"`
    - If `scope="UNIT"` → MUST have top-level `payload["unit_id"]`
    - If `scope="NON_UNIT"` → MUST have `container_id` or fallback `"__NON_UNIT__"`
  - BULK domain is semantic grouping only
  - Container grouping still determined strictly by `(scope, unit_id/container_id)`

**DO NOT flatten** the DataTree before exporter.
Domain separation preserves authoring structure and prevents cross-contamination.

Exporter may internally flatten after reading domain structure.

### Mixed Input Support

A single MatData may contain mixed domains:

- UNIT
- NON_UNIT
- BULK

Exporter routing rules:

1. Routing MUST be based on `props.scope` first
2. Domain path is secondary and used only for validation
3. Container grouping always uses:
   - `(scope, unit_id)` for UNIT
   - `(scope, container_id)` for NON_UNIT
4. Payloads must never cross container boundaries

### Validation

Exporter MUST validate and log:

1. UNIT payloads
   - MUST have valid top-level `unit_id`
   - Missing → ERROR

2. NON_UNIT payloads
   - MUST have `scope="NON_UNIT"`
   - Missing container_id → auto-assign `"__NON_UNIT__"` + WARNING

3. BULK payloads
   - MUST have valid `scope`
   - If `scope="UNIT"` but no `unit_id` → ERROR
   - If `scope="NON_UNIT"` but no container_id → assign default + WARNING

4. Domain mismatch
   Example:
   - payload in `{0}` but scope="NON_UNIT"

   Exporter should:
   - log WARNING
   - trust explicit `scope` over domain

5. Malformed payloads must be clearly reported in log

### Backward Compatibility

- Existing UNIT-only workflows remain valid
- Single-domain MatData still supported
- Flattened list input allowed but NOT recommended
- If `scope` missing:
  - infer from domain if possible
  - else default `"UNIT"` with WARNING

---

# 5. UnitId workflow (STRICT)

UnitId must:

- exist at payload top-level
- match branch paths
- remain stable across pipeline

Used for:

- container grouping
- GUID generation
- assembly grouping

If UnitId missing → exporter should fail.

---

# 6. Canonical workflow example

Typical façade pipeline:

```
Extract extrusion
↓
Override (optional metadata)
↓
Unit_Builder
↓
Assembly (Frame)
↓
Assembly (Unit)
↓
Assembly (System)
↓
Exporter
```

This creates nested IFC assembly hierarchy.

---

# 7. System philosophy

Grasshopper defines structure.
Spec defines truth.
Exporter writes IFC.

Never collapse GH structure.
Never infer assembly automatically.
User-driven assembly only.
