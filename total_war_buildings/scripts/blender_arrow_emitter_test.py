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
    building.name = "ArrowEmitterUiTest"

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

    print("=== add Arrow Emitters collection via operator ===")
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(destruct)
    bpy.ops.tw_buildings.add_destruct_collection(role="ARROW_EMITTERS")
    arrow_collection = [c for c in destruct.children if c.tw_role == "ARROW_EMITTERS"][0]

    print("=== calling add_destruct_collection(ARROW_EMITTERS) again should fail cleanly ===")
    try:
        bpy.ops.tw_buildings.add_destruct_collection(role="ARROW_EMITTERS")
        raise RuntimeError("Expected the second add_destruct_collection(ARROW_EMITTERS) call to fail")
    except RuntimeError as error:
        print("correctly refused:", error)

    print("=== New Arrow Emitter, twice, then move/rotate the second one ===")
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(arrow_collection)
    bpy.ops.tw_buildings.new_arrow_emitter()
    emitter1 = bpy.context.active_object
    print("emitter1:", emitter1.name, "verts:", len(emitter1.data.vertices))

    bpy.ops.tw_buildings.new_arrow_emitter()
    emitter2 = bpy.context.active_object
    emitter2.location = (5.0, 0.0, 2.0)
    emitter2.rotation_euler = (0.0, 0.0, 1.2)
    print("emitter2:", emitter2.name, "moved/rotated")

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
    print("re-parsed OK:", doc.scene_block.rigid_models_count, "rigid,", doc.scene_block.materials_count, "materials")
    arrow_nodes = []
    for rm in doc.rigid_models:
        matids = [sm.material_id for sm in rm.geometry_chunks[0].submeshes]
        class_rigid_info = next((a.value for a in rm.attributes.strings if a.name == "class_rigidINFO"), None)
        print(" ", rm.node_name, "matids:", matids, "class_rigidINFO:", repr(class_rigid_info))
        if "arrow_emitter" in rm.node_name:
            arrow_nodes.append(rm)

    if len(arrow_nodes) != 2:
        raise RuntimeError(f"Expected exactly 2 arrow_emitter nodes, found {len(arrow_nodes)}")

    names = sorted(n.node_name for n in arrow_nodes)
    if names != ["piece01_destruct01_arrow_emitter01", "piece01_destruct01_arrow_emitter02"]:
        raise RuntimeError(f"Unexpected arrow emitter names: {names}")

    # Arrow emitters don't bake world position into geometry (all instances share one local shape -
    # confirmed from the real sample, and confirmed again by a real BOB warning when the transform
    # was left at identity: "the emitter will appear at the centre of the building"). Position and
    # rotation instead live on the node's own SceneNode transform keyframe.
    scene_nodes_by_name = {node.name: node for node in doc.scene_root.scene_nodes}
    moved_scene_node = scene_nodes_by_name["piece01_destruct01_arrow_emitter02"]
    moved_translation = moved_scene_node.anim.translations[0]
    moved_rotation = moved_scene_node.anim.rotations[0]
    print("moved emitter transform (engine space):", moved_translation, moved_rotation)
    if abs(moved_translation[0] - 5.0) > 0.01:
        raise RuntimeError("Moved arrow emitter's SceneNode transform did not carry its moved position")
    if moved_rotation == (0.0, 0.0, 0.0, 1.0):
        raise RuntimeError("Moved/rotated arrow emitter's SceneNode transform is still identity rotation")

    still_node = scene_nodes_by_name["piece01_destruct01_arrow_emitter01"]
    if still_node.anim.rotations[0] != (0.0, 0.0, 0.0, 1.0):
        raise RuntimeError("Unmoved arrow emitter's SceneNode transform should still be identity rotation")

    print("=== ARROW EMITTER UI TEST PASSED ===")


try:
    main()
except Exception:
    print("=== ARROW EMITTER UI TEST FAILED ===")
    traceback.print_exc()
    sys.exit(1)
