
def apply_view_color(model, shape_rep, rgb, style_cache=None):
  """
  IFC4 viewer color (BIMVision-friendly for Brep):
  - Changed to use IfcSurfaceStyleShading instead of Rendering for max compatibility.
  - Attach IfcStyledItem to:
      1) representation item itself
      2) if item is IfcFacetedBrep: ALSO attach to its Outer shell (IfcClosedShell)
  """
  try:
      r, g, b = float(rgb[0]), float(rgb[1]), float(rgb[2])
  except Exception:
      return False, "invalid rgb"

  cache = style_cache if isinstance(style_cache, dict) else None
  key = (round(r, 6), round(g, 6), round(b, 6))

  try:
      psa = cache.get(key) if cache is not None else None
      if psa is None:
          colour = model.create_entity("IfcColourRgb", None, r, g, b)

          # [FIXED FOR BIMVISION]
          # Use IfcSurfaceStyleShading. BIMVision handles Shading reliably.
          # Rendering often fails if not fully defined.
          shading = model.create_entity(
              "IfcSurfaceStyleShading",
              colour
          )

          surf_style = model.create_entity("IfcSurfaceStyle", None, "BOTH", [shading])
          psa = model.create_entity("IfcPresentationStyleAssignment", [surf_style])

          if cache is not None:
              cache[key] = psa

      items = getattr(shape_rep, "Items", None) or []
      for it in items:
          # 1) style the item itself
          try:
              model.create_entity("IfcStyledItem", it, [psa], None)
          except Exception:
              pass

          # 2) if Brep: style its outer shell too (BIMVision often reads here)
          try:
              if it.is_a("IfcFacetedBrep") and hasattr(it, "Outer") and it.Outer:
                  model.create_entity("IfcStyledItem", it.Outer, [psa], None)
          except Exception:
              pass

      return True, ""
  except Exception as e:
      return False, "apply_view_color failed: " + repr(e)

