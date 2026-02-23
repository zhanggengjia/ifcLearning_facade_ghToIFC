# Purpose

Define how assembly nesting is represented and how assembly overrides work.

# Canonical representation

Assembly nesting is carried by:

- payload.props['assembly_path']

## assembly_path format (canonical)

- list[dict], where each dict:
  - name: str
  - key: str # stable identity, often "name|suffix"
  - role: str (optional)

# Behavior: stable outer wrap (MUST)

When applying subassembly(Name, KeySuffix, Role):

- PREPEND a new assembly node to assembly_path
- MUST dedupe to avoid accidental extra depth
- MUST preserve GH DataTree paths (Strategy S1)

# Assembly override (Key/Value)

- Optional Key/Value inputs inject KV onto the _assembly node_
- Implemented by emitting one synthetic AssemblyMeta payload per branch:
  - category=`"__ASSEMBLY_META__"`
  - geo=None (or tiny dummy mesh for GH compatibility)
  - props.pset_overrides = { <scope-specific-pset>: {K: V, ...} }

## Pset selection by scope

The Pset name is determined by the payload's scope:

| Scope | Pset name for assembly overrides |
|---|---|
| UNIT | `Pset_Unit` |
| NON_UNIT | `Pset_NonUnit` |
| CONTEXT | `Pset_Context` |
| Others | `Pset_Assembly` (fallback) |

This ensures assembly-level overrides (e.g., BayNo, Level, InstallSequence) are written to the correct container Pset.

# UnitId validation

- If UnitId tree is supplied, each MatData branch path MUST exist in UnitId
- Branch-missing should fail fast (but allow missing when UnitId input is empty)

# Per-branch Name support (tree access)

- Name input accepts tree access (per-branch strings) or item access (single string, broadcast)
- Resolution priority:
  1. If name_bd has a branch matching the MatData branch path, use its first item
  2. Else if name_bd has exactly one non-empty branch (item access / broadcast), use that value for all branches
  3. Otherwise skip that branch (pass through unmodified)
- Branches with no resolved Name are passed through without annotation
- GH canvas: right-click Name input → change from "Item Access" to "Tree Access"

# Container name derivation (exporter rule)

- Exporter derives container name from the outermost assembly_path level (index 0)
- If assembly_path is present: `cname = assembly_path[0]["name"]`
- If assembly_path is missing: fallback to auto-generated name (e.g. "Unit_XXX", "NON_UNIT")
- The outermost level is then STRIPPED before building the inner assembly chain
  - `inner_apath = apath[1:]`
  - If inner_apath is empty, element goes directly under the container
  - AssemblyMeta overrides with empty inner_apath apply to the container itself
- This means the main ifc_assembly call (outermost) controls the container name and psets

# Multi-level assembly

- AssemblyMeta payload MUST participate in further assemblies
- Therefore: AssemblyMeta itself also receives the same wrapping rule

# Canonical workflow (updated)

```
Builder
→ ifc_assembly (sub-assembly: frame, trim, etc.) [optional, per-part grouping]
→ Entwine({0;…}/{1;…}/{2;…})
→ ifc_assembly (main assembly: per-branch unit name + K/V) [outermost level]
→ Exporter
```

The outermost ifc_assembly call becomes the container in IFC.
Sub-assemblies become nested IfcElementAssembly nodes under the container.
