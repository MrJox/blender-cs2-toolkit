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


def main() -> None:
    module = addon_utils.enable("total_war_buildings", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    prefs = bpy.context.preferences.addons["total_war_buildings"].preferences
    prefs.assembly_kit_root = ASSEMBLY_KIT_ROOT

    print("=== building / piece / destruct ===")
    bpy.ops.tw_buildings.new_building()
    building = [c for c in bpy.data.collections if c.tw_role == "BUILDING"][-1]
    building.name = "SoftCollisionUiTest"

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

    print("=== add soft collision box in the same Collision collection ===")
    soft_obj = add_box(collision, size=3.0)
    soft_obj.location = (2.0, 0.0, 0.0)
    soft_obj.tw_collision_type = "SOFT_COLLISION"
    print("soft collision object added:", soft_obj.name, "type:", soft_obj.tw_collision_type)

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
    print("re-parsed OK:", doc.scene_block.rigid_models_count, "rigid,", doc.scene_block.materials_count, "materials")
    soft_node = None
    for rm in doc.rigid_models:
        matids = [sm.material_id for sm in rm.geometry_chunks[0].submeshes]
        class_rigid_info = next((a.value for a in rm.attributes.strings if a.name == "class_rigidINFO"), None)
        print(" ", rm.node_name, "matids:", matids, "class_rigidINFO:", repr(class_rigid_info))
        if rm.node_name.endswith("soft_collision"):
            soft_node = rm

    if soft_node is None:
        raise RuntimeError("Expected a *_soft_collision node in the exported CS2, found none")

    positions = [v.position for v in soft_node.geometry_chunks[0].vertices]
    ys = [p[1] for p in positions]
    print("soft collision node Y extent (should be > 0, vertical is now Y after axis conversion):", (min(ys), max(ys)))
    if not (min(ys) < max(ys)):
        raise RuntimeError("Soft collision box has no vertical extent after axis conversion - export is broken")

    print("=== SOFT COLLISION UI TEST PASSED ===")


try:
    main()
except Exception:
    print("=== SOFT COLLISION UI TEST FAILED ===")
    traceback.print_exc()
    sys.exit(1)
