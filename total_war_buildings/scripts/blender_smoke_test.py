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


def main() -> None:
    print("=== enabling add-on ===")
    module = addon_utils.enable("total_war_buildings", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    prefs = bpy.context.preferences.addons["total_war_buildings"].preferences
    prefs.assembly_kit_root = ASSEMBLY_KIT_ROOT
    print("assembly_kit_root set to", prefs.assembly_kit_root)

    print("=== new building ===")
    bpy.ops.tw_buildings.new_building()
    building = [c for c in bpy.data.collections if c.tw_role == "BUILDING"][-1]
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    print("building:", building.name)

    print("=== new piece ===")
    bpy.ops.tw_buildings.new_piece()
    piece = building.children[0]
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(piece)
    print("piece:", piece.name)

    print("=== new destruct level ===")
    bpy.ops.tw_buildings.new_destruct_level()
    destruct = piece.children[0]
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(destruct)
    print("destruct:", destruct.name)

    display = [c for c in destruct.children if c.tw_role == "DISPLAY"][0]
    collision = [c for c in destruct.children if c.tw_role == "COLLISION"][0]
    print("display:", display.name, "collision:", collision.name)

    print("=== add cube mesh into Display ===")
    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.active_object
    for coll in list(cube.users_collection):
        coll.objects.unlink(cube)
    display.objects.link(cube)

    bpy.context.view_layer.objects.active = cube
    cube.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project()
    bpy.ops.object.mode_set(mode="OBJECT")
    print("cube has uv layers:", list(cube.data.uv_layers.keys()))

    print("=== make total war material ===")
    _mat_obj = bpy.context.active_object
    _material = bpy.data.materials.new(name=f"{_mat_obj.name}_Material")
    _mat_obj.data.materials.append(_material)
    _mat_obj.active_material = _material
    bpy.ops.tw_buildings.make_material()
    print("active material:", cube.active_material.name, "shader type:", cube.active_material.tw_shader_type)

    print("=== add collision box ===")
    bpy.ops.mesh.primitive_cube_add()
    collision_box = bpy.context.active_object
    for coll in list(collision_box.users_collection):
        coll.objects.unlink(collision_box)
    collision.objects.link(collision_box)
    collision_box.tw_collision_type = "COLLISION"
    print("collision object type:", collision_box.tw_collision_type)

    print("=== validate ===")
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(destruct)
    bpy.ops.tw_buildings.validate()

    print("=== export ===")
    result = bpy.ops.tw_buildings.export_building(directory=OUTPUT_DIR)
    print("export operator result:", result)

    exported_path = f"{OUTPUT_DIR}\\{building.name}.CS2"
    print("checking exported file at", exported_path)

    from binary.cs2_reader import read_cs2

    with open(exported_path, "rb") as f:
        data = f.read()
    doc = read_cs2(data)
    print("re-parsed exported file OK:", doc.scene_block.rigid_models_count, "rigid,", doc.scene_block.materials_count, "materials")
    for rm in doc.rigid_models:
        print(" rigid node:", rm.node_name, "verts:", len(rm.geometry_chunks[0].vertices))
    for m in doc.materials:
        print(" material node:", m.node_name, "rigid_material:", [a.value for a in m.material_attributes.strings if a.name == "rigid_material"])

    print("=== SMOKE TEST PASSED ===")


try:
    main()
except Exception:
    print("=== SMOKE TEST FAILED ===")
    traceback.print_exc()
    sys.exit(1)
