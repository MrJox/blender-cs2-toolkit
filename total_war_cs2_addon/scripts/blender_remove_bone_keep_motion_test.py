import sys
import traceback
from pathlib import Path

import addon_utils
import bpy
import mathutils

REPO_ROOT = r"C:\Users\Khaiali\source\repos\blender_buildings_plugin"
ASSEMBLY_KIT_ROOT = r"D:\SteamLibrary\steamapps\common\Total War Attila\assembly_kit"
SKELETON_CS2 = Path(ASSEMBLY_KIT_ROOT) / "raw_data" / "animations" / "skeletons" / "rome_man_game.cs2"

# The fold is exact algebra on float32-backed matrices, so this is float noise, not tolerance for a
# wrong answer - a real mismatch is orders of magnitude larger.
POSITION_TOLERANCE = 1e-4
ROTATION_TOLERANCE = 1e-4

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

failures = []


def check(label: str, condition: bool) -> None:
    print(("  OK   " if condition else "  FAIL ") + label)
    if not condition:
        failures.append(label)


def world_of(armature_object, names, frames, scene, depsgraph):
    # Clear every basis first: a clip keys only the bones it animates, so without this the bones the
    # clip leaves alone would still be holding the previously assigned clip's pose and the reading
    # would measure that instead. Same reason importer.anim_importer.rest_pose exists.
    for pose_bone in armature_object.pose.bones:
        pose_bone.matrix_basis = mathutils.Matrix()
    captured = {}
    original = scene.frame_current
    for frame in frames:
        scene.frame_set(frame)
        evaluated = armature_object.evaluated_get(depsgraph)
        captured[frame] = {n: evaluated.pose.bones[n].matrix.copy() for n in names}
    scene.frame_set(original)
    return captured


def main() -> None:
    if not SKELETON_CS2.exists():
        raise RuntimeError(f"Sample not found: {SKELETON_CS2}")
    addon_utils.enable("total_war_cs2_addon", default_set=True, persistent=False)

    from importer.skeleton_importer import import_skeleton

    collection, _warnings = import_skeleton(str(SKELETON_CS2), bpy.context)
    armature_object = next(obj for obj in collection.all_objects if obj.type == "ARMATURE")
    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()

    # A bone with children stands in for animroot: it carries travel, its child carries its own
    # motion on top, and a grandchild rides both.
    doomed = next(
        bone.name
        for bone in armature_object.data.bones
        if bone.children and any(grandchild.children for grandchild in bone.children)
    )
    children = [child.name for child in armature_object.data.bones[doomed].children]
    grandchild = next(
        gc.name for c in children for gc in armature_object.data.bones[c].children
    )
    print(f"  removing '{doomed}' | children: {children} | watching grandchild '{grandchild}'")

    frames = [0, 1, 2, 3, 4]
    scene.frame_start, scene.frame_end = frames[0], frames[-1]

    # Three clips at different speeds, plus one that never touches the bone - the whole point is that
    # every clip of the skeleton is rewritten, not just the one currently assigned.
    animation_data = armature_object.animation_data_create()
    actions = []
    for speed, name in ((0.5, "walk"), (1.25, "run"), (0.2, "idle_drift")):
        action = bpy.data.actions.new(name)
        action.use_fake_user = True
        animation_data.action = action
        for frame in frames:
            scene.frame_set(frame)
            travel = armature_object.pose.bones[doomed]
            travel.rotation_mode = "QUATERNION"
            # Forward travel plus a turn, the shape of a real locomotion root track.
            travel.location = (0.0, frame * speed, 0.0)
            travel.rotation_quaternion = mathutils.Quaternion((0, 0, 1), frame * 0.08 * speed)
            travel.keyframe_insert(data_path="location", frame=frame)
            travel.keyframe_insert(data_path="rotation_quaternion", frame=frame)
            for index, child_name in enumerate(children):
                bob = armature_object.pose.bones[child_name]
                bob.rotation_mode = "QUATERNION"
                bob.rotation_quaternion = mathutils.Quaternion((1, 0, 0), 0.15 * (frame + index) * speed)
                bob.keyframe_insert(data_path="rotation_quaternion", frame=frame)
        actions.append(action)

    untouched = bpy.data.actions.new("clip_that_never_moved_it")
    untouched.use_fake_user = True
    animation_data.action = untouched
    for frame in frames:
        scene.frame_set(frame)
        bob = armature_object.pose.bones[children[0]]
        bob.rotation_mode = "QUATERNION"
        bob.rotation_quaternion = mathutils.Quaternion((0, 1, 0), 0.1 * frame)
        bob.keyframe_insert(data_path="rotation_quaternion", frame=frame)

    watched = [*children, grandchild]
    before = {}
    for action in [*actions, untouched]:
        animation_data.action = action
        before[action.name] = world_of(armature_object, watched, frames, scene, depsgraph)
    action = actions[0]
    animation_data.action = action

    print("=== the operator folds the bone away ===")
    bpy.context.view_layer.objects.active = armature_object
    armature_object.select_set(True)
    bpy.context.view_layer.active_layer_collection = (
        bpy.context.view_layer.layer_collection.children[collection.name]
    )
    armature_object.data.bones.active = armature_object.data.bones[doomed]
    bpy.ops.tw_buildings.remove_bone_keep_motion(inherit_bone_type=True)

    check("the bone is gone", doomed not in armature_object.data.bones)
    check("its children survived", all(name in armature_object.data.bones for name in children))
    for candidate in [*actions, untouched]:
        check(f"no channel of the removed bone is left in '{candidate.name}'",
              not any(f'pose.bones["{doomed}"]' in path for path in _paths(candidate)))

    print("=== every watched bone lands exactly where it did, in every clip ===")
    for candidate in [*actions, untouched]:
        animation_data.action = candidate
        after = world_of(armature_object, watched, frames, scene, depsgraph)
        worst_position = 0.0
        worst_rotation = 0.0
        for frame in frames:
            for name in watched:
                old, new = before[candidate.name][frame][name], after[frame][name]
                worst_position = max(worst_position, (old.to_translation() - new.to_translation()).length)
                worst_rotation = max(
                    worst_rotation, quaternion_distance(old.to_quaternion(), new.to_quaternion())
                )
        print(f"       {candidate.name}: position {worst_position:.3e} m, rotation {worst_rotation:.3e}")
        check(f"'{candidate.name}' keeps its motion",
              worst_position <= POSITION_TOLERANCE and worst_rotation <= ROTATION_TOLERANCE)
    animation_data.action = action

    print("=== the clip still exports ===")
    from validation.rules import has_blocking_issues, validate_animation

    issues = validate_animation(armature_object, action, scene)
    for issue in issues:
        print(f"       {issue.severity}: {issue.message}")
    check("nothing blocks the export", not has_blocking_issues(issues))

    print()
    if failures:
        print(f"FAILED {len(failures)} check(s):")
        for failure in failures:
            print("   ", failure)
        raise SystemExit(1)
    print("all checks passed")


def quaternion_distance(a, b) -> float:
    same = max(abs(x - y) for x, y in zip(a, b))
    flipped = max(abs(x + y) for x, y in zip(a, b))
    return min(same, flipped)


def _paths(action):
    from validation.rules import action_data_paths

    return action_data_paths(action)


try:
    main()
except SystemExit:
    raise
except Exception:
    traceback.print_exc()
    sys.exit(1)
