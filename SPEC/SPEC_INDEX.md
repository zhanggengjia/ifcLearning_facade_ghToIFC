# SPEC INDEX (Read this first)

Goal: Keep specs modular. The assistant MUST NOT read every spec file.

## Always relevant

- 00_project_overview.md

## Payload / data contract

- 10_payload_contract.md
  Use when tasks involve: MatData, Payload fields, scope/kind, overrides, typing, tree-branch invariants.

## Assembly system

- 20_assembly_rules.md
  Use when tasks involve: assembly_path, multi-level assembly, AssemblyMeta payload, assembly override KV.

## Export / IFC output

- 30_exporter_pipeline.md
  Use when tasks involve: IFC4 export, meshing, psets, guid_file.json, containers, grouping, colors.

## Semantic model (DBML)

- 40_dbml_semantics.md
  Use when tasks involve: mapping to Element/ElementRel, roles, pset tables, conceptual correctness.

## Grasshopper workflow

- 15_gh_workflow.md → Grasshopper component workflow and usage rules

## IFC Groups

- 50_group_workflow.md
  Use when tasks involve: IFC groups, logical grouping, zone assignment, phase grouping, multi-group membership.

## Rule

Before coding, pick the smallest subset of specs needed for the task.
