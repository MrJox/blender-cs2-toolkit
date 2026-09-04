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
    return dict(line.split(" = ", 1) for line in text.split(chr(13) + chr(10)) if line)


def parse_vec(text):
    return tuple(float(v) for v in re.findall(r'"([-0-9.eE+]+)"', text))


def select_only(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def expect_vec(label, got, want, tolerance=0.001):
    for a, b in zip(got, want):
        if abs(a - b) > tolerance:
            raise RuntimeError(f"{label}: expected {want}, got {got}")
    print(f"  {label}: {tuple(round(v, 3) for v in got)}")


def main() -> None:
    module = addon_utils.enable("total_war_buildings", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    bpy.context.preferences.addons["total_war_buildings"].preferences.assembly_kit_root = ASSEMBLY_KIT_ROOT

    bpy.ops.tw_buildings.new_building()
    building = [c for c in bpy.data.collections if c.tw_role == "BUILDING"][-1]
    building.name = "EFLineDirectionTest"

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
    material = bpy.data.materials.new(name="EFLineDirectionTest_Material")
    lod_obj.data.materials.append(material)
    lod_obj.active_material = material
    bpy.ops.tw_buildings.make_material()
    collision_obj = add_box(collision, size=1.1)
    collision_obj.tw_collision_type = "COLLISION"

    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(destruct)
    bpy.ops.tw_buildings.add_destruct_collection(role="PLATFORM")
    platform_collection = [c for c in destruct.children if c.tw_role == "PLATFORM"][0]
    add_plane(platform_collection, size=8.0)

    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(destruct)
    bpy.ops.tw_buildings.add_destruct_collection(role="EF_LINES")
    ef_collection = [c for c in destruct.children if c.tw_role == "EF_LINES"][0]

    print("=== New Line builds the MaxScript T shape ===")
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(ef_collection)
    bpy.ops.tw_buildings.new_marker_line()
    default_line = bpy.context.active_object
    points = [tuple(v.co) for v in default_line.data.vertices]
    edges = sorted(tuple(e.vertices) for e in default_line.data.edges)
    print("  vertices:", [tuple(round(c, 3) for c in p) for p in points])
    print("  edges:", edges)
    if len(points) != 4:
        raise RuntimeError(f"New Line should build 4 vertices (start, midpoint, end, tip), got {len(points)}")
    if edges != [(0, 1), (1, 2), (1, 3)]:
        raise RuntimeError(f"New Line should wire start-mid, mid-end and mid-tip, got {edges}")
    # TWBuildingsTech.ms: pt_mid + [-Rv.y, Rv.x, 0] with Rv = pt_mid - pt_start.
    expect_vec("midpoint", points[1], (0.0, 0.0, 0.0))
    expect_vec("pointer tip", points[3], (0.0, 1.0, 0.0))

    print("=== a second line, aimed the opposite way by moving only its tip ===")
    bpy.ops.tw_buildings.new_marker_line()
    flipped_line = bpy.context.active_object
    flipped_line.name = "FlippedEFLine"
    flipped_line.location = (0.0, 2.0, 0.0)
    flipped_line.data.vertices[3].co = (0.0, -1.0, 0.0)

    print("=== a legacy 2-vertex line still exports ===")
    legacy_mesh = bpy.data.meshes.new("LegacyEFLine")
    legacy_mesh.from_pydata([(-1.0, -2.0, 0.0), (1.0, -2.0, 0.0)], [(0, 1)], [])
    legacy_mesh.update()
    legacy_line = bpy.data.objects.new("LegacyEFLine", legacy_mesh)
    ef_collection.objects.link(legacy_line)

    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    bpy.ops.tw_buildings.export_building(directory=OUTPUT_DIR)

    from binary.cs2_reader import read_cs2

    with open(rf"{OUTPUT_DIR}\{building.name}.CS2", "rb") as f:
        doc = read_cs2(f.read())

    ef_nodes = [n for n in doc.rigid_models if "EFLine_Info" in (n.user_defined_properties or "")]
    if len(ef_nodes) != 3:
        raise RuntimeError(f"Expected 3 EFLine nodes, got {len(ef_nodes)}")
    directions = {}
    for node in ef_nodes:
        udp = parse_udp(node.user_defined_properties)
        directions[parse_vec(udp["EFLine_Info"])[1]] = parse_vec(udp["EFLine_Direction"])

    print("=== the exported direction is the pointer the artist can see ===")
    expect_vec("default line (tip at +Y)", directions[0.0], (0.0, 1.0, 0.0))
    expect_vec("flipped line (tip moved to -Y)", directions[2.0], (0.0, -1.0, 0.0))
    expect_vec("legacy 2-vertex line", directions[-2.0], (0.0, 1.0, 0.0))
    if directions[0.0][1] * directions[2.0][1] >= 0.0:
        raise RuntimeError("Moving only the pointer tip should flip the exported direction")

    print("=== Reset Direction Pointer restores the perpendicular ===")
    select_only(flipped_line)
    bpy.ops.tw_buildings.reset_marker_line_direction()
    expect_vec("tip after reset", tuple(flipped_line.data.vertices[3].co), (0.0, 1.0, 0.0))

    print("=== Reset Direction Pointer upgrades a legacy 2-vertex line ===")
    select_only(legacy_line)
    bpy.ops.tw_buildings.reset_marker_line_direction()
    if len(legacy_line.data.vertices) != 4:
        raise RuntimeError(f"Reset should give a 2-vertex line a pointer, got {len(legacy_line.data.vertices)} vertices")
    expect_vec("upgraded tip", tuple(legacy_line.data.vertices[3].co), (0.0, -1.0, 0.0))

    print("=== the panel reports the same direction the exporter writes ===")
    from ui.panels import marker_line_direction

    expect_vec("panel direction for the reset line", marker_line_direction(flipped_line), (0.0, 1.0, 0.0))

    print("=== Invert Direction turns the pointer through 180 degrees ===")
    select_only(default_line)
    bpy.ops.tw_buildings.invert_marker_line_direction()
    expect_vec("tip after invert", tuple(default_line.data.vertices[3].co), (0.0, -1.0, 0.0))
    expect_vec("direction after invert", marker_line_direction(default_line), (0.0, -1.0, 0.0))
    bpy.ops.tw_buildings.invert_marker_line_direction()
    expect_vec("tip after inverting back", tuple(default_line.data.vertices[3].co), (0.0, 1.0, 0.0))

    print("=== inverting a legacy 2-vertex line gives it an inverted pointer ===")
    legacy_two = bpy.data.meshes.new("LegacyTwoVertex")
    legacy_two.from_pydata([(-1.0, 0.0, 0.0), (1.0, 0.0, 0.0)], [(0, 1)], [])
    legacy_two.update()
    legacy_two_obj = bpy.data.objects.new("LegacyTwoVertex", legacy_two)
    ef_collection.objects.link(legacy_two_obj)
    select_only(legacy_two_obj)
    bpy.ops.tw_buildings.invert_marker_line_direction()
    if len(legacy_two_obj.data.vertices) != 4:
        raise RuntimeError("Invert should give a 2-vertex line a pointer")
    expect_vec("inverted legacy tip", tuple(legacy_two_obj.data.vertices[3].co), (0.0, -1.0, 0.0))

    print("=== only yaw counts: pitch and roll leave the direction alone ===")
    if not (default_line.lock_rotation[0] and default_line.lock_rotation[1]):
        raise RuntimeError("A marker line should have its pitch and roll rotation axes locked")
    baseline = marker_line_direction(default_line)
    for axis, label in ((0, "pitch (Blender X)"), (1, "roll (Blender Y)")):
        default_line.rotation_euler = (0.0, 0.0, 0.0)
        default_line.rotation_euler[axis] = 0.7
        bpy.context.view_layer.update()
        expect_vec(f"direction after {label}", marker_line_direction(default_line), baseline)
    default_line.rotation_euler = (0.0, 0.0, 0.0)

    print("=== yaw does change it, by exactly the angle applied ===")
    import math

    default_line.rotation_euler = (0.0, 0.0, math.radians(90.0))
    bpy.context.view_layer.update()
    expect_vec("direction after 90 degrees of yaw", marker_line_direction(default_line), (-1.0, 0.0, 0.0))
    default_line.rotation_euler = (0.0, 0.0, 0.0)

    print("=== a tilted marker exports a purely horizontal direction ===")
    tilted = bpy.data.meshes.new("TiltedEFLine")
    tilted.from_pydata([(-1.0, 0.0, 0.0), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.6)], [(0, 1), (1, 2), (1, 3)], [])
    tilted.update()
    tilted_obj = bpy.data.objects.new("TiltedEFLine", tilted)
    tilted_obj.location = (0.0, -4.0, 0.0)
    ef_collection.objects.link(tilted_obj)
    expect_vec("direction from a tip raised 0.6", marker_line_direction(tilted_obj), (0.0, 1.0, 0.0))

    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    bpy.ops.tw_buildings.export_building(directory=OUTPUT_DIR)
    with open(rf"{OUTPUT_DIR}\{building.name}.CS2", "rb") as f:
        doc = read_cs2(f.read())
    for node in doc.rigid_models:
        udp = node.user_defined_properties or ""
        if "EFLine_Info" not in udp:
            continue
        direction = parse_vec(parse_udp(udp)["EFLine_Direction"])
        if abs(direction[2]) > 1e-9:
            raise RuntimeError(f"{node.node_name} exported a direction with a vertical component: {direction}")
    print("  every exported EFLine_Direction has z = 0, as all 158 real markers do")

    print("=== EFLINE DIRECTION TEST PASSED ===")


try:
    main()
except Exception:
    print("=== EFLINE DIRECTION TEST FAILED ===")
    traceback.print_exc()
    sys.exit(1)
