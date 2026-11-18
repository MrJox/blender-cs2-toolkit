import sys
import traceback

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
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


def add_box(collection):
    bpy.ops.mesh.primitive_cube_add()
    obj = bpy.context.active_object
    for coll in list(obj.users_collection):
        coll.objects.unlink(obj)
    collection.objects.link(obj)
    return obj


def add_mesh(collection, name, vertices, faces, location=(0.0, 0.0, 0.0)):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    collection.objects.link(obj)
    return obj


def add_destruct(building, piece_collection):
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(piece_collection)
    bpy.ops.tw_buildings.new_destruct_level()
    destruct = piece_collection.children[-1]
    display = [c for c in destruct.children if c.tw_role == "DISPLAY"][0]
    collision = [c for c in destruct.children if c.tw_role == "COLLISION"][0]
    lod_obj = add_box(display)
    bpy.context.view_layer.objects.active = lod_obj
    lod_obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project()
    bpy.ops.object.mode_set(mode="OBJECT")
    material = bpy.data.materials.new(name=f"{lod_obj.name}_Material")
    lod_obj.data.materials.append(material)
    lod_obj.active_material = material
    bpy.ops.tw_buildings.make_material()
    add_box(collision).tw_collision_type = "COLLISION"
    return destruct


def add_child_collection(destruct, role):
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(destruct)
    bpy.ops.tw_buildings.add_destruct_collection(role=role)
    return [c for c in destruct.children if c.tw_role == role][0]


def add_ef_line(collection, name, start, end, location=(0.0, 0.0, 0.0)):
    mid = tuple((a + b) / 2.0 for a, b in zip(start, end))
    tip = (mid[0], mid[1] + 0.5, mid[2])
    return add_mesh(collection, name, [start, mid, end, tip], [], location)


def square(x0, y0, x1, y1):
    return [(x0, y0, 0.0), (x1, y0, 0.0), (x1, y1, 0.0), (x0, y1, 0.0)]


def main() -> None:
    module = addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")
    bpy.context.preferences.addons["total_war_cs2_addon"].preferences.assembly_kit_root = ASSEMBLY_KIT_ROOT

    from validation.rules import validate_building

    bpy.ops.tw_buildings.new_building()
    building = [c for c in bpy.data.collections if c.tw_role == "BUILDING"][-1]
    building.name = "EflPlatformValidationTest"
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    bpy.ops.tw_buildings.new_piece()
    bpy.ops.tw_buildings.new_piece()
    piece_one, piece_two = building.children[-2], building.children[-1]
    destruct_one = add_destruct(building, piece_one)
    destruct_two = add_destruct(building, piece_two)

    platforms_one = add_child_collection(destruct_one, "PLATFORM")
    platforms_two = add_child_collection(destruct_two, "PLATFORM")
    # An L: the 10x10 square with its top-right 5x5 corner missing, placed through the object's own
    # location so local and world coordinates differ.
    add_mesh(
        platforms_one,
        "LPlatform",
        [(0, 0, 0), (10, 0, 0), (10, 5, 0), (5, 5, 0), (5, 10, 0), (0, 10, 0)],
        [(0, 1, 2, 3), (0, 3, 4, 5)],
        location=(100.0, 0.0, 0.0),
    )
    ground = add_mesh(platforms_two, "GroundOnly", square(0, 0, 10, 10), [(0, 1, 2, 3)], location=(200.0, 0.0, 0.0))
    ground.tw_platform_type = "PLATFORM_GROUND"

    lines_one = add_child_collection(destruct_one, "EF_LINES")
    lines_two = add_child_collection(destruct_two, "EF_LINES")
    add_ef_line(lines_one, "OnPlatform", (101.0, 1.0, 0.0), (103.0, 1.0, 0.0))
    add_ef_line(lines_one, "EndPastEdge", (108.0, 2.0, 0.0), (111.0, 2.0, 0.0))
    add_ef_line(lines_one, "MovedByObject", (1.0, 1.0, 0.0), (3.0, 1.0, 0.0), location=(100.0, 3.0, 0.0))
    add_ef_line(lines_one, "InTheNotch", (107.0, 8.0, 0.0), (109.0, 8.0, 0.0))
    add_ef_line(lines_one, "OffToTheSide", (150.0, 1.0, 0.0), (152.0, 1.0, 0.0))
    add_ef_line(lines_one, "OnOtherPiece", (203.0, 4.0, 0.0), (205.0, 4.0, 0.0))
    add_ef_line(lines_two, "OnGroundPlatform", (203.0, 4.0, 0.0), (205.0, 4.0, 0.0))

    bpy.context.view_layer.update()
    issues = validate_building(building)
    platform_warnings = {
        issue.object_name: issue.message
        for issue in issues
        if issue.severity == "WARNING" and "is not on a platform" in issue.message
    }
    for name, message in platform_warnings.items():
        print(f"  {name}: {message}")

    def check(condition, description):
        if not condition:
            raise AssertionError(description)
        print("  OK:", description)

    check("OnPlatform" not in platform_warnings, "a line inside the platform is not flagged")
    check("EndPastEdge" not in platform_warnings, "a line whose end pokes past the edge but whose midpoint is on it is not flagged")
    check("MovedByObject" not in platform_warnings, "object location is part of the test (world space, not local)")
    check("InTheNotch" in platform_warnings, "a line in the L's missing corner is flagged, which a bounding box would miss")
    check("OffToTheSide" in platform_warnings, "a line away from every platform is flagged")
    check("midpoint" in platform_warnings["OffToTheSide"], "the warning names the midpoint BOB actually tests")
    check("OnOtherPiece" in platform_warnings, "a line standing on another piece's platform is flagged")
    check(
        destruct_two.name in platform_warnings["OnOtherPiece"],
        "the warning says which destruct level's platform the line is really on",
    )
    check(
        destruct_two.name not in platform_warnings["OffToTheSide"],
        "a line on no platform at all gets no cross-piece hint",
    )
    check("OnGroundPlatform" not in platform_warnings, "a Platform Ground mesh counts as a surface for EFLines")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
