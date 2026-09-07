import shutil
import sys
import traceback
from pathlib import Path

import addon_utils
import bpy

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"
SKELETON_CS2 = Path(ASSEMBLY_KIT_ROOT) / "raw_data" / "animations" / "skeletons" / "rome_man_game.cs2"
# Its own folder under the tree BOB scans for animations, removed again in the finally block.
EXPORT_DIR = Path(ASSEMBLY_KIT_ROOT) / "raw_data" / "animations" / "blender_missing_bone_test"

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

failures = []


def check(label: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        failures.append(label)


def key_bones(armature_object: bpy.types.Object, action: bpy.types.Action, names: list[str]) -> None:
    armature_object.animation_data_create().action = action
    for frame, amount in ((0, 0.0), (1, 0.5)):
        bpy.context.scene.frame_set(frame)
        for name in names:
            pose_bone = armature_object.pose.bones[name]
            pose_bone.rotation_mode = "QUATERNION"
            pose_bone.rotation_quaternion = (1.0 - amount, amount, 0.0, 0.0)
            pose_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)


def main() -> None:
    if not SKELETON_CS2.exists():
        raise RuntimeError(f"Sample not found: {SKELETON_CS2}")
    addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False)

    from binary.cs2_reader import read_cs2
    from export.animation_exporter import export_animation
    from importer.skeleton_importer import import_skeleton
    from validation.rules import has_blocking_issues, validate_animation

    collection, _warnings = import_skeleton(str(SKELETON_CS2), bpy.context)
    armature_object = next(obj for obj in collection.all_objects if obj.type == "ARMATURE")

    doomed = armature_object.pose.bones[0].name
    keepers = [bone.name for bone in armature_object.pose.bones[1:4]]

    action = bpy.data.actions.new("clip_over_a_deleted_bone")
    action.use_fake_user = True
    key_bones(armature_object, action, [doomed, *keepers])

    # Delete the bone from the skeleton, the way an artist does in Edit Mode - the Action keeps its
    # channels for it, and Blender itself plays the clip without complaint.
    bpy.context.view_layer.objects.active = armature_object
    armature_object.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = armature_object.data.edit_bones
    for child in list(edit_bones[doomed].children):
        child.parent = edit_bones[doomed].parent
    edit_bones.remove(edit_bones[doomed])
    bpy.ops.object.mode_set(mode="OBJECT")

    bpy.context.scene.frame_start = 0
    bpy.context.scene.frame_end = 1

    print("=== a bone deleted from the skeleton does not block the clip ===")
    check("the bone really is gone", doomed not in armature_object.data.bones)
    issues = validate_animation(armature_object, action, bpy.context.scene)
    for issue in issues:
        print(f"       {issue.severity}: {issue.message}")
    check("the export is not blocked", not has_blocking_issues(issues))
    check("the leftover channels are reported as a warning",
          any(issue.severity == "WARNING" and doomed in issue.message for issue in issues))

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        result = export_animation(
            armature_object, action, str(EXPORT_DIR), ASSEMBLY_KIT_ROOT, bpy.context
        )
        check("the export succeeded", result.success)
        written = EXPORT_DIR / f"{action.name}.CS2"
        check("a .CS2 was written", written.is_file())
        node_names = {node.name for node in read_cs2(written.read_bytes()).scene_root.scene_nodes}
        check("the deleted bone is not in the exported file", doomed not in node_names)
        check("every bone that survived is", all(name in node_names for name in keepers))
    finally:
        shutil.rmtree(EXPORT_DIR, ignore_errors=True)

    print("=== a clip with nothing in common is still refused ===")
    foreign = bpy.data.actions.new("clip_for_another_skeleton")
    foreign.use_fake_user = True
    key_bones(armature_object, foreign, keepers)
    bpy.ops.object.mode_set(mode="EDIT")
    for name in keepers:
        edit_bone = armature_object.data.edit_bones[name]
        for child in list(edit_bone.children):
            child.parent = edit_bone.parent
        armature_object.data.edit_bones.remove(edit_bone)
    bpy.ops.object.mode_set(mode="OBJECT")

    issues = validate_animation(armature_object, foreign, bpy.context.scene)
    for issue in issues:
        print(f"       {issue.severity}: {issue.message}")
    check("it blocks the export", has_blocking_issues(issues))
    check("and says the clip is for a different skeleton",
          any("different skeleton" in issue.message for issue in issues))

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
