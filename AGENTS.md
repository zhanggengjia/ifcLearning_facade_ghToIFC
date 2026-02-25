# Codex Working Agreement (GH -> IFC)

This repository is spec-driven.

## Loading policy (token-safe)

1. Always read: SPEC/SPEC_INDEX.md
2. Then read ONLY the spec files relevant to the current task.
3. Do NOT load all SPEC files.
4. If existing code conflicts with SPEC, SPEC wins (unless SPEC says "Observed behavior").

## Repo facts (current)

- Core contracts live in py_modules/ifc_types.py (Payload core keys + props rule)
- Assembly behavior in py_modules/ifc_assembly.py (stable outer wrap via props['assembly_path'])
- Export behavior in py_modules/ifc_exporter.py (mesh-based IFC4 export, psets + guid json)
- Semantic framework in ifc_framework_dbml_v2.txt

## Output expectation

- Prefer minimal diffs
- Preserve GH DataTree branch boundaries (Strategy S1) unless SPEC explicitly changes it
