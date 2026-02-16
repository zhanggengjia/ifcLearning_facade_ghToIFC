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
- Implemented by emitting one synthetic AssemblyMeta payload per unit branch:
  - category=`"__ASSEMBLY_META__"`
  - geo=None
  - props.pset_overrides = { "Pset_Assembly": {K: V, ...} }

# UnitId validation

- If UnitId tree is supplied, each MatData branch path MUST exist in UnitId
- Branch-missing should fail fast (but allow missing when UnitId input is empty)

# Multi-level assembly

- AssemblyMeta payload MUST participate in further assemblies
- Therefore: AssemblyMeta itself also receives the same wrapping rule
