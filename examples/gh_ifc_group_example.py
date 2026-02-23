"""
GHPython component example for ifc_group

Component Name: IFC_Group
Description: Annotate objects with IFC group membership

Inputs:
  Obj (Tree Access): GH wrapper objects [geo, name] or [geo, name, override]
  GroupNames (Item Access or Tree Access): Group name(s)
    - String: single group for all objects
    - List: multiple groups for all objects
    - Tree: per-branch groups (switch to Tree Access)

Outputs:
  MatData: Annotated objects with group membership
  Log: Diagnostic messages

Usage:
  1. Single group:
     GroupNames = "Zone_A"

  2. Multiple groups:
     GroupNames = ["Zone_A", "Phase_1"]

  3. Per-branch groups:
     Right-click GroupNames → Type Hint → Tree Access
     Connect a DataTree with per-branch group names
"""

import sys
sys.path.append(r"d:\Kevin\GH\ifc_test\py_modules")

from ifc_group import annotate_group

# Execute
MatData, Log = annotate_group(
    Obj=Obj,
    GroupNames=GroupNames,
)

print(Log)
