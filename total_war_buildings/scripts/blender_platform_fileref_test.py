import math
import sys
import traceback

import addon_utils
import bpy
import mathutils

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


def add_plane(collection: bpy.types.Collection) -> bpy.types.Object:
    bpy.ops.mesh.primitive_plane_add(size=2.0)
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
    building.name = "PlatformFileRefUiTest"

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

    print("=== add platform collection via operator ===")
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(destruct)
    bpy.ops.tw_buildings.add_destruct_collection(role="PLATFORM")
    platform_collection = [c for c in destruct.children if c.tw_role == "PLATFORM"][0]
    platform_obj = add_plane(platform_collection)
    print("platform object added:", platform_obj.name)

    print("=== calling add_destruct_collection(PLATFORM) again should fail cleanly ===")
    try:
        bpy.ops.tw_buildings.add_destruct_collection(role="PLATFORM")
        raise RuntimeError("Expected the second add_destruct_collection(PLATFORM) call to fail")
    except RuntimeError as error:
        print("correctly refused:", error)

    print("=== add referenced props collection via operator ===")
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(destruct)
    bpy.ops.tw_buildings.add_destruct_collection(role="FILE_REFERENCE")
    file_ref_collection = [c for c in destruct.children if c.tw_role == "FILE_REFERENCE"][0]
    file_ref_obj = add_box(file_ref_collection, size=0.3)
    add_uv(file_ref_obj)
    _mat_obj = bpy.context.active_object
    _material = bpy.data.materials.new(name=f"{_mat_obj.name}_Material")
    _mat_obj.data.materials.append(_material)
    _mat_obj.active_material = _material
    bpy.ops.tw_buildings.make_material()
    file_ref_obj.tw_file_reference_name = "torch_sconce"
    file_ref_obj.location = (3.0, 1.0, 2.0)
    print("file reference object added:", file_ref_obj.name, "-> ref name:", file_ref_obj.tw_file_reference_name)

    print("=== an Empty is a complete referenced prop on its own ===")
    empty_ref = bpy.data.objects.new("BarrelRef", None)
    empty_ref.empty_display_type = "CUBE"
    empty_ref.location = (-4.0, 5.0, 6.0)
    empty_ref.rotation_mode = "QUATERNION"
    empty_ref.rotation_quaternion = mathutils.Quaternion((0.0, 0.0, 1.0), math.radians(90.0))
    empty_ref.tw_file_reference_name = "barrel"
    file_ref_collection.objects.link(empty_ref)

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
    for rm in doc.rigid_models:
        matids = [sm.material_id for sm in rm.geometry_chunks[0].submeshes]
        rigid_object = next((a.value for a in rm.attributes.strings if a.name == "rigid_OBJECT"), None)
        print(" ", rm.node_name, "matids:", matids, "rigid_OBJECT:", repr(rigid_object))

    print("=== referenced props are placed by their own transform, not by baked geometry ===")
    # BOB copies a file reference node's scene-node keyframe verbatim into the compiled .cs2.parsed
    # matrix and drops its mesh, so the transform is the only thing that places the prop - see
    # gondor_fort_gateway_e's four torch_sconce nodes, one local mesh with four different keyframes.
    scene_nodes = {node.name: node for node in doc.scene_root.scene_nodes}
    for node_name, expected_translation in (
        ("piece01_destruct01_file:torch_sconce", (3.0, 2.0, 1.0)),
        ("piece01_destruct01_file:barrel", (-4.0, 6.0, 5.0)),
    ):
        node = scene_nodes[node_name]
        translation = node.anim.translations[0]
        if any(abs(a - b) > 1e-4 for a, b in zip(translation, expected_translation)):
            raise RuntimeError(f"{node_name} exported translation {translation}, expected {expected_translation}")
        print(f"  {node_name} at {tuple(round(c, 3) for c in translation)}")

    empty_node = next(rm for rm in doc.rigid_models if rm.node_name == "piece01_destruct01_file:barrel")
    if any(chunk.vertices for chunk in empty_node.geometry_chunks):
        raise RuntimeError("an Empty referenced prop should export no geometry")
    barrel_rotation = scene_nodes["piece01_destruct01_file:barrel"].anim.rotations[0]
    if abs(abs(barrel_rotation[1]) - math.sin(math.radians(45.0))) > 1e-4:
        raise RuntimeError(f"the Empty's 90-degree yaw did not survive export: {barrel_rotation}")
    print("  the Empty exported a real rotation and no geometry")

    mesh_node = next(rm for rm in doc.rigid_models if rm.node_name == "piece01_destruct01_file:torch_sconce")
    positions = [v.position for chunk in mesh_node.geometry_chunks for v in chunk.vertices]
    if any(abs(p[axis]) > 1.0 for p in positions for axis in range(3)):
        raise RuntimeError("a referenced prop's preview mesh should stay local, not bake its world position")
    print("  the preview mesh stayed in local space")

    print("=== PLATFORM/FILE REFERENCE UI TEST PASSED ===")


try:
    main()
except Exception:
    print("=== PLATFORM/FILE REFERENCE UI TEST FAILED ===")
    traceback.print_exc()
    sys.exit(1)
