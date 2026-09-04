import sys
import tempfile
import traceback
from pathlib import Path

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

failures = []


def check(label: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        failures.append(label)


def layer_collection_for(collection):
    def find(layer_collection):
        if layer_collection.collection == collection:
            return layer_collection
        for child in layer_collection.children:
            found = find(child)
            if found is not None:
                return found
        return None

    found = find(bpy.context.view_layer.layer_collection)
    if found is None:
        raise RuntimeError(f"no layer collection for {collection.name}")
    return found


def activate(collection) -> None:
    bpy.context.view_layer.active_layer_collection = layer_collection_for(collection)


def deselect_all() -> None:
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)


def textured_box(name: str, collection, size: float = 1.0):
    bpy.ops.mesh.primitive_cube_add(size=size)
    obj = bpy.context.active_object
    obj.name = name
    for existing in list(obj.users_collection):
        existing.objects.unlink(obj)
    collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project()
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


def material_for(obj, shader_type: str = "default") -> None:
    from materials.material_builder import create_total_war_material

    material = bpy.data.materials.new(name=f"{obj.name}_Material")
    material.tw_shader_type = shader_type
    create_total_war_material(material)
    obj.data.materials.append(material)


def build_building(name: str):
    bpy.ops.tw_buildings.new_building()
    building = [c for c in bpy.data.collections if c.tw_role == "BUILDING"][-1]
    building.name = name
    activate(building)
    bpy.ops.tw_buildings.new_piece()
    piece = building.children[0]
    activate(piece)
    bpy.ops.tw_buildings.new_destruct_level()
    destruct = piece.children[0]
    display = [c for c in destruct.children if c.tw_role == "DISPLAY"][0]
    collision = [c for c in destruct.children if c.tw_role == "COLLISION"][0]
    box = textured_box(f"{name}_display", display)
    material_for(box)
    textured_box(f"{name}_collision", collision)
    return building


def build_skeleton(name: str):
    collection = bpy.data.collections.new(name)
    collection.tw_role = "SKELETON"
    bpy.context.scene.collection.children.link(collection)
    armature = bpy.data.armatures.new(name)
    armature_object = bpy.data.objects.new(name, armature)
    collection.objects.link(armature_object)

    bpy.context.view_layer.objects.active = armature_object
    armature_object.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    root = armature.edit_bones.new("bn_root")
    root.head = (0.0, 0.0, 0.0)
    root.tail = (0.0, 0.0, 1.0)
    child = armature.edit_bones.new("bn_child")
    child.head = (0.0, 0.0, 1.0)
    child.tail = (0.0, 0.0, 2.0)
    child.parent = root
    bpy.ops.object.mode_set(mode="OBJECT")
    armature_object.select_set(False)
    return collection, armature_object


def build_unit(name: str, armature_object):
    unit = bpy.data.collections.new(name)
    unit.tw_role = "UNIT"
    bpy.context.scene.collection.children.link(unit)
    model = bpy.data.collections.new(f"{name}_model")
    model.tw_role = "UNIT_MESH"
    model.tw_unit_part_kind = "WEIGHTED"
    unit.children.link(model)

    box = textured_box(f"{name}_lod0", model)
    box.tw_lod_index = "LOD01"
    material_for(box, "weighted")
    modifier = box.modifiers.new(name="Armature", type="ARMATURE")
    modifier.object = armature_object
    group = box.vertex_groups.new(name="bn_root")
    group.add(range(len(box.data.vertices)), 1.0, "REPLACE")
    return unit


def keyed_clip(armature_object, name: str, angle: float):
    import mathutils

    action = bpy.data.actions.new(name)
    armature_object.animation_data_create().action = action
    for pose_bone in armature_object.pose.bones:
        pose_bone.rotation_mode = "QUATERNION"
    pose_bone = armature_object.pose.bones["bn_child"]
    for frame, factor in ((1, 0.0), (5, 1.0)):
        pose_bone.rotation_quaternion = mathutils.Quaternion((1.0, 0.0, 0.0), angle * factor)
        pose_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)
    action.tw_frame_rate = 20.0
    return action


def select_objects(*objects) -> None:
    deselect_all()
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0] if objects else None


def mesh_objects_of(collection):
    return [obj for obj in collection.all_objects if obj.type == "MESH"]


def main() -> None:
    module = addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False)
    if module is None:
        raise RuntimeError("addon_utils.enable returned failure")
    bpy.context.preferences.addons["total_war_cs2_addon"].preferences.assembly_kit_root = ASSEMBLY_KIT_ROOT

    from bob import cli
    from ui.collection_utils import export_batch, find_building_collection, MixedSelectionError, selected_assets

    output = Path(tempfile.mkdtemp(prefix="tw_batch_"))

    print("=== the selection decides the batch ===")
    first = build_building("BatchOne")
    second = build_building("BatchTwo")
    select_objects(*mesh_objects_of(first), *mesh_objects_of(second))
    found = selected_assets(bpy.context)
    check("two selected buildings resolve to two BUILDING assets", [c.name for c in found.get("BUILDING", [])] == ["BatchOne", "BatchTwo"])
    check("nothing else is resolved", set(found) == {"BUILDING"})

    select_objects(*mesh_objects_of(second))
    check(
        "one selected building resolves to itself",
        [c.name for c in export_batch(bpy.context, "BUILDING", find_building_collection)] == ["BatchTwo"],
    )

    print("=== an empty selection still falls back to the active collection ===")
    deselect_all()
    activate(first)
    check(
        "the active collection is the batch when nothing is selected",
        [c.name for c in export_batch(bpy.context, "BUILDING", find_building_collection)] == ["BatchOne"],
    )

    print("=== a mixed selection is refused ===")
    skeleton_collection, armature_object = build_skeleton("batch_skeleton")
    unit = build_unit("batch_unit", armature_object)
    select_objects(*mesh_objects_of(first), *mesh_objects_of(unit))
    refused = False
    try:
        export_batch(bpy.context, "BUILDING", find_building_collection)
    except MixedSelectionError as error:
        refused = True
        print("   ", str(error).splitlines()[0])
    check("a building plus a unit asset raises MixedSelectionError", refused)

    select_objects(*mesh_objects_of(unit), armature_object)
    refused = False
    try:
        export_batch(bpy.context, "UNIT", lambda context: None)
    except MixedSelectionError:
        refused = True
    check("a unit asset plus a skeleton raises MixedSelectionError", refused)

    select_objects(*mesh_objects_of(first))
    refused = False
    try:
        export_batch(bpy.context, "UNIT", lambda context: None)
    except MixedSelectionError:
        refused = True
    check("selecting only buildings is refused by the unit export", refused)

    print("=== a batch export writes one file per asset ===")
    select_objects(*mesh_objects_of(first), *mesh_objects_of(second))
    result = bpy.ops.tw_buildings.export_building(directory=str(output), compile_with_bob=False)
    check("the batch export finished", result == {"FINISHED"})
    check("BatchOne.CS2 was written", (output / "BatchOne.CS2").is_file())
    check("BatchTwo.CS2 was written", (output / "BatchTwo.CS2").is_file())

    print("=== a batch of skeletons writes both files for each ===")
    second_skeleton, _ = build_skeleton("batch_skeleton_two")
    skeleton_output = Path(tempfile.mkdtemp(prefix="tw_batch_skel_"))
    select_objects(
        *[obj for obj in skeleton_collection.all_objects],
        *[obj for obj in second_skeleton.all_objects],
    )
    result = bpy.ops.tw_buildings.export_skeleton(directory=str(skeleton_output), compile_with_bob=False)
    check("the skeleton batch finished", result == {"FINISHED"})
    for name in ("batch_skeleton", "batch_skeleton_two"):
        check(f"{name}.CS2 was written", (skeleton_output / f"{name}.CS2").is_file())
        check(f"{name}.bone_table was written", (skeleton_output / f"{name}.bone_table").is_file())

    print("=== a batch of unit assets writes one file per asset ===")
    other_unit = build_unit("batch_unit_two", armature_object)
    unit_output = Path(tempfile.mkdtemp(prefix="tw_batch_unit_"))
    select_objects(*mesh_objects_of(unit), *mesh_objects_of(other_unit))
    result = bpy.ops.tw_buildings.export_units(directory=str(unit_output), compile_with_bob=False)
    check("the unit batch finished", result == {"FINISHED"})
    check("batch_unit.CS2 was written", (unit_output / "batch_unit.CS2").is_file())
    check("batch_unit_two.CS2 was written", (unit_output / "batch_unit_two.CS2").is_file())

    print("=== every clip of a batch is sampled from its own keys ===")
    from extraction.animation_extract import extract_animation

    quarter = keyed_clip(armature_object, "batch_clip_quarter", 0.7853981633974483)
    half = keyed_clip(armature_object, "batch_clip_half", 1.5707963267948966)
    armature_object.animation_data.action = half
    bpy.context.scene.frame_start = 1
    bpy.context.scene.frame_end = 5

    _skeleton, sampled_quarter, _warnings = extract_animation(
        armature_object, quarter, bpy.context.scene, bpy.context.evaluated_depsgraph_get()
    )
    _skeleton, sampled_half, _warnings = extract_animation(
        armature_object, half, bpy.context.scene, bpy.context.evaluated_depsgraph_get()
    )
    check("the unassigned clip still produced a track", "bn_child" in sampled_quarter.tracks)
    check(
        "the two clips did not sample to the same rotations",
        sampled_quarter.tracks["bn_child"].rotations != sampled_half.tracks["bn_child"].rotations,
    )
    check(
        "sampling an unassigned clip left the artist's own choice assigned",
        armature_object.animation_data.action == half,
    )

    print("=== the animation export builds the ticked clips ===")
    animation_output = Path(tempfile.mkdtemp(prefix="tw_batch_anim_"))
    select_objects(armature_object)
    operator_result = bpy.ops.tw_buildings.export_animation(
        directory=str(animation_output),
        compile_with_bob=False,
        clips=[{"name": "batch_clip_quarter", "export": True}, {"name": "batch_clip_half", "export": True}],
    )
    check("the clip batch finished", operator_result == {"FINISHED"})
    check("batch_clip_quarter.CS2 was written", (animation_output / "batch_clip_quarter.CS2").is_file())
    check("batch_clip_half.CS2 was written", (animation_output / "batch_clip_half.CS2").is_file())
    check(
        "the two exported clips are not the same file twice",
        (animation_output / "batch_clip_quarter.CS2").read_bytes()
        != (animation_output / "batch_clip_half.CS2").read_bytes(),
    )

    print("=== two selected skeletons are refused by the clip export ===")
    other_armature = next(obj for obj in second_skeleton.all_objects if obj.type == "ARMATURE")
    select_objects(armature_object, other_armature)
    refused = False
    try:
        refused = bpy.ops.tw_buildings.export_animation(
            directory=str(animation_output), compile_with_bob=False
        ) == {"CANCELLED"}
    except RuntimeError:
        refused = True
    check("exporting clips with two skeletons selected is refused", refused)

    print("=== one BOB run for the whole batch, whatever the workflow ===")
    kit = Path(tempfile.mkdtemp(prefix="tw_batch_kit_"))
    (kit / "binaries").mkdir(parents=True, exist_ok=True)
    raw_buildings = kit / "raw_data" / "art" / "battle" / "land" / "models" / "architecture" / "b"
    raw_buildings.mkdir(parents=True, exist_ok=True)
    building_paths = [raw_buildings / f"One.CS2", raw_buildings / "Two.CS2"]

    written = cli.write_configuration(
        str(kit),
        cli.CONFIGURATION_NAME,
        cli._CONFIGURATION_TEMPLATE,
        [cli.raw_data_logical_path(str(kit), path) for path in building_paths],
    )
    configuration = written.read_text(encoding="utf-8")
    check(
        "the building configuration lists every building as its own consumer",
        configuration.count("<entry>") == 2
        and "architecture/b/One.CS2</entry>" in configuration
        and "architecture/b/Two.CS2</entry>" in configuration,
    )
    check("it is still the Building processor", "<processor>Building</processor>" in configuration)

    raw_clips = kit / "raw_data" / "animations" / "clips"
    raw_clips.mkdir(parents=True, exist_ok=True)
    clip_paths = [raw_clips / "a.CS2", raw_clips / "b.CS2", raw_clips / "c.CS2"]
    written = cli.write_configuration(
        str(kit),
        cli.ANIMATION_CONFIGURATION_NAME,
        cli._CS2_CONFIGURATION_TEMPLATE,
        [cli.raw_data_logical_path(str(kit), path) for path in clip_paths],
        directory="<raw>/animations/clips/",
    )
    configuration = written.read_text(encoding="utf-8")
    check("the Cs2 configuration lists every clip", configuration.count("<entry>") == 3)
    check("it scans the one shared folder", "<directory>&lt;raw&gt;/animations/clips/</directory>" in configuration)

    print("=== the pack rules cover every building of the run ===")
    from bob import rules

    rules.write_pack_rules(str(kit), ["one", "two"])
    db_rules = (kit / "working_data" / "db" / "rules.bob").read_bytes().decode("ascii")
    check("the shared db rules carry a section per pack", db_rules.count("[Pack]") == 2)
    check("each section names its own pack file",
          "PackFile = <retail>/data/one.pack" in db_rules and "PackFile = <retail>/data/two.pack" in db_rules)
    check("each section is scoped to its own tables",
          "bob_building_one_models_building" in db_rules and "bob_building_two_models_building" in db_rules)
    for name in ("one", "two"):
        own = kit / "working_data" / "RigidModels" / "Buildings" / name / "rules.bob"
        check(f"{name} got its own compiled-output pack rule", own.is_file())
    rules.remove_pack_rules(str(kit), ["one", "two"])
    check("removing them clears the shared db rule",
          not (kit / "working_data" / "db" / "rules.bob").exists())
    check("removing them clears each building's own rule",
          not any((kit / "working_data" / "RigidModels" / "Buildings" / n / "rules.bob").exists()
                  for n in ("one", "two")))

    print("=== an empty batch is refused rather than crashing ===")
    for label, call in (
        ("buildings", lambda: cli.start_building_batch(str(kit), [])),
        ("skeletons", lambda: cli.start_skeleton_batch(str(kit), [])),
        ("clips", lambda: cli.start_animation_batch(str(kit), [])),
        ("unit parts", lambda: cli.start_unit_build(str(kit), [])),
    ):
        refused = False
        try:
            call()
        except cli.BobError:
            refused = True
        check(f"an empty {label} batch raises BobError", refused)

    if failures:
        raise RuntimeError(f"{len(failures)} check(s) failed: " + "; ".join(failures))
    print("ALL BATCH EXPORT CHECKS PASSED")


try:
    main()
except Exception:
    print("=== BATCH EXPORT TEST FAILED ===")
    traceback.print_exc()
    sys.exit(1)
