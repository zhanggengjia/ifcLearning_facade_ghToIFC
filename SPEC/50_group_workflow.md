# IFC Group Workflow

## Purpose

Define how to use IFC groups for logical grouping of elements.

## Groups vs Assemblies

| Aspect | IfcElementAssembly | IfcGroup |
|--------|-------------------|----------|
| **Purpose** | Physical/geometric composition | Logical grouping |
| **Example** | Frame + Panels = Curtain Wall Unit | All elements in Zone A |
| **Hierarchy** | Nested physical structure | Flat membership |
| **Multiplicity** | Element belongs to one assembly chain | Element can belong to multiple groups |
| **IFC Relation** | IfcRelAggregates | IfcRelAssignsToGroup |

## Common Use Cases

### 1. Spatial Zones
Group elements by spatial location:
- Zone_A, Zone_B, Zone_C
- Floor_1, Floor_2, Floor_3
- Wing_North, Wing_South

### 2. Installation Phases
Group elements by construction sequence:
- Phase_1_Foundation
- Phase_2_Structure
- Phase_3_Envelope

### 3. Functional Systems
Group elements by building system:
- HVAC_System
- Electrical_System
- Structural_System

### 4. Responsibility
Group elements by contractor/team:
- Contractor_A
- Contractor_B
- MEP_Team

## Workflow

### Basic Workflow

```
GH Extract
↓
ifc_group(GroupNames="Zone_A")
↓
Builder
↓
Exporter
```

### Multi-Group Workflow

One element can belong to multiple groups:

```
GH Extract
↓
ifc_group(GroupNames="Zone_A")  # Add spatial group
↓
ifc_group(GroupNames="Phase_1") # Add phase group
↓
Builder
↓
Exporter
```

Result: Elements are in both "Zone_A" and "Phase_1" groups.

### Per-Branch Groups

Use DataTree with different groups per branch:

```
GH Extract (Tree with multiple branches)
↓
ifc_group(GroupNames=GroupNamesTree)  # Tree Access
  Branch {0} → "Zone_A"
  Branch {1} → "Zone_B"
  Branch {2} → "Zone_C"
↓
Builder
↓
Exporter
```

## Integration with Existing Components

### With Override Component

```
GH Extract
↓
ifc_override(Key="CustomProp", Value="Value1")
↓
ifc_group(GroupNames="Zone_A")
↓
Builder
```

Both override data and groups are merged into the same override_data dict.

### With Assembly Component

```
GH Extract
↓
ifc_group(GroupNames="Zone_A")
↓
Builder
↓
ifc_assembly(Name="Unit_A")  # Physical assembly
↓
Exporter
```

Result:
- Elements are physically aggregated in "Unit_A" (IfcElementAssembly)
- Elements are logically grouped in "Zone_A" (IfcGroup)

## Implementation Details

### GH Wrapper Format

Before ifc_group:
```python
[geo, name]
```

After ifc_group:
```python
[geo, name, {"groups": ["Zone_A", "Phase_1"]}]
```

### Payload Format

Builder writes groups to payload:
```python
payload = {
    "schema": 1,
    "unit_id": "U001",
    "geo": geo,
    "name": "Panel_A",
    "category": "Vertical",
    "props": {
        "groups": ["Zone_A", "Phase_1"]
    }
}
```

### IFC Export

Exporter creates IfcGroup entities:

```python
# Create IfcGroup for "Zone_A"
group_zone_a = IfcGroup(Name="Zone_A")

# Create IfcGroup for "Phase_1"
group_phase_1 = IfcGroup(Name="Phase_1")

# Assign elements to groups
IfcRelAssignsToGroup(RelatingGroup=group_zone_a, RelatedObjects=[elem1, elem2, ...])
IfcRelAssignsToGroup(RelatingGroup=group_phase_1, RelatedObjects=[elem1, elem3, ...])
```

## Best Practices

### 1. Naming Convention

Use clear, hierarchical names:
- ✅ `Zone_A`, `Zone_B`, `Zone_C`
- ✅ `Phase_1_Foundation`, `Phase_2_Structure`
- ❌ `Group1`, `Group2`, `Group3`

### 2. Group Granularity

Choose appropriate level:
- Too many groups → hard to manage
- Too few groups → not useful

### 3. Multiple Groups

Use multiple groups for multi-dimensional classification:
```python
# Spatial + Phase + System
ifc_group(GroupNames="Zone_A")
ifc_group(GroupNames="Phase_1")
ifc_group(GroupNames="HVAC_System")
```

### 4. Tree Access for Flexibility

Use Tree Access when different branches need different groups:
```python
# Right-click GroupNames input → Type Hint → Tree Access
```

## Example: Complete Workflow

```
1. Extract objects
   → [geo, name]

2. Mark spatial zones (per-branch)
   ifc_group(GroupNames=ZoneTree)
   → [geo, name, {"groups": ["Zone_A"]}]

3. Mark installation phase (common)
   ifc_group(GroupNames="Phase_1")
   → [geo, name, {"groups": ["Zone_A", "Phase_1"]}]

4. Add custom properties
   ifc_override(Key="Contractor", Value="Company_A")
   → [geo, name, {"groups": [...], "Pset_Override": {"Contractor": "Company_A"}}]

5. Build payloads
   Unit_Builder
   → payload.props.groups = ["Zone_A", "Phase_1"]

6. Create assemblies
   ifc_assembly(Name="Unit_A")
   → physical assembly hierarchy

7. Export
   Exporter
   → Creates IfcElementAssembly (physical)
   → Creates IfcGroup (logical)
```

## Querying in IFC Viewers

After export, IFC viewers can:
- Filter by group: "Show only Zone_A"
- Count by group: "How many elements in Phase_1?"
- Visualize by group: Color elements by zone

## Limitations

- Groups are flat (no nested groups)
- Group membership is write-only (cannot remove groups once added)
- Groups are created at export time (not visible in GH)

## Future Enhancements

Potential future features:
- Nested groups
- Group removal/editing
- Group-based pset assignment
- Dynamic group rules
