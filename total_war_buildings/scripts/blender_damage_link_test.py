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


def make_piece(building, piece_name, x_offset):
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
    lod_obj.location = (x_offset, 0.0, 0.0)
    add_uv(lod_obj)
    material = bpy.data.materials.new(name=f"{lod_obj.name}_Material")
    lod_obj.data.materials.append(material)
    lod_obj.active_material = material
    bpy.ops.tw_buildings.make_material()

    collision_obj = add_box(collision)
    collision_obj.location = (x_offset, 0.0, 0.0)
    collision_obj.tw_collision_type = "COLLISION"
    return piece


def main() -> None:
    module = addon_utils.enable("total_war_buildings", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")

    prefs = bpy.context.preferences.addons["total_war_buildings"].preferences
    prefs.assembly_kit_root = ASSEMBLY_KIT_ROOT

    print("=== new building ===")
    bpy.ops.tw_buildings.new_building()
    building = [c for c in bpy.data.collections if c.tw_role == "BUILDING"][-1]
    building.name = "DamageLinkTest"

    print("=== three pieces: a central wall with a segment either side ===")
    centre = make_piece(building, "WallCentre", 0.0)
    left = make_piece(building, "WallLeft", -3.0)
    right = make_piece(building, "WallRight", 3.0)

    print("=== link both flanking segments to the centre ===")
    left.tw_damage_parent = centre
    right.tw_damage_parent = centre

    print("=== validate ===")
    bpy.context.view_layer.active_layer_collection = active_layer_collection_for(building)
    bpy.ops.tw_buildings.validate()

    print("=== export ===")
    result = bpy.ops.tw_buildings.export_building(directory=OUTPUT_DIR)
    print("export operator result:", result)

    from binary.cs2_reader import read_cs2

    exported_path = f"{OUTPUT_DIR}\{building.name}.CS2"
    with open(exported_path, "rb") as f:
        doc = read_cs2(f.read())

    scene_nodes = doc.scene_root.scene_nodes
    node_index_by_name = {rm.node_name: rm.node_index for rm in doc.rigid_models}
    parent_index_by_name = {sn.name: sn.parent_index for sn in scene_nodes}
    for name in sorted(node_index_by_name):
        if "collision3d" in name:
            print(f"  {name}: node_index={node_index_by_name[name]} parent_index={parent_index_by_name[name]}")

    if min(node_index_by_name.values()) != 1:
        raise RuntimeError(
            f"node_index must be 1-based to match every real sample, got a minimum of "
            f"{min(node_index_by_name.values())}."
        )

    expected_parent = node_index_by_name["piece01_destruct01_collision3d"]
    for child in ("piece02_destruct01_collision3d", "piece03_destruct01_collision3d"):
        actual = parent_index_by_name[child]
        if actual != expected_parent:
            raise RuntimeError(f"{child} parent_index is {actual}, expected {expected_parent}.")

    if parent_index_by_name["piece01_destruct01_collision3d"] != 0:
        raise RuntimeError("The centre piece has no Damage Parent, so its parent_index must be 0.")

    for name, parent_index in parent_index_by_name.items():
        if "collision3d" not in name and parent_index != 0:
            raise RuntimeError(f"Non-collision node {name} unexpectedly carries parent_index={parent_index}.")

    print("=== validation rejects the bad shapes ===")
    from validation.rules import validate_building

    def errors_for(building_collection):
        return [i.message for i in validate_building(building_collection) if i.severity == "ERROR"]

    left.tw_damage_parent = left
    if not any("its own Damage Parent" in m for m in errors_for(building)):
        raise RuntimeError("A self-referencing Damage Parent was not reported as an error.")

    left.tw_damage_parent = centre
    centre.tw_damage_parent = left
    if not any("Damage Parent loop" in m for m in errors_for(building)):
        raise RuntimeError("A Damage Parent loop was not reported as an error.")
    centre.tw_damage_parent = None

    stray = bpy.data.collections.new("NotAPiece")
    right.tw_damage_parent = stray
    if not any("isn't a Building Piece" in m for m in errors_for(building)):
        raise RuntimeError("A Damage Parent outside the building was not reported as an error.")
    right.tw_damage_parent = centre

    if errors_for(building):
        raise RuntimeError(f"The valid building should report no errors, got {errors_for(building)}.")

    print("=== reimport and check the link survives the round trip ===")
    for collection in list(bpy.data.collections):
        bpy.data.collections.remove(collection)
    bpy.ops.tw_buildings.import_file(filepath=exported_path)

    pieces = [c for c in bpy.data.collections if c.tw_role == "PIECE"]
    linked = {c.name: (c.tw_damage_parent.name if c.tw_damage_parent else None) for c in pieces}
    print("  reimported Damage Parents:", linked)
    if sum(1 for parent in linked.values() if parent is not None) != 2:
        raise RuntimeError(f"Expected exactly 2 reimported Damage Parent links, got {linked}.")

    print("=== DAMAGE LINK TEST PASSED ===")


try:
    main()
except Exception:
    print("=== DAMAGE LINK TEST FAILED ===")
    traceback.print_exc()
    sys.exit(1)
