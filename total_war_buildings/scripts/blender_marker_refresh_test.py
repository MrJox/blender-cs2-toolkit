import re
import sys
import traceback

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
OUTPUT_DIR = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin\total_war_buildings\scripts"
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def active_layer_collection_for(collection):
    def find(layer_collection):
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


def add_box(collection, size=1.0):
    bpy.ops.mesh.primitive_cube_add(size=size)
    obj = bpy.context.active_object
    for coll in list(obj.users_collection):
        coll.objects.unlink(obj)
    collection.objects.link(obj)
    return obj


def add_uv(obj):
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project()
    bpy.ops.object.mode_set(mode="OBJECT")


def add_plane(collection, size=2.0):
    bpy.ops.mesh.primitive_plane_add(size=size)
    obj = bpy.context.active_object
    for coll in list(obj.users_collection):
        coll.objects.unlink(obj)
    collection.objects.link(obj)
    return obj


def parse_udp(text):
    return {key.strip(): value for key, value in (line.split("=", 1) for line in text.split("\r\n") if line)}


def parse_vec(text):
    return tuple(float(value) for value in re.findall(r'"([-0-9.eE+]+)"', text))


def build_scene():
    bpy.ops.tw_buildings.new_building()
    building = [c for c in bpy.data.collections if c.tw_role == "BUILDING"][-1]
    building.name = "MarkerRefreshTest"

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
    material = bpy.data.materials.new(name="MarkerRefreshTest_Material")
    lod_obj.data.materials.append(material)
    lod_obj.active_material = material
    bpy.ops.tw_buildings.make_material()

    collision_obj = add_box(collision, size=1.1)
    collision_obj.tw_collision_type = "COLLISION"

    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(destruct)
    bpy.ops.tw_buildings.add_destruct_collection(role="PLATFORM")
    platform_collection = [c for c in destruct.children if c.tw_role == "PLATFORM"][0]
    add_plane(platform_collection, size=200.0)

    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(destruct)
    bpy.ops.tw_buildings.add_destruct_collection(role="EF_LINES")
    ef_collection = [c for c in destruct.children if c.tw_role == "EF_LINES"][0]
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(ef_collection)
    bpy.ops.tw_buildings.new_marker_line()
    ef_obj = bpy.context.active_object

    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(destruct)
    bpy.ops.tw_buildings.add_destruct_collection(role="DOCKING_LINES")
    docking_collection = [c for c in destruct.children if c.tw_role == "DOCKING_LINES"][0]
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(docking_collection)
    bpy.ops.tw_buildings.new_marker_line()
    docking_obj = bpy.context.active_object

    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    bpy.ops.tw_buildings.add_building_collection(role="REGION_ZONES")
    zone_collection = [c for c in building.children if c.tw_role == "REGION_ZONES"][0]
    curve = bpy.data.curves.new("Zone", "CURVE")
    curve.dimensions = "3D"
    spline = curve.splines.new("POLY")
    spline.points.add(3)
    for index, point in enumerate([(0, 0, 0), (4, 0, 0), (4, 4, 0), (0, 4, 0)]):
        spline.points[index].co = (*point, 1.0)
    spline.use_cyclic_u = True
    zone_obj = bpy.data.objects.new("Zone", curve)
    zone_collection.objects.link(zone_obj)

    return building, ef_obj, docking_obj, zone_obj, ef_collection, docking_collection, zone_collection


def export_and_read(building):
    from binary.cs2_reader import read_cs2

    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    bpy.ops.tw_buildings.export_building(directory=OUTPUT_DIR)
    with open(rf"{OUTPUT_DIR}\{building.name}.CS2", "rb") as handle:
        doc = read_cs2(handle.read())

    rigid_models = {node.node_name: node for node in doc.rigid_models}
    lines = {node.node_name: node for node in doc.lines}
    ef_udp = parse_udp(rigid_models["EFline_piece01_destruct01_line01"].user_defined_properties)
    docking_udp = parse_udp(rigid_models["DockingLine_piece01_destruct01_line01"].user_defined_properties)
    zone_udp = parse_udp(lines["region_zone01"].user_defined_properties)
    return {
        "efline": parse_vec(ef_udp["EFLine_Info"]),
        "dockingline": parse_vec(docking_udp["DockingLine_Info"]),
        "region_zone": parse_vec(zone_udp["Region_pos1"]),
    }


def check(label, got, expected):
    print(f"  {label}: {tuple(round(v, 3) for v in got)} expected {expected}")
    for got_value, expected_value in zip(got, expected):
        if abs(got_value - expected_value) > 0.001:
            raise RuntimeError(f"{label} exported {got} but the object sits at {expected}")


def main() -> None:
    module = addon_utils.enable("total_war_buildings", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    bpy.context.preferences.addons["total_war_buildings"].preferences.assembly_kit_root = ASSEMBLY_KIT_ROOT

    building, ef_obj, docking_obj, zone_obj, ef_collection, docking_collection, zone_collection = build_scene()

    print("=== markers export where they were authored ===")
    udp = export_and_read(building)
    check("EFLine_Info", udp["efline"], (-1.0, 0.0, 0.0))
    check("DockingLine_Info", udp["dockingline"], (-1.0, 0.0, 0.0))
    check("Region_pos1", udp["region_zone"], (0.0, 0.0, 0.0))

    print("=== a plain move re-exports from the new position ===")
    ef_obj.location = (0.0, 12.0, 0.0)
    docking_obj.location = (0.0, -9.0, 0.0)
    zone_obj.location = (20.0, 0.0, 0.0)
    udp = export_and_read(building)
    check("EFLine_Info", udp["efline"], (-1.0, 12.0, 0.0))
    check("DockingLine_Info", udp["dockingline"], (-1.0, -9.0, 0.0))
    check("Region_pos1", udp["region_zone"], (20.0, 0.0, 0.0))

    print("=== an edit-mode move re-exports from the new position ===")
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = ef_obj
    ef_obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.transform.translate(value=(0.0, 3.0, 0.0))
    bpy.ops.object.mode_set(mode="OBJECT")
    udp = export_and_read(building)
    check("EFLine_Info", udp["efline"], (-1.0, 15.0, 0.0))

    # matrix_world only refreshes while the view layer evaluates the object, so a marker moved while
    # its monitor icon or collection tick was off used to export the position it had before the move.
    print("=== a move made while the object is hidden from the viewport still re-exports ===")
    for obj in (ef_obj, docking_obj, zone_obj):
        obj.hide_viewport = True
    bpy.context.view_layer.update()
    ef_obj.location = (0.0, 40.0, 0.0)
    docking_obj.location = (0.0, -41.0, 0.0)
    zone_obj.location = (42.0, 0.0, 0.0)
    udp = export_and_read(building)
    check("EFLine_Info", udp["efline"], (-1.0, 43.0, 0.0))
    check("DockingLine_Info", udp["dockingline"], (-1.0, -41.0, 0.0))
    check("Region_pos1", udp["region_zone"], (42.0, 0.0, 0.0))
    for obj in (ef_obj, docking_obj, zone_obj):
        if not obj.hide_viewport:
            raise RuntimeError(f"'{obj.name}' was left visible after the export restored its state")
        obj.hide_viewport = False
    bpy.context.view_layer.update()

    print("=== a move made while the collection is hidden from the viewport still re-exports ===")
    for collection in (ef_collection, docking_collection, zone_collection):
        collection.hide_viewport = True
    bpy.context.view_layer.update()
    ef_obj.location = (0.0, 50.0, 0.0)
    docking_obj.location = (0.0, -51.0, 0.0)
    zone_obj.location = (52.0, 0.0, 0.0)
    udp = export_and_read(building)
    check("EFLine_Info", udp["efline"], (-1.0, 53.0, 0.0))
    check("DockingLine_Info", udp["dockingline"], (-1.0, -51.0, 0.0))
    check("Region_pos1", udp["region_zone"], (52.0, 0.0, 0.0))
    for collection in (ef_collection, docking_collection, zone_collection):
        if not collection.hide_viewport:
            raise RuntimeError(f"'{collection.name}' was left visible after the export restored its state")
        collection.hide_viewport = False
    bpy.context.view_layer.update()

    print("=== a move made while the collection is excluded from the view layer still re-exports ===")
    layer_collections = [active_layer_collection_for(c) for c in (ef_collection, docking_collection, zone_collection)]
    for layer_collection in layer_collections:
        layer_collection.exclude = True
    bpy.context.view_layer.update()
    ef_obj.location = (0.0, 60.0, 0.0)
    docking_obj.location = (0.0, -61.0, 0.0)
    zone_obj.location = (62.0, 0.0, 0.0)
    udp = export_and_read(building)
    check("EFLine_Info", udp["efline"], (-1.0, 63.0, 0.0))
    check("DockingLine_Info", udp["dockingline"], (-1.0, -61.0, 0.0))
    check("Region_pos1", udp["region_zone"], (62.0, 0.0, 0.0))
    for layer_collection in layer_collections:
        if not layer_collection.exclude:
            raise RuntimeError(f"'{layer_collection.name}' was left included after the export restored its state")

    print("\nALL MARKER REFRESH CHECKS PASSED")


try:
    main()
except Exception:
    traceback.print_exc()
    sys.exit(1)
