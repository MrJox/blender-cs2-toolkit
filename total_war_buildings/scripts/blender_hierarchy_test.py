import math
import sys
import traceback

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
OUTPUT_DIR = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin\total_war_buildings\scripts"
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


def make_piece_with_collision(building, piece_name, collision_size=1.0):
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    bpy.ops.tw_buildings.new_piece()
    piece = building.children[-1]
    piece.name = piece_name

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

    collision_obj = add_box(collision, size=collision_size)
    collision_obj.tw_collision_type = "COLLISION"
    return piece, collision_obj


def main() -> None:
    module = addon_utils.enable("total_war_buildings", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    prefs = bpy.context.preferences.addons["total_war_buildings"].preferences
    prefs.assembly_kit_root = ASSEMBLY_KIT_ROOT

    print("=== new building ===")
    bpy.ops.tw_buildings.new_building()
    building = [c for c in bpy.data.collections if c.tw_role == "BUILDING"][-1]
    building.name = "HierarchyTest"

    print("=== piece 1 (gatehouse) - collision stays at the origin ===")
    gatehouse_piece, gatehouse_collision = make_piece_with_collision(building, "Gatehouse", collision_size=2.0)

    print("=== piece 2 (tower) - collision parented to the gatehouse's collision, offset + rotated ===")
    tower_piece, tower_collision = make_piece_with_collision(building, "Tower", collision_size=1.0)
    tower_collision.parent = gatehouse_collision
    tower_collision.location = (5.0, 0.0, 0.0)
    tower_collision.rotation_euler = (0.0, 0.0, math.radians(90.0))

    bpy.context.view_layer.update()
    expected_world = tower_collision.matrix_world.copy()
    print("tower collision matrix_world translation:", tuple(expected_world.translation))

    print("=== validate ===")
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    bpy.ops.tw_buildings.validate()

    print("=== export ===")
    result = bpy.ops.tw_buildings.export_building(directory=OUTPUT_DIR)
    print("export operator result:", result)

    from binary.cs2_reader import read_cs2

    exported_path = f"{OUTPUT_DIR}\\{building.name}.CS2"
    with open(exported_path, "rb") as f:
        data = f.read()
    doc = read_cs2(data)

    def bbox_of(node_name):
        for n in doc.rigid_models:
            if n.node_name == node_name:
                positions = [v.position for v in n.geometry_chunks[0].vertices]
                xs = [p[0] for p in positions]
                ys = [p[1] for p in positions]
                zs = [p[2] for p in positions]
                return (min(xs), max(xs)), (min(ys), max(ys)), (min(zs), max(zs))
        raise RuntimeError(f"node {node_name!r} not found in exported CS2")

    gatehouse_bbox = bbox_of("piece01_destruct01_collision3d")
    tower_bbox = bbox_of("piece02_destruct01_collision3d")
    print("gatehouse collision bbox (engine space):", gatehouse_bbox)
    print("tower collision bbox (engine space):", tower_bbox)

    # tower_collision.location = (5,0,0) in Blender space -> _to_engine_space (x,y,z)->(x,z,-y)
    # keeps the X component unchanged, so the tower's exported X range must be centered near 5.0,
    # not near 0.0 - this is the exact bug the matrix_world fix addresses, now exercised through a
    # real parent/child object relationship (Blender composes the full chain into matrix_world).
    min_x, max_x = tower_bbox[0]
    center_x = (min_x + max_x) / 2.0
    print("tower collision X center (engine space, expected ~5.0):", center_x)
    if abs(center_x - 5.0) > 0.5:
        raise RuntimeError(
            f"Tower collision did not export at its parented world position - expected X center "
            f"near 5.0, got {center_x}. The matrix_world fix is not taking effect for parented objects."
        )

    print("=== HIERARCHY TEST PASSED (matrix_world composes parent chain correctly) ===")


try:
    main()
except Exception:
    print("=== HIERARCHY TEST FAILED ===")
    traceback.print_exc()
    sys.exit(1)
