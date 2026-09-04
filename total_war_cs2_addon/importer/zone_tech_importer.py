import os
import math
import xml.etree.ElementTree as ET
import bpy

Vec3 = tuple[float, float, float]


def _to_blender_space(vector: Vec3) -> Vec3:
    # Inverse of extraction._to_engine_space, which is its own inverse.
    x, y, z = vector
    return (x, z, y)


def find_zone_tech_xml(filepath: str) -> str | None:
    dir_path = os.path.dirname(filepath)
    filename = os.path.basename(filepath)
    filename_lower = filename.lower()

    stems = []

    if filename_lower.endswith(".cs2.parsed"):
        stem = filename[:-11]
        stems.append(stem)
        if stem.lower().endswith("_tech"):
            stems.append(stem[:-5])
    elif filename_lower.endswith(".cs2"):
        stem = filename[:-4]
        stems.append(stem)
        if stem.lower().endswith("_tech"):
            stems.append(stem[:-5])
    else:
        stem = os.path.splitext(filename)[0]
        stems.append(stem)
        if stem.lower().endswith("_tech"):
            stems.append(stem[:-5])

    candidates = []
    for s in stems:
        candidates.append(os.path.join(dir_path, f"{s}_zone_tech.xml"))
        candidates.append(os.path.join(dir_path, f"{s}_tech_zone_tech.xml"))

    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate

    return None


def import_zone_tech_xml(xml_path: str, building_coll: bpy.types.Collection) -> int:
    tree = ET.parse(xml_path)
    root = tree.getroot()

    regions_data: list[tuple[str, list[Vec3]]] = []

    for group_tag in ("zone_regions", "go_regions", "no_go_regions"):
        group_elem = root.find(group_tag)
        if group_elem is not None:
            for region_elem in group_elem.findall("region"):
                region_name = region_elem.attrib.get("name", f"region_zone{len(regions_data) + 1:02d}")
                points: list[Vec3] = []
                for pt_elem in region_elem.findall("point"):
                    x = float(pt_elem.attrib.get("x", "0.0"))
                    y = float(pt_elem.attrib.get("y", "0.0"))
                    z = float(pt_elem.attrib.get("z", "0.0"))
                    points.append((x, y, z))
                if len(points) >= 3:
                    regions_data.append((region_name, points))

    if not regions_data:
        return 0

    region_zones_colls = [child for child in building_coll.children if child.tw_role == "REGION_ZONES"]
    if region_zones_colls:
        region_zones_coll = region_zones_colls[0]
    else:
        region_zones_coll = bpy.data.collections.new("Region Zones")
        region_zones_coll.tw_role = "REGION_ZONES"
        building_coll.children.link(region_zones_coll)

    for region_name, pts in regions_data:
        blender_pts = [_to_blender_space(pt) for pt in pts]
        if (
            len(blender_pts) > 2
            and math.isclose(blender_pts[0][0], blender_pts[-1][0], abs_tol=1e-3)
            and math.isclose(blender_pts[0][1], blender_pts[-1][1], abs_tol=1e-3)
            and math.isclose(blender_pts[0][2], blender_pts[-1][2], abs_tol=1e-3)
        ):
            blender_pts = blender_pts[:-1]

        curve_data = bpy.data.curves.new(region_name, type="CURVE")
        curve_data.dimensions = "3D"
        spline = curve_data.splines.new("POLY")
        spline.use_cyclic_u = True  # Region zones are closed loops!
        spline.points.add(len(blender_pts) - 1)
        for pt_idx, pt in enumerate(blender_pts):
            spline.points[pt_idx].co = (pt[0], pt[1], pt[2], 1.0)

        curve_obj = bpy.data.objects.new(region_name, curve_data)
        region_zones_coll.objects.link(curve_obj)

    return len(regions_data)
