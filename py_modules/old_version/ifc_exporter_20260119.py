# -*- coding: utf-8 -*-
"""
ifc_exporter.py

Purpose
-------
Export an IFC file from MatData (payload dicts wrapped by GH_ObjectWrapper or plain dicts).

This module is designed for GHPython usage, but avoids hard dependency on Grasshopper types:
- If GH_ObjectWrapper is available, it will unwrap automatically.
- MatData can be any nested list/tuple structure (Graft/Flatten/Merge tolerant).

Key assumptions
---------------
- Each payload dict MUST include:
    - "unit_id": str-like (used for grouping into IfcGroup)
    - "name": str-like (used for element naming, also used as a de-dup key)
    - "geo": Rhino geometry (Mesh/Brep/Extrusion/Surface/... that can be meshed)

- Units:
    - Project length unit is explicitly set to MILLIMETRE (IFC4).
    - Mesh vertices are passed as mm coordinates with unit_scale=1.0.

Output
------
Returns: (OK: bool, Log: str, ResolvedOutPath: Optional[str])

Notes
-----
- This exporter creates:
    IfcProject -> IfcSite -> IfcBuilding -> IfcBuildingStorey (with Elevation in mm)
  then creates elements under the storey and groups them per unit_id into IfcGroup.

- De-dup behavior:
    Current behavior de-dups elements by payload["name"] globally.
    If your naming includes GUID, this prevents accidental collisions.
"""

from __future__ import annotations

import os
import traceback
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple, Union


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------

def export_ifc_from_matdata(
    Run: bool,
    MatData: Any,
    StoreyName: Any,
    StoreyElev: Any,
    OutPath: Any
) -> Tuple[bool, str, Optional[str]]:
    """
    Export IFC from MatData.

    Parameters
    ----------
    Run:
        If False, returns immediately with (False, "Run=False", None).

    MatData:
        Accepts:
          - GH_ObjectWrapper(dict)
          - dict
          - nested list/tuple of the above (any depth)

    StoreyName:
        Name for IfcBuildingStorey and project naming.

    StoreyElev:
        Elevation of storey (mm). Will be cast to float.

    OutPath:
        If a directory path (or empty extension), write to "<StoreyName>_multi_units.ifc" under it.
        If a file path without .ifc extension, it will be forced to .ifc.

    Returns
    -------
    (OK, Log, ResolvedOutPath)
        OK:
            True if export succeeded.
        Log:
            Human-readable trace.
        ResolvedOutPath:
            Final output path used when OK=True, else None.
    """
    if not Run:
        return False, "Run=False", None

    OK: bool = False
    Log: str = ""

    try:
        # Heavy imports inside try for GH environment stability.
        import Rhino.Geometry as rg  # type: ignore

        import ifcopenshell  # type: ignore
        from ifcopenshell.api import run as ifc_run  # type: ignore

        # ---------------------------------------------------------------------
        # Debug helpers
        # ---------------------------------------------------------------------

        def tname(x: Any) -> str:
            """Return .NET type name if possible; fallback to Python type name."""
            try:
                return x.GetType().FullName  # type: ignore[attr-defined]
            except Exception:
                try:
                    return str(type(x))
                except Exception:
                    return "<unknown-type>"

        # ---------------------------------------------------------------------
        # OutPath normalization (kept compatible with your original behavior)
        # ---------------------------------------------------------------------

        def normalize_outpath(out_path: Any, storey_name: str) -> str:
            """
            Normalize output path.
            - If out_path is a directory OR has no extension => create "<storey>_multi_units.ifc"
            - Else ensure extension is .ifc
            Also ensures output directories exist.
            """
            p = str(out_path).strip().strip('"')

            # If user passed empty or whitespace, treat as current dir.
            if p == "":
                p = "."

            ext = os.path.splitext(p)[1]
            if os.path.isdir(p) or ext == "":
                out_dir = p
                if not os.path.exists(out_dir):
                    os.makedirs(out_dir, exist_ok=True)
                return os.path.join(out_dir, f"{storey_name}_multi_units.ifc")

            out_dir = os.path.dirname(p)
            if out_dir and not os.path.exists(out_dir):
                os.makedirs(out_dir, exist_ok=True)

            root, ext2 = os.path.splitext(p)
            return (root + ".ifc") if ext2.lower() != ".ifc" else p

        ResolvedOutPath: str = normalize_outpath(OutPath, str(StoreyName))

        # ---------------------------------------------------------------------
        # GH goo / payload helpers
        # ---------------------------------------------------------------------

        try:
            from Grasshopper.Kernel.Types import GH_ObjectWrapper  # type: ignore
        except Exception:
            GH_ObjectWrapper = None  # type: ignore

        Payload = Dict[str, Any]

        def unwrap_payload(x: Any) -> Payload:
            """
            Accept GH_ObjectWrapper(dict) or plain dict.
            Raises TypeError if not dict-like after unwrapping.
            """
            if GH_ObjectWrapper is not None and isinstance(x, GH_ObjectWrapper):  # type: ignore
                x = x.Value  # type: ignore[attr-defined]

            if not isinstance(x, dict):
                raise TypeError(f"MatData item is not dict/goo(dict). Got {tname(x)}")
            return x

        def iter_payloads(obj: Any) -> Iterator[Payload]:
            """
            Flatten ANY nested list/tuple structure into payload dicts.
            This allows Grasshopper users to freely Merge / Graft / Flatten.
            """
            if obj is None:
                return
            if isinstance(obj, (list, tuple)):
                for it in obj:
                    for p in iter_payloads(it):
                        yield p
                return
            yield unwrap_payload(obj)

        # ---------------------------------------------------------------------
        # Geometry helpers (meshing + triangulation)
        # ---------------------------------------------------------------------

        def brep_to_mesh(brep: "rg.Brep") -> Optional["rg.Mesh"]:
            """Convert Brep to a single joined mesh using FastRenderMesh params."""
            mp = rg.MeshingParameters.FastRenderMesh
            meshes = rg.Mesh.CreateFromBrep(brep, mp)
            if not meshes:
                return None

            m = rg.Mesh()
            for part in meshes:
                if part:
                    m.Append(part)

            m.Normals.ComputeNormals()
            m.Compact()
            return m

        def geom_to_mesh(geo: Any) -> Optional["rg.Mesh"]:
            """
            Convert various Rhino geometry types into a mesh.
            Returns None if cannot be meshed.
            """
            if geo is None:
                return None

            if isinstance(geo, rg.Mesh):
                m = geo.DuplicateMesh()
                m.Normals.ComputeNormals()
                m.Compact()
                return m

            if isinstance(geo, rg.Brep):
                return brep_to_mesh(geo)

            if isinstance(geo, rg.Extrusion):
                return brep_to_mesh(geo.ToBrep())

            if isinstance(geo, rg.Surface):
                return brep_to_mesh(geo.ToBrep())

            brep = rg.Brep.TryConvertBrep(geo)
            if brep:
                return brep_to_mesh(brep)

            return None

        def mesh_to_vertices_faces(mesh: "rg.Mesh") -> Tuple[List[Tuple[float, float, float]], List[Tuple[int, int, int]]]:
            """
            Ensure triangles and produce:
              - verts: [(x,y,z), ...]
              - faces: [(a,b,c), ...]
            """
            if mesh is None or mesh.Vertices.Count == 0:
                return [], []

            m = mesh.DuplicateMesh()
            m.Faces.ConvertQuadsToTriangles()
            m.Normals.ComputeNormals()
            m.Compact()

            verts = [(float(v.X), float(v.Y), float(v.Z)) for v in m.Vertices]  # mm
            faces = [(int(f.A), int(f.B), int(f.C)) for f in m.Faces]
            return verts, faces

        # ---------------------------------------------------------------------
        # IFC setup (explicit millimetre)
        # ---------------------------------------------------------------------

        model = ifcopenshell.file(schema="IFC4")
        project = ifc_run(
            "root.create_entity",
            model,
            ifc_class="IfcProject",
            name=f"{StoreyName}_Units"
        )

        # IMPORTANT: explicit millimetre unit
        ifc_run("unit.assign_unit", model, length={"is_metric": True, "raw": "MILLIMETRE"})

        model_context = ifc_run("context.add_context", model, context_type="Model")
        body_context = ifc_run(
            "context.add_context",
            model,
            context_type="Model",
            context_identifier="Body",
            target_view="MODEL_VIEW",
            parent=model_context
        )

        site = ifc_run("root.create_entity", model, ifc_class="IfcSite", name="Default Site")
        building = ifc_run("root.create_entity", model, ifc_class="IfcBuilding", name="Default Building")
        storey = ifc_run("root.create_entity", model, ifc_class="IfcBuildingStorey", name=str(StoreyName))

        # Elevation mm
        storey.Elevation = float(StoreyElev)

        ifc_run("aggregate.assign_object", model, products=[site], relating_object=project)
        ifc_run("aggregate.assign_object", model, products=[building], relating_object=site)
        ifc_run("aggregate.assign_object", model, products=[storey], relating_object=building)

        # ---------------------------------------------------------------------
        # Pset helper
        # ---------------------------------------------------------------------

        def add_pset(product: Any, pset_name: str, props: Dict[str, Any]) -> None:
            """
            Add property set if any non-empty property exists.
            - Removes None / "" entries.
            """
            if not props:
                return
            clean = {k: v for k, v in props.items() if v is not None and v != ""}
            if not clean:
                return
            pset = ifc_run("pset.add_pset", model, product=product, name=pset_name)
            ifc_run("pset.edit_pset", model, pset=pset, properties=clean)

        # ---------------------------------------------------------------------
        # Element creation
        # ---------------------------------------------------------------------

        def category_to_ifc_class(cat: str) -> str:
            """
            Map a category string to a concrete IFC class.
            Keep conservative defaults to avoid schema invalidity.
            """
            c = (cat or "").strip().lower()
            if c == "vertical":
                return "IfcMember"
            if c == "horizontal":
                return "IfcBeam"
            return "IfcBuildingElementProxy"

        def create_element(payload: Payload) -> Any:
            """
            Create IFC element + representation + psets from a payload.

            Raises
            ------
            ValueError:
                - If geometry cannot be meshed or results in empty mesh.
            """
            name = str(payload.get("name", "Unnamed"))
            cat = str(payload.get("category", "Unspecified"))
            ifc_class = category_to_ifc_class(cat)

            geo = payload.get("geo", None)
            mesh = geom_to_mesh(geo)
            if mesh is None:
                raise ValueError(
                    f"[create_element] name='{name}' cat='{cat}': geometry cannot be meshed. geo_type={tname(geo)}"
                )

            verts, faces = mesh_to_vertices_faces(mesh)
            if not verts or not faces:
                raise ValueError(
                    f"[create_element] name='{name}' cat='{cat}': empty mesh after meshing. geo_type={tname(geo)}"
                )

            elem = ifc_run("root.create_entity", model, ifc_class=ifc_class, name=name)
            ifc_run("spatial.assign_container", model, products=[elem], relating_structure=storey)

            # IMPORTANT:
            # ifcopenshell.api.geometry.add_mesh_representation expects:
            #   vertices=[verts], faces=[faces]  (list-of-lists)
            shape = ifc_run(
                "geometry.add_mesh_representation",
                model,
                context=body_context,
                vertices=[verts],
                faces=[faces],
                unit_scale=1.0,          # project is mm
                force_faceted_brep=True
            )
            ifc_run("geometry.assign_representation", model, product=elem, representation=shape)

            # Required grouping field
            uid = payload.get("unit_id")

            # Psets (optional fields allowed)
            add_pset(elem, "Pset_CWIdentity", {
                "UnitId": uid,
                "PartNo": payload.get("part_no"),
                "Category": cat
            })

            dims = payload.get("dims") or {}
            add_pset(elem, "Pset_CWDimensions", {
                "Length_mm": dims.get("L"),
                "Width_mm": dims.get("W"),
                "Radius_mm": dims.get("R")
            })

            mat = payload.get("material") or {}
            add_pset(elem, "Pset_CWMaterial", {
                "MaterialName": mat.get("name")
            })

            finish = payload.get("finish") or {}
            add_pset(elem, "Pset_CWSurfaceFinish", {
                "FinishType": finish.get("type"),
                "FinishThickness_um": finish.get("thickness_um")
            })

            add_pset(elem, "Pset_CWAppearance", {
                "ColorCode": payload.get("color_code")
            })

            return elem

        # ---------------------------------------------------------------------
        # Flatten MatData -> regroup by unit_id -> create IfcGroup per unit -> assign
        # ---------------------------------------------------------------------

        payloads: List[Payload] = list(iter_payloads(MatData))
        if not payloads:
            raise ValueError("MatData is empty (no payloads).")

        units: Dict[str, List[Payload]] = {}
        for idx, pl in enumerate(payloads):
            uid = pl.get("unit_id", None)
            if not uid:
                raise ValueError(f"payload[{idx}] missing 'unit_id' (Builder must provide unit_id).")
            units.setdefault(str(uid), []).append(pl)

        Log += f"ifcopenshell version: {getattr(ifcopenshell, 'version', 'unknown')}\n"
        Log += f"Resolved OutPath: {ResolvedOutPath}\n"
        Log += f"Storey: {StoreyName} Elev(mm): {float(StoreyElev)}\n"
        Log += f"Units: {len(units)}\n"
        Log += f"Payloads(flat): {len(payloads)}\n"

        created_by_name: Dict[str, Any] = {}   # de-dup table
        unit_groups: List[Any] = []
        created_count: int = 0

        for uid, items in units.items():
            group = ifc_run("root.create_entity", model, ifc_class="IfcGroup", name=f"Unit_{uid}")
            unit_groups.append(group)

            # unit-level Pset
            add_pset(group, "Pset_Unit", {"UnitId": uid})

            members: List[Any] = []
            cats: List[str] = []

            for pl in items:
                nm = str(pl.get("name", "Unnamed"))
                cats.append(str(pl.get("category", "Unspecified")))

                # De-dup by name (global)
                if nm in created_by_name:
                    elem = created_by_name[nm]
                else:
                    elem = create_element(pl)
                    created_by_name[nm] = elem
                    created_count += 1

                members.append(elem)

            if members:
                ifc_run("group.assign_group", model, products=members, group=group)

            Log += f"Unit {uid}: payloads={len(items)} cats={cats}\n"

        # Write IFC
        model.write(ResolvedOutPath)

        OK = True
        Log += "\n"
        Log += f"Created elements: {created_count}\n"
        Log += f"Created unit groups: {len(unit_groups)}\n"
        Log += f"Wrote: {ResolvedOutPath}\n"

        return OK, Log, ResolvedOutPath

    except Exception as e:
        OK = False
        Log += "\nFAILED:\n" + repr(e) + "\n\n" + traceback.format_exc()
        return OK, Log, None
