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


def make_destruct(piece: bpy.types.Collection, lod_count: int, add_collision: bool = True) -> bpy.types.Collection:
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(piece)
    bpy.ops.tw_buildings.new_destruct_level()
    destruct = piece.children[-1]

    display = [c for c in destruct.children if c.tw_role == "DISPLAY"][0]
    for i in range(lod_count):
        obj = add_box(display, size=1.0 - i * 0.1)
        obj.tw_lod_index = f"LOD{i+1:02d}"
        mat = bpy.data.materials.new("HardeningMat")
        obj.data.materials.append(mat)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.tw_buildings.make_material()

    if add_collision:
        collision = [c for c in destruct.children if c.tw_role == "COLLISION"][0]
        collision_obj = add_box(collision, size=1.1)
        collision_obj.tw_collision_type = "COLLISION"

    return destruct


def make_piece(building: bpy.types.Collection, destruct_count: int, lod_count: int) -> bpy.types.Collection:
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    bpy.ops.tw_buildings.new_piece()
    piece = building.children[-1]
    for _ in range(destruct_count):
        make_destruct(piece, lod_count=lod_count)
    return piece


def assign_real_texture(material: bpy.types.Material) -> None:
    texture_path = ASSEMBLY_KIT_ROOT + r"\max_exporter\max_shader\test_gray.tga"
    image = bpy.data.images.load(texture_path, check_existing=True)
    node = material.node_tree.nodes.get("Diffuse")
    node.image = image


def main() -> None:
    module = addon_utils.enable("total_war_buildings", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    prefs = bpy.context.preferences.addons["total_war_buildings"].preferences
    prefs.assembly_kit_root = ASSEMBLY_KIT_ROOT

    print("=== new building ===")
    bpy.ops.tw_buildings.new_building()
    building = [c for c in bpy.data.collections if c.tw_role == "BUILDING"][-1]
    building.name = "HardeningTest"

    print("=== piece 1: 2 destruct levels, 2 LODs each ===")
    piece1 = make_piece(building, destruct_count=2, lod_count=2)

    print("=== piece 2: 1 destruct level, 3 LODs ===")
    piece2 = make_piece(building, destruct_count=1, lod_count=3)

    print("=== assign a real texture to one material ===")
    first_display = [c for c in piece1.children[0].children if c.tw_role == "DISPLAY"][0]
    first_obj = first_display.objects[0]
    assign_real_texture(first_obj.active_material)
    print("assigned texture to", first_obj.active_material.name)

    print("=== validate ===")
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
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
    print("re-parsed OK:", doc.scene_block.rigid_models_count, "rigid,", doc.scene_block.materials_count, "materials")
    for rm in doc.rigid_models:
        print(" rigid node:", rm.node_name, "verts:", len(rm.geometry_chunks[0].vertices))
    for m in doc.materials:
        diffuse = next((t.texture_path for t in m.directx_material.textures if t.texture_name == "t_albedo"), None)
        print(" material node:", m.node_name, "diffuse:", diffuse)
    print("scene_root nodes:", len(doc.scene_root.scene_nodes))

    print("=== HARDENING TEST PASSED ===")


try:
    main()
except Exception:
    print("=== HARDENING TEST FAILED ===")
    traceback.print_exc()
    sys.exit(1)
