# Purpose

Define how MatData payloads become an IFC4 file.

# IFC setup

- IFC schema: IFC4
- Create: IfcProject → IfcSite → IfcBuilding → IfcBuildingStorey
- Storey name and elevation are inputs

# Geometry policy

- All geometry is meshed (FastRenderMesh)
- Export uses geometry.add_mesh_representation(... force_faceted_brep=True)
- If payload.geo is None: treat as meta payload (no element geometry)

# Classification

- IFC class chosen by:
  1. props.ifc_class_hint if present
  2. else category mapping:
     - Vertical → IfcMember
     - Horizontal → IfcBeam
     - fallback → IfcBuildingElementProxy

# Psets

- Core psets are built schema-driven (build_psets_for_payload)
- Then apply user overrides:
  - props.pset_overrides: {PsetName: {k:v}}

# Containers

- Payloads are grouped into containers by (scope, container_id)
- Each container is an IfcElementAssembly
- Containers are assigned to storey
- Within a container:
  - If payload has assembly_path: create nested assembly chain (IfcElementAssembly nodes)
  - Else: aggregate directly under container

# AssemblyMeta handling (STRICT)

A payload is treated as AssemblyMeta if:

category == `"__ASSEMBLY_META__"`

This string constant MUST be used exactly.

Behavior:

- Do NOT create geometric IFC element
- Ensure assembly chain exists
- Apply props.pset_overrides onto the deepest assembly node
- geo may be empty Mesh (workaround for GH output filtering)
- GUID assignment is skipped for AssemblyMeta payloads

Note:
- This is a literal constant, not markdown formatting.
- Due to Grasshopper DataTree output filtering, geo=None payloads may be lost. Use empty Mesh as placeholder.
- Exporter identifies AssemblyMeta by category only, not by geo value.

# GUID / source_guid policy

- GUID is assigned in exporter (builders must not generate GUID)
- source_guid can be stabilized via JSON (guid_file.json) keyed by deterministic signature

# Accepted Input Forms

## Preferred: DataTree with Domain Paths

MatData SHOULD be a Grasshopper DataTree with domain-based organization:

- **Domain 0** `{0;...}`: UNIT payloads
  - MUST have top-level `payload["unit_id"]`
  - `props.scope` defaults to "UNIT" if missing

- **Domain 1** `{1;...}`: NON_UNIT payloads
  - `props.scope` MUST be "NON_UNIT"
  - Container grouping uses `container_id` or defaults to `"__NON_UNIT__"`

- **Domain 2** `{2;...}`: BULK payloads
  - `props.scope` MUST be explicitly set ("UNIT" or "NON_UNIT")
  - Container grouping follows scope rules

## Scope Determination (Priority Order)

When routing payloads to containers:

1. **Explicit scope**: Use `payload.props.scope` if present and valid
2. **Inferred from domain**:
   - Domain 0 → "UNIT"
   - Domain 1 → "NON_UNIT"
   - Domain 2 → require explicit scope (no default)
3. **Fallback**: Default to "UNIT" with WARNING

Exporter MUST trust explicit `props.scope` over domain path.

## Container Grouping Rules

Containers are determined by `(scope, container_id)`:

- **UNIT scope**:
  - `container_id` = `payload["unit_id"]` (top-level, STRICT)
  - Missing `unit_id` → ERROR

- **NON_UNIT scope**:
  - `container_id` = `payload.props.container_id` OR `"__NON_UNIT__"`
  - Missing `container_id` → auto-assign `"__NON_UNIT__"` + WARNING

## Validation Requirements

Exporter MUST validate:

1. **UNIT payloads**:
   - Top-level `unit_id` exists and non-empty
   - Log ERROR and skip if missing

2. **NON_UNIT payloads**:
   - `props.scope == "NON_UNIT"`
   - If `container_id` missing: assign default + WARNING

3. **Domain-scope mismatch**:
   - Example: payload in `{0}` but `scope="NON_UNIT"`
   - Log WARNING
   - Trust explicit `scope` value over domain

4. **Malformed payloads**: Clear log messages with payload name/category

## Fallback: List Input

If MatData is a flattened list (not DataTree):

- Exporter MUST strictly validate `scope` and `container_id` for each payload
- NO domain inference available
- Missing scope → default "UNIT" + WARNING
- NOT recommended for mixed UNIT/NON_UNIT workflows

## Backward Compatibility

- Existing UNIT-only single-domain trees continue to work
- Scope inference preserves existing behavior
- Mixed input support is additive (does not break existing workflows)
