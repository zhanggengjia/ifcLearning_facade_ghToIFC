# IFC Property Specification

**Audience:** IFC viewers, QC reviewers, coordination teams.
**Scope:** What Psets and properties must exist on each IFC object in the exported file.
This document does NOT describe builder logic or the GH pipeline.

> **Convention note:** Properties use `Pset_*` naming. These are custom psets,
> not buildingSMART standard sets. This is a known project convention.

---

## 1. Scope Definitions (IFC level)

Each exported IFC file has one `IfcBuildingStorey`. Under the storey, payloads are
grouped into top-level `IfcElementAssembly` containers by scope:

| Scope | Meaning | Container pset |
|---|---|---|
| **Unit** | Hoistable / shippable fabrication unit. Each unit is one container. | `Pset_Unit` |
| **NonUnit** | Elements that are not unit-bound (site-installed, misc., secondary elements). Grouped by container code. | `Pset_NonUnit` |
| **Context** | Structural reference objects (beams, slabs, steel, embedded parts). Viewer/coordination reference only — not fabrication assembly. | `Pset_Context` |

> **Context containers are reference geometry.** They exist for coordination and clash detection, not for fabrication or installation sequencing.
> Viewers should treat `Pset_Context` containers as non-fabrication reference objects (`IsReference = true` recommended at viewer level).

---

## 2. Object Types and Required Psets

`R` = Required · `O` = Optional · `—` = Not applicable

| IFC Class | Role | Required Psets | Notes |
|---|---|---|---|
| `IfcElementAssembly` | **Unit container** | `Pset_Unit` | One per unit. Direct child of storey. |
| `IfcElementAssembly` | **NonUnit container** | `Pset_NonUnit` | One per non-unit group. Direct child of storey. |
| `IfcElementAssembly` | **Context container** | `Pset_Context` | Reference objects. Direct child of storey. |
| `IfcElementAssembly` | **Sub-assembly node** | — | Nested under container. Optional psets from user overrides. |
| `IfcMember` | Vertical extrusion (mullion, post) | `Pset_Part` | Category: `vertical`, `mullion` |
| `IfcMember` | Horizontal / transom | `Pset_Part` | Category: `horizontal`, `transom` |
| `IfcBeam` | Horizontal structural member | `Pset_Part` | Category: `horizontal` (explicit hint) |
| `IfcPlate` | Panel / glazing unit | `Pset_Part` | Category: `panel`, `glass` |
| `IfcDiscreteAccessory` | Bracket / fitting / accessory | `Pset_Part` | Category: `bracket`, `fitting`, `accessory` |
| `IfcMechanicalFastener` | Bolt / screw / fastener | `Pset_Part` or `Pset_Bulk` | Category: `fastener`, `bolt`, `screw` |
| `IfcBuildingElementProxy` | Fallback (unknown category) | `Pset_Part` or `Pset_Bulk` | Applied when no category mapping exists. |

All geometric leaf elements additionally receive `Pset_CWAppearance` when a color code is set.

---

## 3. Pset Definitions

### `Pset_Unit`
Applied to: `IfcElementAssembly` (Unit container)

| Property | Type | Required | Description |
|---|---|---|---|
| `ContainerCode` | string | **R** | Unique unit identifier. e.g. `"02N_001"` |
| `BayNo` | string | O | Bay / grid reference. e.g. `"02N"` |
| `Level` | string | O | Floor / storey label. e.g. `"10F"` |
| `InstallSequence` | int | O | Installation order within the storey. |

---

### `Pset_NonUnit`
Applied to: `IfcElementAssembly` (NonUnit container)

| Property | Type | Required | Description |
|---|---|---|---|
| `ContainerCode` | string | **R** | Group identifier. e.g. `"BALCONY_RAIL"` |

---

### `Pset_Context`
Applied to: `IfcElementAssembly` (Context container)

| Property | Type | Required | Description |
|---|---|---|---|
| `ContainerCode` | string | **R** | Group identifier. e.g. `"STRUCT_REF"` |
| `IsReference` | boolean | **R** (strongly) | Mark as reference-only (`true`). Viewers should use this to exclude from fabrication lists. |
| `ContextType` | string | O | Descriptor: `"BeamRef"` \| `"SlabRef"` \| `"EmbeddedPart"` \| … |

---

### `Pset_Part`
Applied to: geometric leaf elements with `kind = Part`

| Property | Type | Required | Description |
|---|---|---|---|
| `PartCode` | string | **R** | Part number / internal code. |
| `ElementCode` | string | O | Alias / secondary code if needed. |
| `MaterialName` | string | O | e.g. `"AL6063"`, `"SS304"` |
| `FinishType` | string | O | e.g. `"Anodized"`, `"PowderCoat"` |
| `FinishThicknessUm` | float | O | Finish thickness in micrometres. |
| `Dims_L` | float | O | Cut length (mm). |
| `Dims_W` | float | O | Width (mm). |
| `Dims_R` | float | O | Radius or secondary dimension (mm). |
| `ColorCode` | string | O | RAL or project color code. (Also in `Pset_CWAppearance`.) |

---

### `Pset_Bulk`
Applied to: geometric leaf elements with `kind = Bulk`

| Property | Type | Required | Description |
|---|---|---|---|
| `BulkCode` | string | **R** | Bulk item code. |
| `Quantity` | int | O | Item count. |
| `AreaM2` | float | O | Area in m². |
| `LengthM` | float | O | Length in m. |
| `InstallLocation` | string | O | Installation location description. |
| `ColorCode` | string | O | RAL or project color code. |

---

### `Pset_CWAppearance`
Applied to: any element where color is set

| Property | Type | Required | Description |
|---|---|---|---|
| `ColorCode` | string | O | RAL / project color reference. |

---

## 4. Mapping Rules

### Scope → Container pset

| `props.scope` | Container pset |
|---|---|
| `UNIT` | `Pset_Unit` |
| `NON_UNIT` | `Pset_NonUnit` |
| `CONTEXT` | `Pset_Context` |

### Kind → Element pset

| `props.kind` | Element pset |
|---|---|
| `Part` | `Pset_Part` |
| `Bulk` | `Pset_Bulk` |

### Category → IFC class

Resolution order (first match wins):

1. `props.ifc_class_hint` — explicit override set upstream
2. Category string mapping (case-insensitive) — see `py_modules/ifc_class_map.py`:

| Category | IFC class |
|---|---|
| `vertical`, `mullion` | `IfcMember` |
| `horizontal`, `transom` | `IfcBeam` / `IfcMember` |
| `panel`, `glass` | `IfcPlate` |
| `bracket`, `fitting`, `accessory` | `IfcDiscreteAccessory` |
| `fastener`, `bolt`, `screw` | `IfcMechanicalFastener` |
| *(unknown)* | `IfcBuildingElementProxy` |

3. Fallback: `IfcBuildingElementProxy`

---

## 5. Identifier Rules

### `ContainerCode`
- Must be **stable and human-readable** — survives round-trips through IFC viewers.
- Should reflect the project coding convention. e.g. `"02N_001"` for units, `"BALCONY_RAIL"` for non-unit groups.
- Avoid internal sentinel strings (`"__NON_UNIT__"`, `"__CONTEXT__"`) in production exports.
  These appear when the upstream GH workflow does not provide an explicit `container_id`.
  Provide explicit container codes wherever possible.

### `PartCode` / `BulkCode`
- Should match the project part numbering scheme.
- Must not contain characters that break IFC string encoding (avoid `<`, `>`, `&`).
- Legacy format `CODE_GUID` is supported by builders — the `_GUID` suffix is stripped automatically.
