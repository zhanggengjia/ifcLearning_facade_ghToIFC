# -*- coding: utf-8 -*-
"""
ifc_exporter.py

Purpose
-------
Export an IFC file from a Grasshopper-friendly "MatData" payload.

Design principles
-----------------
1) Stable GH calling signature (DO NOT CHANGE):
   - export_ifc_from_matdata(Run, MatData, StoreyName, StoreyElev, OutPath)

2) Payload contract (ifc_types.Payload):
   Required keys:
     schema   : int
     unit_id  : str-like
     name     : str-like
     geo      : Rhino geometry
     category : str-like (if missing -> "Unspecified")
     props    : dict

3) Container strategy (UPDATED: UNIT + BULK):
   - Each payload belongs to a "container" determined by:
       scope = payload["props"].get("scope", "UNIT")
       if scope == "BULK":
           container_id = payload["props"].get("container_id", "DEFAULT")
           container assembly name: Bulk_{container_id}
       else:
           unit_id = payload["unit_id"]
           container assembly name: Unit_{unit_id}
   - Container assemblies are placed under the Storey.

4) Multi-level assembly strategy (UPDATED: supports multi-level):
   - Sub-assemblies are read from:
       payload["props"]["assembly_path"] = [{"name": "...", "key": "..."}, ...]
     appended by ifc_assembly.py (AUTO WRAP / multi-level).
   - Elements are assigned to the deepest assembly node if assembly_path exists;
     otherwise assigned directly to the container.
"""

from __future__ import annotations

import os
import traceback
from typing import Any, Dict, Iterator, List, Optional, Tuple

from ifc_types import Payload


# ---------------------------------------------------------------------
# Public API (DO NOT CHANGE signature)
# ---------------------------------------------------------------------
def export_ifc_from_matdata(
    Run: bool,
    MatData: Any,
    StoreyName: Any,
    StoreyElev: Any,
    OutPath: Any,
) -> Tuple[bool, str, Optional[str]]:
    if not Run:
        return False, "Run=False", None

    OK: bool = False
    Log: str = ""

    try:
        import Rhino.Geometry as rg

        import ifcopenshell  # type: ignore
        from ifcopenshell.api import run as ifc_run  # type: ignore

        # ---------------------------------------------------------------------
        # Debug helpers
        # ---------------------------------------------------------------------
        def tname(x: Any) -> str:
            try:
                return x.GetType().FullName  # type: ignore[attr-defined]
            except Exception:
                try:
                    return str(type(x))
                except Exception:
                    return "<unknown-type>"

        # ---------------------------------------------------------------------
        # OutPath normalization
        # ---------------------------------------------------------------------
        def normalize_outpath(out_path: Any, storey_name: str) -> str:
            p = str(out_path).strip().strip('"')
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

        def is_datatree_like(x: Any) -> bool:
            return x is not None and hasattr(x, "BranchCount") and hasattr(x, "Branch")

        def unwrap_payload(x: Any) -> Payload:
            if GH_ObjectWrapper is not None and isinstance(x, GH_ObjectWrapper):  # type: ignore
                x = getattr(x, "Value", x)

            if not isinstance(x, dict):
                raise TypeError(f"MatData item is not dict/goo(dict). Got {tname(x)}")

            if "unit_id" not in x:
                raise KeyError("Payload missing required key: 'unit_id'")
            if "name" not in x:
                raise KeyError("Payload missing required key: 'name'")
            if "geo" not in x:
                raise KeyError("Payload missing required key: 'geo'")

            if "category" not in x or x["category"] is None:
                x["category"] = "Unspecified"

            if "props" not in x or x["props"] is None:
                x["props"] = {}

            if "schema" not in x or x["schema"] is None:
                x["schema"] = 1

            return x  # type: ignore[return-value]

        def iter_payloads(obj: Any) -> Iterator[Payload]:
            if obj is None:
                return

            if is_datatree_like(obj):
                for i in range(int(obj.BranchCount)):
                    br = obj.Branch(i)
                    for it in br:
                        for p in iter_payloads(it):
                            yield p
                return

            if isinstance(obj, (list, tuple)):
                for it in obj:
                    for p in iter_payloads(it):
                        yield p
                return

            yield unwrap_payload(obj)

        # ---------------------------------------------------------------------
        # props helpers
        # ---------------------------------------------------------------------
        def get_props(pl: Payload) -> Dict[str, Any]:
            props = pl.get("props")  # type: ignore[arg-type]
            return props if isinstance(props, dict) else {}

        def get_val(pl: Payload, key: str, default: Any = None) -> Any:
            if key in pl:
                return pl.get(key, default)  # type: ignore[arg-type]
            props = get_props(pl)
            return props.get(key, default)

        def get_dict(pl: Payload, key: str) -> Dict[str, Any]:
            v = get_val(pl, key, {})
            return v if isinstance(v, dict) else {}

        # ---------------------------------------------------------------------
        # Container (UNIT/BULK) helpers (NEW)
        # ---------------------------------------------------------------------
        def get_scope(pl: Payload) -> str:
            scope = get_props(pl).get("scope", "UNIT")
            s = str(scope).strip().upper() if scope is not None else "UNIT"
            return "BULK" if s == "BULK" else "UNIT"

        def get_container_id(pl: Payload) -> str:
            scope = get_scope(pl)
            if scope == "BULK":
                cid = get_props(pl).get("container_id", "DEFAULT")
                c = str(cid).strip() if cid is not None else "DEFAULT"
                return c if c else "DEFAULT"
            # UNIT
            uid = pl.get("unit_id", None)
            if uid is None or str(uid).strip() == "":
                raise ValueError("UNIT payload missing 'unit_id'.")
            return str(uid)

        def container_display_name(scope: str, cid: str) -> str:
            return f"Bulk_{cid}" if scope == "BULK" else f"Unit_{cid}"

        # ---------------------------------------------------------------------
        # Multi-level Assembly annotation reader
        # ---------------------------------------------------------------------
        def get_assembly_path(pl: Payload) -> List[Dict[str, str]]:
            """
            Preferred:
              props["assembly_path"] = [{"name": "...", "key": "..."}, ...]
            Legacy (single level):
              props["assembly"] = {"sub_name": "...", "sub_key": "..."}
            Returns:
              normalized list of {"name": str, "key": str}
            """
            props = get_props(pl)

            ap = props.get("assembly_path")
            out: List[Dict[str, str]] = []

            if isinstance(ap, list):
                for level in ap:
                    if not isinstance(level, dict):
                        continue
                    nm = str(level.get("name", "")).strip()
                    ky = str(level.get("key", "")).strip()
                    if ky == "" and nm == "":
                        continue
                    if ky == "":
                        ky = nm
                    if nm == "":
                        nm = ky
                    out.append({"name": nm, "key": ky})
                return out

            # backward compatible: single-level tag
            asm = props.get("assembly")
            if isinstance(asm, dict):
                sub_key = str(asm.get("sub_key", "")).strip()
                sub_name = str(asm.get("sub_name", "")).strip()
                if sub_key != "":
                    if sub_name == "":
                        sub_name = sub_key
                    return [{"name": sub_name, "key": sub_key}]

            return []

        # ---------------------------------------------------------------------
        # Geometry helpers
        # ---------------------------------------------------------------------
        def brep_to_mesh(brep: "rg.Brep") -> Optional["rg.Mesh"]:
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
                return brep_to_mesh(geo.ToBrep(True))

            if isinstance(geo, rg.Surface):
                brep = geo.ToBrep()
                return brep_to_mesh(brep)

            brep = rg.Brep.TryConvertBrep(geo)
            if brep:
                return brep_to_mesh(brep)

            return None

        def mesh_to_vertices_faces(
            mesh: "rg.Mesh",
        ) -> Tuple[List[Tuple[float, float, float]], List[Tuple[int, int, int]]]:
            if mesh is None or mesh.Vertices.Count == 0:
                return [], []

            m = mesh.DuplicateMesh()
            m.Faces.ConvertQuadsToTriangles()
            m.Normals.ComputeNormals()
            m.Compact()

            verts = [(float(v.X), float(v.Y), float(v.Z)) for v in m.Vertices]
            faces = [(int(f.A), int(f.B), int(f.C)) for f in m.Faces]
            return verts, faces

        # ---------------------------------------------------------------------
        # IFC setup
        # ---------------------------------------------------------------------
        model = ifcopenshell.file(schema="IFC4")

        project = ifc_run(
            "root.create_entity",
            model,
            ifc_class="IfcProject",
            name=f"{StoreyName}_Export",
        )

        ifc_run("unit.assign_unit", model, length={"is_metric": True, "raw": "MILLIMETRE"})

        model_context = ifc_run("context.add_context", model, context_type="Model")
        body_context = ifc_run(
            "context.add_context",
            model,
            context_type="Model",
            context_identifier="Body",
            target_view="MODEL_VIEW",
            parent=model_context,
        )

        site = ifc_run("root.create_entity", model, ifc_class="IfcSite", name="Default Site")
        building = ifc_run("root.create_entity", model, ifc_class="IfcBuilding", name="Default Building")
        storey = ifc_run("root.create_entity", model, ifc_class="IfcBuildingStorey", name=str(StoreyName))
        storey.Elevation = float(StoreyElev)

        ifc_run("aggregate.assign_object", model, products=[site], relating_object=project)
        ifc_run("aggregate.assign_object", model, products=[building], relating_object=site)
        ifc_run("aggregate.assign_object", model, products=[storey], relating_object=building)

        # ---------------------------------------------------------------------
        # Pset helper
        # ---------------------------------------------------------------------
        def add_pset(product: Any, pset_name: str, props: Dict[str, Any]) -> None:
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
            c = (cat or "").strip().lower()
            if c == "vertical":
                return "IfcMember"
            if c == "horizontal":
                return "IfcBeam"
            return "IfcBuildingElementProxy"

        def create_element(payload: Payload) -> Any:
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

            shape = ifc_run(
                "geometry.add_mesh_representation",
                model,
                context=body_context,
                vertices=[verts],
                faces=[faces],
                unit_scale=1.0,
                force_faceted_brep=True,
            )
            ifc_run("geometry.assign_representation", model, product=elem, representation=shape)

            uid = str(payload.get("unit_id", ""))
            props = get_props(payload)
            scope = get_scope(payload)
            container_id = props.get("container_id")

            part_no = get_val(payload, "part_no")
            dims = get_dict(payload, "dims")
            material = get_dict(payload, "material")
            finish = get_dict(payload, "finish")
            color_code = get_val(payload, "color_code")
            source_guid = get_val(payload, "source_guid")

            add_pset(elem, "Pset_CWIdentity", {
                "Scope": scope,
                "UnitId": uid,
                "ContainerId": str(container_id) if container_id is not None else None,
                "PartNo": part_no,
                "Category": cat,
                "SourceGuid": source_guid,
            })

            add_pset(elem, "Pset_CWDimensions", {
                "Length_mm": dims.get("L"),
                "Width_mm": dims.get("W"),
                "Radius_mm": dims.get("R"),
            })

            add_pset(elem, "Pset_CWMaterial", {
                "MaterialName": material.get("name"),
            })

            add_pset(elem, "Pset_CWSurfaceFinish", {
                "FinishType": finish.get("type"),
                "FinishThickness_um": finish.get("thickness_um"),
            })

            add_pset(elem, "Pset_CWAppearance", {
                "ColorCode": color_code,
            })

            return elem

        # ---------------------------------------------------------------------
        # Flatten -> regroup by container (UNIT + BULK)  (UPDATED)
        # ---------------------------------------------------------------------
        payloads: List[Payload] = list(iter_payloads(MatData))
        if not payloads:
            raise ValueError("MatData is empty (no payloads).")

        containers: Dict[Tuple[str, str], List[Payload]] = {}
        for idx, pl in enumerate(payloads):
            scope = get_scope(pl)
            cid = get_container_id(pl)
            containers.setdefault((scope, cid), []).append(pl)

        # basic log header
        Log += f"ifcopenshell version: {getattr(ifcopenshell, 'version', 'unknown')}\n"
        Log += f"Resolved OutPath: {ResolvedOutPath}\n"
        Log += f"Storey: {StoreyName} Elev(mm): {float(StoreyElev)}\n"
        Log += f"Containers: {len(containers)} (UNIT+BULK)\n"
        Log += f"Payloads(flat): {len(payloads)}\n"

        # ---------------------------------------------------------------------
        # Multi-level assembly builder (PER CONTAINER)
        # ---------------------------------------------------------------------
        def ensure_assembly_chain(
            container_elem: Any,
            scope: str,
            container_id: str,
            assembly_path: List[Dict[str, str]],
            node_cache: Dict[Tuple[int, str], Any],
        ) -> Any:
            """
            Create / reuse assemblies under `container_elem` following assembly_path.
            Cache key = (id(parent), level_key)
            Returns deepest assembly element.
            """
            parent = container_elem
            depth = 0

            for lvl in assembly_path:
                depth += 1
                nm = str(lvl.get("name", "")).strip()
                ky = str(lvl.get("key", "")).strip()
                if ky == "" and nm == "":
                    continue
                if ky == "":
                    ky = nm
                if nm == "":
                    nm = ky

                k = (id(parent), ky)
                if k in node_cache:
                    parent = node_cache[k]
                    continue

                asm = ifc_run(
                    "root.create_entity",
                    model,
                    ifc_class="IfcElementAssembly",
                    name=nm,
                )

                ifc_run("aggregate.assign_object", model, products=[asm], relating_object=parent)

                # minimal traceability (low-noise)
                ps = {"Scope": scope, "ContainerId": container_id, "Level": int(depth), "Name": nm}
                if ky != nm:
                    ps["Key"] = ky
                add_pset(asm, "Pset_AssemblyNode", ps)

                node_cache[k] = asm
                parent = asm

            return parent

        created_elements = 0
        created_containers = 0
        created_assembly_nodes = 0

        # iterate containers
        for (scope, cid), items in containers.items():
            cname = container_display_name(scope, cid)

            container = ifc_run(
                "root.create_entity",
                model,
                ifc_class="IfcElementAssembly",
                name=cname,
            )
            created_containers += 1

            # container-specific pset
            if scope == "UNIT":
                add_pset(container, "Pset_Unit", {"UnitId": cid})
            else:
                add_pset(container, "Pset_Bulk", {"ContainerId": cid})

            # place container under storey
            ifc_run("spatial.assign_container", model, products=[container], relating_structure=storey)

            # cache assemblies per container
            node_cache: Dict[Tuple[int, str], Any] = {}

            grouped_count = 0
            direct_count = 0
            cats: List[str] = []

            for pl in items:
                cats.append(str(pl.get("category", "Unspecified")))
                elem = create_element(pl)
                created_elements += 1

                apath = get_assembly_path(pl)
                if apath:
                    deepest = ensure_assembly_chain(container, scope, cid, apath, node_cache)
                    ifc_run("aggregate.assign_object", model, products=[elem], relating_object=deepest)
                    grouped_count += 1
                else:
                    ifc_run("aggregate.assign_object", model, products=[elem], relating_object=container)
                    direct_count += 1

            created_assembly_nodes += len(node_cache)

            Log += (
                f"{cname}: payloads={len(items)} "
                f"with_assembly_path={grouped_count} direct_to_container={direct_count} "
                f"assembly_nodes={len(node_cache)} cats={cats}\n"
            )

        model.write(ResolvedOutPath)

        OK = True
        Log += "\n"
        Log += f"Created elements: {created_elements}\n"
        Log += f"Created containers (UNIT+BULK): {created_containers}\n"
        Log += f"Created assembly nodes (all containers): {created_assembly_nodes}\n"
        Log += f"Wrote: {ResolvedOutPath}\n"

        return OK, Log, ResolvedOutPath

    except Exception as e:
        OK = False
        Log += "\nFAILED:\n" + repr(e) + "\n\n" + traceback.format_exc()
        return OK, Log, None
