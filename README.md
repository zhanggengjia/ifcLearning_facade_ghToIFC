# ifcLearning_facade_ghToIFC

A simple **Grasshopper → IFC** experimental project for **façade / curtain wall workflows**.

This repository explores exporting **unit-based IFC files** using
**Grasshopper + GHPython + ifcopenshell**, without relying on Revit.

The focus is on:

- unit-level grouping
- flexible geometry input from Grasshopper
- basic assembly hierarchy support

---

## Folder Structure

```
.
├─ .gitignore
├─ README.md
├─ openshell_test.gh        # Grasshopper test file
│
├─ my_modules/              # Python modules for GHPython
│  ├─ ifc_types.py          # Shared payload type definitions
│  ├─ ifc_builder.py        # Build unit-based MatData
│  ├─ ifc_assembly.py       # Annotate sub-assembly hierarchy (optional)
│  └─ ifc_exporter.py       # Export IFC from MatData
│
├─ ifc_test_file/           # IFC export outputs (not versioned)
└─ rhino_model/             # Rhino source models (not versioned)
```

---

## Large Files (Rhino / IFC)

Large `.3dm` and `.ifc` files are **not stored in this repository** due to file size limits.

### Unit model files can be downloaded from Google Drive:

👉
[https://drive.google.com/drive/folders/1wDdWIqzuKG9pSJIgunSWJQMx7P8IkPxj](https://drive.google.com/drive/folders/1wDdWIqzuKG9pSJIgunSWJQMx7P8IkPxj)

These files include:

- Rhino unit models (`.3dm`)
- Exported unit-based IFC files (`.ifc`)

---

## Basic Workflow

1. Open `openshell_test.gh` in Grasshopper
2. Prepare geometry and unit-related data in GH
3. `ifc_builder.py` converts GH inputs into unit-based `MatData`
4. (Optional) `ifc_assembly.py` adds sub-assembly information
5. `ifc_exporter.py` exports IFC files grouped by unit

---

## Notes

- This is an **experimental / learning repository**
- Geometry files are managed externally
- GitHub is used mainly for **code and Grasshopper logic**
- The IFC output is mesh-based and intentionally simplified
