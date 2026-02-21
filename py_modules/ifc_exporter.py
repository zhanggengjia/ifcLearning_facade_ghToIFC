# -*- coding: utf-8 -*-
"""
ifc_exporter.py

This version keeps your existing utils untouched and only refactors exporter
to use the new additive helper module: utils/exporter_utils.py

Key contract:
- UNIT payload MUST have top-level payload["unit_id"]
- props["assembly_path"] supports list[dict] and list[str] ("name|role") formats
- legacy props["assembly"] is supported
"""

from __future__ import annotations

import os
import traceback
from typing import Any, Dict, List, Optional, Tuple

from ifc_types import Payload

from ifc_color_csv import load_color_map_csv_with_diag, resolve_view_color

from utils.path_utils import normalize_outpath
from utils.gh_utils import tname
from utils.viewColor_utils import apply_view_color
from utils.payload_utils import ensure_props

from utils.exporter_utils import (
    collect_payloads,
    group_by_container,
    get_scope,
    get_kind,
    build_psets_for_payload,
    container_display_name,
    parse_assembly_path,
    ensure_assembly_chain,
    resolve_guid_json_path,
    locked_guid_db,
    ensure_source_guid_from_json_inplace,
)


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

        import Grasshopper as gh
        gh_path = gh.Instances.ActiveCanvas.Document.FilePath
        proj_dir = os.path.dirname(gh_path) if gh_path else os.getcwd()
        csv_path = os.path.join(proj_dir, "py_modules", "colorList.csv")

        COLOR_MAP, diag = load_color_map_csv_with_diag(csv_path)

        Log += f"[Color] csv_path = {csv_path}\n"
        Log += f"[Color] diag = {diag}\n"
        Log += f"[Color] entries = {len(COLOR_MAP)}\n"

        DEFAULT_VIEW_COLOR = (0.75, 0.75, 0.75)
        STYLE_CACHE: Dict[Any, Any] = {}

        def log_add(s: str) -> None:
            nonlocal Log
            Log += s

        # ---------------------------------------------------------------------
        # OutPath normalization (uses your existing utils.path_utils.normalize_outpath)
        # ---------------------------------------------------------------------
        storey_name_str = str(StoreyName) if StoreyName is not None else "Storey"
        ResolvedOutPath: str = normalize_outpath(OutPath, storey_name_str)

        # ---------------------------------------------------------------------
        # IFC setup
        # ---------------------------------------------------------------------
        model = ifcopenshell.file(schema="IFC4")

        project = ifc_run(
            "root.create_entity",
            model,
            ifc_class="IfcProject",
            name=f"{storey_name_str}_Export",
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
        storey = ifc_run("root.create_entity", model, ifc_class="IfcBuildingStorey", name=storey_name_str)

        try:
            storey.Elevation = float(StoreyElev)
        except Exception:
            storey.Elevation = 0.0

        ifc_run("aggregate.assign_object", model, products=[site], relating_object=project)
        ifc_run("aggregate.assign_object", model, products=[building], relating_object=site)
        ifc_run("aggregate.assign_object", model, products=[storey], relating_object=building)

        # ---------------------------------------------------------------------
        # Pset helper
        # ---------------------------------------------------------------------
        def add_pset(product: Any, pset_name: str, props: Dict[str, Any]) -> None:
            """
            Add or merge properties into a Pset.

            If pset_name already exists on product, merge properties (new values override existing).
            Otherwise create new Pset.
            """
            if not props:
                return
            clean = {k: v for k, v in props.items() if v is not None and v != ""}
            if not clean:
                return

            # Check if Pset already exists on this product
            existing_pset = None
            if hasattr(product, 'IsDefinedBy') and product.IsDefinedBy:
                for rel in product.IsDefinedBy:
                    if hasattr(rel, 'RelatingPropertyDefinition'):
                        pdef = rel.RelatingPropertyDefinition
                        if hasattr(pdef, 'Name') and pdef.Name == pset_name:
                            existing_pset = pdef
                            break

            if existing_pset:
                # Merge: get existing properties, update with new ones
                existing_props = {}
                if hasattr(existing_pset, 'HasProperties') and existing_pset.HasProperties:
                    for prop in existing_pset.HasProperties:
                        if hasattr(prop, 'Name') and hasattr(prop, 'NominalValue'):
                            prop_name = prop.Name
                            # Extract value from IfcPropertySingleValue
                            if hasattr(prop.NominalValue, 'wrappedValue'):
                                existing_props[prop_name] = prop.NominalValue.wrappedValue
                            else:
                                # Fallback: use NominalValue directly
                                existing_props[prop_name] = prop.NominalValue

                # Merge: new properties override existing (allowing user overrides to take precedence)
                merged = {**existing_props, **clean}
                log_add(
                    f"[DEBUG] Merging Pset '{pset_name}' on {getattr(product, 'Name', 'Unknown')}: "
                    f"existing={list(existing_props.keys())}, new={list(clean.keys())}, merged={list(merged.keys())}\n"
                )
                ifc_run("pset.edit_pset", model, pset=existing_pset, properties=merged)
            else:
                # Create new Pset
                pset = ifc_run("pset.add_pset", model, product=product, name=pset_name)
                ifc_run("pset.edit_pset", model, pset=pset, properties=clean)

        # ---------------------------------------------------------------------
        # Geometry helpers (keep local: exporter policy, not util)
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
            props = ensure_props(payload)

            name = str(payload.get("name", "Unnamed"))
            cat = str(payload.get("category", "Unspecified"))

            hint = props.get("ifc_class_hint")
            if hint is not None and str(hint).strip():
                ifc_class = str(hint).strip()
            else:
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

            # viewer color
            name_key = (elem.Name or "").strip()
            rgb = resolve_view_color(name_key, COLOR_MAP, DEFAULT_VIEW_COLOR)
            ok, msg = apply_view_color(model, shape, rgb, style_cache=STYLE_CACHE)
            if not ok:
                log_add("[Color] " + msg + "\n")

            # psets
            # - scope controls container ownership (UNIT / NON_UNIT)
            # - kind controls element semantics (Part / Bulk)
            scope = get_scope(payload)
            kind = get_kind(payload)

            # Core Psets (schema-driven)
            for pset_name, pset_props in build_psets_for_payload(payload, scope=scope, kind=kind):
                add_pset(elem, pset_name, pset_props)

            # User overrides (from GH override component)
            overrides = props.get("pset_overrides")
            if isinstance(overrides, dict):
                for pset_name, kv in overrides.items():
                    if not isinstance(pset_name, str) or not pset_name.strip():
                        continue
                    if not isinstance(kv, dict):
                        continue
                    add_pset(elem, pset_name.strip(), kv)

            return elem

        # ---------------------------------------------------------------------
        # Payloads: collect + group by container
        # ---------------------------------------------------------------------
        payloads, bad = collect_payloads(MatData, log_fn=log_add)
        if not payloads:
            raise ValueError(f"MatData is empty (no payloads). ignored_non_payload={bad}")

        # -----------------------------------------------------------------
        # Stable source_guid assignment (JSON-backed)
        # - Builder may output props['source_guid']=None.
        # - We key by (unit_id, part name, bbox center) and persist to guid_file.json.
        # - Skip AssemblyMeta payloads (no geometry, no GUID needed)
        # -----------------------------------------------------------------
        guid_json_path = resolve_guid_json_path(ResolvedOutPath)
        with locked_guid_db(guid_json_path) as guid_db:
            for p in payloads:
                # Skip GUID assignment for AssemblyMeta (category-based check)
                cat = str(p.get("category", "") or "").strip()
                if cat == "__ASSEMBLY_META__":
                    continue
                ensure_source_guid_from_json_inplace(p, guid_db, storey_name=storey_name_str, decimals=3)

        # DEBUG: Category statistics
        from collections import Counter
        cat_counts = Counter(str(p.get("category", "")).strip() for p in payloads)
        log_add(f"[DEBUG] Category counts: {dict(cat_counts)}\n")
        assembly_meta_count = cat_counts.get("__ASSEMBLY_META__", 0)
        if assembly_meta_count > 0:
            log_add(f"[DEBUG] Found {assembly_meta_count} AssemblyMeta payloads\n")
            # Sample first AssemblyMeta
            for p in payloads:
                if str(p.get("category", "")).strip() == "__ASSEMBLY_META__":
                    props_sample = p.get("props", {})
                    log_add(
                        f"[DEBUG] Sample AssemblyMeta: name={p.get('name','')!r} "
                        f"unit_id={p.get('unit_id','')!r} geo={p.get('geo')} "
                        f"pset_overrides={props_sample.get('pset_overrides',{})!r} "
                        f"assembly_path={props_sample.get('assembly_path',[])!r}\n"
                    )
                    break

        containers = group_by_container(payloads, log_fn=log_add)

        Log += f"ifcopenshell version: {getattr(ifcopenshell, 'version', 'unknown')}\n"
        Log += f"Resolved OutPath: {ResolvedOutPath}\n"
        Log += f"Guid JSON: {guid_json_path}\n"
        Log += f"Storey: {storey_name_str} Elev(mm): {storey.Elevation}\n"
        Log += f"Containers: {len(containers)} (UNIT/NON_UNIT)\n"
        Log += f"Payloads(flat): {len(payloads)} (ignored non-payload: {bad})\n"

        # ---------------------------------------------------------------------
        # Build containers + nested assemblies, assign elements
        # ---------------------------------------------------------------------
        created_elements = 0
        created_containers = 0
        created_assembly_nodes = 0

        for (scope, cid), items in containers.items():
            # Derive container name from outermost assembly_path level if available.
            # This allows ifc_assembly to control the top-level name (e.g. per-unit names).
            # Fallback to auto-generated name (e.g. "Unit_XXX") if no assembly_path.
            first_apath = None
            for _pl in items:
                _ap = parse_assembly_path(_pl)
                if _ap:
                    first_apath = _ap
                    break

            if first_apath:
                cname = first_apath[0].get("name", container_display_name(scope, cid))
            else:
                cname = container_display_name(scope, cid)

            container = ifc_run("root.create_entity", model, ifc_class="IfcElementAssembly", name=cname)
            created_containers += 1

            # container pset
            if scope == "UNIT":
                add_pset(container, "Pset_Unit", {
                    "UnitCode": cid,
                    "BayNo": None,
                    "Level": None,
                    "InstallSequence": None,
                })
            else:
                add_pset(container, "Pset_NonUnit", {"GroupCode": cid, "Scope": scope})

            ifc_run("spatial.assign_container", model, products=[container], relating_structure=storey)

            # assembly nodes cache per container
            node_cache: Dict[Tuple[int, str], Any] = {}

            grouped = 0
            direct = 0

            for pl in items:
                # -----------------------------------------------------------------
                # AssemblyMeta payloads (no geometry): write psets to the assembly node
                # -----------------------------------------------------------------
                try:
                    props = ensure_props(pl)
                except Exception:
                    props = {}


                cat = str(pl.get("category", "") or "").strip()
                apath = parse_assembly_path(pl)

                # STRICT: only category == "__ASSEMBLY_META__" is AssemblyMeta
                is_assembly_meta = (cat == "__ASSEMBLY_META__")

                # ---- AssemblyMeta payloads (no geometry): write psets to the assembly node ----
                if is_assembly_meta:
                    # Spec: geo MUST be None. If not, ignore geometry and warn.
                    if pl.get("geo", None) is not None:
                        log_add(
                            f"[WARN] AssemblyMeta payload has geo!=None; ignoring geo. "
                            f"name={pl.get('name','')!r} cat={cat!r}\n"
                        )

                    if apath:
                        # Strip outermost level (already used as container name).
                        # Inner levels form the sub-assembly chain under the container.
                        inner_apath = apath[1:]

                        if inner_apath:
                            deepest = ensure_assembly_chain(
                                ifc_run=ifc_run,
                                model=model,
                                container_elem=container,
                                scope=scope,
                                container_id=cid,
                                assembly_path=inner_apath,
                                node_cache=node_cache,
                                add_pset=add_pset,
                            )
                        else:
                            # Only outermost level existed -> overrides apply to container itself
                            deepest = container

                        overrides = props.get("pset_overrides")
                        log_add(
                            f"[DEBUG] AssemblyMeta: name={pl.get('name','')!r} apath={apath} "
                            f"inner_apath={inner_apath} overrides={overrides!r}\n"
                        )
                        if isinstance(overrides, dict):
                            for pset_name, kv in overrides.items():
                                if not isinstance(pset_name, str) or not pset_name.strip():
                                    continue
                                if not isinstance(kv, dict):
                                    continue
                                log_add(
                                    f"[DEBUG] Calling add_pset on {getattr(deepest, 'Name', 'Unknown')}: "
                                    f"pset_name={pset_name!r} kv={kv!r}\n"
                                )
                                add_pset(deepest, pset_name.strip(), kv)
                        grouped += 1
                    else:
                        # No assembly_path means nowhere to apply; warn and skip.
                        log_add(
                            f"[WARN] AssemblyMeta payload missing assembly_path; skipped. "
                            f"name={pl.get('name','')!r} cat={cat!r}\n"
                        )
                    continue

                # ---- Normal payloads: geo is required to create an IFC element ----
                if pl.get("geo", None) is None:
                    # This is NOT AssemblyMeta (category differs), so treat as data error and skip.
                    log_add(
                        f"[WARN] Non-AssemblyMeta payload has geo=None; skipped. "
                        f"name={pl.get('name','')!r} cat={cat!r}\n"
                    )
                    continue

                # -----------------------------------------------------------------
                # Normal element payloads
                # -----------------------------------------------------------------
                elem = create_element(pl)
                created_elements += 1

                if apath:
                    # Strip outermost level (already used as container name).
                    inner_apath = apath[1:]

                    if inner_apath:
                        deepest = ensure_assembly_chain(
                            ifc_run=ifc_run,
                            model=model,
                            container_elem=container,
                            scope=scope,
                            container_id=cid,
                            assembly_path=inner_apath,
                            node_cache=node_cache,
                            add_pset=add_pset,
                        )
                        ifc_run("aggregate.assign_object", model, products=[elem], relating_object=deepest)
                    else:
                        # Only outermost level -> element goes directly under container
                        ifc_run("aggregate.assign_object", model, products=[elem], relating_object=container)
                    grouped += 1
                else:
                    ifc_run("aggregate.assign_object", model, products=[elem], relating_object=container)
                    direct += 1

            created_assembly_nodes += len(node_cache)

            Log += (
                f"{cname}: payloads={len(items)} "
                f"with_assembly_path={grouped} direct_to_container={direct} "
                f"assembly_nodes={len(node_cache)}\n"
            )

        model.write(ResolvedOutPath)

        OK = True
        Log += "\n"
        Log += f"Created elements: {created_elements}\n"
        Log += f"Created containers (UNIT+NON_UNIT): {created_containers}\n"
        Log += f"Created assembly nodes (all containers): {created_assembly_nodes}\n"
        Log += f"Wrote: {ResolvedOutPath}\n"

        return OK, Log, ResolvedOutPath

    except Exception as e:
        OK = False
        Log += "\nFAILED:\n" + repr(e) + "\n\n" + traceback.format_exc()
        return OK, Log, None
