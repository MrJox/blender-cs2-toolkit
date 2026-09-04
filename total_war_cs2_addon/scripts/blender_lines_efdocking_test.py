import sys
import traceback

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
OUTPUT_DIR = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin\total_war_cs2_addon\scripts"
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def active_layer_collection_for(collection: bpy.types.Collection) -> bpy.types.LayerCollection:
    def find(layer_collection: bpy.types.LayerCollection):
        if layer_collection.collection == collection:
            return layer_collection
        for child in layer_collection.children:
            found = find(child)
            if found is not None:
                return found
        return None

    result = find(bpy.context.view_layer.layer_collection)
    if result is None:
        raise RuntimeError(f"Could not find layer collection for {collection.name}")
    return result


def add_box(collection: bpy.types.Collection, size: float = 1.0) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(size=size)
    obj = bpy.context.active_object
    for coll in list(obj.users_collection):
        coll.objects.unlink(obj)
    collection.objects.link(obj)
    return obj


def add_uv(obj: bpy.types.Object) -> None:
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project()
    bpy.ops.object.mode_set(mode="OBJECT")


def add_poly_curve(collection: bpy.types.Collection, points: list[tuple[float, float, float]], cyclic: bool, name: str) -> bpy.types.Object:
    curve_data = bpy.data.curves.new(name, type="CURVE")
    curve_data.dimensions = "3D"
    spline = curve_data.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for i, (x, y, z) in enumerate(points):
        spline.points[i].co = (x, y, z, 1.0)
    spline.use_cyclic_u = cyclic
    obj = bpy.data.objects.new(name, curve_data)
    collection.objects.link(obj)
    return obj


def add_plane(collection: bpy.types.Collection, size: float = 2.0) -> bpy.types.Object:
    bpy.ops.mesh.primitive_plane_add(size=size)
    obj = bpy.context.active_object
    for coll in list(obj.users_collection):
        coll.objects.unlink(obj)
    collection.objects.link(obj)
    return obj


def add_edge(collection: bpy.types.Collection, start: tuple[float, float, float], end: tuple[float, float, float], name: str) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([start, end], [(0, 1)], [])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


def main() -> None:
    module = addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    prefs = bpy.context.preferences.addons["total_war_cs2_addon"].preferences
    prefs.assembly_kit_root = ASSEMBLY_KIT_ROOT

    print("=== building / piece / destruct ===")
    bpy.ops.tw_buildings.new_building()
    building = [c for c in bpy.data.collections if c.tw_role == "BUILDING"][-1]
    building.name = "LinesEFDockingUiTest"

    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    bpy.ops.tw_buildings.new_piece()
    piece = building.children[-1]

    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(piece)
    bpy.ops.tw_buildings.new_destruct_level()
    destruct = piece.children[-1]

    display = [c for c in destruct.children if c.tw_role == "DISPLAY"][0]
    collision = [c for c in destruct.children if c.tw_role == "COLLISION"][0]

    lod_obj = add_box(display)
    add_uv(lod_obj)
    _mat_obj = bpy.context.active_object
    _material = bpy.data.materials.new(name=f"{_mat_obj.name}_Material")
    _mat_obj.data.materials.append(_material)
    _mat_obj.active_material = _material
    bpy.ops.tw_buildings.make_material()

    collision_obj = add_box(collision, size=1.1)
    collision_obj.tw_collision_type = "COLLISION"

    print("=== add Lines collection via operator: outline (closed) + ground_ad (open) + a pipe ===")
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(destruct)
    bpy.ops.tw_buildings.add_destruct_collection(role="LINES")
    lines_collection = [c for c in destruct.children if c.tw_role == "LINES"][0]

    outline_obj = add_poly_curve(
        lines_collection, [(-2, -2, 0), (2, -2, 0), (2, 2, 0), (-2, 2, 0)], cyclic=True, name="Outline"
    )
    outline_obj.tw_line_type = "OUTLINE"

    ground_ad_obj = add_poly_curve(lines_collection, [(-1, 0, 0), (1, 0, 0)], cyclic=False, name="GroundAD")
    ground_ad_obj.tw_line_type = "GROUND_AD"

    pipe_obj = add_poly_curve(lines_collection, [(0, 0, 0), (0, 0, 3)], cyclic=False, name="Pipe")
    pipe_obj.tw_line_type = "PIPE_LADDER"

    print("=== calling add_destruct_collection(LINES) again should fail cleanly ===")
    try:
        bpy.ops.tw_buildings.add_destruct_collection(role="LINES")
        raise RuntimeError("Expected the second add_destruct_collection(LINES) call to fail")
    except RuntimeError as error:
        print("correctly refused:", error)

    print("=== add Platform collection via operator (BOB requires EFLines to sit on one) ===")
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(destruct)
    bpy.ops.tw_buildings.add_destruct_collection(role="PLATFORM")
    platform_collection = [c for c in destruct.children if c.tw_role == "PLATFORM"][0]
    # size=8 -> spans X/Y [-4, 4], comfortably covering the EFLine/DockingLine edges added below.
    add_plane(platform_collection, size=8.0)

    print("=== add EFLines collection via operator (separate tech/collection from Docking Lines) ===")
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(destruct)
    bpy.ops.tw_buildings.add_destruct_collection(role="EF_LINES")
    ef_lines_collection = [c for c in destruct.children if c.tw_role == "EF_LINES"][0]

    ef_line_obj = add_edge(ef_lines_collection, (-1, 0, 0), (1, 0, 0), "EFLineTest")
    ef_line_obj.tw_efline_action = "LOW_WALL"

    print("=== add Docking Lines collection via operator (separate tech/collection from EFLines) ===")
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(destruct)
    bpy.ops.tw_buildings.add_destruct_collection(role="DOCKING_LINES")
    docking_lines_collection = [c for c in destruct.children if c.tw_role == "DOCKING_LINES"][0]

    docking_line_obj = add_edge(docking_lines_collection, (-1, 0, 2), (1, 0, 2), "DockingLineTest")

    print("=== add Region Zones collection via operator ===")
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    bpy.ops.tw_buildings.add_building_collection(role="REGION_ZONES")
    region_zones_collection = [c for c in building.children if c.tw_role == "REGION_ZONES"][0]
    region_zone_obj = add_poly_curve(
        region_zones_collection, [(-5, -5, 0), (5, -5, 0), (5, 5, 0), (-5, 5, 0)], cyclic=True, name="RegionZone"
    )

    print("=== calling add_building_collection(REGION_ZONES) again should fail cleanly ===")
    try:
        bpy.ops.tw_buildings.add_building_collection(role="REGION_ZONES")
        raise RuntimeError("Expected the second add_building_collection(REGION_ZONES) call to fail")
    except RuntimeError as error:
        print("correctly refused:", error)

    print("=== validate ===")
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    bpy.ops.tw_buildings.validate()

    print("=== export ===")
    result = bpy.ops.tw_buildings.export_building(directory=OUTPUT_DIR)
    print("export operator result:", result)

    exported_path = f"{OUTPUT_DIR}\\{building.name}.CS2"
    from binary.cs2_reader import read_cs2

    with open(exported_path, "rb") as f:
        data = f.read()
    doc = read_cs2(data)
    print(
        "re-parsed OK:",
        doc.scene_block.rigid_models_count, "rigid,",
        doc.scene_block.lines_count, "lines,",
        doc.scene_block.materials_count, "materials",
    )
    for ln in doc.lines:
        verts = ln.geometry_chunks[0].lines[0].vertices
        print(" line", ln.node_name, "verts:", len(verts), "first==last:", verts[0] == verts[-1])
    for rm in doc.rigid_models:
        if rm.node_name.startswith("EFline_") or rm.node_name.startswith("DockingLine_"):
            chunk = rm.geometry_chunks[0]
            print(" zero-geo rigid", rm.node_name, "verts:", len(chunk.vertices))
            print("   user_defined_properties:", repr(rm.user_defined_properties))

    print("=== LINES / EFLINE / DOCKING LINE / REGION ZONE UI TEST PASSED ===")


try:
    main()
except Exception:
    print("=== LINES / EFLINE / DOCKING LINE / REGION ZONE UI TEST FAILED ===")
    traceback.print_exc()
    sys.exit(1)
