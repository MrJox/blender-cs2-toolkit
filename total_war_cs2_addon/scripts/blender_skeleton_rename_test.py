import shutil
import sys
import traceback
from pathlib import Path

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"
SKELETON_NAME = "rome_man_game"
SKELETON_CS2 = Path(ASSEMBLY_KIT_ROOT) / "raw_data" / "animations" / "skeletons" / f"{SKELETON_NAME}.cs2"
NEW_NAME = "blender_renamed_skeleton"
# Its own folder under the tree BOB scans for animations, removed again in the finally block.
EXPORT_DIR = Path(ASSEMBLY_KIT_ROOT) / "raw_data" / "animations" / "blender_rename_test"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

failures = []


def check(label: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        failures.append(label)


def key_clip(armature_object: bpy.types.Object, action: bpy.types.Action, bone_name: str) -> None:
    armature_object.animation_data.action = action
    pose_bone = armature_object.pose.bones[bone_name]
    for frame, amount in ((0, 0.0), (1, 0.5)):
        bpy.context.scene.frame_set(frame)
        pose_bone.rotation_quaternion = (1.0 - amount, amount, 0.0, 0.0)
        pose_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)


def main() -> None:
    if not SKELETON_CS2.exists():
        raise RuntimeError(f"Sample not found: {SKELETON_CS2}")
    addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False)

    from export.animation_exporter import export_animation
    from extraction.unit_extract import skeleton_name_for
    from importer.skeleton_importer import import_skeleton
    from ui.animation_operators import clips_for

    collection, _warnings = import_skeleton(str(SKELETON_CS2), bpy.context)
    armature_object = next(obj for obj in collection.all_objects if obj.type == "ARMATURE")
    bone_name = armature_object.pose.bones[0].name
    armature_object.animation_data_create()

    ours = []
    for index in range(3):
        action = bpy.data.actions.new(f"rename_clip_{index}")
        action.use_fake_user = True
        action.tw_skeleton_name = SKELETON_NAME
        key_clip(armature_object, action, bone_name)
        ours.append(action)

    foreign = bpy.data.actions.new("foreign_clip")
    foreign.tw_skeleton_name = "some_other_skeleton"
    unstamped = bpy.data.actions.new("unstamped_clip")

    # A weighted mesh bound to the skeleton: an Armature modifier holds a pointer rather than a
    # name, so the rename must not need to touch it.
    mesh = bpy.data.meshes.new("bound_mesh")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    bound = bpy.data.objects.new("bound_mesh", mesh)
    bpy.context.scene.collection.objects.link(bound)
    modifier = bound.modifiers.new(name="Armature", type="ARMATURE")
    modifier.object = armature_object

    bpy.context.view_layer.objects.active = armature_object
    armature_object.select_set(True)
    bpy.context.view_layer.active_layer_collection = (
        bpy.context.view_layer.layer_collection.children[collection.name]
    )

    print("=== the rename reaches every reference ===")
    bpy.ops.tw_buildings.rename_skeleton(new_name=NEW_NAME)

    check("the collection took the new name", collection.name == NEW_NAME)
    check("the Armature object followed", armature_object.name == NEW_NAME)
    check("the Armature data followed", armature_object.data.name == NEW_NAME)
    check("skeleton_name_for reports the new name", skeleton_name_for(armature_object) == NEW_NAME)
    check("every clip of this skeleton was restamped",
          all(action.tw_skeleton_name == NEW_NAME for action in ours))
    check("a clip of another skeleton was left alone", foreign.tw_skeleton_name == "some_other_skeleton")
    check("an unstamped clip was left unstamped", unstamped.tw_skeleton_name == "")
    check("the bound mesh still points at the armature", modifier.object is armature_object)
    check("all three clips are still offered by the picker",
          {action.name for action in ours} <= {action.name for action in clips_for(armature_object)})

    print("=== the exported rules.bob quotes the new name ===")
    bpy.context.scene.frame_start = 0
    bpy.context.scene.frame_end = 1
    armature_object.animation_data.action = ours[0]
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        result = export_animation(
            armature_object, ours[0], str(EXPORT_DIR), ASSEMBLY_KIT_ROOT, bpy.context
        )
        check("the export succeeded", result.success)
        rules_text = (EXPORT_DIR / "rules.bob").read_bytes().decode("ascii")
        print("       rules.bob:", rules_text.replace("\r\n", " | "))
        check("its AnimationType is the new name", f"AnimationType = {NEW_NAME}" in rules_text)
        check("no trace of the old name is left", SKELETON_NAME not in rules_text)
    finally:
        shutil.rmtree(EXPORT_DIR, ignore_errors=True)
        print("       cleaned up")

    print()
    if failures:
        print(f"FAILED {len(failures)} check(s):")
        for failure in failures:
            print("   ", failure)
        raise SystemExit(1)
    print("all checks passed")


try:
    main()
except SystemExit:
    raise
except Exception:
    traceback.print_exc()
    sys.exit(1)
