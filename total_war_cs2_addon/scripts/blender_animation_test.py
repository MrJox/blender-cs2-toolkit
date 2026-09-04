import sys
import tempfile
from pathlib import Path

import addon_utils
import bpy

ADDON_DIR = Path(__file__).resolve().parent.parent
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from importer import import_cs2
from export.exporter import export_building
from binary.cs2_reader import read_cs2
from props import properties
from extraction.animation import object_keyframe_frames, _object_fcurves

RAW = ADDON_DIR.parent / "Input/examples/raw_data/gondor_fort_gateway_e/gondor_fort_gateway_e.CS2"
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"
OUTPUT_DIR = str(ADDON_DIR / "scripts")


def reset() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False)
    properties.register()


def all_collections(root):
    yield root
    for child in root.children:
        yield from all_collections(child)


def find_role(root, role):
    return [c for c in all_collections(root) if c.tw_role == role]


def test_cs2_import_and_reexport() -> None:
    print("=== animation: .CS2 import + re-export ===")
    reset()
    building_coll, warnings = import_cs2(str(RAW), bpy.context)

    for w in warnings:
        assert "anim" not in w.lower(), f"an animation node was skipped rather than imported: {w}"

    destruction_colls = find_role(building_coll, "DESTRUCTION_ANIM")
    gate_anim_colls = find_role(building_coll, "GATE_ANIMATION")
    print(f"  {len(destruction_colls)} Destruction Animation collection(s), {len(gate_anim_colls)} Gate Animation collection(s)")
    assert destruction_colls, "no Destruction Animation collection was imported"
    assert gate_anim_colls, "no Gate Animation collection was imported"

    destruction_objs = [obj for coll in destruction_colls for obj in coll.objects]
    gate_anim_objs = [obj for coll in gate_anim_colls for obj in coll.objects]
    print(f"  {len(destruction_objs)} destruction debris object(s), {len(gate_anim_objs)} gate animation object(s)")
    # Ground truth: 13 debris chunks share the name building_piece01_destruct01_anim (piece01
    # destruct01 alone), plus more across piece03/piece04 and one more piece01 instance - 18 total
    # rigid "anim" nodes excluding the 4 gate_*_anim kinds (32 total anim rigid nodes - 14 gate ones).
    assert len(destruction_objs) == 18, f"expected 18 destruction debris objects, got {len(destruction_objs)}"
    assert len(gate_anim_objs) == 14, f"expected 14 gate animation objects, got {len(gate_anim_objs)}"

    kinds_seen = {obj.tw_gate_anim_kind for obj in gate_anim_objs}
    assert kinds_seen == {"GATE_OPENING", "GATE_CLOSING", "GATE_CLOSED_DESTRUCT", "GATE_OPEN_DESTRUCT"}, kinds_seen

    # At least one object of each kind must carry real baked keyframes (multi-key ground truth).
    multi_key_objs = [obj for obj in destruction_objs + gate_anim_objs if len(object_keyframe_frames(obj)) > 1]
    print(f"  {len(multi_key_objs)} object(s) with baked F-curves")
    assert len(multi_key_objs) >= 25, f"expected most animation objects to carry real keyframes, got {len(multi_key_objs)}"

    sample = next(obj for obj in gate_anim_objs if obj.tw_gate_anim_kind == "GATE_OPENING" and len(object_keyframe_frames(obj)) > 1)
    rot_fcurves = [fc for fc in _object_fcurves(sample) if fc.data_path == "rotation_quaternion"]
    assert rot_fcurves, f"'{sample.name}' (GATE_OPENING) has no rotation_quaternion F-curve"
    keyframe_count = len(rot_fcurves[0].keyframe_points)
    print(f"  '{sample.name}' rotation_quaternion has {keyframe_count} keyframe(s)")
    assert keyframe_count >= 100, f"expected ~115 rotation keyframes on a real gate_opening_anim leaf, got {keyframe_count}"

    assert all(obj.data.materials for obj in destruction_objs + gate_anim_objs), "animation meshes lost their material"

    with tempfile.TemporaryDirectory() as tmp_dir:
        result = export_building(building_coll, tmp_dir, ASSEMBLY_KIT_ROOT, bpy.context)
        assert result.success, f"export failed: {result.message}"
        doc = read_cs2((Path(tmp_dir) / f"{building_coll.name}.CS2").read_bytes())

    re_exported_anim = [rm for rm in doc.rigid_models if "anim" in rm.node_name.lower()]
    print(f"  re-exported {len(re_exported_anim)} animation rigid node(s)")
    assert len(re_exported_anim) == len(destruction_objs) + len(gate_anim_objs), (
        f"re-export dropped animation nodes: {len(re_exported_anim)} vs "
        f"{len(destruction_objs) + len(gate_anim_objs)} imported"
    )

    scene_nodes_by_name = {}
    for sn in doc.scene_root.scene_nodes:
        scene_nodes_by_name.setdefault(sn.name, []).append(sn)

    re_exported_gate_opening = next(rm for rm in re_exported_anim if rm.node_name.endswith("gate_opening_anim"))
    sn = scene_nodes_by_name[re_exported_gate_opening.node_name][0]
    print(f"  re-exported '{re_exported_gate_opening.node_name}' rotation keys: {len(sn.anim.rotation_frame_times)}")
    assert len(sn.anim.rotation_frame_times) >= 100, "re-export lost the real gate rotation keyframes"


def test_authoring() -> None:
    print("=== animation: authoring from scratch ===")
    reset()

    bpy.ops.tw_buildings.new_building(asset_name="Building")
    building_coll = bpy.data.collections["Building"]
    layer = bpy.context.view_layer.layer_collection.children
    bpy.context.view_layer.active_layer_collection = layer[building_coll.name]
    bpy.ops.tw_buildings.new_piece()
    piece_coll = next(c for c in building_coll.children if c.tw_role == "PIECE")
    bpy.context.view_layer.active_layer_collection = layer[building_coll.name].children[piece_coll.name]
    bpy.ops.tw_buildings.new_destruct_level()

    destruct_coll = next(c for c in piece_coll.children if c.tw_role == "DESTRUCT")
    display_coll = next(c for c in destruct_coll.children if c.tw_role == "DISPLAY")
    collision_coll = next(c for c in destruct_coll.children if c.tw_role == "COLLISION")
    destruct_layer = layer[building_coll.name].children[piece_coll.name].children[destruct_coll.name]

    def add_cube(target_coll, name, location=(0.0, 0.0, 0.0), material=False):
        bpy.ops.mesh.primitive_cube_add(size=2.0, location=location)
        obj = bpy.context.object
        for c in list(obj.users_collection):
            c.objects.unlink(obj)
        target_coll.objects.link(obj)
        obj.name = name
        obj.data.uv_layers.new(name="UVMap")
        if material:
            obj.active_material = bpy.data.materials.new(name=f"{name}_Material")
            bpy.context.view_layer.objects.active = obj
            bpy.ops.tw_buildings.make_material()
        return obj

    add_cube(display_coll, "Body", material=True)
    add_cube(collision_coll, "BodyCollision").tw_collision_type = "COLLISION"

    # Destruction Animation: a debris chunk keyframed flying away.
    bpy.context.view_layer.active_layer_collection = destruct_layer
    bpy.ops.tw_buildings.add_destruct_collection(role="DESTRUCTION_ANIM")
    destruction_anim_coll = next(c for c in destruct_coll.children if c.tw_role == "DESTRUCTION_ANIM")
    debris = add_cube(destruction_anim_coll, "Debris1", material=True)
    debris.location = (0.0, 0.0, 0.0)
    debris.keyframe_insert(data_path="location", frame=1)
    debris.location = (3.0, 1.0, -2.0)
    debris.keyframe_insert(data_path="location", frame=30)
    debris.rotation_euler = (0.0, 0.0, 0.0)
    debris.keyframe_insert(data_path="rotation_euler", frame=1)
    debris.rotation_euler = (1.5, 0.0, 0.0)
    debris.keyframe_insert(data_path="rotation_euler", frame=30)

    # A second debris chunk left static (no keyframes) - the valid "authored but not moving" case.
    add_cube(destruction_anim_coll, "Debris2", material=True)

    # Gate Animation: a door leaf swinging on rotation only, like the real gate_opening_anim.
    bpy.context.view_layer.active_layer_collection = destruct_layer.children[display_coll.name]
    bpy.ops.tw_buildings.add_display_collection(role="GATE_ANIMATION")
    gate_anim_coll = next(c for c in display_coll.children if c.tw_role == "GATE_ANIMATION")
    leaf = add_cube(gate_anim_coll, "GateLeaf", location=(2.0, 0.0, 0.0), material=True)
    leaf.tw_gate_anim_kind = "GATE_OPENING"
    leaf.rotation_euler = (0.0, 0.0, 0.0)
    leaf.keyframe_insert(data_path="rotation_euler", frame=1)
    leaf.rotation_euler = (0.0, 0.0, 1.4)
    leaf.keyframe_insert(data_path="rotation_euler", frame=20)

    print(
        f"  authored {len(destruction_anim_coll.objects)} destruction anim object(s), "
        f"{len(gate_anim_coll.objects)} gate anim object(s)"
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        result = export_building(building_coll, tmp_dir, ASSEMBLY_KIT_ROOT, bpy.context)
        assert result.success, f"export failed: {result.message}"
        doc = read_cs2((Path(tmp_dir) / f"{building_coll.name}.CS2").read_bytes())

    anim_nodes = [rm for rm in doc.rigid_models if "anim" in rm.node_name.lower()]
    by_name = {}
    for node in anim_nodes:
        by_name.setdefault(node.node_name, []).append(node)
    print(f"  exported anim node names: {sorted(by_name)}")

    assert "building_piece01_destruct01_anim" in by_name, "destruction anim node missing from export"
    assert len(by_name["building_piece01_destruct01_anim"]) == 2, "both debris chunks should share one node name"
    assert "building_piece01_destruct01_gate_opening_anim" in by_name, "gate anim node missing from export"

    # Resolve each rigid node's own SceneNode via node_index (1-based), not by name - debris chunks
    # share a node name, so a name-keyed lookup would silently collapse them (see cs2_importer's
    # _scene_node_for_index for the same fix on the import side).
    scene_nodes = doc.scene_root.scene_nodes

    def scene_node_for(rigid_node):
        return scene_nodes[rigid_node.node_index - 1]

    debris_scene_nodes = [scene_node_for(rm) for rm in by_name["building_piece01_destruct01_anim"]]
    key_counts = sorted(len(sn.anim.translation_frame_times) for sn in debris_scene_nodes)
    print(f"  debris translation key counts: {key_counts}")
    assert key_counts == [1, 2], f"expected one static (1 key) and one animated (2 keys) debris chunk, got {key_counts}"

    gate_scene_node = scene_node_for(by_name["building_piece01_destruct01_gate_opening_anim"][0])
    print(f"  gate leaf rotation key count: {len(gate_scene_node.anim.rotation_frame_times)}")
    assert len(gate_scene_node.anim.rotation_frame_times) == 2

    attrs = {a.name: a.value for a in by_name["building_piece01_destruct01_gate_opening_anim"][0].attributes.strings}
    assert attrs["class_rigidINFO"] == "gate_opening_anim"
    assert attrs["class_TYPE"] == "DISPLAY"
    assert attrs["graphics_OPTION"] == "GRAPHICS_HIGH"

    # Leave a persistent, real-UI-authored .CS2 in scripts/ for a manual BOB compile - matches the
    # project's established pattern (SoftCollisionUiTest.CS2, PlatformFileRefUiTest.CS2, ...): this
    # implementation is structurally verified above, but never yet BOB-confirmed.
    building_coll.name = "AnimationUiTest"
    layer_for_building = next(
        lc for lc in [bpy.context.view_layer.layer_collection] for lc in _iter_layer_collections(lc)
        if lc.collection == building_coll
    )
    bpy.context.view_layer.active_layer_collection = layer_for_building
    result = bpy.ops.tw_buildings.export_building(directory=OUTPUT_DIR)
    print(f"  UI export operator result: {result}, wrote {OUTPUT_DIR}\\{building_coll.name}.CS2")


def _iter_layer_collections(layer_collection):
    yield layer_collection
    for child in layer_collection.children:
        yield from _iter_layer_collections(child)


def main() -> None:
    print("=== enabling add-on ===")
    if addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False) is None:
        raise RuntimeError("addon_utils.enable returned failure")
    properties.register()

    test_cs2_import_and_reexport()
    test_authoring()

    print("=== ALL ANIMATION TESTS PASSED ===")


if __name__ == "__main__":
    main()
